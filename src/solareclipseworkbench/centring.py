"""Keeping the sun centred: calibration of the mount against the live view.

Step 3 of docs/MOUNT_PLAN.md.  Before the mount can be corrected from the live
view, it must be known how a guide pulse moves the sun in the frame.  That
depends on the setup: the camera can be turned on the telescope, a diagonal
mirrors the image, the guide rate of the driver, the focal length.  The
calibration measures it:

    1. Find the sun (``sun_finder``) in a few frames: where it is now.
    2. Guide east in pulses until the sun has moved ``target_px`` in the frame
       (about 8 pixels: enough to measure the direction to a few degrees), and
       guide west as long to bring it back.  The same north and south.
    3. Each axis gives a vector: pixels moved per millisecond of guiding.
       Together they make a 2×2 matrix from (north ms, east ms) to (dx, dy) in
       pixels, which the centring inverts to know which pulses bring the sun to
       where it should be.

    4. When the mount has slew rates, the same once more, briefly, at a fast one
       (the driver's "Centering" rate): how far a second of moving at that rate
       moves the sun.  The centring uses it to bring a sun that is far off back
       in seconds; the guide pulses then do the fine work.

Guide pulses are slow on purpose (half the sidereal rate is common: 7.5″ a
second, half a pixel of a sun of 60 pixels), so a calibration takes a minute or
two; a higher guide rate in the driver (0.9× or 1×) makes it faster.  It is done
once, before C1, with the sun in the live view.

Checks: the sun must be found, it must move (else the guide pulses do not reach
the mount), and the two axes must be roughly perpendicular in the frame (else
something else moved the sun, such as a mount that does not track).  Dec
backlash, when the return leg moves the sun much less than the outward one, is
reported but not refused.
"""

import json
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import numpy as np

from solareclipseworkbench.sun_finder import SunFix, find_sun

logger = logging.getLogger(__name__)

#: How far each calibration leg moves the sun, in pixels
TARGET_PX = 8.0

#: Longest single guide pulse.  Some drivers refuse long pulses; several short ones do the same.
MAX_PULSE_MS = 3000.0

#: Longest total guiding of one leg.  When the sun has not moved by then, the pulses do not reach the mount.
MAX_LEG_MS = 90_000.0

#: Less than this movement after MAX_LEG_MS: the sun did not move
MIN_MOVE_PX = 1.0

#: The two axes must be at least this far from parallel in the frame (degrees from 90°)
MAX_SKEW_DEG = 30.0

#: How long the calibration moves at the fast rate, in seconds (about 7 px at 8× sidereal and 16″/px)
FAST_LEG_S = 1.0

#: Frames averaged for one position of the sun
FRAMES_PER_POSITION = 2

#: When the return leg moves the sun less than this share of the outward leg, there is backlash
BACKLASH_SHARE = 0.7


class CalibrationError(Exception):
    """The calibration could not be done; the message says why, for the user."""


