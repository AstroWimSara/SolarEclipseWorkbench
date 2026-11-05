"""Telescope mount control through INDI.

Keeps the sun in the field of view during a run: the mount tracks at the solar
rate, and is parked at the end when the script asks for it.  The mount is never
sent to a position (no GOTO): it is pointed at the sun by hand, behind a solar
filter, and ``sew`` only tracks, nudges and parks it.

The mount is reached through an INDI server (``indiserver`` with the driver of
the mount), on this computer, in WSL on Windows, or on another machine such as
a Raspberry Pi at the mount.  See docs/MOUNT.md.

Closing the connection leaves the driver connected to the mount, so the mount
keeps tracking when ``sew`` is closed.
"""

import datetime
import logging
import threading
from typing import Optional

from solareclipseworkbench import hardware_problems, wsl_usb
from solareclipseworkbench.indi_client import DEFAULT_PORT, IndiClient, IndiError

logger = logging.getLogger(__name__)

#: Host name that starts the built-in simulated mount instead of connecting to a server
SIMULATED_HOST = "simulated"

#: Host names of an INDI server on this computer
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

#: Interface bit of a telescope in DRIVER_INFO.DRIVER_INTERFACE
TELESCOPE_INTERFACE = 1

#: How far the sun drifts from a mount tracking at the sidereal rate
SIDEREAL_DRIFT_ARCMIN_PER_HOUR = 2.5

DIRECTIONS = {
    "N": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_N", "TELESCOPE_MOTION_NS", "MOTION_NORTH"),
    "S": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_S", "TELESCOPE_MOTION_NS", "MOTION_SOUTH"),
    "E": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_E", "TELESCOPE_MOTION_WE", "MOTION_EAST"),
    "W": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_W", "TELESCOPE_MOTION_WE", "MOTION_WEST"),
}


class MountError(Exception):
    """The mount could not be reached, or did not do what was asked."""


def parse_address(address: str) -> tuple:
    """``host[:port]`` → (host, port)."""
    address = (address or "").strip() or "localhost"
    if address.count(":") == 1:
        host, port = address.split(":")
        try:
            return host.strip() or "localhost", int(port)
        except ValueError:
            raise MountError(f"not a port number: {port!r}") from None
    return address, DEFAULT_PORT


def find_mounts(client: IndiClient) -> list:
    """The devices on the server that are telescope mounts."""
    mounts = []
    for device in client.devices():
        interface = client.value(device, "DRIVER_INFO", "DRIVER_INTERFACE")
        try:
            if interface is not None and int(interface) & TELESCOPE_INTERFACE:
                mounts.append(device)
                continue
        except ValueError:
            pass
        if client.property(device, "TELESCOPE_ABORT_MOTION") or client.property(device, "EQUATORIAL_EOD_COORD"):
            mounts.append(device)
    return mounts


