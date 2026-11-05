"""
USB GPS capture for Solar Eclipse Workbench.

Detects a connected USB GPS receiver (such as the VK-162 G-Mouse), reads NMEA
sentences directly via pyserial/pynmea2, and returns:

  - Latitude / longitude / altitude
  - A UTC timestamp from the GPS satellite network
  - The offset between GPS time and the computer's system clock

No gpsd installation is required.

Typical usage
-------------
::

    from solareclipseworkbench.usb_gps import get_usb_gps_worker_class

    UsbGpsWorker = get_usb_gps_worker_class()
    worker = UsbGpsWorker()
    worker.location_received.connect(on_fix)
    worker.error.connect(on_error)
    worker.status.connect(on_status)
    worker.start()

The ``location_received`` signal carries a ``dict`` with keys:
    ``lat``, ``lon``, ``alt`` (metres, 0.0 if unavailable),
    ``gps_time`` (``datetime`` UTC), ``time_offset`` (``timedelta``,
    GPS time − computer time).

Platform notes
--------------
Linux  : device usually appears as ``/dev/ttyACM0`` or ``/dev/ttyUSB0``.
macOS  : device usually appears as ``/dev/cu.usbmodem*`` or ``/dev/cu.usbserial*``.
WSL    : device appears as ``/dev/ttyACM0`` after attaching with ``usbipd``.

One-time setup (Linux / WSL only)
----------------------------------
The calling user must be in the ``dialout`` group::

    sudo usermod -aG dialout $USER   # then log out and back in
"""

from __future__ import annotations

import glob
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# USB vendor/product IDs for common GPS chipsets (integers)
# ---------------------------------------------------------------------------

_KNOWN_GPS_IDS: frozenset = frozenset(
    [
        (0x1546, 0x01A7),  # u-blox 7  – VK-162 G-Mouse and generic u-blox 7
        (0x1546, 0x01A8),  # u-blox 8
        (0x1546, 0x01A9),  # u-blox 9
        (0x067B, 0x2303),  # Prolific PL2303 – many cheap GPS adapters
        (0x10C4, 0xEA60),  # Silicon Labs CP210x UART bridge
        (0x0403, 0x6001),  # FTDI FT232R
    ]
)

_BAUD_RATE = 9600

# Number of RMC time stamps used to measure the GPS–computer clock offset
# (one per second at the usual 1 Hz update rate).
_OFFSET_SAMPLES = 5


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def find_gps_device() -> Optional[str]:
    """Return the serial port of the first detected USB GPS receiver, or ``None``.

    Three strategies are tried in order:

    1. Match by USB vendor/product ID (requires pyserial ≥ 3.x).
    2. Scan all ``ttyACM*`` / ``ttyUSB*`` / ``cu.usb*`` port names returned by
       pyserial (covers devices with un-recognised VID/PID).
    3. Glob directly in ``/dev/`` (fallback when pyserial is unavailable).
    """
    try:
        import serial.tools.list_ports as lp

        all_ports = list(lp.comports())

        # Strategy 1 – match by known VID/PID
        for port in all_ports:
            if (port.vid, port.pid) in _KNOWN_GPS_IDS:
                return port.device

        # Strategy 2 – scan common GPS port-name prefixes
        for port in all_ports:
            dev = port.device
            if any(
                dev.startswith(prefix)
                for prefix in ("/dev/ttyACM", "/dev/ttyUSB", "/dev/cu.usb")
            ):
                return dev

    except ImportError:
        pass

    # Strategy 3 – direct glob (no pyserial)
    for pattern in (
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
        "/dev/cu.usbmodem*",
        "/dev/cu.usbserial*",
    ):
        matches = glob.glob(pattern)
        if matches:
            return sorted(matches)[0]

    return None


def check_serial_permission() -> bool:
    """Return ``True`` if the current user can open serial ports without sudo.

    On macOS this always returns ``True`` (no group membership required).
    On Linux/WSL the user must be in the ``dialout`` group.
    """
    if sys.platform == "darwin":
        return True

    import grp
    import os

    try:
        dialout_gid = grp.getgrnam("dialout").gr_gid
        # Check the process's supplementary group list (fastest path)
        if dialout_gid in os.getgroups():
            return True
        # Also check by username in group member list
        username = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        return username in grp.getgrnam("dialout").gr_mem
    except (KeyError, OSError):
        # Group doesn't exist or cannot be queried – optimistically allow
        return True


