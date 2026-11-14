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

Some mounts take guide pulses and do nothing with them: the iOptron HAZ31 in
alt-az mode answers every pulse with "Ok" and does not move.  The mount's own
coordinates show it (they must change by the guide rate times the time guided),
and so does a return leg that does not bring the sun back.  The calibration then
starts again with slews at the slowest slew rate instead of guide pulses (timed
moves, as the N/S/E/W buttons make), and the centring corrects with those too.

Guide pulses are slow on purpose (half the sidereal rate is common: 7.5″ a
second, half a pixel of a sun of 60 pixels), so a calibration takes a minute or
two; a higher guide rate in the driver (0.9× or 1×) makes it faster.  It is done
once, before C1, with the sun in the live view.

Checks: the mount must track (else the sky drifts through the frame and that is
what gets measured), the sun must be found, it must move (else the guide pulses
do not reach the mount), and the two axes must be roughly perpendicular in the frame (else
something else moved the sun, such as a mount that does not track).  Dec
backlash, when the return leg moves the sun much less than the outward one, is
reported but not refused.
"""

import datetime
import json
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
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

#: When the return leg moves the sun further the same way, by more than this share of the outward
#: leg, it was not the guiding that moved the sun but the sky drifting (backlash alone gives 0 at worst)
DRIFT_SHARE = -0.3

#: How the calibration moves the mount: guide pulses, or timed slews at the slowest slew rate
#: (for a mount that ignores guide pulses)
PULSES, SLEWS = "pulses", "slews"

#: Sidereal rate, in arcseconds a second: guide rates are multiples of it
SIDEREAL_ARCSEC_PER_S = 15.041

#: After this much guiding of one leg, the mount's own coordinates must show that the pulses moved it
PROBE_MS = 20_000.0

#: How old the position a driver reports can be (the iOptron driver asks the mount every 10 s)
POSITION_LAG_S = 12.0

#: The coordinates moved less than this share of what the guide rate predicts: the pulses are ignored
MIN_GUIDED_SHARE = 0.25

#: Less than this movement predicted by the guide rate is too little to judge the coordinates on
MIN_PREDICTED_ARCSEC = 20.0

#: How long tracking may be off before the calibration refuses: some drivers (iOptron) switch it
#: off for a second or two now and then while the mount tracks
TRACKING_WAIT_S = 5.0

#: Shortest slew of a correction by slews: shorter ones are not timed well over Wi-Fi
MIN_SLEW_MS = 200.0

#: Longest slewing of one calibration leg: a slew rate that has not moved the sun far enough by
#: then is too slow (in that direction) for the calibration
MAX_SLEW_LEG_MS = 20_000.0

#: Slewing back as long must bring the sun back at least this share of the way, or the rate is too
#: slow that way: an iOptron HAZ31 in alt-az mode slews at "1x" as fast as 2× sidereal east and does
#: not move west (the sky drifting west as fast as it turns); at "2x" 3× east and 1× west (33 %).
#: West and south are measured on their own, so a slower way back is fine as long as it moves.
MIN_SLEW_BACK_SHARE = 0.2

#: Slew rates tried, from the slowest up, before the calibration with slews gives up
MAX_SLEW_RATES_TRIED = 3


class CalibrationError(Exception):
    """The calibration could not be done; the message says why, for the user."""


class _PulsesIgnored(Exception):
    """The mount does not move on guide pulses; the message says how that was seen."""


class _RateTooSlow(Exception):
    """A slew rate does not move the sun (well enough) one way; the message says which."""


def save_frame(frames, reason: str) -> Optional[Path]:
    """Save the newest frame next to the log file, to see later why the sun was not found in it.

    Returns the path, or None when there is no log file (tests) or no frame, or saving failed.
    """
    try:
        from solareclipseworkbench.logging_setup import get_log_path
        log_path = get_log_path()
        latest = frames.latest() if frames is not None else None
        if log_path is None or latest is None:
            return None
        from PIL import Image
        frame = np.asarray(latest[1])
        if frame.dtype != np.uint8:
            top = float(frame.max()) or 1.0
            frame = np.clip(frame.astype(np.float64) * 255.0 / top, 0, 255).astype(np.uint8)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = log_path.parent / f"no-sun-{stamp}Z.png"
        Image.fromarray(frame).save(path)
        logger.info("The frame in which the sun was not found (%s) is saved in %s", reason, path)
        return path
    except Exception:
        logger.debug("Could not save the frame without the sun", exc_info=True)
        return None


@dataclass
class Calibration:
    """How guide pulses move the sun in the live-view frame.

    ``north`` and ``east`` are the movement of the sun in pixels (dx, dy) per
    millisecond of guiding north and east.  Guiding south and west moves it the
    opposite way, unless ``south`` and ``west`` say otherwise: slews of an
    alt-az mount need not be (an iOptron HAZ31 in alt-az mode slews at "1x"
    as fast as 2× sidereal east and does not move west).
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
    #: Mount it was made with (Mount.identity); another mount turns and moves the sun differently
    mount: str = ""
    #: How ``north`` and ``east`` move the mount: PULSES (guide pulses) or SLEWS (timed slews at
    #: ``slow_rate``, for a mount that ignores guide pulses)
    guide_by: str = PULSES
    slow_rate: Optional[str] = None
    #: How moving south and west (dx, dy per ms) moves the sun, when that is not the opposite of
    #: north and east (slews of an alt-az mount); None: the opposite.  The same at the fast rate.
    south: Optional[tuple] = None
    west: Optional[tuple] = None
    fast_south: Optional[tuple] = None
    fast_west: Optional[tuple] = None

    @property
    def by_slews(self) -> bool:
        return self.guide_by == SLEWS

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

    def vectors(self, fast: bool = False) -> dict:
        """How a millisecond of moving N, S, E and W moves the sun: {direction: array (dx, dy)}."""
        north, east = (self.fast_north, self.fast_east) if fast else (self.north, self.east)
        south, west = (self.fast_south, self.fast_west) if fast else (self.south, self.west)
        north, east = np.array(north, dtype=float), np.array(east, dtype=float)
        return {"N": north, "E": east,
                "S": np.array(south, dtype=float) if south is not None else -north,
                "W": np.array(west, dtype=float) if west is not None else -east}

    @staticmethod
    def _solve(vectors: dict, dx: float, dy: float) -> dict:
        """The moves (ms, one direction per axis) that move the sun by (dx, dy): {direction: milliseconds}.

        Each of the four pairs (N or S with E or W) is tried: the one that needs
        no negative time is the answer.  With opposite vectors that is the
        ordinary inverse of the matrix.
        """
        target = np.array([dx, dy], dtype=float)
        for ns in ("N", "S"):
            for ew in ("E", "W"):
                try:
                    a, b = np.linalg.solve(np.column_stack((vectors[ns], vectors[ew])), target)
                except np.linalg.LinAlgError:
                    continue
                if a > -1e-6 and b > -1e-6:
                    return {d: float(ms) for d, ms in ((ns, a), (ew, b)) if ms >= 1}
        # Not reachable with the vectors measured (should not happen): the N and E vectors, signs as needed
        north_ms, east_ms = np.linalg.solve(np.column_stack((vectors["N"], vectors["E"])), target)
        moves = {}
        if abs(north_ms) >= 1:
            moves["N" if north_ms > 0 else "S"] = float(abs(north_ms))
        if abs(east_ms) >= 1:
            moves["E" if east_ms > 0 else "W"] = float(abs(east_ms))
        return moves

    def movement(self, moves: dict, fast: bool = False) -> np.ndarray:
        """How far moves {direction: milliseconds} move the sun: (dx, dy) in pixels."""
        vectors = self.vectors(fast)
        return sum((vectors[d] * ms for d, ms in moves.items()), np.zeros(2))

    def pulses_for(self, dx: float, dy: float) -> dict:
        """The guide pulses (or slews) that move the sun by (dx, dy) pixels: {direction: milliseconds}.

        Directions are "N", "S", "E" and "W"; an axis that needs no pulse is left out.
        """
        return self._solve(self.vectors(), dx, dy)

    @property
    def has_fast_rate(self) -> bool:
        return self.fast_rate is not None and self.fast_north is not None and self.fast_east is not None

    def moves_for(self, dx: float, dy: float) -> dict:
        """How long to move at the fast rate to move the sun by (dx, dy): {direction: milliseconds}."""
        return self._solve(self.vectors(fast=True), dx, dy)

    def matches(self, frame_size: tuple, camera: str = "", mount: Optional[str] = None) -> bool:
        """Whether this calibration is for frames of this size (and this camera, when both are known).

        When the mount is given, the calibration must have been made with that
        mount: one made before the mount was recorded does not match either.
        """
        return (tuple(frame_size) == tuple(self.frame_size)
                and (not camera or not self.camera or camera == self.camera)
                and (mount is None or mount == self.mount))

    def describe(self) -> str:
        north_pps, east_pps = self.pixels_per_second()
        moving = f"slewing at the {self.slow_rate} rate" if self.by_slews else "guiding"
        text = (f"{moving} east moves the sun towards {self.angle_deg:.0f}° in the frame, the frame is "
                f"{'mirrored' if self.mirrored else 'not mirrored'}; a second of {moving} moves the sun "
                f"{north_pps:.2f} px north/south, {east_pps:.2f} px east/west")
        if self.south is not None and self.west is not None:
            text += (f" ({float(np.linalg.norm(self.south)) * 1000:.2f} px south, "
                     f"{float(np.linalg.norm(self.west)) * 1000:.2f} px west)")
        if self.by_slews:
            text += " (the mount ignores guide pulses)"
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
        for key in ("north", "east", "frame_size", "fast_north", "fast_east", "south", "west", "fast_south",
                    "fast_west"):
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
                           mount that moves at once (tests).  Slews are always timed for real.
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
        #: How the legs move the mount: PULSES, or SLEWS at slow_rate once the pulses turned out to be ignored
        self.method = PULSES
        self.slow_rate: Optional[str] = None
        self._saved_frame = False

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
        """Move for ``milliseconds``: guide pulses of at most MAX_PULSE_MS, or one slew; waits for the end."""
        if self.method == SLEWS:
            try:
                self.mount.set_slew_rate(self.slow_rate)
            except Exception as exc:
                raise CalibrationError(f"the mount refused the {self.slow_rate} slew rate: {exc}") from exc
            self._timed_slew(direction, milliseconds / 1000.0)
            return
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

    def _timed_slew(self, direction: str, seconds: float) -> float:
        """Slew at the current slew rate for about ``seconds``.  Returns how long it really moved."""
        start = time.monotonic()
        try:
            self.mount.nudge_start(direction)
        except Exception as exc:
            raise CalibrationError(f"the mount refused to move {direction}: {exc}") from exc
        try:
            self._sleep(seconds)
        finally:
            try:
                self.mount.nudge_stop(direction)
            except Exception:
                logger.exception("Could not stop the mount moving %s", direction)
        return time.monotonic() - start

    def _position(self, radius: float) -> tuple:
        self._sleep(self.settle_s)
        return self._measure(time.monotonic(), radius)[:2]

    def _measure(self, after: float, radius: Optional[float]) -> tuple:
        """measure(), and the frame saved for later when the sun is not found in it (once)."""
        try:
            return measure(self.frames, after, radius_hint=radius, timeout=self.find_timeout, cancel=self.cancel)
        except CalibrationError as exc:
            if not self.cancel.is_set() and not self._saved_frame:
                self._saved_frame = True
                save_frame(self.frames, "calibration")
            raise exc

    def _guide_rate(self, direction: str) -> Optional[float]:
        """The guide rate of the axis of this direction, as a multiple of sidereal; None when unknown."""
        rates = _mount_value(self.mount, "guide_rate")
        if not rates:
            return None
        rate = rates[0] if direction in ("E", "W") else rates[1]
        return float(rate) if rate else None

    def _check_pulses_move(self, direction: str, total_ms: float, start: Optional[tuple]) -> None:
        """Raise _PulsesIgnored when the mount's own coordinates show the guide pulses did not move it."""
        rate = self._guide_rate(direction)
        now = _mount_value(self.mount, "position")
        if rate is None or not start or not now or None in (*start, *now) or total_ms < PROBE_MS:
            return
        if direction in ("E", "W"):
            hours = (now[0] - start[0] + 12.0) % 24.0 - 12.0
            moved = abs(hours) * 15 * 3600
        else:
            moved = abs(now[1] - start[1]) * 3600
        # The newest position the driver reported may be POSITION_LAG_S old
        predicted = rate * SIDEREAL_ARCSEC_PER_S * (total_ms / 1000.0 - POSITION_LAG_S)
        if predicted >= MIN_PREDICTED_ARCSEC and moved < MIN_GUIDED_SHARE * predicted:
            raise _PulsesIgnored(f"{total_ms / 1000:.0f} s of guide pulses {direction} moved the mount "
                                 f"{moved:.0f}″ by its own coordinates, not the {predicted:.0f}″ of its guide rate "
                                 f"({rate:g}× sidereal): the mount ignores guide pulses")

    def _leg(self, direction: str, back: str, radius: float, start: tuple) -> tuple:
        """Guide towards ``direction`` until the sun moved target_px, then back.

        Returns (vector px/ms, vector px/ms of the way back, warning).
        """
        total_ms = 0.0
        moved = np.zeros(2)
        step_ms = 1000.0
        max_leg_ms = self.max_leg_ms if self.method == PULSES else min(self.max_leg_ms, MAX_SLEW_LEG_MS)
        start_position = _mount_value(self.mount, "position")
        moving = "guided" if self.method == PULSES else f"slewed at the {self.slow_rate} rate"
        while True:
            self._guide(direction, step_ms)
            total_ms += step_ms
            position = self._position(radius)
            moved = np.array(position) - np.array(start)
            distance = float(np.linalg.norm(moved))
            self._say(f"{moving} {direction} for {total_ms / 1000:.1f} s: the sun moved {distance:.1f} px")
            if distance >= self.target_px:
                break
            if self.method == PULSES:
                self._check_pulses_move(direction, total_ms, start_position)
            if total_ms >= max_leg_ms:
                if self.method == SLEWS:
                    raise _RateTooSlow(f"{total_ms / 1000:.0f} s of slewing {direction} at the {self.slow_rate} "
                                       f"rate moved the sun only {distance:.1f} px")
                if distance < MIN_MOVE_PX:
                    raise _PulsesIgnored(f"the sun did not move after {total_ms / 1000:.0f} s of guide pulses "
                                         f"{direction}")
                break
            # Guide as long again as it takes, from the speed so far, with some margin
            if distance > 0.5:
                needed = (self.target_px - distance) / (distance / total_ms)
                step_ms = float(np.clip(needed * 1.1, 500.0, max(max_leg_ms - total_ms, 500.0)))
            else:
                step_ms = max(min(2 * step_ms, max_leg_ms - total_ms), 500.0)
        vector = moved / total_ms

        # Back as long, and see how far it comes back
        self._guide(back, total_ms)
        returned = np.array(self._position(radius)) - (np.array(start) + moved)
        back_share = float(-np.dot(returned, moved) / np.dot(moved, moved))
        back_moving = "guided" if self.method == PULSES else "slewed"
        self._say(f"{back_moving} {back} for {total_ms / 1000:.1f} s: the sun came back {back_share:.0%} of the way")
        if self.method == SLEWS and back_share < MIN_SLEW_BACK_SHARE:
            raise _RateTooSlow(f"slewing {back} at the {self.slow_rate} rate brought the sun back only "
                               f"{back_share:.0%} of the way {direction} moved it")
        if self.method == SLEWS and back_share < 0.9:
            # Slower that way: slew back longer, so the sun does not end up off where it started
            self._guide(back, min(total_ms * (1 - back_share) / back_share, MAX_SLEW_LEG_MS))
        if back_share < DRIFT_SHARE:
            reason = (f"{back_moving} {back} as long as {direction} moved the sun on the same way instead of back: "
                      f"the sky drifting moved it, not the mount")
            if self.method == PULSES:
                raise _PulsesIgnored(reason)
            raise CalibrationError(reason + ".  Does the mount track the sun (Track sun)?")
        warning = None
        if back_share < BACKLASH_SHARE and self.method == PULSES:
            warning = (f"backlash: {back_moving} {back} moved the sun only {back_share:.0%} as far as "
                       f"{direction}")
        return vector, returned / total_ms, warning

    def _slew_rate_names(self) -> list:
        """The slew rates, slowest first; empty when the mount cannot slew at a rate."""
        if not hasattr(self.mount, "nudge_start"):
            return []
        try:
            return [name for name, _ in self.mount.slew_rates()]
        except Exception:
            return []

    def _fast_rate(self) -> Optional[str]:
        """The fast slew rate to calibrate: the driver's centering rate, else the second slowest; None without rates.

        Always faster than the slow rate of a calibration with slews.
        """
        try:
            rates = self.mount.slew_rates()
        except Exception:
            return None
        names = [name for name, _ in rates]
        first = names.index(self.slow_rate) + 1 if self.slow_rate in names else 1
        faster = rates[first:]
        if not faster:
            return None
        for name, label in faster:
            if "center" in label.lower() or "centre" in label.lower() or "centering" in name.lower():
                return name
        return faster[0][0]

    def _fast_leg(self, direction: str, back: str, radius: float) -> Optional[tuple]:
        """Move a second at the fast rate and back.

        Returns the vectors (px per ms) there and back, or None when either barely moved the sun.
        """
        start = np.array(self._position(radius))
        seconds = self._timed_slew(direction, FAST_LEG_S)
        there = np.array(self._position(radius))
        back_seconds = self._timed_slew(back, seconds)
        returned = np.array(self._position(radius)) - there
        moved = there - start
        distance, back_distance = float(np.linalg.norm(moved)), float(np.linalg.norm(returned))
        self._say(f"moved {direction} at the fast rate for {seconds:.1f} s: the sun moved {distance:.1f} px; "
                  f"{back} {back_distance:.1f} px")
        if distance < MIN_MOVE_PX * 2 or back_distance < MIN_MOVE_PX * 2:
            return None
        return moved / (seconds * 1000), returned / (back_seconds * 1000)

    def _calibrate_fast(self, radius: float) -> dict:
        """The fast slew rate and how it moves the sun, as Calibration fields; empty when there is none or it fails."""
        rate = self._fast_rate()
        if rate is None:
            return {}
        previous = getattr(self.mount, "slew_rate", None)
        try:
            self.mount.set_slew_rate(rate)
            east = self._fast_leg("E", "W", radius)
            north = self._fast_leg("N", "S", radius)
        except CalibrationError:
            raise
        except Exception as exc:
            self._say(f"the fast rate could not be calibrated: {exc}")
            return {}
        finally:
            if previous:
                try:
                    self.mount.set_slew_rate(previous)
                except Exception:
                    pass
        if east is None or north is None:
            self._say("the fast rate barely moved the sun one way: only the slow moves will be used")
            return {}
        fields = {"fast_rate": rate, "fast_north": tuple(map(float, north[0])),
                  "fast_east": tuple(map(float, east[0]))}
        if self.method == SLEWS:
            fields.update(fast_south=tuple(map(float, north[1])), fast_west=tuple(map(float, east[1])))
        return fields

    def _check_tracking(self) -> None:
        """Refuse a mount that does not track: the sky drifting through the frame would be measured."""
        if _mount_value(self.mount, "tracking") is not False:
            return          # tracking, or the mount cannot tell
        deadline = time.monotonic() + TRACKING_WAIT_S
        while time.monotonic() < deadline:
            self._sleep(0.2)
            if _mount_value(self.mount, "tracking") is not False:
                return
        raise CalibrationError("the mount does not track: the sun drifts through the frame and that is what the "
                               "calibration would measure.  Press Track sun first")

    def _axes(self, radius: float, start: Optional[tuple] = None) -> dict:
        """The east and north legs, from where the sun is (measured when not given), as Calibration fields.

        With slews, west and south are kept as measured on the way back: slews
        of an alt-az mount need not be the opposite of east and north.
        """
        warnings = []
        if start is None:
            start = self._position(radius)
        east, west, warning = self._leg("E", "W", radius, start)
        if warning:
            warnings.append(warning)
        start = self._position(radius)
        north, south, warning = self._leg("N", "S", radius, start)
        if warning:
            warnings.append(warning)
        fields = {"east": tuple(map(float, east)), "north": tuple(map(float, north)), "warnings": warnings}
        if self.method == SLEWS:
            fields.update(west=tuple(map(float, west)), south=tuple(map(float, south)))
        return fields

    def _axes_by_slews(self, radius: float) -> dict:
        """The axes with slews, from the slowest rate up until one moves the sun every way."""
        rates = self._slew_rate_names()[:MAX_SLEW_RATES_TRIED]
        for i, rate in enumerate(rates):
            self.slow_rate = rate
            try:
                return self._axes(radius)
            except _RateTooSlow as exc:
                if i + 1 == len(rates):
                    raise CalibrationError(f"{exc}, and the faster rates did not do better either: the mount does "
                                           f"not move the sun every way at the rates tried "
                                           f"({', '.join(rates)})") from None
                self._say(f"{exc}: trying the {rates[i + 1]} rate")
        raise CalibrationError("the mount has no slew rates")

    def run(self) -> Calibration:
        """Calibrate.  Raises CalibrationError with a message for the user when it cannot."""
        position = _mount_value(self.mount, "position")
        if position and position[1] is not None and abs(position[1]) >= POLE_DEC_DEG:
            raise CalibrationError(
                f"the mount points at the celestial pole (declination {position[1]:+.0f}°), its home position, not "
                f"at the sun: guiding east and west would not move the sun.  Point the mount at the sun first "
                f"(INDI's telescope simulator: sew_hardware, mount connect localhost, mount sun goto)")
        if _mount_value(self.mount, "parked", False):
            raise CalibrationError("the mount is parked: unpark it (Track) and point it at the sun first")
        self._check_tracking()
        self._say("looking for the sun")
        latest = self.frames.latest()
        start_x, start_y, fix = self._measure((latest[0] - 1e-6) if latest else 0.0, None)
        radius = fix.radius
        frame = self.frames.latest()
        frame_size = (frame[1].shape[1], frame[1].shape[0]) if frame else (0, 0)
        self._say(f"the sun is at {start_x:.1f}, {start_y:.1f}, radius {radius:.1f} px")

        original_rate = getattr(self.mount, "slew_rate", None)
        try:
            try:
                axes = self._axes(radius, (start_x, start_y))
            except _PulsesIgnored as exc:
                rates = self._slew_rate_names()
                if not rates:
                    raise CalibrationError(f"{exc}; do the guide pulses reach the mount (driver, cable), and is "
                                           f"the mount not parked?") from None
                self._say(f"{exc}: calibrating again with slews at the {rates[0]} rate instead")
                self.method = SLEWS
                axes = self._axes_by_slews(radius)
            fast = self._calibrate_fast(radius)
        finally:
            if self.method == SLEWS and original_rate and original_rate != getattr(self.mount, "slew_rate", None):
                try:
                    self.mount.set_slew_rate(original_rate)
                except Exception:
                    pass

        calibration = Calibration(frame_size=frame_size, radius=float(radius), camera=self.camera,
                                  mount=getattr(self.mount, "identity", ""), guide_by=self.method,
                                  slow_rate=self.slow_rate, **axes, **fast)
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