class Mount:
    """One mount on an INDI server.

    Use ``Mount.open()`` to make one.  Every call is safe from any thread; the
    calls are serialised, so a script command and a button press do not mix
    their property changes.
    """

    def __init__(self, client: IndiClient, device: str, simulator=None):
        self.client = client
        self.device = device
        self._simulator = simulator
        self._lock = threading.RLock()

    # ------------------------------------------------------------ connection

    @classmethod
    def open(cls, address: str = "localhost", device: Optional[str] = None, device_port: Optional[str] = None,
             timeout: float = 15.0) -> "Mount":
        """Connect to the INDI server, pick the mount and connect its driver to the mount.

        Args:
            - address: ``host[:port]`` of the INDI server, or ``simulated``
            - device: Name of the mount on the server; may be left out when there is only one
            - device_port: Serial port of the mount on the server's machine (e.g.
                           /dev/ttyUSB0), when the driver does not have it saved yet
            - timeout: Seconds to wait for the driver to connect to the mount
        """
        simulator = None
        if address.strip().lower() == SIMULATED_HOST:
            from solareclipseworkbench.indi_simulator import SimulatedIndiServer
            simulator = SimulatedIndiServer()
            host, port = "127.0.0.1", simulator.port
        else:
            host, port = parse_address(address)
            if host.lower() in LOCAL_HOSTS:
                # Under WSL the mount's USB cable belongs to Windows until it is
                # attached, like a camera.  A no-op elsewhere.
                wsl_usb.attach_shared_devices()
        try:
            client = IndiClient(host, port)
        except IndiError as exc:
            if simulator is not None:
                simulator.close()
            raise MountError(str(exc)) from exc
        try:
            client.wait_settled()
            mounts = find_mounts(client)
            if device:
                if device not in client.devices():
                    raise MountError(f"there is no device {device!r} on the INDI server at {client.describe()}"
                                     + (f"; mounts there: {', '.join(mounts)}" if mounts else ""))
            elif len(mounts) == 1:
                device = mounts[0]
            elif not mounts:
                raise MountError(f"the INDI server at {client.describe()} has no mount; "
                                 f"start it with the driver of the mount, e.g. indiserver indi_eqmod_telescope")
            else:
                raise MountError(f"the INDI server at {client.describe()} has more than one mount "
                                 f"({', '.join(mounts)}); choose one")
            mount = cls(client, device, simulator)
            mount.connect_driver(device_port, timeout)
        except BaseException:
            client.close()
            if simulator is not None:
                simulator.close()
            raise
        logger.info("Mount ready: %s", mount.describe())
        return mount

    def connect_driver(self, device_port: Optional[str] = None, timeout: float = 15.0) -> None:
        """Make the driver connect to the mount, if it is not connected yet."""
        with self._lock:
            if self.driver_connected:
                return
            if device_port and self.client.property(self.device, "DEVICE_PORT") is not None:
                self._change("DEVICE_PORT", {"PORT": device_port})
            self._change("CONNECTION", {"CONNECT": True}, timeout=timeout)
            # The driver defines the telescope properties once it is connected
            if not self.client.wait_for(
                    lambda: self._has("EQUATORIAL_EOD_COORD"), 5.0):
                raise MountError(f"{self.device} connected, but does not report its position")

    @property
    def driver_connected(self) -> bool:
        return bool(self.client.value(self.device, "CONNECTION", "CONNECT", False))

    @property
    def connected(self) -> bool:
        return self.client.connected and self.driver_connected

    def close(self) -> None:
        """Close the connection to the INDI server.  The mount keeps tracking."""
        self.client.close()
        if self._simulator is not None:
            self._simulator.close()
            self._simulator = None
        logger.info("Mount connection closed: %s", self.device)

    def _change(self, name: str, values: dict, timeout: float = 5.0, wait_done: bool = True):
        try:
            return self.client.change(self.device, name, values, timeout=timeout, wait_done=wait_done)
        except IndiError as exc:
            raise MountError(str(exc)) from exc

    def _has(self, name: str) -> bool:
        return self.client.property(self.device, name) is not None

    # ------------------------------------------------------------------ site

    def send_site(self, latitude: float, longitude: float, elevation: float,
                  utc: Optional[datetime.datetime] = None) -> list:
        """Give the mount the observer's location and the time.

        Args:
            - latitude, longitude: Degrees, north and east positive
            - elevation: Metres
            - utc: The time to set; now (by this computer's clock) when not given.
                   Pass the GPS-corrected time when there is one.

        Returns: What was sent, as text, for the log and the status line.
        """
        if utc is None:
            utc = datetime.datetime.now(datetime.timezone.utc)
        elif utc.tzinfo is None:
            utc = utc.replace(tzinfo=datetime.timezone.utc)
        utc = utc.astimezone(datetime.timezone.utc)
        sent = []
        with self._lock:
            if self._has("GEOGRAPHIC_COORD"):
                self._change("GEOGRAPHIC_COORD", {"LAT": float(latitude), "LONG": float(longitude) % 360.0,
                                                  "ELEV": float(elevation)})
                sent.append(f"location {latitude:.5f}, {longitude:.5f}, {elevation:.0f} m")
            if self._has("TIME_UTC"):
                offset = datetime.datetime.now().astimezone().utcoffset() or datetime.timedelta(0)
                self._change("TIME_UTC", {"UTC": utc.strftime("%Y-%m-%dT%H:%M:%S"),
                                          "OFFSET": f"{offset.total_seconds() / 3600:g}"})
                sent.append(f"time {utc:%Y-%m-%d %H:%M:%S} UTC")
        logger.info("Sent to %s: %s", self.device, "; ".join(sent) or "nothing (the driver takes neither)")
        return sent

    # -------------------------------------------------------------- tracking

    @property
    def parked(self) -> bool:
        return bool(self.client.value(self.device, "TELESCOPE_PARK", "PARK", False))

    @property
    def tracking(self) -> bool:
        return bool(self.client.value(self.device, "TELESCOPE_TRACK_STATE", "TRACK_ON", False))

    @property
    def track_mode(self) -> Optional[str]:
        prop = self.client.property(self.device, "TELESCOPE_TRACK_MODE")
        if prop is None:
            return None
        on = prop.on_switches()
        return on[0] if on else None

    @property
    def has_solar_rate(self) -> bool:
        prop = self.client.property(self.device, "TELESCOPE_TRACK_MODE")
        return prop is not None and "TRACK_SOLAR" in prop.values

    def track_solar(self) -> str:
        """Unpark if needed, and track at the solar rate.

        Returns: The rate the mount tracks at: "solar", or "sidereal" when the
                 driver has no solar rate (the sun then drifts about 2.5′ an hour).
        """
        with self._lock:
            if self.parked:
                self.unpark()
            rate = "sidereal"
            if self.has_solar_rate:
                self._change("TELESCOPE_TRACK_MODE", {"TRACK_SOLAR": True})
                rate = "solar"
            elif self._has("TELESCOPE_TRACK_MODE") and "TRACK_SIDEREAL" in \
                    self.client.property(self.device, "TELESCOPE_TRACK_MODE").values:
                self._change("TELESCOPE_TRACK_MODE", {"TRACK_SIDEREAL": True})
            if self._has("TELESCOPE_TRACK_STATE"):
                self._change("TELESCOPE_TRACK_STATE", {"TRACK_ON": True})
        logger.info("%s tracks at the %s rate", self.device, rate)
        return rate

    def stop_tracking(self) -> None:
        with self._lock:
            if not self._has("TELESCOPE_TRACK_STATE"):
                raise MountError(f"{self.device} cannot switch tracking off")
            self._change("TELESCOPE_TRACK_STATE", {"TRACK_OFF": True})
        logger.info("%s stopped tracking", self.device)

    def park(self) -> None:
        """Start parking.  The mount moves to its park position; this returns before it gets there."""
        with self._lock:
            if not self._has("TELESCOPE_PARK"):
                raise MountError(f"{self.device} cannot park")
            self._change("TELESCOPE_PARK", {"PARK": True}, wait_done=False)
        logger.info("%s is parking", self.device)

    def unpark(self) -> None:
        with self._lock:
            if not self._has("TELESCOPE_PARK"):
                return
            self._change("TELESCOPE_PARK", {"UNPARK": True}, timeout=10.0)
        logger.info("%s unparked", self.device)

    def abort(self) -> None:
        """Stop every motion now (a park or a nudge); tracking is left as it is."""
        with self._lock:
            self._change("TELESCOPE_ABORT_MOTION", {"ABORT": True}, wait_done=False)
        logger.info("%s: motion aborted", self.device)

    # ---------------------------------------------------------------- nudges

    def guide(self, direction: str, milliseconds: float) -> None:
        """A guide pulse of ``milliseconds`` towards N, S, E or W, at the guide rate."""
        prop, element, _, _ = self._direction(direction)
        with self._lock:
            self._change(prop, {element: float(milliseconds)}, wait_done=False)

    def nudge_start(self, direction: str) -> None:
        """Start moving towards N, S, E or W, until nudge_stop."""
        _, _, prop, element = self._direction(direction)
        with self._lock:
            self._change(prop, {element: True})

    def nudge_stop(self, direction: str) -> None:
        _, _, prop, element = self._direction(direction)
        with self._lock:
            self._change(prop, {element: False})

    @staticmethod
    def _direction(direction: str) -> tuple:
        try:
            return DIRECTIONS[direction.strip().upper()[:1]]
        except (KeyError, AttributeError):
            raise MountError(f"not a direction: {direction!r}; use N, S, E or W") from None

    # ---------------------------------------------------------------- status

    def position(self) -> Optional[tuple]:
        """(right ascension in hours, declination in degrees) of date, or None."""
        prop = self.client.property(self.device, "EQUATORIAL_EOD_COORD")
        if prop is None:
            return None
        return prop.values.get("RA"), prop.values.get("DEC")

    def describe(self) -> str:
        if not self.client.connected:
            return f"{self.device}: connection to {self.client.describe()} lost"
        if not self.driver_connected:
            state = "driver not connected to the mount"
        elif self.parked:
            state = "parked"
        elif self.tracking:
            mode = (self.track_mode or "").replace("TRACK_", "").lower()
            state = f"tracking ({mode})" if mode else "tracking"
        else:
            state = "not tracking"
        where = "simulated" if self._simulator is not None else self.client.describe()
        return f"{self.device} on {where}: {state}"


