"""The mount driver interface.

A driver is a class derived from :class:`MountDriver` that talks to one family
of mounts.  The rest of the application uses only this interface.  To add a new
mount, write a driver and register it.  The GUI, the scheduler and the eclipse
scripts do not change.

Angles cross this interface in one form only: right ascension in hours,
declination in degrees, altitude and azimuth in degrees.  Sexagesimal strings are
a wire format, and each driver converts them itself.
"""

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Tuple

from skyfield.api import load

from solareclipseworkbench.discovery import Candidate

logger = logging.getLogger(__name__)


class MountError(Exception):
    """Raised when a mount cannot be reached, or rejects a command."""


class MountNotSupported(MountError):
    """Raised when a driver is asked for something its mount cannot do."""


@dataclass(frozen=True)
class Capabilities:
    """What a particular mount can actually do.

    The console and GUI consult this instead of catching exceptions, so an
    unsupported feature can be hidden rather than offered and then refused.
    """

    goto: bool = True
    sync: bool = True
    park: bool = True
    tracking_toggle: bool = True
    tracking_rates: Tuple[str, ...] = ("sidereal", "solar", "lunar")
    manual_move: bool = True
    rate_presets: Tuple[str, ...] = ("guide", "center", "find", "fast", "slew")
    pulse_guide: bool = True
    altaz_readout: bool = True
    site_time: bool = False


@dataclass
class MountStatus:
    """A driver-independent snapshot of what the mount is doing.

    ``raw`` carries whatever the controller actually said, so the bench console
    can show detail this structure does not model.
    """

    raw: str = ""
    connected: bool = True
    tracking: bool = False
    slewing: bool = False
    parked: bool = False
    parking: bool = False
    park_failed: bool = False
    at_home: bool = False
    homing: bool = False
    pulse_guiding: bool = False
    tracking_rate: str = "sidereal"
    pier_side: str = "none"
    mount_type: str = "unknown"
    error_code: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def summary(self) -> str:
        """One line fit for a status bar."""
        if not self.connected:
            return "disconnected"
        if self.parked:
            state = "parked"
        elif self.slewing:
            state = "slewing"
        elif self.tracking:
            state = f"tracking {self.tracking_rate}"
        else:
            state = "idle"

        bits = [state]
        if self.at_home:
            bits.append("at home")
        if self.park_failed:
            bits.append("PARK FAILED")
        if self.pier_side != "none":
            bits.append(f"pier {self.pier_side}")
        return ", ".join(bits)