@dataclass
class Calibration:
    """How guide pulses move the sun in the live-view frame.

    ``north`` and ``east`` are the movement of the sun in pixels (dx, dy) per
    millisecond of guiding north and east.  Guiding south and west moves it the
    opposite way.
    """
    north: tuple
    east: tuple
    #: Size of the frames it was made with: another size (or orientation) needs a new calibration
    frame_size: tuple
    #: Radius of the sun in the frames, in pixels
    radius: float
    #: Camera it was made with
    camera: str = ""
    #: When it was made (seconds since the epoch)
    made: float = field(default_factory=time.time)
    #: Problems seen that did not stop it (backlash), for the user
    warnings: list = field(default_factory=list)
    #: A fast slew rate (its name on the driver) and how moving at it moves the sun, (dx, dy) in
    #: pixels per millisecond north and east; None when not calibrated
    fast_rate: Optional[str] = None
    fast_north: Optional[tuple] = None
    fast_east: Optional[tuple] = None

    @property
    def matrix(self) -> np.ndarray:
        """Pixels (dx, dy) per (north ms, east ms)."""
        return np.array([[self.north[0], self.east[0]], [self.north[1], self.east[1]]], dtype=float)

    @property
    def mirrored(self) -> bool:
        """Whether the frame shows the sky mirrored (through a diagonal, for instance).

        Looking up at the sky with north up, east is to the left.  In frame
        coordinates (y down), that makes the matrix's determinant negative;
        a mirror makes it positive.
        """
        return float(np.linalg.det(self.matrix)) > 0

    @property
    def angle_deg(self) -> float:
        """Which way guiding east moves the sun in the frame, in degrees anticlockwise from the x axis.

        Guiding east turns the telescope east, so the sun moves west in the frame:
        0° for a frame showing the sky as it looks, north up and east left.
        """
        return math.degrees(math.atan2(-self.east[1], self.east[0])) % 360

    @property
    def skew_deg(self) -> float:
        """How far the two axes are from perpendicular in the frame, in degrees."""
        n, e = np.array(self.north), np.array(self.east)
        cos = float(np.dot(n, e) / (np.linalg.norm(n) * np.linalg.norm(e)))
        return abs(90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos)))))

    def pixels_per_second(self) -> tuple:
        """(north, east): how many pixels a second of guiding moves the sun."""
        return float(np.linalg.norm(self.north)) * 1000, float(np.linalg.norm(self.east)) * 1000

    def pulses_for(self, dx: float, dy: float) -> dict:
        """The guide pulses that move the sun by (dx, dy) pixels: {direction: milliseconds}.

        Directions are "N", "S", "E" and "W"; an axis that needs no pulse is left out.
        """
        north_ms, east_ms = np.linalg.solve(self.matrix, np.array([dx, dy], dtype=float))
        pulses = {}
        if abs(north_ms) >= 1:
            pulses["N" if north_ms > 0 else "S"] = float(abs(north_ms))
        if abs(east_ms) >= 1:
            pulses["E" if east_ms > 0 else "W"] = float(abs(east_ms))
        return pulses

    @property
    def has_fast_rate(self) -> bool:
        return self.fast_rate is not None and self.fast_north is not None and self.fast_east is not None

    def moves_for(self, dx: float, dy: float) -> dict:
        """How long to move at the fast rate to move the sun by (dx, dy): {direction: milliseconds}."""
        matrix = np.array([[self.fast_north[0], self.fast_east[0]], [self.fast_north[1], self.fast_east[1]]])
        north_ms, east_ms = np.linalg.solve(matrix, np.array([dx, dy], dtype=float))
        moves = {}
        if abs(north_ms) >= 1:
            moves["N" if north_ms > 0 else "S"] = float(abs(north_ms))
        if abs(east_ms) >= 1:
            moves["E" if east_ms > 0 else "W"] = float(abs(east_ms))
        return moves

    def matches(self, frame_size: tuple, camera: str = "") -> bool:
        """Whether this calibration is for frames of this size (and this camera, when both are known)."""
        return tuple(frame_size) == tuple(self.frame_size) and (not camera or not self.camera
                                                                  or camera == self.camera)

    def describe(self) -> str:
        north_pps, east_pps = self.pixels_per_second()
        text = (f"guiding east moves the sun towards {self.angle_deg:.0f}° in the frame, the frame is "
                f"{'mirrored' if self.mirrored else 'not mirrored'}; a second of guiding moves the sun "
                f"{north_pps:.2f} px north/south, {east_pps:.2f} px east/west")
        if self.has_fast_rate:
            fast = (float(np.linalg.norm(self.fast_north)) + float(np.linalg.norm(self.fast_east))) * 500
            text += f"; at the {self.fast_rate} rate {fast:.1f} px a second"
        if self.warnings:
            text += "; " + "; ".join(self.warnings)
        return text

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "Calibration":
        data = json.loads(text)
        for key in ("north", "east", "frame_size", "fast_north", "fast_east"):
            if data.get(key) is not None:
                data[key] = tuple(data[key])
        return cls(**data)


