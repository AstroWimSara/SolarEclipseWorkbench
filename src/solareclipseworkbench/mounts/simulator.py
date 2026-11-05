"""A mount that exists only in software.

Lets a whole eclipse script be rehearsed indoors, the way the virtual camera
does.  It models a mount rather than a serial link, so it is also the reference
for what a minimal driver has to implement.

Slews take realistic time, so a script that assumes a goto completes instantly
will fail here rather than at the eclipse.
"""

import logging
import time
from typing import Optional, Tuple

from solareclipseworkbench.mounts.base import (
    Capabilities,
    MountDriver,
    MountError,
    MountStatus,
    sun_radec,
)
from solareclipseworkbench.mounts import register_driver

logger = logging.getLogger(__name__)

# Degrees per second the simulated mount slews at.
DEFAULT_SLEW_RATE = 4.0


@register_driver
class SimulatorMount(MountDriver):
    """A mount with no hardware behind it."""

    name = "simulator"
    display_name = "Simulator"
    description = "Software-only mount, for rehearsing scripts with no hardware connected"
    capabilities = Capabilities(
        goto=True,
        sync=True,
        park=True,
        tracking_toggle=True,
        tracking_rates=("sidereal", "solar", "lunar", "king"),
        manual_move=True,
        rate_presets=("guide", "center", "find", "fast", "slew"),
        pulse_guide=True,
        altaz_readout=False,
    )

    def __init__(self, slew_rate: float = DEFAULT_SLEW_RATE, start_at_sun: bool = False, **config):
        super().__init__(slew_rate=slew_rate, start_at_sun=start_at_sun, **config)
        self.slew_rate = slew_rate
        self.start_at_sun = start_at_sun
        self._connected = False
        self._tracking = False
        self._parked = False
        self._rate = "sidereal"
        self._ra = 0.0
        self._dec = 0.0
        self._slew_until = 0.0
        self._moving: set = set()

    @classmethod
    def discover(cls) -> list:
        # Never offered by discovery: connecting to a simulated mount has to be a
        # deliberate choice, or a real mount could be silently replaced by one.
        return []

    # ------------------------------------------------------------ connection

    def connect(self) -> None:
        self._connected = True
        if self.start_at_sun:
            self._ra, self._dec = sun_radec()
        logger.info("Simulated mount connected")

    def close(self) -> None:
        self._connected = False

    def describe(self) -> str:
        return "simulated mount (no hardware)"

    def _require_connected(self) -> None:
        if not self._connected:
            raise MountError("mount is not connected")

    # ----------------------------------------------------------------- state

    @property
    def _slewing(self) -> bool:
        return time.perf_counter() < self._slew_until

    def status(self) -> MountStatus:
        return MountStatus(
            raw="simulated",
            connected=self._connected,
            tracking=self._tracking and not self._parked,
            slewing=self._slewing,
            parked=self._parked,
            tracking_rate=self._rate,
            mount_type="SIMULATED",
        )

    def get_radec(self) -> Tuple[float, float]:
        self._require_connected()
        return self._ra, self._dec

    # ------------------------------------------------------------------ goto

    def goto(self, ra_hours: float, dec_degrees: float, wait: bool = False,
             timeout: float = 180.0) -> None:
        self._require_connected()
        if self._parked:
            raise MountError("goto refused: mount parked")

        separation = abs(dec_degrees - self._dec) + abs(ra_hours - self._ra) * 15.0
        duration = separation / max(self.slew_rate, 0.1)
        self._slew_until = time.perf_counter() + duration
        self._ra, self._dec = ra_hours, dec_degrees
        logger.info("Simulated slew of %.1f° taking %.1f s", separation, duration)
        if wait:
            self.wait_for_slew(timeout)

    def sync(self, ra_hours: float, dec_degrees: float) -> None:
        self._require_connected()
        self._ra, self._dec = ra_hours, dec_degrees

    def abort(self) -> None:
        self._slew_until = 0.0
        self._moving.clear()
        logger.info("Simulated mount motion aborted")

    # -------------------------------------------------------------- tracking

    def tracking_on(self) -> bool:
        self._require_connected()
        if self._parked:
            return False
        self._tracking = True
        return True

    def tracking_off(self) -> bool:
        self._require_connected()
        self._tracking = False
        return True

    def set_tracking_rate(self, rate: str) -> None:
        if rate.lower() not in self.capabilities.tracking_rates:
            raise MountError(f"unknown tracking rate: {rate}")
        self._rate = rate.lower()

    def tracking_rate_name(self):
        return getattr(self, '_rate', None)

    # --------------------------------------------------------- manual motion

    def move(self, direction: str) -> None:
        self._require_connected()
        if direction.lower() not in ("north", "south", "east", "west"):
            raise MountError(f"unknown direction: {direction}")
        self._moving.add(direction.lower())

    def stop_move(self, direction: Optional[str] = None) -> None:
        if direction is None:
            self._moving.clear()
        else:
            self._moving.discard(direction.lower())

    def set_rate(self, rate: str) -> None:
        if rate.lower() not in self.capabilities.rate_presets:
            raise MountError(f"unknown rate preset: {rate}")

    def pulse_guide(self, direction: str, milliseconds: int) -> bool:
        self._require_connected()
        return True

    # ------------------------------------------------------------- parking

    def park(self) -> bool:
        self._require_connected()
        self._parked = True
        self._tracking = False
        return True

    def unpark(self) -> bool:
        self._require_connected()
        self._parked = False
        return True

    def set_park_here(self) -> bool:
        return True
