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

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from solareclipseworkbench.bracketing import HDR_ROUND_TRIP, bracket_exposures, hdr_offsets, parse_bracket
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

# A Sony bracket is a continuous bracketing mode with the shutter held for the
# exposures of all frames; the configuration writes, bulb on/off and emptying
# the events add this much.  Calibrated on the 2026-08-12 eclipse (discussion
# #192): back-to-back "Bracketing C 3.0 Steps 5 Pictures" at 1/30 on a Sony
# A7R IIIA (2.4 s of exposures) kept the camera busy for about 7 s each.
SONY_BRACKET_OVERHEAD_S = 4.5

# Extra time taken by the first command after the camera changes drive mode
# (single picture, continuous burst, a bracketing mode).  Sony changes its
# capture mode slowly and steps the shutter speed one notch at a time.  On the
# 2026-08-12 eclipse, the first bracket after the partial-phase pictures took
# about 4 s longer than the ones after it, and the next bracket was dropped
# (discussion #192).  Other brands have not shown a measurable delay.
MODE_SWITCH_S = {"Sony": 4.0}


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


def mode_switch_s(vendor: Optional[str]) -> float:
    """Extra busy time of the first command after a change of drive mode (see MODE_SWITCH_S)."""
    return MODE_SWITCH_S.get(vendor, 0.0)


def drive_mode(func_name: str, bracket: Optional[str] = None) -> Optional[str]:
    """The drive mode a camera command puts the camera in, or None for non-camera commands.

    ``bracket`` is the bracket of a take_bracket, or the mode of a prepare_camera.

    Two commands with a different drive mode make the camera switch modes in
    between (see MODE_SWITCH_S).  Each bracket is its own mode, as a Sony has a
    separate capture mode per EV step and number of frames.
    """
    if func_name in ("take_picture", "take_hdr"):
        return "single"
    if func_name == "take_burst":
        return "burst"
    if func_name == "take_bracket":
        return "bracket " + (bracket or "").strip().strip('"')
    if func_name == "prepare_camera":
        # Prepares the mode of the command that follows: 'single', 'burst' or a bracket
        mode = (bracket or "").strip().strip('"').strip()
        if mode.lower() in ("single", "burst"):
            return mode.lower()
        return "bracket " + mode
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


def hdr_duration_s(start_shutter_speed: str, stops: int, sequence: str = HDR_ROUND_TRIP) -> float:
    """Busy time of a take_hdr: ramp up to the longest exposure (and back down for a round trip)."""
    start_s = _exposure_s(start_shutter_speed)
    offsets = hdr_offsets(stops, sequence)
    return sum(start_s * 2 ** k for k in offsets) + len(offsets) * HDR_SHOT_OVERHEAD_S + HDR_FIXED_OVERHEAD_S


def bracket_duration_s(shutter_speed: str, profile: TimingProfile = DEFAULT_PROFILE,
                       bracket: Optional[str] = None, vendor: Optional[str] = None) -> float:
    """Lower bound for a take_bracket: the exposures of all frames plus one picture overhead.

    Canon and the software bracket pay the overhead per frame, Nikon and Sony
    shoot the frames as one burst; counting it once can miss a conflict but
    never invents one.  A Sony bracket has a measured overhead of its own
    (SONY_BRACKET_OVERHEAD_S).  Without a readable bracket, a single frame is counted.
    """
    try:
        spec = parse_bracket(bracket) if bracket is not None else None
    except ValueError:
        spec = None
    if spec is None:
        return picture_duration_s(shutter_speed, profile)
    overhead = SONY_BRACKET_OVERHEAD_S if vendor == "Sony" else profile.picture_overhead_s
    return sum(bracket_exposures(_exposure_s(shutter_speed), spec)) + overhead