# ------------------------------------------------------------------ measuring


def measure(frames, after: float, radius_hint: Optional[float] = None, count: int = FRAMES_PER_POSITION,
            timeout: float = 10.0, cancel: Optional[threading.Event] = None) -> tuple:
    """Where the sun is: the mean centre in ``count`` frames taken after ``after``.

    Args:
        - frames: Has ``latest()`` → (time, frame) or None (the live view, or a simulated camera)
        - after: time.monotonic() after which the frames must be taken (after the mount has settled)

    Returns: (x, y, SunFix of the last frame).  Raises CalibrationError when the sun is not found in time.
    """
    deadline = time.monotonic() + timeout
    fixes: list = []
    seen = after
    while len(fixes) < count:
        if cancel is not None and cancel.is_set():
            raise CalibrationError("stopped")
        if time.monotonic() > deadline:
            if fixes:
                break
            raise CalibrationError("the sun is not found in the live view: is it in the frame, through the filter, "
                                   "and is the live view running?")
        latest = frames.latest()
        if latest is None or latest[0] <= seen:
            time.sleep(0.05)
            continue
        seen = latest[0]
        fix = find_sun(latest[1], radius_hint=radius_hint)
        if fix is not None:
            fixes.append(fix)
    x = float(np.mean([f.x for f in fixes]))
    y = float(np.mean([f.y for f in fixes]))
    return x, y, fixes[-1]


# ---------------------------------------------------------------- calibrating


