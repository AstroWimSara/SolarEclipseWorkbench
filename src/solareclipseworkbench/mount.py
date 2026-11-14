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
import math
import threading
import time
from typing import Optional

from solareclipseworkbench import hardware_problems, wsl_usb
from solareclipseworkbench.indi_client import DEFAULT_PORT, IndiClient, IndiError

logger = logging.getLogger(__name__)

#: Host name that starts the built-in simulated mount instead of connecting to a server
SIMULATED_HOST = "simulated"

#: Guide rate of the built-in simulated mount, as a multiple of the sidereal rate.  Faster than
#: a real mount (0.5× is common), so calibrating and centring can be tried in seconds, not minutes.
SIMULATED_GUIDE_RATE = 2.0

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


#: A location sent this far from the one the mount had is worth a warning: an alt-azimuth mount
#: computes its tracking from it, and the `Location` window may hold the eclipse site, not this one
SITE_WARNING_KM = 50.0


def distance_km(a: tuple, b: tuple) -> float:
    """Great-circle distance between two (latitude, longitude) in degrees."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def format_site(latitude: float, longitude: float) -> str:
    """'50.83° N, 4.86° E'."""
    longitude = (longitude + 180.0) % 360.0 - 180.0
    return (f"{abs(latitude):.2f}° {'N' if latitude >= 0 else 'S'}, "
            f"{abs(longitude):.2f}° {'E' if longitude >= 0 else 'W'}")


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


#: The address of a mount on its own Wi-Fi network (the mount is the access point)
SKYWATCHER_WIFI = "192.168.4.1:11880"
IOPTRON_WIFI = "10.10.100.254:8899"


def network_address(connection: str) -> Optional[tuple]:
    """(host, port) when a connection is a network address ("192.168.4.1:8899", "tcp://mount.local:8899"),
    None when it is a serial port ("/dev/ttyUSB0", "COM3")."""
    text = (connection or "").strip()
    if text.lower().startswith(("tcp://", "udp://")):
        text = text.split("://", 1)[1]
    elif "/" in text or "\\" in text or text.upper().startswith("COM"):
        return None
    if text.count(":") != 1:
        return None
    host, port = text.split(":")
    try:
        return host.strip(), int(port)
    except ValueError:
        return None


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

    #: How long tracking must stay on after it was switched on, before it counts (see _tracking_holds)
    TRACK_SETTLE_S = 1.5

    #: How often tracking is switched on before giving up, when the driver switches it off again each time
    TRACK_ATTEMPTS = 4

    def __init__(self, client: IndiClient, device: str, simulator=None):
        self.client = client
        self.device = device
        self._simulator = simulator
        self._lock = threading.RLock()
        self._nudger: Optional["Nudger"] = None
        #: Swap N and S, or E and W, for the nudge buttons, when the mount moves the other way than
        #: the button says.  Guide pulses and the centring are not swapped: the calibration measures
        #: which way they move the sun.
        self.reverse_ns = False
        self.reverse_we = False
        #: The location the mount had before send_site replaced it (None when it had none), and how far
        #: that is from the location sent
        self.previous_site: Optional[tuple] = None
        self.site_moved_km: Optional[float] = None

    @property
    def identity(self) -> str:
        """Which mount this is, for a calibration: the name INDI gives it, and whether it is sew's simulator.

        sew's simulated mount and INDI's telescope simulator have the same name,
        but turn the sun differently in the frame.
        """
        return f"{self.device} (simulated by sew)" if self._simulator is not None else self.device

    # ------------------------------------------------------------ connection

    @classmethod
    def open(cls, address: str = "localhost", device: Optional[str] = None, device_port: Optional[str] = None,
             timeout: float = 15.0, network: bool = False) -> "Mount":
        """Connect to the INDI server, pick the mount and connect its driver to the mount.

        Args:
            - address: ``host[:port]`` of the INDI server, or ``simulated``
            - device: Name of the mount on the server; may be left out when there is only one
            - device_port: How the driver reaches the mount: a serial port on the
                           server's machine (e.g. /dev/ttyUSB0), or host:port of a
                           mount on the network (Wi-Fi).  When not given, the
                           driver's own port search is switched on, if it has one.
            - timeout: Seconds to wait for the driver to connect to the mount
            - network: The mount is on Wi-Fi.  Without a device_port, the driver
                       is then put in network mode with its own default address
                       (192.168.4.1:11880 for a SkyWatcher), instead of searching
                       its serial ports.
        """
        simulator = None
        if address.strip().lower() == SIMULATED_HOST:
            from solareclipseworkbench.indi_simulator import SimulatedIndiServer
            simulator = SimulatedIndiServer(guide_rate=SIMULATED_GUIDE_RATE)
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
            mount.connect_driver(device_port, timeout, network)
        except BaseException:
            client.close()
            if simulator is not None:
                simulator.close()
            raise
        logger.info("Mount ready: %s", mount.describe())
        return mount

    def connect_driver(self, device_port: Optional[str] = None, timeout: float = 15.0,
                       network: bool = False) -> None:
        """Make the driver connect to the mount, if it is not connected yet."""
        with self._lock:
            if self.driver_connected:
                return
            self._set_connection(device_port, network)
            try:
                self._change("CONNECTION", {"CONNECT": True}, timeout=timeout)
            except MountError as exc:
                if device_port or network:
                    raise
                raise MountError(f"{exc}\n\nFor a mount on Wi-Fi, give its address as host:port, e.g. "
                                 f"{SKYWATCHER_WIFI} (SkyWatcher) or {IOPTRON_WIFI} (iOptron)") from exc
            # The driver defines the telescope properties once it is connected
            if not self.client.wait_for(
                    lambda: self._has("EQUATORIAL_EOD_COORD"), 5.0):
                raise MountError(f"{self.device} connected, but does not report its position")

    def _set_connection(self, connection: Optional[str], network: bool = False) -> None:
        """Tell the driver how to reach the mount (the standard INDI connection properties)."""
        if not connection and network:
            self._use_driver_address()
            return
        if not connection:
            if self._has("DEVICE_AUTO_SEARCH"):
                try:
                    self._change("DEVICE_AUTO_SEARCH", {"INDI_ENABLED": True})
                except MountError as exc:
                    logger.info("%s: the port search could not be switched on: %s", self.device, exc)
            return
        network = network_address(connection)
        mode = self.client.property(self.device, "CONNECTION_MODE")
        if network is not None:
            host, port = network
            if mode is not None and "CONNECTION_TCP" in mode.values:
                self._change("CONNECTION_MODE", {"CONNECTION_TCP": True})
                # The driver defines the network properties once it is in that mode
                self.client.wait_for(lambda: self._has("DEVICE_ADDRESS"), 3.0)
            if not self._has("DEVICE_ADDRESS"):
                raise MountError(f"{self.device} cannot connect over the network; give its serial port instead")
            self._change("DEVICE_ADDRESS", {"ADDRESS": host, "PORT": str(port)})
        else:
            if mode is not None and "CONNECTION_SERIAL" in mode.values:
                self._change("CONNECTION_MODE", {"CONNECTION_SERIAL": True})
                self.client.wait_for(lambda: self._has("DEVICE_PORT"), 3.0)
            if self._has("DEVICE_PORT"):
                self._change("DEVICE_PORT", {"PORT": connection})

    def _use_driver_address(self) -> None:
        """Put the driver in network mode, with the address it has (its default, or the one saved in it)."""
        mode = self.client.property(self.device, "CONNECTION_MODE")
        if mode is None or "CONNECTION_TCP" not in mode.values:
            raise MountError(f"{self.device} cannot connect over the network; give its serial port instead")
        if not mode.values.get("CONNECTION_TCP"):
            self._change("CONNECTION_MODE", {"CONNECTION_TCP": True})
            self.client.wait_for(lambda: self._has("DEVICE_ADDRESS"), 3.0)
        host = str(self.client.value(self.device, "DEVICE_ADDRESS", "ADDRESS", "") or "").strip()
        if not host:
            raise MountError(f"{self.device} has no network address of the mount: give it as host:port, "
                             f"e.g. {SKYWATCHER_WIFI} (SkyWatcher) or {IOPTRON_WIFI} (iOptron)")
        logger.info("%s: connecting over the network to %s:%s", self.device, host,
                    self.client.value(self.device, "DEVICE_ADDRESS", "PORT", ""))

    @property
    def driver_connected(self) -> bool:
        return bool(self.client.value(self.device, "CONNECTION", "CONNECT", False))

    @property
    def connected(self) -> bool:
        return self.client.connected and self.driver_connected

    def close(self) -> None:
        """Close the connection to the INDI server.  The mount keeps tracking.

        A nudge that is still running is stopped first.
        """
        if self._nudger is not None:
            self._nudger.stop()
            self._nudger = None
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
                self.previous_site = self._site()
                self.site_moved_km = (distance_km(self.previous_site, (latitude, longitude))
                                      if self.previous_site is not None else None)
                if self.site_moved_km is not None and self.site_moved_km > SITE_WARNING_KM:
                    logger.warning("%s had the location %s, %.0f km from the one sent (%s)", self.device,
                                   format_site(*self.previous_site), self.site_moved_km,
                                   format_site(latitude, longitude))
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

    def _site(self) -> Optional[tuple]:
        """(latitude, longitude) the mount has now, east positive; None when it has none (0, 0)."""
        prop = self.client.property(self.device, "GEOGRAPHIC_COORD")
        if prop is None:
            return None
        latitude, longitude = prop.values.get("LAT"), prop.values.get("LONG")
        if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
            return None
        return latitude, (longitude + 180.0) % 360.0 - 180.0

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

        Raises MountError when the driver refuses, or keeps switching tracking off
        again right after it was switched on (it is tried TRACK_ATTEMPTS times).
        """
        with self._lock:
            if self.parked:
                self.unpark()
            rate, mode = "sidereal", None
            if self.has_solar_rate:
                rate, mode = "solar", "TRACK_SOLAR"
            elif self._has("TELESCOPE_TRACK_MODE") and "TRACK_SIDEREAL" in \
                    self.client.property(self.device, "TELESCOPE_TRACK_MODE").values:
                mode = "TRACK_SIDEREAL"
            if not self._has("TELESCOPE_TRACK_STATE"):
                if mode:
                    self._change("TELESCOPE_TRACK_MODE", {mode: True})
            else:
                for attempt in range(1, self.TRACK_ATTEMPTS + 1):
                    if mode:
                        self._change("TELESCOPE_TRACK_MODE", {mode: True})
                    # INDI drivers keep this Busy for as long as the mount tracks: the first answer is the answer
                    self._change("TELESCOPE_TRACK_STATE", {"TRACK_ON": True}, wait_done=False)
                    if self._tracking_holds():
                        break
                    logger.warning("%s switched tracking off again right after it was switched on "
                                   "(try %d of %d)", self.device, attempt, self.TRACK_ATTEMPTS)
                else:
                    raise MountError(f"{self.device} does not keep tracking: the driver switched tracking off "
                                     f"again each of the {self.TRACK_ATTEMPTS} times it was switched on")
        logger.info("%s tracks at the %s rate", self.device, rate)
        return rate

    def _tracking_holds(self) -> bool:
        """Whether tracking, just switched on, stays on.

        Some drivers answer "tracking" and switch it off again a moment later, when
        the mount did not take the command: the iOptron v3 driver with a HAZ31 does
        it twice before tracking.  Tracking that goes off and comes back by itself
        within TRACK_SETTLE_S counts as holding: the same driver switches it off
        for a second now and then while the mount tracks.
        """
        went_off = self.client.wait_for(lambda: not self.tracking, self.TRACK_SETTLE_S)
        if not self.client.connected:
            raise MountError(f"the connection to the INDI server at {self.client.describe()} was lost")
        return not went_off or self.client.wait_for(lambda: self.tracking, self.TRACK_SETTLE_S)

    def stop_tracking(self) -> None:
        with self._lock:
            if not self._has("TELESCOPE_TRACK_STATE"):
                raise MountError(f"{self.device} cannot switch tracking off")
            self._change("TELESCOPE_TRACK_STATE", {"TRACK_OFF": True}, wait_done=False)
        logger.info("%s stopped tracking", self.device)

    def park(self) -> None:
        """Start parking.  The mount moves to its park position; this returns before it gets there.

        A tracking mount stops tracking first, and the park waits until its motors
        stand still: the AZ-GTi driver refuses a park while they run ("Motor not
        stopped") and then answers nothing for a minute.
        """
        with self._lock:
            if not self._has("TELESCOPE_PARK"):
                raise MountError(f"{self.device} cannot park")
            if self.tracking:
                self._change("TELESCOPE_TRACK_STATE", {"TRACK_OFF": True}, wait_done=False)
                logger.info("%s stopped tracking, to park", self.device)
            if not self._standing_still():
                self._wait_until_still()
            self._change("TELESCOPE_PARK", {"PARK": True}, wait_done=False)
        logger.info("%s is parking", self.device)

    #: Axis states some drivers have (the SkyWatcher drivers), with FULL_STOP on when the axis stands still
    AXIS_STATES = ("AXIS_ONE_STATE", "AXIS_TWO_STATE")

    #: How long a park waits for the motors to stop after tracking was switched off
    STOP_TIMEOUT_S = 10.0

    #: How long the motors must stand still before the park is sent (a tracking driver moves them in steps)
    STILL_S = 0.5

    def _standing_still(self) -> bool:
        """Not tracking, and every axis the driver reports on at full stop."""
        if self.tracking:
            return False
        return all(self.client.value(self.device, name, "FULL_STOP", True) for name in self.AXIS_STATES)

    def _wait_until_still(self) -> None:
        """Wait until the motors have stood still for STILL_S; give up after STOP_TIMEOUT_S."""
        deadline = time.monotonic() + self.STOP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.client.wait_for(self._standing_still, max(0.0, deadline - time.monotonic())) and \
                    not self.client.wait_for(lambda: not self._standing_still(), self.STILL_S):
                return
            if not self.client.connected:
                raise MountError(f"the connection to the INDI server at {self.client.describe()} was lost")
        logger.warning("%s: the motors did not stop within %.0f s; parking anyway", self.device,
                       self.STOP_TIMEOUT_S)

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

    def guide_rate(self) -> Optional[tuple]:
        """(right ascension, declination) guide rate as multiples of the sidereal rate; None when unknown."""
        prop = self.client.property(self.device, "GUIDE_RATE")
        if prop is None:
            return None
        ra, dec = prop.values.get("RA_GUIDE_RATE"), prop.values.get("DE_GUIDE_RATE")
        if ra is None and dec is None:
            return None
        return ra if ra is not None else dec, dec if dec is not None else ra

    def nudge_start(self, direction: str) -> None:
        """Start moving towards N, S, E or W, until nudge_stop."""
        _, _, prop, element = self._direction(direction)
        with self._lock:
            # Busy for as long as the mount moves: the first answer is the answer
            self._change(prop, {element: True}, wait_done=False)

    def nudge_stop(self, direction: str) -> None:
        _, _, prop, element = self._direction(direction)
        with self._lock:
            self._change(prop, {element: False}, wait_done=False)

    def slew_rates(self) -> list:
        """The rates the mount can be nudged at, slowest first: [(name, label), ...].

        Empty when the driver has no TELESCOPE_SLEW_RATE; the mount then moves
        at whatever rate its driver uses.
        """
        prop = self.client.property(self.device, "TELESCOPE_SLEW_RATE")
        if prop is None:
            return []
        return [(name, prop.labels.get(name, name)) for name in prop.values]

    @property
    def slew_rate(self) -> Optional[str]:
        prop = self.client.property(self.device, "TELESCOPE_SLEW_RATE")
        if prop is None:
            return None
        on = prop.on_switches()
        return on[0] if on else None

    def set_slew_rate(self, rate: str) -> None:
        """Set the rate of the nudges (a name from ``slew_rates()``)."""
        names = [name for name, _ in self.slew_rates()]
        if rate not in names:
            raise MountError(f"{self.device} has no slew rate {rate!r}"
                             + (f"; it has {', '.join(names)}" if names else ""))
        with self._lock:
            if self.slew_rate != rate:
                self._change("TELESCOPE_SLEW_RATE", {rate: True})

    @property
    def nudger(self) -> "Nudger":
        """The nudger of this mount, for the N/S/E/W buttons."""
        with self._lock:
            if self._nudger is None:
                self._nudger = Nudger(self)
            return self._nudger

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