# ------------------------------------------------------------ scheduler commands
#
# Script commands, like the relay commands: the scheduler passes the mount that
# is registered as 'mount' when the job fires.  A mount problem is reported and
# logged, but never stops the run: the cameras do not need the mount.

def _report(command: str, exc: Exception) -> None:
    hardware_problems.report("Mount", f"{command} failed: {exc}",
                             detail="the cameras keep shooting; check the mount and the INDI server")


def mount_track(mount: Mount) -> None:
    """Track at the solar rate (unparking first when needed)."""
    logger.info("mount_track")
    try:
        rate = mount.track_solar()
    except (MountError, IndiError) as exc:
        _report("mount_track", exc)
        return
    if rate != "solar":
        hardware_problems.report(
            "Mount", "the mount has no solar tracking rate, so it tracks at the sidereal rate",
            detail=f"the sun drifts about {SIDEREAL_DRIFT_ARCMIN_PER_HOUR}′ an hour in the field of view",
            severity="warning")


def mount_stop(mount: Mount) -> None:
    """Stop tracking."""
    logger.info("mount_stop")
    try:
        mount.stop_tracking()
    except (MountError, IndiError) as exc:
        _report("mount_stop", exc)


def mount_park(mount: Mount) -> None:
    """Park the mount."""
    logger.info("mount_park")
    try:
        mount.park()
    except (MountError, IndiError) as exc:
        _report("mount_park", exc)