class Calibrator:
    """Calibrates a mount against the live view.

    Args:
        - mount: A mount.Mount
        - frames: Has ``latest()`` → (time, frame) or None
        - settle_s: Wait after the end of a pulse before frames count: the mount
                    must stop shaking and a frame taken during the move must pass
        - target_px: How far each leg moves the sun
        - progress: Called with a line of text at every step (on the calibration thread)
        - max_leg_ms: Longest total guiding of one leg before the sun counts as not moving
        - wait_for_pulses: Wait as long as each pulse lasts (a real mount); False for a
                           mount that moves at once (tests)
        - find_timeout: Seconds to look for the sun before giving up
    """

    def __init__(self, mount, frames, settle_s: float = 1.5, target_px: float = TARGET_PX,
                 progress: Optional[Callable[[str], None]] = None, camera: str = "",
                 max_leg_ms: float = MAX_LEG_MS, wait_for_pulses: bool = True, find_timeout: float = 10.0):
        self.max_leg_ms = max_leg_ms
        self.wait_for_pulses = wait_for_pulses
        self.find_timeout = find_timeout
        self.mount = mount
        self.frames = frames
        self.settle_s = settle_s
        self.target_px = target_px
        self.camera = camera
        self._progress = progress
        self.cancel = threading.Event()

    def _say(self, text: str) -> None:
        logger.info("Calibration: %s", text)
        if self._progress is not None:
            try:
                self._progress(text)
            except Exception:
                logger.debug("Calibration progress callback failed", exc_info=True)

    def _sleep(self, seconds: float) -> None:
        if self.cancel.wait(max(0.0, seconds)):
            raise CalibrationError("stopped")

    def _guide(self, direction: str, milliseconds: float) -> None:
        """Guide for ``milliseconds`` in pulses of at most MAX_PULSE_MS, waiting for each to end."""
        remaining = milliseconds
        while remaining > 0.5:
            pulse = min(remaining, MAX_PULSE_MS)
            try:
                self.mount.guide(direction, pulse)
            except Exception as exc:
                raise CalibrationError(f"the mount refused a guide pulse: {exc}") from exc
            if self.wait_for_pulses:
                self._sleep(pulse / 1000.0)
            remaining -= pulse

    def _position(self, radius: float) -> tuple:
        self._sleep(self.settle_s)
        return measure(self.frames, time.monotonic(), radius_hint=radius, timeout=self.find_timeout,
                       cancel=self.cancel)[:2]

    def _leg(self, direction: str, back: str, radius: float, start: tuple) -> tuple:
        """Guide towards ``direction`` until the sun moved target_px, then back.  Returns (vector px/ms, warning)."""
        total_ms = 0.0
        moved = np.zeros(2)
        step_ms = 1000.0
        while True:
            self._guide(direction, step_ms)
            total_ms += step_ms
            position = self._position(radius)
            moved = np.array(position) - np.array(start)
            distance = float(np.linalg.norm(moved))
            self._say(f"guided {direction} for {total_ms / 1000:.1f} s: the sun moved {distance:.1f} px")
            if distance >= self.target_px:
                break
            if total_ms >= self.max_leg_ms:
                if distance < MIN_MOVE_PX:
                    raise CalibrationError(
                        f"the sun did not move after {total_ms / 1000:.0f} s of guiding {direction}: do the guide "
                        f"pulses reach the mount (driver, cable), and is the mount not parked?")
                break
            # Guide as long again as it takes, from the speed so far, with some margin
            if distance > 0.5:
                needed = (self.target_px - distance) / (distance / total_ms)
                step_ms = float(np.clip(needed * 1.1, 500.0, max(self.max_leg_ms - total_ms, 500.0)))
            else:
                step_ms = max(min(2 * step_ms, self.max_leg_ms - total_ms), 500.0)
        vector = moved / total_ms

        # Back as long, and see how far it comes back
        self._guide(back, total_ms)
        returned = np.array(self._position(radius)) - (np.array(start) + moved)
        back_share = float(-np.dot(returned, moved) / np.dot(moved, moved))
        self._say(f"guided {back} for {total_ms / 1000:.1f} s: the sun came back {back_share:.0%} of the way")
        warning = None
        if back_share < BACKLASH_SHARE:
            warning = (f"backlash: guiding {back} moved the sun only {back_share:.0%} as far as guiding "
                       f"{direction}")
        return vector, warning

    def _fast_rate(self) -> Optional[str]:
        """The fast slew rate to calibrate: the driver's centering rate, else the second slowest; None without rates."""
        try:
            rates = self.mount.slew_rates()
        except Exception:
            return None
        if len(rates) < 2:
            return None
        for name, label in rates:
            if "center" in label.lower() or "centre" in label.lower() or "centering" in name.lower():
                return name
        return rates[1][0]

    def _move(self, direction: str, seconds: float) -> float:
        """Move at the current slew rate for about ``seconds``.  Returns how long it really moved."""
        start = time.monotonic()
        self.mount.nudge_start(direction)
        try:
            self._sleep(seconds)
        finally:
            self.mount.nudge_stop(direction)
        return time.monotonic() - start

    def _fast_leg(self, direction: str, back: str, radius: float) -> Optional[np.ndarray]:
        """Move a second at the fast rate and back.  Returns the vector (px per ms), or None when it barely moved."""
        start = np.array(self._position(radius))
        seconds = self._move(direction, FAST_LEG_S)
        moved = np.array(self._position(radius)) - start
        self._move(back, seconds)
        distance = float(np.linalg.norm(moved))
        self._say(f"moved {direction} at the fast rate for {seconds:.1f} s: the sun moved {distance:.1f} px")
        if distance < MIN_MOVE_PX * 2:
            return None
        return moved / (seconds * 1000)

    def _calibrate_fast(self, radius: float) -> tuple:
        """(rate, north, east) at a fast slew rate, or (None, None, None) when the mount has none or it fails."""
        rate = self._fast_rate()
        if rate is None:
            return None, None, None
        previous = getattr(self.mount, "slew_rate", None)
        try:
            self.mount.set_slew_rate(rate)
            east = self._fast_leg("E", "W", radius)
            north = self._fast_leg("N", "S", radius)
        except CalibrationError:
            raise
        except Exception as exc:
            self._say(f"the fast rate could not be calibrated: {exc}")
            return None, None, None
        finally:
            if previous:
                try:
                    self.mount.set_slew_rate(previous)
                except Exception:
                    pass
        if east is None or north is None:
            self._say("the fast rate barely moved the sun: only guide pulses will be used")
            return None, None, None
        return rate, tuple(map(float, north)), tuple(map(float, east))

    def run(self) -> Calibration:
        """Calibrate.  Raises CalibrationError with a message for the user when it cannot."""
        self._say("looking for the sun")
        latest = self.frames.latest()
        start_x, start_y, fix = measure(self.frames, (latest[0] - 1e-6) if latest else 0.0,
                                        timeout=self.find_timeout, cancel=self.cancel)
        radius = fix.radius
        frame = self.frames.latest()
        frame_size = (frame[1].shape[1], frame[1].shape[0]) if frame else (0, 0)
        self._say(f"the sun is at {start_x:.1f}, {start_y:.1f}, radius {radius:.1f} px")

        warnings = []
        east, warning = self._leg("E", "W", radius, (start_x, start_y))
        if warning:
            warnings.append(warning)
        start = self._position(radius)
        north, warning = self._leg("N", "S", radius, start)
        if warning:
            warnings.append(warning)

        fast_rate, fast_north, fast_east = self._calibrate_fast(radius)

        calibration = Calibration(north=tuple(map(float, north)), east=tuple(map(float, east)),
                                  frame_size=frame_size, radius=float(radius), camera=self.camera,
                                  warnings=warnings, fast_rate=fast_rate, fast_north=fast_north,
                                  fast_east=fast_east)
        if calibration.skew_deg > MAX_SKEW_DEG:
            raise CalibrationError(
                f"guiding north and guiding east moved the sun in nearly the same direction (the axes are "
                f"{90 - calibration.skew_deg:.0f}° apart, not 90°): did something else move the sun, or does the "
                f"mount not track?")
        self._say("done: " + calibration.describe())
        return calibration

    def stop(self) -> None:
        """Stop a calibration that is running (from another thread)."""
        self.cancel.set()