class Nudger:
    """Moves the mount while a button is held, and stops it by itself when the holding stops.

    A button sends ``hold()`` when it is pressed and again every few tenths of a
    second while it stays pressed, and ``release()`` when it is let go.  Each
    ``hold()`` keeps the mount moving for ``hold_s`` more.  When the release is
    lost (the window loses the mouse, the phone loses the network), the mount
    stops by itself at most ``hold_s`` later.

    The INDI calls run on a thread of their own, so a button never waits for the
    mount.  The two axes are independent: N/S and E/W can move at the same time;
    the opposite direction on the same axis replaces the first one.
    """

    #: How long one hold() keeps the mount moving
    HOLD_S = 0.6

    _AXES = {"N": "NS", "S": "NS", "E": "WE", "W": "WE"}

    def __init__(self, mount: Mount):
        self.mount = mount
        self._cond = threading.Condition()
        self._wanted: dict = {}          # axis → (direction, deadline)
        self._moving: dict = {}          # axis → direction that was started
        self._rate: Optional[str] = None
        self._abort = False
        self._running = True
        self._last_error = ""
        self._thread = threading.Thread(target=self._run, name=f"nudge-{mount.device}", daemon=True)
        self._thread.start()

    _OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}

    def _axis(self, direction: str) -> tuple:
        """(direction to move the mount in, axis) for a button, swapped when the mount reverses that axis."""
        key = (direction or "").strip().upper()[:1]
        if key not in self._AXES:
            raise MountError(f"not a direction: {direction!r}; use N, S, E or W")
        axis = self._AXES[key]
        if getattr(self.mount, "reverse_ns" if axis == "NS" else "reverse_we", False):
            key = self._OPPOSITE[key]
        return key, axis

    def hold(self, direction: str, rate: Optional[str] = None, hold_s: Optional[float] = None) -> None:
        """Move towards ``direction`` (N, S, E or W) for ``hold_s`` more, at ``rate`` when given."""
        key, axis = self._axis(direction)
        with self._cond:
            self._wanted[axis] = (key, time.monotonic() + (hold_s or self.HOLD_S))
            if rate:
                self._rate = rate
            self._cond.notify_all()

    def release(self, direction: Optional[str] = None) -> None:
        """Stop moving towards ``direction``, or in every direction when it is None."""
        with self._cond:
            if direction is None:
                self._wanted.clear()
            else:
                key, axis = self._axis(direction)
                if self._wanted.get(axis, (None,))[0] == key:
                    del self._wanted[axis]
            self._cond.notify_all()

    def abort(self) -> None:
        """Stop every nudge, and every other motion of the mount (a park as well)."""
        with self._cond:
            self._wanted.clear()
            self._abort = True
            self._cond.notify_all()

    @property
    def moving(self) -> list:
        """The directions the mount is being moved in now."""
        with self._cond:
            return sorted(self._moving.values())

    @property
    def last_error(self) -> str:
        return self._last_error

    def stop(self, timeout: float = 3.0) -> None:
        """Stop every nudge and end the thread."""
        with self._cond:
            self._wanted.clear()
            self._running = False
            self._cond.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------- the thread

    def _run(self) -> None:
        while True:
            with self._cond:
                now = time.monotonic()
                for axis in [a for a, (_, deadline) in self._wanted.items() if deadline <= now]:
                    del self._wanted[axis]
                wanted = {axis: key for axis, (key, _) in self._wanted.items()}
                rate, self._rate = self._rate, None
                abort, self._abort = self._abort, False
                running = self._running
            self._apply(wanted, rate, abort)
            if not running:
                return
            with self._cond:
                deadlines = [deadline for _, deadline in self._wanted.values()]
                wait = min(deadlines) - time.monotonic() if deadlines else 1.0
                if not (self._abort or self._rate or not self._running
                        or {a: k for a, (k, _) in self._wanted.items()} != self._moving):
                    self._cond.wait(max(0.01, wait))

    def _apply(self, wanted: dict, rate: Optional[str], abort: bool) -> None:
        """Make the motion of the mount what is wanted.  Runs on the nudge thread only."""
        mount = self.mount
        try:
            if abort:
                self._moving.clear()
                mount.abort()
                return
            if rate:
                mount.set_slew_rate(rate)
            for axis in ("NS", "WE"):
                current, target = self._moving.get(axis), wanted.get(axis)
                if current == target:
                    continue
                if current is not None:
                    # Forget it first: a stop that fails must not be retried for ever
                    del self._moving[axis]
                    mount.nudge_stop(current)
                if target is not None:
                    mount.nudge_start(target)
                    self._moving[axis] = target
            self._last_error = ""
        except Exception as exc:
            # Anything else than a MountError/IndiError is a bug, but it must not end the nudge thread:
            # the buttons would then do nothing for the rest of the session, without a word
            if not isinstance(exc, (MountError, IndiError)):
                logger.exception("Unexpected error while nudging the mount")
            if str(exc) != self._last_error:
                logger.warning("Mount nudge failed: %s", exc)
                hardware_problems.report("Mount", "a nudge of the mount failed", detail=str(exc),
                                         severity="warning")
            self._last_error = str(exc)
            # Do not try to start again until the button is pressed again
            with self._cond:
                self._wanted.clear()


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
    except Exception as exc:
        # A bug, or a device that is not a Mount: still only this command fails, and it is shown
        logger.exception("mount_track failed")
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
        return
    except Exception as exc:
        # A bug, or a device that is not a Mount: still only this command fails, and it is shown
        logger.exception("mount_stop failed")
        _report("mount_stop", exc)


def mount_park(mount: Mount) -> None:
    """Park the mount."""
    logger.info("mount_park")
    try:
        mount.park()
    except (MountError, IndiError) as exc:
        _report("mount_park", exc)
        return
    except Exception as exc:
        # A bug, or a device that is not a Mount: still only this command fails, and it is shown
        logger.exception("mount_park failed")
        _report("mount_park", exc)