class MountDriver(ABC):
    """Base class for every mount driver.

    Subclasses set :attr:`name` and implement the abstract methods.  Anything the
    mount cannot do should raise :class:`MountNotSupported` and be declared false
    in :attr:`capabilities`, so callers can check before asking.
    """

    #: Short identifier used in configuration and on the command line.
    name: str = ""
    #: Human-readable name for menus.
    display_name: str = ""
    #: One line describing what hardware this driver speaks to.
    description: str = ""
    #: What this driver's mounts can do.
    capabilities: Capabilities = Capabilities()

    def __init__(self, **config):
        self.config = config

    # ------------------------------------------------------------- discovery

    @classmethod
    def discover(cls) -> list:
        """Places this driver's mounts might be found.

        Default is none, which is correct for drivers that need an explicit
        address.  Returning candidates is a convenience, never a guarantee.
        """
        return []

    # ------------------------------------------------------------ connection

    @abstractmethod
    def connect(self) -> None:
        """Open the link.  Raise :class:`MountError` if it cannot be opened."""

    @abstractmethod
    def close(self) -> None:
        """Close the link.  Must be safe to call more than once."""

    @abstractmethod
    def describe(self) -> str:
        """Identify the connected mount, for logs and the status bar."""

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    # ---------------------------------------------------------------- state

    @abstractmethod
    def status(self) -> MountStatus:
        """What the mount is doing right now."""

    @abstractmethod
    def get_radec(self) -> Tuple[float, float]:
        """Current pointing as (ra_hours, dec_degrees)."""

    def get_altaz(self) -> Tuple[float, float]:
        """Current pointing as (altitude_degrees, azimuth_degrees)."""
        raise MountNotSupported(f"{self.name} cannot report altitude and azimuth")

    # ----------------------------------------------------------------- goto

    @abstractmethod
    def goto(self, ra_hours: float, dec_degrees: float, wait: bool = False,
             timeout: float = 180.0) -> None:
        """Slew to a target.  Raise :class:`MountError` with the reason if refused."""

    @abstractmethod
    def abort(self) -> None:
        """Stop all motion immediately."""

    def sync(self, ra_hours: float, dec_degrees: float) -> None:
        """Tell the mount it is already pointing at these coordinates."""
        raise MountNotSupported(f"{self.name} cannot sync")

    def wait_for_slew(self, timeout: float = 180.0) -> bool:
        """Block until a slew finishes.  False if still slewing at timeout."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if not self.status().slewing:
                return True
            time.sleep(0.5)
        return False

    def goto_sun(self, when=None, wait: bool = False, timeout: float = 180.0) -> Tuple[float, float]:
        """Slew to the Sun and return the coordinates used."""
        ra_hours, dec_degrees = sun_radec(when)
        self.goto(ra_hours, dec_degrees, wait=wait, timeout=timeout)
        return ra_hours, dec_degrees

    # ------------------------------------------------------------- tracking

    @abstractmethod
    def tracking_on(self) -> bool: ...

    @abstractmethod
    def tracking_off(self) -> bool: ...

    def set_tracking_rate(self, rate: str) -> None:
        """Select a tracking rate by name.

        Use solar for an eclipse.  From first to last contact, the sidereal
        rate lets the Sun move out of the field of a long lens.
        """
        raise MountNotSupported(f"{self.name} cannot change tracking rate")

    def tracking_rate_name(self) -> Optional[str]:
        """The rate at which the mount tracks, or None if it cannot be read.

        The driver reads the rate from the controller.  It does not return the
        rate that it sent last, because the controller can use another rate.
        """
        return None

    # ------------------------------------------------------------ site & time

    def set_site(self, latitude_deg: float, longitude_deg: float,
                 elevation_m: Optional[float] = None) -> None:
        """Tell the mount where it stands.  Longitude is degrees east-positive,
        like everywhere else in this program; drivers convert to their wire
        convention themselves."""
        raise MountNotSupported(f"{self.name} cannot be told its site")

    def set_datetime(self, when=None) -> None:
        """Set the mount's clock.  ``None`` means this computer's time, now."""
        raise MountNotSupported(f"{self.name} cannot be told the time")

    # -------------------------------------------------------- manual motion

    def move(self, direction: str) -> None:
        raise MountNotSupported(f"{self.name} cannot be moved manually")

    def stop_move(self, direction: Optional[str] = None) -> None:
        raise MountNotSupported(f"{self.name} cannot be moved manually")

    def set_rate(self, rate: str) -> None:
        raise MountNotSupported(f"{self.name} has no rate presets")

    def pulse_guide(self, direction: str, milliseconds: int) -> bool:
        raise MountNotSupported(f"{self.name} cannot pulse guide")

    # -------------------------------------------------------------- parking

    def park(self) -> bool:
        raise MountNotSupported(f"{self.name} cannot park")

    def unpark(self) -> bool:
        raise MountNotSupported(f"{self.name} cannot park")

    def set_park_here(self) -> bool:
        raise MountNotSupported(f"{self.name} cannot set a park position")

    # ---------------------------------------------------------- diagnostics

    def raw(self, command: str, **kwargs) -> str:
        """Send a driver-specific command verbatim, for bench debugging."""
        raise MountNotSupported(f"{self.name} has no raw command channel")


# ---------------------------------------------------------------- coordinates


def format_ra(hours: float) -> str:
    """Right ascension as ``HH:MM:SS``."""
    hours = hours % 24.0
    h = int(hours)
    remainder = (hours - h) * 60.0
    m = int(remainder)
    s = int(round((remainder - m) * 60.0))
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, h = 0, (h + 1) % 24
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_dec(degrees: float) -> str:
    """Declination as ``sDD*MM:SS``."""
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
    return f"{sign}{d:02d}*{m:02d}:{s:02d}"


def parse_ra(text: str) -> float:
    """Parse ``HH:MM:SS(.sss)`` or ``HH:MM.T`` into hours."""
    text = text.strip().rstrip("#")
    parts = [p for p in re.split(r"[:]", text) if p]
    try:
        if len(parts) == 2:
            return float(parts[0]) + float(parts[1]) / 60.0
        if len(parts) == 3:
            return float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0
    except ValueError:
        pass
    raise MountError(f"cannot parse right ascension: {text!r}")


def parse_dec(text: str) -> float:
    """Parse ``sDD*MM(:SS(.sss))`` into degrees."""
    text = text.strip().rstrip("#")
    sign = -1.0 if text.startswith("-") else 1.0
    text = text.lstrip("+-")
    parts = [p for p in re.split(r"[*:'°]", text) if p]
    try:
        if len(parts) == 2:
            return sign * (float(parts[0]) + float(parts[1]) / 60.0)
        if len(parts) == 3:
            return sign * (float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0)
    except ValueError:
        pass
    raise MountError(f"cannot parse declination: {text!r}")


#: Loaded ephemerides, by filename.  load() reads the .bsp file from disk on each
#: call (and downloads it the first time), and sun_radec runs on the GUI thread
#: when the Goto Sun button is pressed.
_ephemeris_cache: dict = {}


def sun_radec(when=None, ephemeris: str = "de421.bsp") -> Tuple[float, float]:
    """Apparent geocentric right ascension and declination of the Sun.

    Returns (ra_hours, dec_degrees).  Good enough to put the Sun inside the field
    of a telephoto lens; the mount's own alignment dominates the error.
    """
    cached = _ephemeris_cache.get(ephemeris)
    if cached is None:
        cached = (load(ephemeris), load.timescale())
        _ephemeris_cache[ephemeris] = cached
    eph, ts = cached
    t = ts.now() if when is None else ts.from_datetime(when)
    apparent = eph["Earth"].at(t).observe(eph["Sun"]).apparent()
    # Equinox of date, not the ICRF/J2000 default.  OnStepX works in current
    # coordinates, and the precession since J2000 is more than the radius of
    # the Sun.  A J2000 goto puts the Sun outside the field of a long lens.
    ra, dec, _ = apparent.radec(epoch='date')
    return ra.hours, dec.degrees