# ------------------------------------------------------------------ centring

#: Seconds between looks while the sun is centred
CENTRING_INTERVAL_S = 30.0

#: Seconds until the next look after a correction (to see it worked) or while waiting for a gap
RECHECK_S = 2.0

#: Offsets up to this many pixels are left alone
DEADBAND_PX = 2.0

#: Share of the offset corrected at once: a little less than all, so a calibration a
#: little off does not make it overshoot back and forth
GAIN = 0.7

#: Longest guiding of one correction, per axis.  A correction is as long as the gap
#: between the scheduled shots allows (before C1 that is as long as it needs), sent as
#: pulses of at most MAX_PULSE_MS; this only keeps a wild offset from guiding for ever.
MAX_CORRECTION_MS = 120_000.0

#: Farther off than this, and with the fast rate calibrated, the sun is first moved at the
#: fast rate (most of the way), and the guide pulses do the rest
COARSE_PX = 10.0

#: Share of the offset a coarse move covers: not all, so it does not overshoot
COARSE_GAIN = 0.85

#: Corrections in a row that do not move the sun as they should before the centring gives up
MAX_FAILED_CORRECTIONS = 3

#: A correction failed when the sun moved less than this share of the way the
#: calibration says the pulses move it (in that direction)
MIN_CORRECTION_SHARE = 0.3

#: Fixes kept for the running radius of the sun
RADIUS_HISTORY = 10

#: States of the centring
OFF, LOOKING, CENTRED, CORRECTING, WAITING, PAUSED, NO_SUN, STOPPED = (
    "off", "looking", "centred", "correcting", "waiting for a gap", "paused", "no sun", "stopped")


@dataclass
class CentringStatus:
    """What the centring is doing, for the windows and the phone."""
    state: str = OFF
    message: str = ""
    #: Offset of the sun from the target, (dx, dy) in pixels, at the last look
    offset: Optional[tuple] = None
    #: Corrections made
    corrections: int = 0
    #: time.monotonic() of the last time the sun was found
    last_fix: Optional[float] = None
    #: Where the sun was found last, (x, y), and the target, in pixels of the frame
    sun: Optional[tuple] = None
    target: Optional[tuple] = None

    @property
    def distance(self) -> Optional[float]:
        return None if self.offset is None else float(math.hypot(*self.offset))