def estimate_time_offset(samples) -> timedelta:
    """Return the GPS − computer clock offset from ``(gps_time, arrival_time)`` pairs.

    ``gps_time`` is the UTC time stamp in an RMC sentence and ``arrival_time``
    the computer time at which that sentence was read.  An NMEA time stamp
    refers to the start of the GPS second, but the sentence only arrives after
    the receiver has computed and transmitted it, and lines can sit in the
    serial buffer for a while.  Every sample therefore underestimates the
    offset by its latency, so the sample with the largest offset (smallest
    latency) is the best estimate.
    """
    if not samples:
        raise ValueError("At least one (gps_time, arrival_time) sample is required")
    return max(gps_time - arrival_time for gps_time, arrival_time in samples)


# ---------------------------------------------------------------------------
# Qt worker (lazy import so the module is usable without PyQt6)
# ---------------------------------------------------------------------------

def _make_usb_gps_worker():
    """Build and return the ``UsbGpsWorker`` QThread class."""
    from PyQt6.QtCore import QThread, pyqtSignal  # type: ignore

    class UsbGpsWorker(QThread):
        """QThread that reads NMEA sentences from a USB GPS and emits Qt signals.

        Signals
        -------
        location_received(data: dict)
            Emitted when a valid GPS fix is obtained.  Dict keys:
            ``lat``, ``lon``, ``alt`` (metres), ``gps_time`` (datetime UTC),
            ``time_offset`` (timedelta = GPS time − computer time).
        error(message: str)
            Emitted when the device cannot be opened or an unrecoverable error
            occurs.
        status(message: str)
            Status updates suitable for display in the UI.
        """

        location_received = pyqtSignal(dict)
        error = pyqtSignal(str)
        status = pyqtSignal(str)

        def __init__(
            self,
            device: Optional[str] = None,
            baudrate: int = _BAUD_RATE,
            fix_timeout: float = 120.0,
            parent=None,
        ):
            super().__init__(parent)
            self._device = device
            self._baudrate = baudrate
            self._fix_timeout = fix_timeout
            self._stop_event = threading.Event()

        def stop(self) -> None:
            """Ask the worker thread to stop reading (non-blocking)."""
            self._stop_event.set()

        def run(self) -> None:
            # --- dependency checks ---
            try:
                import serial  # noqa: F401 (pyserial)
            except ImportError:
                self.error.emit(
                    "pyserial is not installed.\n"
                    "Install it with:  pip install pyserial"
                )
                return

            try:
                import pynmea2  # noqa: F401
            except ImportError:
                self.error.emit(
                    "pynmea2 is not installed.\n"
                    "Install it with:  pip install pynmea2"
                )
                return

            import serial
            import pynmea2

            # --- permission check ---
            if not check_serial_permission():
                self.error.emit(
                    "No permission to open serial port.\n\n"
                    "On Linux/WSL, add your user to the dialout group:\n\n"
                    "    sudo usermod -aG dialout $USER\n\n"
                    "Then log out and log back in (or reboot)."
                )
                return

            # --- device discovery ---
            if not self._device:
                try:
                    from solareclipseworkbench import wsl_usb
                    wsl_usb.attach_shared_devices()
                except Exception:
                    pass  # discovery carries on with what is already attached
            device = self._device or find_gps_device()
            if device is None:
                self.error.emit(
                    "No USB GPS device found.\n\n"
                    "Make sure the GPS receiver is plugged in and recognised by the OS.\n"
                    "Expected: /dev/ttyACM0 on Linux/WSL, /dev/cu.usbmodem* on macOS."
                )
                return

            self.status.emit(f"Opening GPS device: {device} …")

            try:
                ser = serial.Serial(device, self._baudrate, timeout=1)
            except serial.SerialException as exc:
                self.error.emit(f"Could not open {device}:\n{exc}")
                return

            # Discard sentences buffered before the port was opened: their time
            # stamps are stale and would make the GPS clock look behind.
            try:
                ser.reset_input_buffer()
            except (serial.SerialException, OSError):
                pass

            self.status.emit(
                "Waiting for GPS fix (may take 1–3 minutes in open sky)…"
            )

            lat: Optional[float] = None
            lon: Optional[float] = None
            alt: float = 0.0
            gps_time: Optional[datetime] = None
            time_samples: list = []  # (RMC gps_time, computer arrival time)
            total_lines = 0
            nmea_lines = 0
            parsed_lines = 0
            last_activity = datetime.now(timezone.utc)
            last_progress_emit = datetime.now(timezone.utc)
            last_sentence_type = "none"
            last_gga_fix_quality = 0
            last_gga_sats = 0
            last_rmc_status = "?"

            try:
                start = datetime.now(timezone.utc)
                while not self._stop_event.is_set():
                    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                    if elapsed > self._fix_timeout:
                        if nmea_lines == 0:
                            detail = (
                                "No NMEA data received from the serial device. "
                                "Check device path, baud rate, cable, and permissions."
                            )
                        else:
                            detail = (
                                f"Received {nmea_lines} NMEA lines "
                                f"({parsed_lines} parsed). Last sentence: {last_sentence_type}. "
                                f"GGA quality={last_gga_fix_quality}, sats={last_gga_sats}, "
                                f"RMC status={last_rmc_status}."
                            )
                        self.error.emit(
                            "GPS fix timeout.\n\n"
                            f"No valid fix received within {int(self._fix_timeout)} s.\n"
                            "Make sure the GPS antenna has a clear view of the sky.\n"
                            f"{detail}"
                        )
                        return

                    try:
                        raw = ser.readline()
                    except serial.SerialException as exc:
                        self.error.emit(f"Serial read error:\n{exc}")
                        return

                    # Computer time at which this line arrived, used for the clock offset
                    arrival_time = datetime.now(timezone.utc)

                    total_lines += 1
                    if raw:
                        last_activity = arrival_time

                    line = raw.decode("ascii", errors="replace").strip()
                    if not line.startswith("$"):
                        if (
                            datetime.now(timezone.utc) - last_progress_emit
                        ).total_seconds() >= 2.0:
                            idle = (
                                datetime.now(timezone.utc) - last_activity
                            ).total_seconds()
                            self.status.emit(
                                "Waiting for NMEA sentences... "
                                f"raw lines={total_lines}, idle={idle:.0f}s"
                            )
                            last_progress_emit = datetime.now(timezone.utc)
                        continue

                    nmea_lines += 1

                    try:
                        msg = pynmea2.parse(line)
                    except pynmea2.ParseError:
                        if (
                            datetime.now(timezone.utc) - last_progress_emit
                        ).total_seconds() >= 2.0:
                            self.status.emit(
                                "Receiving GPS data, but parsing is not stable yet... "
                                f"nmea={nmea_lines}, parsed={parsed_lines}"
                            )
                            last_progress_emit = datetime.now(timezone.utc)
                        continue

                    parsed_lines += 1
                    last_sentence_type = getattr(msg, "sentence_type", "?")

                    # GGA sentence: position + altitude + fix quality
                    if isinstance(msg, pynmea2.GGA):
                        try:
                            last_gga_fix_quality = int(msg.gps_qual) if msg.gps_qual else 0
                        except (TypeError, ValueError):
                            last_gga_fix_quality = 0
                        try:
                            last_gga_sats = int(msg.num_sats) if msg.num_sats else 0
                        except (TypeError, ValueError):
                            last_gga_sats = 0

                        if msg.gps_qual and int(msg.gps_qual) > 0:
                            lat = msg.latitude
                            lon = msg.longitude
                            if msg.altitude is not None:
                                try:
                                    alt = float(msg.altitude)
                                except (ValueError, TypeError):
                                    alt = 0.0

                    # RMC sentence: position + precise UTC time + valid flag
                    elif isinstance(msg, pynmea2.RMC):
                        last_rmc_status = msg.status or "?"
                        if msg.status == "A":
                            lat = msg.latitude
                            lon = msg.longitude
                            if msg.datetime:
                                gps_time = msg.datetime.replace(tzinfo=timezone.utc)
                                time_samples.append((gps_time, arrival_time))

                    if (
                        datetime.now(timezone.utc) - last_progress_emit
                    ).total_seconds() >= 2.0:
                        idle = (datetime.now(timezone.utc) - last_activity).total_seconds()
                        if lat is not None and lon is not None and time_samples:
                            self.status.emit(
                                "GPS fix acquired, measuring clock offset "
                                f"({len(time_samples)}/{_OFFSET_SAMPLES})…"
                            )
                        else:
                            self.status.emit(
                                "GPS stream active. "
                                f"nmea={nmea_lines}, parsed={parsed_lines}, "
                                f"GGA quality={last_gga_fix_quality}, sats={last_gga_sats}, "
                                f"RMC={last_rmc_status}, idle={idle:.0f}s"
                            )
                        last_progress_emit = datetime.now(timezone.utc)

                    # Emit once we have a valid position and enough GPS time stamps
                    if (
                        lat is not None
                        and lon is not None
                        and len(time_samples) >= _OFFSET_SAMPLES
                    ):
                        time_offset = estimate_time_offset(time_samples)
                        self.location_received.emit(
                            {
                                "lat": lat,
                                "lon": lon,
                                "alt": alt,
                                "gps_time": gps_time,
                                "time_offset": time_offset,
                            }
                        )
                        return
            finally:
                ser.close()

    return UsbGpsWorker


# Lazy singleton so PyQt6 is only imported on demand
_UsbGpsWorker = None


def get_usb_gps_worker_class():
    """Return the ``UsbGpsWorker`` class (requires PyQt6)."""
    global _UsbGpsWorker
    if _UsbGpsWorker is None:
        _UsbGpsWorker = _make_usb_gps_worker()
    return _UsbGpsWorker
