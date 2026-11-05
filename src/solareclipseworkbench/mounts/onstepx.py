"""OnStepX driver, speaking LX200 over a USB cable.

Written for an MLAstro SAL-33 that runs OnStepX.  The same driver works over TCP
for the WiFi builds.  The USB cable is the primary path, because it does not drop
and does not need the access point of the mount.

Protocol shape, from the OnStepX command reference:

    - A command frame is ``:CC...#``.
    - Replies come in three shapes, and which one you get depends on the command:
      a payload terminated with ``#``, a single ``0``/``1`` boolean with no
      terminator, or nothing at all.
    - There is no way to tell these apart from the reply stream, so every command
      here declares the shape it expects.  Guessing desynchronises the link.

Coordinates use the highest-precision variants (``:GRH#``, ``:GDH#``) so the
reply format does not depend on the controller's precision mode.
"""

import logging
import re
import socket
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

import serial

from solareclipseworkbench.mounts.base import (
    Candidate,
    Capabilities,
    MountDriver,
    MountError,
    MountStatus,
    format_dec,
    format_ra,
    parse_dec,
    parse_ra,
)
from solareclipseworkbench.mounts import register_driver
from solareclipseworkbench.serial_ports import resolve_port, usb_serial_ports

logger = logging.getLogger(__name__)

DEFAULT_BAUDRATE = 9600
# OnStepX builds do not all use the same rate, so connect() probes these in turn.
CANDIDATE_BAUDRATES = [9600, 19200, 38400, 57600, 115200]

DEFAULT_TCP_PORT = 9999
DEFAULT_TIMEOUT_S = 2.0
SLEW_POLL_INTERVAL_S = 0.5

GOTO_ERRORS = {
    "0": "goto accepted",
    "1": "below horizon limit",
    "2": "above overhead limit",
    "3": "controller in standby",
    "4": "mount parked",
    "5": "goto already in progress",
    "6": "outside limits",
    "7": "hardware fault",
    "8": "already in motion",
    "9": "unspecified error",
}

DIRECTIONS = {"north": "n", "south": "s", "east": "e", "west": "w"}
RATE_PRESETS = {"guide": ":RG#", "center": ":RC#", "find": ":RM#", "fast": ":RF#", "slew": ":RS#"}
TRACKING_RATES = {"sidereal": ":TQ#", "solar": ":TS#", "lunar": ":TL#", "king": ":TK#"}


class ReplyKind(Enum):
    """What a command sends back."""

    NONE = "none"
    BOOL = "bool"              # a single '0' or '1', no terminator
    CHAR = "char"              # a single character, no terminator (goto results)
    TERMINATED = "terminated"  # payload ending in '#'


# --------------------------------------------------------------------- transport


class Transport(ABC):
    """A byte pipe to the controller."""

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, size: int, timeout: float) -> bytes: ...

    @abstractmethod
    def reset_input(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def describe(self) -> str: ...


class SerialTransport(Transport):
    """USB cable to the controller."""

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE, timeout: float = DEFAULT_TIMEOUT_S):
        self.port = port
        self.baudrate = baudrate
        try:
            # Exclusive: a port another subsystem already holds must fail here
            # rather than put two devices on one wire.
            self._serial = serial.Serial(port, baudrate, timeout=timeout, exclusive=True)
        except serial.SerialException as exc:
            raise MountError(f"cannot open mount on {port}: {exc}") from exc
        # Controllers commonly emit a banner or reset when the port opens.
        time.sleep(0.2)
        self.reset_input()

    def write(self, data: bytes) -> None:
        try:
            self._serial.write(data)
            self._serial.flush()
        except serial.SerialException as exc:
            raise MountError(f"write failed on {self.port}: {exc}") from exc

    def read(self, size: int, timeout: float) -> bytes:
        self._serial.timeout = timeout
        try:
            return self._serial.read(size)
        except serial.SerialException as exc:
            raise MountError(f"read failed on {self.port}: {exc}") from exc

    def reset_input(self) -> None:
        try:
            self._serial.reset_input_buffer()
        except Exception:
            logger.debug("Could not reset serial input buffer", exc_info=True)

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            logger.debug("Error closing mount serial port", exc_info=True)

    def describe(self) -> str:
        return f"serial {self.port} @ {self.baudrate}"


