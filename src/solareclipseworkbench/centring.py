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

Guide pulses are slow on purpose (half the sidereal rate is common: 7.5″ a
second, half a pixel of a sun of 60 pixels), so a calibration takes a minute or
two.  It is done once, before C1, with the sun in the live view.

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

    def matches(self, frame_size: tuple, camera: str = "") -> bool:
        """Whether this calibration is for frames of this size (and this camera, when both are known)."""
        return tuple(frame_size) == tuple(self.frame_size) and (not camera or not self.camera
                                                                  or camera == self.camera)

    def describe(self) -> str:
        north_pps, east_pps = self.pixels_per_second()
        text = (f"guiding east moves the sun towards {self.angle_deg:.0f}° in the frame, the frame is "
                f"{'mirrored' if self.mirrored else 'not mirrored'}; a second of guiding moves the sun "
                f"{north_pps:.2f} px north/south, {east_pps:.2f} px east/west")
        if self.warnings:
            text += "; " + "; ".join(self.warnings)
        return text

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "Calibration":
        data = json.loads(text)
        for key in ("north", "east", "frame_size"):
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

        calibration = Calibration(north=tuple(map(float, north)), east=tuple(map(float, east)),
                                  frame_size=frame_size, radius=float(radius), camera=self.camera,
                                  warnings=warnings)
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