def bracket_planning_s(shutter_speed: str, bracket: str, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Busy time to plan a take_bracket with: every frame pays the picture overhead.

    That is what a Canon AEB and the software bracket take; Nikon and Sony shoot
    the bracket as one burst and are faster.  Longer than bracket_duration_s, so
    a generated script never triggers the load-time warning.
    """
    spec = parse_bracket(bracket)
    return sum(bracket_exposures(_exposure_s(shutter_speed), spec)) + spec.frames * profile.picture_overhead_s


# Partial-phase shots stay at least this far from C1, C2, C3 and C4.
CONTACT_BUFFER_S = 10

# The beads burst before C2 starts this many seconds before C2: shooting begins
# about a second later, so it covers the last ~3 s before C2.  Used when the
# Baily's beads window is not known (no lunar limb profile).
C2_BEADS_START_S = 4
# The beads burst after C3 starts this many seconds after C3.
C3_BEADS_START_S = 1

# Shooting starts about this long after a take_burst command: the camera
# configuration is written first.
BURST_LEAD_S = 1.0


@dataclass(frozen=True)
class ContactBurstPlan:
    """When the diamond ring and Baily's beads bursts around C2 and C3 start.

    The bursts follow the order of the phenomena: before C2 the diamond ring is
    followed by the beads, after C3 the beads are followed by the diamond ring.
    The burst starts are in tenths of a second; when the Baily's beads window
    is known, a beads burst can start after C2 or before C3, which shows as a
    negative value.  The buffers and the first totality shot are whole seconds.
    """

    burst_param: float           # script parameter: frames for Nikon, seconds for Canon/Sony
    burst_s: float               # estimated time a burst keeps the camera busy
    c2_diamond_start: float      # seconds before C2
    c2_beads_start: float        # seconds before C2 (negative: after C2)
    c3_beads_start: float        # seconds after C3 (negative: before C3)
    c3_diamond_start: float      # seconds after C3
    c2_buffer: int               # partial shots end at least this long before C2
    c3_buffer: int               # partial shots start at least this long after C3
    totality_first_shot: int     # seconds after C2 of the first totality shot
    beads_timed: bool = False    # whether the beads bursts are aimed at the Baily's beads windows
    switch_s: float = 0.0        # time the camera needs to change drive mode (see MODE_SWITCH_S)
    # A prepare_camera before the C2 diamond ring burst and before the C3 beads burst
    # changes the drive mode ahead of them; None when the camera changes mode quickly.
    c2_prepare_start: Optional[float] = None    # seconds before C2
    c3_prepare_start: Optional[float] = None    # seconds after C3 (negative: before C3)

    @property
    def c3_first_start(self) -> float:
        """Seconds after C3 (negative: before C3) of the first command of the C3 sequence."""
        return self.c3_prepare_start if self.c3_prepare_start is not None else self.c3_beads_start


def prepare_duration_s(switch_s: float, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Busy time of a prepare_camera that changes the drive mode: the configuration plus the change."""
    return profile.picture_overhead_s + switch_s


def beads_burst_start(window: Tuple[float, float], shooting_s: float) -> float:
    """When to start a beads burst so its shooting is centred on the Baily's beads window.

    Args:
        - window: Start and end of the window, in seconds relative to the contact (negative: before it)
        - shooting_s: Time the shutter is held during the burst

    Returns: Start of the take_burst command in seconds relative to the contact, to a tenth of a second.
    """
    centre = (window[0] + window[1]) / 2
    return round(centre - shooting_s / 2 - BURST_LEAD_S, 1)


def contact_burst_plan(vendor: Optional[str], bursts_enabled: bool = True,
                       profile: TimingProfile = DEFAULT_PROFILE,
                       beads_c2: Optional[Tuple[float, float]] = None,
                       beads_c3: Optional[Tuple[float, float]] = None) -> ContactBurstPlan:
    """Space the C2/C3 bursts, and the shots next to them, by the estimated burst duration.

    Args:
        - vendor: 'Canon', 'Nikon', 'Sony' or None
        - bursts_enabled: False when the script has no diamond ring/beads bursts; the
                          neighbouring shots then keep their usual distance from C2/C3.
        - profile: Overheads to plan with (defaults, or measured on the camera)
        - beads_c2, beads_c3: Baily's beads window around C2 and C3 (BEADS_C2_START/_END, ...), in
                              seconds relative to the contact.  The beads bursts are centred on them;
                              without both, the bursts start at C2-4 s and C3+1 s.

    The C2 diamond ring burst follows the partial-phase pictures and the C3 beads
    burst follows the totality shots, so both start in another drive mode than
    the shot before.  On a camera that is slow to change drive mode (see
    MODE_SWITCH_S), a prepare_camera changes the mode before each of them, so
    the bursts shoot at the planned time however long the change takes.
    """
    # Nikon: number of frames.  Canon and Sony: seconds the shutter is held.
    burst_param = 30 if vendor == "Nikon" else 2
    burst_s = burst_duration_s(vendor, burst_param, profile)
    burst_whole_s = math.ceil(burst_s)
    switch_s = mode_switch_s(vendor) if bursts_enabled else 0.0

    beads_timed = beads_c2 is not None and beads_c3 is not None
    if beads_timed:
        shooting_s = burst_shooting_s(vendor, burst_param, profile)
        c2_beads_start = -beads_burst_start(beads_c2, shooting_s)
        c3_beads_start = beads_burst_start(beads_c3, shooting_s)
    else:
        c2_beads_start = C2_BEADS_START_S
        c3_beads_start = C3_BEADS_START_S
    c2_diamond_start = round(c2_beads_start + burst_whole_s, 1)
    c3_diamond_start = round(c3_beads_start + burst_whole_s, 1)

    c2_prepare_start = c3_prepare_start = None
    if switch_s > 0:
        # A prepare_camera writes the configuration and changes the drive mode
        prepare_whole_s = math.ceil(prepare_duration_s(switch_s, profile))
        c2_prepare_start = round(c2_diamond_start + prepare_whole_s, 1)
        c3_prepare_start = round(c3_beads_start - prepare_whole_s, 1)

    if bursts_enabled:
        # Room for the last partial shot (at most 1/30 s) to finish before the
        # C2 sequence starts, and for the C3 diamond ring burst to finish
        # before the first partial shot after C3.
        c2_first_start = c2_prepare_start if c2_prepare_start is not None else c2_diamond_start
        c2_buffer = max(CONTACT_BUFFER_S, math.ceil(c2_first_start + picture_duration_s("1/30", profile)))
        c3_buffer = max(CONTACT_BUFFER_S, math.ceil(c3_diamond_start + burst_whole_s))
        # Totality starts with the camera still busy with the beads burst.
        totality_first_shot = max(3, math.ceil(burst_s - c2_beads_start))
    else:
        c2_buffer = CONTACT_BUFFER_S
        c3_buffer = CONTACT_BUFFER_S
        totality_first_shot = 3

    return ContactBurstPlan(burst_param, burst_s, c2_diamond_start, c2_beads_start, c3_beads_start,
                            c3_diamond_start, c2_buffer, c3_buffer, totality_first_shot,
                            beads_timed and bursts_enabled, switch_s, c2_prepare_start, c3_prepare_start)