#: Seconds between looks while the sun is centred.  An alt-az mount (iOptron HAZ31) lets the sun
#: drift 4-6 px in 40 s: with looks every 15 s it stays about half as far off
CENTRING_INTERVAL_S = 15.0

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

#: A move at the fast rate is only accurate when it is long compared with how fast the mount
#: reacts (the serial link, the motors speeding up and slowing down; INDI's telescope simulator
#: moves in steps of 250 ms).  Shorter corrections are guide pulses, which the driver times.
MIN_COARSE_MS = 1000.0

#: Within a fast move, an axis that would move less than this is left to the guide pulses
MIN_COARSE_AXIS_MS = 250.0

#: Corrections in a row that do not move the sun as they should before the centring gives up
MAX_FAILED_CORRECTIONS = 3

#: A correction failed when the sun moved less than this share of the way the
#: calibration says the pulses move it (in that direction)
MIN_CORRECTION_SHARE = 0.3

#: A correction that moved the sun back by more than this share of the way it should have moved
#: it (and by at least WRONG_WAY_PX) went the wrong way: the calibration is not for this mount or
#: camera (any more), and the centring stops at once instead of pushing the sun further out
WRONG_WAY_SHARE = -0.3
WRONG_WAY_PX = 5.0

#: Fixes kept for the running radius of the sun
RADIUS_HISTORY = 10