class TcpTransport(Transport):
    """WiFi or Ethernet build of OnStepX."""

    def __init__(self, host: str, port: int = DEFAULT_TCP_PORT, timeout: float = DEFAULT_TIMEOUT_S):
        self.host = host
        self.port = port
        try:
            self._socket = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise MountError(f"cannot connect to mount at {host}:{port}: {exc}") from exc

    def write(self, data: bytes) -> None:
        try:
            self._socket.sendall(data)
        except OSError as exc:
            raise MountError(f"write failed to {self.host}: {exc}") from exc

    def read(self, size: int, timeout: float) -> bytes:
        self._socket.settimeout(timeout)
        try:
            return self._socket.recv(size)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise MountError(f"read failed from {self.host}: {exc}") from exc

    def reset_input(self) -> None:
        self._socket.settimeout(0.05)
        try:
            while self._socket.recv(4096):
                pass
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            logger.debug("Error closing mount socket", exc_info=True)

    def describe(self) -> str:
        return f"tcp {self.host}:{self.port}"


class LoopbackTransport(Transport):
    """Answers the wire protocol, for testing the driver without a controller.

    This exists to exercise the framing and reply-shape handling.  For rehearsing
    an eclipse script, use the ``simulator`` driver instead.  It models a mount
    rather than a serial link.
    """

    def __init__(self):
        self._pending = b""
        self.tracking = False
        self.parked = False
        self.slewing = False
        self.ra_hours = 0.0
        self.dec_degrees = 0.0
        self.target: Tuple[Optional[float], Optional[float]] = (None, None)
        self.rate = "solar"
        self.site_time: dict = {}

    def write(self, data: bytes) -> None:
        self._pending += self._respond(data.decode("ascii", errors="replace")).encode("ascii")

    def _respond(self, command: str) -> str:
        if command == ":GVP#":
            return "OnStepX (loopback)#"
        if command == ":GVN#":
            return "10.24#"
        if command == ":GRH#":
            return _format_ra_highp(self.ra_hours)
        if command == ":GDH#":
            return _format_dec_highp(self.dec_degrees)
        if command == ":GU#":
            flags = "" if self.tracking else "n"
            flags += "" if self.slewing else "N"
            flags += "P" if self.parked else "p"
            flags += "O" if self.rate == "solar" else ""
            return flags + "#"
        if command == ":Te#":
            self.tracking = True
            return "1"
        if command == ":Td#":
            self.tracking = False
            return "1"
        if command in TRACKING_RATES.values():
            self.rate = next(k for k, v in TRACKING_RATES.items() if v == command)
            return ""
        if command.startswith(":Sr"):
            self.target = (parse_ra(command[3:-1]), self.target[1])
            return "1"
        if command.startswith(":Sd"):
            self.target = (self.target[0], parse_dec(command[3:-1]))
            return "1"
        if command.startswith((":SG", ":SL", ":SC", ":St", ":Sg")):
            self.site_time[command[1:3]] = command[3:-1]
            return "1"
        if command == ":MS#":
            if self.parked:
                return "4"
            if self.target[0] is None or self.target[1] is None:
                return "9"
            self.ra_hours, self.dec_degrees = self.target
            return "0"
        if command == ":hP#":
            self.parked = True
            self.tracking = False
            return "1"
        if command == ":hR#":
            self.parked = False
            return "1"
        if command == ":CM#":
            return "N/A#"
        if command.startswith((":M", ":R", ":Q")):
            return ""
        return "0"

    def read(self, size: int, timeout: float) -> bytes:
        chunk, self._pending = self._pending[:size], self._pending[size:]
        return chunk

    def reset_input(self) -> None:
        self._pending = b""

    def close(self) -> None:
        self._pending = b""

    def describe(self) -> str:
        return "loopback OnStepX (no hardware)"


# ------------------------------------------------------------------ coordinates


def _format_ra_highp(hours: float) -> str:
    h = int(hours)
    remainder = (hours - h) * 60.0
    m = int(remainder)
    s = (remainder - m) * 60.0
    return f"{h:02d}:{m:02d}:{s:07.4f}#"


def _format_dec_highp(degrees: float) -> str:
    sign = "+" if degrees >= 0 else "-"
    value = abs(degrees)
    d = int(value)
    remainder = (value - d) * 60.0
    m = int(remainder)
    s = (remainder - m) * 60.0
    return f"{sign}{d:02d}*{m:02d}:{s:06.3f}#"


def _format_longitude(degrees: float) -> str:
    """``sDDD*MM:SS`` for :Sg, whose degrees field is three digits wide."""
    sign = "+" if degrees >= 0 else "-"
    value = abs(degrees)
    d = int(value)
    remainder = (value - d) * 60.0
    m = int(remainder)
    s = int(round((remainder - m) * 60.0))
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return f"{sign}{d:03d}*{m:02d}:{s:02d}"


