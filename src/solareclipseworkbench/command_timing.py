"""How long a camera command keeps the camera busy.

Every camera command holds the camera's USB lock from start to finish, and a
command that cannot get the lock within ``camera._MAX_LOCK_WAIT_S`` is dropped.
Two commands for the same camera therefore have to be spaced by at least the
time the first one really takes, which is far more than its exposure time:
reading and writing the camera configuration, waiting for the capture to
complete and, after a burst, waiting for the camera to empty its buffer to the
card all happen while the lock is held.

The wizard uses these estimates to space the commands it writes, and the
scheduler uses them to warn when a script asks for more than the camera can do.
Keeping both on the same numbers means a generated script never triggers its
own warning.

The estimates are deliberately realistic rather than worst case: a warning
that fires for every script would be ignored.  The burst overhead was
calibrated on the 2026-08-12 eclipse, where a Canon EOS R and 80D burst
started at C2-8s was still busy at C2-0.5s and the C2 diamond ring burst
queued behind it was dropped.
"""

from dataclasses import dataclass
from typing import Optional

from solareclipseworkbench.exposure_calculator import parse_shutter_speed

# get_config/set_config + trigger_capture + wait for capture complete.  Matches
# the buffer the wizard has always used between corona shots.
PICTURE_OVERHEAD_S = 2.0

# Per shot and fixed overhead of a take_hdr sequence (see wizard HDR planning).
HDR_SHOT_OVERHEAD_S = 1.5
HDR_FIXED_OVERHEAD_S = 2.0

# Configuration round trips before the shutter is pressed, plus the time after
# release until the camera reports capture complete and has written its burst
# buffer to the card.
BURST_OVERHEAD_S = 6.0

# Nikon bursts are given as a number of frames.  Frame rate depends on the
# body and the drive mode set on its dial; this is a middle-of-the-road guess.
NIKON_BURST_FPS = 10.0


@dataclass(frozen=True)
class TimingProfile:
    """Overheads used for the estimates; the defaults, or values measured on a camera."""

    picture_overhead_s: float = PICTURE_OVERHEAD_S
    burst_overhead_s: float = BURST_OVERHEAD_S
    nikon_burst_fps: float = NIKON_BURST_FPS


DEFAULT_PROFILE = TimingProfile()


def vendor_from_name(camera_name: str) -> Optional[str]:
    """Guess the vendor from a camera name as written in a script.

    Returns 'Canon', 'Nikon', 'Sony' or None (e.g. for a user-defined alias).
    """
    name = (camera_name or "").lower()
    for vendor in ("Canon", "Nikon", "Sony"):
        if vendor.lower() in name:
            return vendor
    return None


def _exposure_s(shutter_speed: str) -> float:
    try:
        return max(0.0, parse_shutter_speed(str(shutter_speed)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def picture_duration_s(shutter_speed: str, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Busy time of a take_picture."""
    return _exposure_s(shutter_speed) + profile.picture_overhead_s


def burst_shooting_s(vendor: Optional[str], burst_param: float, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Time the shutter is held during a take_burst (without the overhead)."""
    if vendor == "Nikon":
        return float(burst_param) / profile.nikon_burst_fps
    return float(burst_param)


def burst_duration_s(vendor: Optional[str], burst_param: float, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Busy time of a take_burst.

    For Nikon ``burst_param`` is a number of frames; for Canon and Sony it is
    the number of seconds the shutter is held down.  An unknown vendor is
    treated as seconds, which is what the script format documents.
    """
    return burst_shooting_s(vendor, burst_param, profile) + profile.burst_overhead_s


def hdr_duration_s(start_shutter_speed: str, stops: int) -> float:
    """Busy time of a take_hdr: ramp down to the slowest speed and back up."""
    start_s = _exposure_s(start_shutter_speed)
    ramp_down = sum(start_s * (2 ** k) for k in range(stops + 1))
    ramp_up = sum(start_s * (2 ** k) for k in range(stops - 1, -1, -1))
    n_shots = 2 * stops + 1
    return ramp_down + ramp_up + n_shots * HDR_SHOT_OVERHEAD_S + HDR_FIXED_OVERHEAD_S


def bracket_duration_s(shutter_speed: str, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Lower bound for a take_bracket.

    The number of frames depends on vendor-specific bracket syntax, so only a
    single frame is counted: this can miss a conflict but never invents one.
    """
    return picture_duration_s(shutter_speed, profile)