#: States of the centring
#: A mount pointing closer to a celestial pole than this (in declination) does not point at the sun
#: (it is in its home position): guiding east and west there only turns the view around the pole
POLE_DEC_DEG = 85.0


def _mount_value(mount, name: str, default=None):
    """A property of the mount (parked, position()), or the default when the mount cannot tell."""
    try:
        value = getattr(mount, name, default)
        return value() if callable(value) else value
    except Exception:
        return default


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

    With a calibration made by slews (a mount that ignores guide pulses), the
    corrections are timed slews at the calibration's slow rate instead.

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
        before = self.status
        self.status = CentringStatus(**{**asdict(self.status), "state": state, "message": message, **changes})
        if state in (STOPPED, NO_SUN) and (before.state, before.message) != (state, message):
            # Once: not again at every look while it lasts
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
        if _mount_value(self.mount, "parked", False):
            self._before = self._expected = None
            self._set(PAUSED, "the mount is parked: the centring waits until it tracks again")
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
            if self.status.state != NO_SUN:
                save_frame(self.frames, "centring")
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
            if share < WRONG_WAY_SHARE and float(np.linalg.norm(self._expected)) * -share >= WRONG_WAY_PX:
                logger.warning("Centring: the correction moved the sun the wrong way (%.0f%% of the way it should)",
                               100 * share)
                self._set(STOPPED, "the correction moved the sun the wrong way: the calibration is not for this "
                                   "mount or camera (any more); calibrate again", **found)
                return self.interval_s
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
            moves = {d: ms for d, ms in self.calibration.moves_for(-dx * COARSE_GAIN, -dy * COARSE_GAIN).items()
                     if ms >= MIN_COARSE_AXIS_MS}
            if moves and max(moves.values()) >= MIN_COARSE_MS:
                return self._coarse_move(moves, dx, dy, distance, found)

        pulses = self.calibration.pulses_for(-dx * self.gain, -dy * self.gain)
        shortest = MIN_SLEW_MS if self.calibration.by_slews else 50
        pulses = {d: min(ms, self.max_correction_ms) for d, ms in pulses.items() if ms >= shortest}
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
        moving = f"slewing at the {self.calibration.slow_rate} rate" if self.calibration.by_slews else "guiding"
        logger.info("Centring: the sun is %.1f px off (%.1f, %.1f): %s %s", distance, dx, dy, moving, text)
        self._set(CORRECTING, f"{distance:.1f} px off: {moving} {text}", corrections=self.status.corrections + 1,
                  **found)
        try:
            if self.calibration.by_slews:
                self._timed_moves(pulses, self.calibration.slow_rate)
            else:
                self._guide(pulses)
        except Exception as exc:
            what = "to move" if self.calibration.by_slews else "a guide pulse"
            self._set(STOPPED, f"the mount refused {what}: {exc}", **found)
            return self.interval_s
        if self.wait_for_pulses:
            self._stop.wait(self.settle_s)
        return self._corrected(x, y, self.calibration.movement(pulses))

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

    def _coarse_move(self, moves: dict, dx: float, dy: float, distance: float, found: dict) -> float:
        """Move most of the way at the fast slew rate: {direction: milliseconds}."""
        calibration = self.calibration
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
        try:
            self._timed_moves(moves, calibration.fast_rate)
        except Exception as exc:
            self._set(STOPPED, f"the mount refused to move: {exc}", **found)
            return self.interval_s
        if self.wait_for_pulses:
            self._stop.wait(self.settle_s)
        return self._corrected(dx + self.target[0], dy + self.target[1], calibration.movement(moves, fast=True))

    def _timed_moves(self, moves: dict, rate: str) -> None:
        """Slew at ``rate``, every axis at once, each for its own time: {direction: milliseconds}.

        Always timed for real: unlike a guide pulse, nothing but this stops the move.
        """
        mount = self.mount
        previous = getattr(mount, "slew_rate", None)
        started = []
        try:
            mount.set_slew_rate(rate)
            begin = time.monotonic()
            for direction in moves:
                mount.nudge_start(direction)
                started.append(direction)
            # Stop each axis after its own time, the shortest first
            for direction, ms in sorted(moves.items(), key=lambda item: item[1]):
                wait = begin + ms / 1000.0 - time.monotonic()
                if wait > 0:
                    self._stop.wait(wait)
                mount.nudge_stop(direction)
                started.remove(direction)
        finally:
            for direction in started:
                try:
                    mount.nudge_stop(direction)
                except Exception:
                    logger.exception("Could not stop the mount moving %s", direction)
            if previous and previous != rate:
                try:
                    mount.set_slew_rate(previous)
                except Exception:
                    pass

    def _corrected(self, x: float, y: float, expected: np.ndarray) -> float:
        """Remember what the correction should have done, to check it at the next look."""
        self._ready_after = time.monotonic()
        self._before = np.array((x, y))
        self._expected = expected
        return RECHECK_S if self.wait_for_pulses else 0.0