class Centrer:
    """Keeps the sun on the target in the live view by guide pulses, between scheduled shots.

    Every ``interval_s`` it finds the sun in the newest frame.  When the sun is
    more than ``deadband_px`` from the target, it computes the guide pulses that
    bring it most of the way back (``gain``) and sends them once ``quiet(seconds)``
    says no camera is busy for as long as the pulses and the settling take.  When
    the whole correction does not fit in the gap, it sends pulses of at most
    MAX_PULSE_MS, if those fit.  A sun more than COARSE_PX off is first moved at
    the fast slew rate, when the calibration has one: seconds instead of minutes.
    Then it looks again soon, to see the correction worked.

    It does nothing while ``paused()`` (around totality: from C2 - 15 s to
    C3 + 15 s, when the live view is paused too and the mount just tracks), and
    it stops itself when the frame size no longer matches the calibration or
    when corrections in a row do not move the sun the way the calibration says
    they should (a wrong or old calibration).

    Args:
        - mount: A mount.Mount (or anything with ``guide(direction, ms)``)
        - frames: Has ``latest()`` → (time, frame) or None
        - calibration: A Calibration of this mount and camera
        - quiet: ``quiet(seconds)`` → whether no shot is due for that long (utils.quiet_for)
        - paused: ``paused()`` → whether to leave the mount alone now (around totality)
        - target: (x, y) to keep the sun on; the middle of the frame when None
        - on_status: Called with a CentringStatus after every look (on the centring thread)
        - wait_for_pulses: Wait as long as each pulse lasts (a real mount); False for tests
    """

    def __init__(self, mount, frames, calibration: Calibration, quiet: Callable[[float], bool] = lambda s: True,
                 paused: Callable[[], bool] = lambda: False, target: Optional[tuple] = None,
                 interval_s: float = CENTRING_INTERVAL_S, deadband_px: float = DEADBAND_PX, gain: float = GAIN,
                 max_correction_ms: float = MAX_CORRECTION_MS, settle_s: float = 1.5,
                 on_status: Optional[Callable[[CentringStatus], None]] = None, wait_for_pulses: bool = True):
        self.mount = mount
        self.frames = frames
        self.calibration = calibration
        self.quiet = quiet
        self.paused = paused
        width, height = calibration.frame_size
        self.target = target or ((width - 1) / 2, (height - 1) / 2)
        self.interval_s = interval_s
        self.deadband_px = deadband_px
        self.gain = gain
        self.max_correction_ms = max_correction_ms
        self.settle_s = settle_s
        self.wait_for_pulses = wait_for_pulses
        self._on_status = on_status
        self.status = CentringStatus(target=self.target)
        self._radii: list = [calibration.radius]
        self._ready_after = 0.0
        # Where the sun was before the last correction, and how far that correction should move it
        self._before: Optional[np.ndarray] = None
        self._expected: Optional[np.ndarray] = None
        self._failed = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -------------------------------------------------------------- the thread

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._set(LOOKING, "looking for the sun")
        self._thread = threading.Thread(target=self._run, name="centring", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout)
        if self.status.state != STOPPED:
            self._set(OFF, "off")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.step()
            except Exception as exc:
                logger.exception("Centring failed")
                self._set(STOPPED, f"stopped: {exc}")
                return
            if self.status.state == STOPPED:
                return
            self._stop.wait(wait)

    # ------------------------------------------------------------------ a look

    @property
    def radius(self) -> float:
        """The running radius of the sun: the median of the recent fixes on a long arc."""
        return float(np.median(self._radii))

    def _set(self, state: str, message: str, **changes) -> None:
        self.status = CentringStatus(**{**asdict(self.status), "state": state, "message": message, **changes})
        if state in (STOPPED, NO_SUN):
            logger.warning("Centring: %s", message)
        else:
            logger.debug("Centring: %s", message)
        if self._on_status is not None:
            try:
                self._on_status(self.status)
            except Exception:
                logger.debug("Centring status callback failed", exc_info=True)

    def step(self) -> float:
        """One look, and a correction when needed.  Returns the seconds until the next look."""
        if self.paused():
            self._before = self._expected = None
            self._set(PAUSED, "paused around totality: the mount just tracks")
            return RECHECK_S

        latest = self.frames.latest()
        if latest is not None:
            size = (latest[1].shape[1], latest[1].shape[0])
            if tuple(size) != tuple(self.calibration.frame_size):
                self._set(STOPPED, f"the live view frames are {size[0]}×{size[1]}, the calibration was made on "
                                   f"{self.calibration.frame_size[0]}×{self.calibration.frame_size[1]}: "
                                   f"calibrate again")
                return self.interval_s
        try:
            x, y, fix = measure(self.frames, max(self._ready_after, (latest[0] - 1e-6) if latest else 0.0),
                                radius_hint=self.radius, count=1, timeout=5.0, cancel=self._stop)
        except CalibrationError:
            if self._stop.is_set():
                return 0.0
            self._before = self._expected = None
            self._set(NO_SUN, "the sun is not found in the live view")
            return self.interval_s
        if fix.arc_deg >= 150:
            self._radii = (self._radii + [fix.radius])[-RADIUS_HISTORY:]

        dx, dy = x - self.target[0], y - self.target[1]
        distance = math.hypot(dx, dy)
        found = {"offset": (dx, dy), "last_fix": time.monotonic(), "sun": (x, y)}

        # Did the last correction move the sun the way the calibration says it should?
        if self._expected is not None:
            moved = np.array((x, y)) - self._before
            share = float(np.dot(moved, self._expected) / np.dot(self._expected, self._expected))
            if share < MIN_CORRECTION_SHARE:
                self._failed += 1
                logger.info("Centring: the correction moved the sun %.0f%% of the way it should", 100 * share)
                if self._failed >= MAX_FAILED_CORRECTIONS:
                    self._set(STOPPED, f"{self._failed} corrections in a row did not move the sun the way they "
                                       f"should: calibrate again", **found)
                    return self.interval_s
            else:
                self._failed = 0
        self._before = self._expected = None

        if distance <= self.deadband_px:
            self._set(CENTRED, f"centred ({distance:.1f} px off)", **found)
            return self.interval_s

        if distance > COARSE_PX and self.calibration.has_fast_rate and hasattr(self.mount, "nudge_start"):
            return self._coarse_move(dx, dy, distance, found)

        pulses = self.calibration.pulses_for(-dx * self.gain, -dy * self.gain)
        pulses = {d: min(ms, self.max_correction_ms) for d, ms in pulses.items() if ms >= 50}
        if not pulses:
            self._set(CENTRED, f"centred ({distance:.1f} px off)", **found)
            return self.interval_s
        busy_s = max(pulses.values()) / 1000.0 + self.settle_s
        if not self.quiet(busy_s):
            # Not the whole correction: one pulse per axis, if that fits
            short = {d: min(ms, MAX_PULSE_MS) for d, ms in pulses.items()}
            short_s = max(short.values()) / 1000.0 + self.settle_s
            if short_s >= busy_s or not self.quiet(short_s):
                self._set(WAITING, f"{distance:.1f} px off: waiting for a gap of {short_s:.0f} s between the shots",
                          **found)
                return RECHECK_S
            pulses, busy_s = short, short_s

        text = ", ".join(f"{d} {ms / 1000:.1f} s" for d, ms in pulses.items())
        logger.info("Centring: the sun is %.1f px off (%.1f, %.1f): guiding %s", distance, dx, dy, text)
        self._set(CORRECTING, f"{distance:.1f} px off: guiding {text}", corrections=self.status.corrections + 1,
                  **found)
        try:
            self._guide(pulses)
        except Exception as exc:
            self._set(STOPPED, f"the mount refused a guide pulse: {exc}", **found)
            return self.interval_s
        if self.wait_for_pulses:
            self._stop.wait(self.settle_s)
        north_ms = pulses.get("N", 0.0) - pulses.get("S", 0.0)
        east_ms = pulses.get("E", 0.0) - pulses.get("W", 0.0)
        return self._corrected(x, y, self.calibration.matrix @ np.array((north_ms, east_ms)))

    def _guide(self, pulses: dict) -> None:
        """Send the guide pulses, both axes at once, in pulses of at most MAX_PULSE_MS."""
        remaining = dict(pulses)
        while remaining and not self._stop.is_set():
            chunk = {d: min(ms, MAX_PULSE_MS) for d, ms in remaining.items()}
            for direction, ms in chunk.items():
                self.mount.guide(direction, ms)
            if self.wait_for_pulses:
                self._stop.wait(max(chunk.values()) / 1000.0)
            remaining = {d: ms - chunk[d] for d, ms in remaining.items() if ms - chunk[d] >= 50}

    def _coarse_move(self, dx: float, dy: float, distance: float, found: dict) -> float:
        """Move most of the way at the fast slew rate."""
        calibration = self.calibration
        moves = calibration.moves_for(-dx * COARSE_GAIN, -dy * COARSE_GAIN)
        if not moves:
            return RECHECK_S
        busy_s = max(moves.values()) / 1000.0 + self.settle_s
        if not self.quiet(busy_s):
            self._set(WAITING, f"{distance:.1f} px off: waiting for a gap of {busy_s:.0f} s between the shots",
                      **found)
            return RECHECK_S
        text = ", ".join(f"{d} {ms / 1000:.1f} s" for d, ms in moves.items())
        logger.info("Centring: the sun is %.1f px off (%.1f, %.1f): moving %s at the %s rate", distance, dx, dy,
                    text, calibration.fast_rate)
        self._set(CORRECTING, f"{distance:.1f} px off: moving {text} at the {calibration.fast_rate} rate",
                  corrections=self.status.corrections + 1, **found)
        mount = self.mount
        previous = getattr(mount, "slew_rate", None)
        started = []
        try:
            mount.set_slew_rate(calibration.fast_rate)
            begin = time.monotonic()
            for direction in moves:
                mount.nudge_start(direction)
                started.append(direction)
            # Stop each axis after its own time, the shortest first
            for direction, ms in sorted(moves.items(), key=lambda item: item[1]):
                wait = begin + ms / 1000.0 - time.monotonic()
                if self.wait_for_pulses and wait > 0:
                    self._stop.wait(wait)
                mount.nudge_stop(direction)
                started.remove(direction)
        except Exception as exc:
            self._set(STOPPED, f"the mount refused to move: {exc}", **found)
            return self.interval_s
        finally:
            for direction in started:
                try:
                    mount.nudge_stop(direction)
                except Exception:
                    logger.exception("Could not stop the mount moving %s", direction)
            if previous and previous != calibration.fast_rate:
                try:
                    mount.set_slew_rate(previous)
                except Exception:
                    pass
        if self.wait_for_pulses:
            self._stop.wait(self.settle_s)
        north_ms = moves.get("N", 0.0) - moves.get("S", 0.0)
        east_ms = moves.get("E", 0.0) - moves.get("W", 0.0)
        fast = np.array([[calibration.fast_north[0], calibration.fast_east[0]],
                         [calibration.fast_north[1], calibration.fast_east[1]]])
        return self._corrected(dx + self.target[0], dy + self.target[1], fast @ np.array((north_ms, east_ms)))

    def _corrected(self, x: float, y: float, expected: np.ndarray) -> float:
        """Remember what the correction should have done, to check it at the next look."""
        self._ready_after = time.monotonic()
        self._before = np.array((x, y))
        self._expected = expected
        return RECHECK_S if self.wait_for_pulses else 0.0