def parse_status(raw: str) -> MountStatus:
    """Decode a ``:GU#`` reply."""
    raw = raw.strip().rstrip("#")
    status = MountStatus(raw=raw)

    # The reply is a set of condition characters; absence is as meaningful as
    # presence, which is why tracking is "not the 'n' flag" rather than a
    # positive flag of its own.
    status.tracking = "n" not in raw
    status.slewing = "N" not in raw
    status.parked = "P" in raw
    status.parking = "I" in raw
    status.park_failed = "F" in raw
    status.at_home = "H" in raw
    status.homing = "h" in raw
    status.pulse_guiding = "G" in raw

    if "(" in raw:
        status.tracking_rate = "lunar"
    elif "O" in raw:
        status.tracking_rate = "solar"
    elif "k" in raw:
        status.tracking_rate = "king"
    else:
        status.tracking_rate = "sidereal"

    if "T" in raw:
        status.pier_side = "east"
    elif "W" in raw:
        status.pier_side = "west"

    for char, name in (("E", "GEM"), ("K", "FORK"), ("A", "ALTAZM"), ("L", "ALTALT")):
        if char in raw:
            status.mount_type = name
            break

    trailing = re.search(r"(\d+)$", raw)
    if trailing:
        status.error_code = trailing.group(1)

    return status


# ---------------------------------------------------------------------- driver


@register_driver
class OnStepXMount(MountDriver):
    """LX200 client for an OnStepX controller."""

    name = "onstepx"
    display_name = "OnStepX"
    description = "OnStep / OnStepX controllers over USB serial or TCP (LX200 protocol)"
    capabilities = Capabilities(
        goto=True,
        sync=True,
        park=True,
        tracking_toggle=True,
        tracking_rates=("sidereal", "solar", "lunar", "king"),
        manual_move=True,
        rate_presets=("guide", "center", "find", "fast", "slew"),
        pulse_guide=True,
        altaz_readout=True,
        site_time=True,
    )

    def __init__(self, port: Optional[str] = None, baudrate: Optional[int] = None,
                 host: Optional[str] = None, tcp_port: int = DEFAULT_TCP_PORT,
                 transport: Optional[Transport] = None, timeout: float = DEFAULT_TIMEOUT_S,
                 **config):
        super().__init__(port=port, baudrate=baudrate, host=host, tcp_port=tcp_port, **config)
        self.port = port
        self.baudrate = baudrate
        self.host = host
        self.tcp_port = tcp_port
        self.timeout = timeout
        self.transport = transport
        self._lock = threading.RLock()
        self.traffic: list = []
        self.record_traffic = True

    # ------------------------------------------------------------- discovery

    @classmethod
    def discover(cls) -> list:
        """Every USB serial port, as a candidate worth probing."""
        return [
            Candidate(kind="mount", driver=cls.name, target=p.device,
                      description=p.description or "USB serial",
                      config={"port": p.device})
            for p in usb_serial_ports()
        ]

    # ------------------------------------------------------------ connection

    def connect(self) -> None:
        if self.transport is not None:
            return
        if self.host:
            self.transport = TcpTransport(self.host, self.tcp_port, self.timeout)
            return
        if self.port:
            # A saved port name can change when the adapter is plugged in again
            self.port = resolve_port(self.port)
            # No fallback rate: when no rate answers, nothing on this port
            # speaks LX200, and a link opened anyway does not work.
            rate = self.baudrate or probe_serial(self.port)
            if rate is None:
                raise MountError(
                    f"nothing answered LX200 on {self.port} at any baud rate "
                    f"({', '.join(str(b) for b in CANDIDATE_BAUDRATES)}): "
                    "wrong port, or the mount has no power")
            self.transport = SerialTransport(self.port, rate, self.timeout)
            return
        raise MountError("onstepx needs a port (USB cable) or a host (network)")

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def describe(self) -> str:
        try:
            return f"{self.product_name()} on {self.transport.describe()}"
        except MountError:
            return f"OnStepX on {self.transport.describe() if self.transport else 'not connected'}"

    # ---------------------------------------------------------------- plumbing

    def _require_transport(self) -> Transport:
        if self.transport is None:
            raise MountError("mount is not connected")
        return self.transport

    def _read_terminated(self, timeout: float) -> str:
        transport = self._require_transport()
        deadline = time.perf_counter() + timeout
        buffer = ""
        while time.perf_counter() < deadline:
            chunk = transport.read(1, max(0.01, deadline - time.perf_counter()))
            if not chunk:
                continue
            char = chunk.decode("ascii", errors="replace")
            if char == "#":
                return buffer
            buffer += char
        raise MountError(f"timed out waiting for a terminated reply (got {buffer!r})")

    def send(self, command: str, reply: ReplyKind = ReplyKind.TERMINATED,
             timeout: Optional[float] = None) -> str:
        """Send one command frame and read the reply shape it declares.

        ``command`` may be given with or without the leading ``:`` and trailing
        ``#``; both are added if missing.
        """
        timeout = self.timeout if timeout is None else timeout
        transport = self._require_transport()

        if not command.startswith((":", ";")):
            command = ":" + command
        if not command.endswith("#"):
            command = command + "#"

        with self._lock:
            started = time.perf_counter()
            transport.write(command.encode("ascii"))

            if reply is ReplyKind.NONE:
                result = ""
            elif reply in (ReplyKind.BOOL, ReplyKind.CHAR):
                raw = transport.read(1, timeout)
                if not raw:
                    raise MountError(f"no reply to {command}")
                result = raw.decode("ascii", errors="replace")
            else:
                result = self._read_terminated(timeout)

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if self.record_traffic:
                self.traffic.append((time.time(), command, result, elapsed_ms))
            logger.debug("Mount %s -> %r (%.1f ms)", command, result, elapsed_ms)
            return result

    def send_bool(self, command: str, timeout: Optional[float] = None) -> bool:
        return self.send(command, ReplyKind.BOOL, timeout) == "1"

    def raw(self, command: str, reply: str = "terminated", timeout: Optional[float] = None) -> str:
        """Escape hatch for the bench console: send anything, read any shape."""
        return self.send(command, ReplyKind(reply), timeout)

    # ------------------------------------------------------------------ identity

    def product_name(self) -> str:
        """The controller's own name for itself.

        Not every build answers this: OnStepX 10.27 replies with a bare "0",
        which is not a name and not a terminated reply.  Then the firmware
        version is used instead, so that the connection does not fail.
        """
        try:
            name = self.send(":GVP#")
        except MountError:
            name = ""
        if name and name != "0":
            return name
        try:
            return f"OnStepX {self.firmware_version()}"
        except MountError:
            return "OnStepX"

    def firmware_version(self) -> str:
        return self.send(":GVN#")

    # --------------------------------------------------------------------- state

    def status(self) -> MountStatus:
        return parse_status(self.send(":GU#"))

    def get_radec(self) -> Tuple[float, float]:
        return parse_ra(self.send(":GRH#")), parse_dec(self.send(":GDH#"))

    def get_altaz(self) -> Tuple[float, float]:
        return parse_dec(self.send(":GAH#")), parse_dec(self.send(":GZH#"))

    # ------------------------------------------------------------------ tracking

    def tracking_on(self) -> bool:
        return self.send_bool(":Te#")

    def tracking_off(self) -> bool:
        return self.send_bool(":Td#")

    def set_tracking_rate(self, rate: str) -> None:
        try:
            command = TRACKING_RATES[rate.lower()]
        except KeyError:
            raise MountError(f"unknown tracking rate: {rate}") from None
        self.send(command, ReplyKind.NONE)

    def tracking_rate_name(self) -> Optional[str]:
        """The rate the controller reports, mapped back to a name.

        :GT# answers in Hz, where the whole point is the second decimal:
        sidereal is 60.164 and solar is 60.000, and the difference is the Sun
        drifting out of a long lens over the hours of an eclipse.
        """
        try:
            hz = float(self.send(":GT#").rstrip("#"))
        except (MountError, ValueError):
            return None
        for name, reference in (("sidereal", 60.1643), ("solar", 60.0),
                                ("lunar", 57.9), ("king", 60.136)):
            if abs(hz - reference) < 0.02:
                return name
        return f"{hz:.3f} Hz"

    # ----------------------------------------------------------- site & time

    def set_site(self, latitude_deg: float, longitude_deg: float,
                 elevation_m: Optional[float] = None) -> None:
        """Tell the controller where it stands.

        ``longitude_deg`` arrives east-positive and goes out west-positive,
        which is the LX200 convention.  Elevation is accepted for the
        interface but not sent: its effect on tracking is refraction-level,
        and not every OnStep build takes the command - and per the module
        docstring, guessing at a command desynchronises the link.
        """
        if not self.send_bool(f":St{format_dec(latitude_deg)}#"):
            raise MountError(f"mount rejected latitude {format_dec(latitude_deg)}")
        longitude_west = _format_longitude(-longitude_deg)
        if not self.send_bool(f":Sg{longitude_west}#"):
            raise MountError(f"mount rejected longitude {longitude_west}")

    def set_datetime(self, when: Optional[datetime] = None) -> None:
        """Set the controller's clock, in UTC.

        The UTC offset is set to zero and UTC is sent as the "local" time, so
        no time zone or daylight saving time is necessary.  The controller
        calculates the sidereal time, and from it the position of the Sun,
        from UTC.  Only a display on the controller shows the difference.

        Naive datetimes are taken as this computer's local time.
        """
        if when is None:
            when = datetime.now(timezone.utc)
        else:
            when = when.astimezone(timezone.utc)
        if not self.send_bool(":SG+00:00#"):
            raise MountError("mount rejected the UTC offset")
        if not self.send_bool(f":SL{when:%H:%M:%S}#"):
            raise MountError(f"mount rejected the time {when:%H:%M:%S}")
        if not self.send_bool(f":SC{when:%m/%d/%y}#"):
            raise MountError(f"mount rejected the date {when:%m/%d/%y}")

    # ---------------------------------------------------------------------- goto

    def set_target(self, ra_hours: float, dec_degrees: float) -> None:
        if not self.send_bool(f":Sr{format_ra(ra_hours)}#"):
            raise MountError(f"mount rejected target RA {format_ra(ra_hours)}")
        if not self.send_bool(f":Sd{format_dec(dec_degrees)}#"):
            raise MountError(f"mount rejected target Dec {format_dec(dec_degrees)}")

    def goto(self, ra_hours: float, dec_degrees: float, wait: bool = False,
             timeout: float = 180.0) -> None:
        self.set_target(ra_hours, dec_degrees)
        code = self.send(":MS#", ReplyKind.CHAR)
        if code != "0":
            raise MountError(f"goto refused: {GOTO_ERRORS.get(code, f'unknown code {code}')}")
        logger.info("Mount slewing to RA %s Dec %s", format_ra(ra_hours), format_dec(dec_degrees))
        if wait:
            self.wait_for_slew(timeout)

    def sync(self, ra_hours: float, dec_degrees: float) -> None:
        self.set_target(ra_hours, dec_degrees)
        self.send(":CM#")

    def abort(self) -> None:
        self.send(":Q#", ReplyKind.NONE)
        logger.info("Mount motion aborted")

    # ------------------------------------------------------------ manual motion

    def move(self, direction: str) -> None:
        letter = DIRECTIONS.get(direction.lower(), direction.lower())
        if letter not in ("n", "s", "e", "w"):
            raise MountError(f"unknown direction: {direction}")
        self.send(f":M{letter}#", ReplyKind.NONE)

    def stop_move(self, direction: Optional[str] = None) -> None:
        if direction is None:
            self.send(":Q#", ReplyKind.NONE)
            return
        letter = DIRECTIONS.get(direction.lower(), direction.lower())
        self.send(f":Q{letter}#", ReplyKind.NONE)

    def set_rate(self, rate: str) -> None:
        try:
            command = RATE_PRESETS[rate.lower()]
        except KeyError:
            raise MountError(f"unknown rate preset: {rate}") from None
        self.send(command, ReplyKind.NONE)

    def pulse_guide(self, direction: str, milliseconds: int) -> bool:
        letter = DIRECTIONS.get(direction.lower(), direction.lower())
        return self.send_bool(f":MG{letter}{int(milliseconds)}#")

    # ------------------------------------------------------------------- parking

    def park(self) -> bool:
        return self.send_bool(":hP#")

    def unpark(self) -> bool:
        return self.send_bool(":hR#")

    def set_park_here(self) -> bool:
        return self.send_bool(":hQ#")


# ------------------------------------------------------------------ discovery


#: Asked in turn until one answers, to decide whether a mount is on a port.
#: More than one, because not every build answers every question: OnStepX
#: 10.27 replies to :GVP# with a bare "0" while answering the rest normally.
IDENTITY_COMMANDS = (":GVN#", ":GU#", ":GVP#")


def probe_serial(port: str, baudrates=None, timeout: float = 1.0) -> Optional[int]:
    """Find the baud rate a controller answers on, or None."""
    for baudrate in (baudrates or CANDIDATE_BAUDRATES):
        transport = None
        try:
            transport = SerialTransport(port, baudrate, timeout=timeout)
            mount = OnStepXMount(transport=transport, timeout=timeout)
            for command in IDENTITY_COMMANDS:
                try:
                    if mount.send(command, ReplyKind.TERMINATED, timeout=timeout):
                        logger.info("Mount answered %s at %d baud on %s",
                                    command, baudrate, port)
                        return baudrate
                except MountError:
                    # This one command; the next may still answer.  A wrong
                    # baud rate simply fails all of them.
                    continue
        except MountError:
            continue
        finally:
            if transport is not None:
                transport.close()
    return None
