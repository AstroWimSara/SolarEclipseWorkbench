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
from typing import Dict, Optional, Tuple

from solareclipseworkbench.bracketing import HDR_ROUND_TRIP, bracket_exposures, hdr_offsets, parse_bracket
from solareclipseworkbench.exposure_calculator import parse_shutter_speed

# get_config/set_config + trigger_capture + wait for capture complete.  Matches
# the buffer the wizard has always used between corona shots.
PICTURE_OVERHEAD_S = 2.0

# Per shot and fixed overhead of a take_hdr sequence (see wizard HDR planning).
HDR_SHOT_OVERHEAD_S = 1.5
HDR_FIXED_OVERHEAD_S = 2.0
# An HDR frame is triggered without waiting for the full picture round trip, so
# it is this much quicker than a picture on the same camera: an EOS 80D took
# about 1.4 s per HDR frame, an EOS R (2.35 s per picture) about 1.9 s.
HDR_SHOT_SAVING_S = 0.5

# Configuration round trips before the shutter is pressed, plus the time after
# release until the camera reports capture complete and has written its burst
# buffer to the card.
BURST_OVERHEAD_S = 6.0

# Nikon bursts are given as a number of frames.  Frame rate depends on the
# body and the drive mode set on its dial; this is a middle-of-the-road guess.
NIKON_BURST_FPS = 10.0

# A burst measured by the camera test is planned with BURST_MARGIN_FACTOR times
# its measured overhead plus BURST_MARGIN_S, also when that is shorter than
# BURST_OVERHEAD_S: a camera writing to a fast card (CFexpress on a Z 8 or an
# EOS R5) finishes a burst within a second or two, and the default would hold
# the next shot back for six.  The planned burst always outlasts the measured
# ones by at least the margin.  BURST_OVERHEAD_S stays for untested cameras: it
# was calibrated on a burst that was still busy during the 2026-08-12 eclipse
# long after it was planned to end.  The test bursts are taken back to back so
# they include a camera that is still writing the previous burst to its card.
BURST_MARGIN_FACTOR = 1.5
BURST_MARGIN_S = 1.0

# The diamond ring bursts, and the beads bursts when the Baily's beads window is
# not known, shoot this long.  A Nikon takes this many seconds' worth of frames.
CONTACT_BURST_S = 2.0
# With the lunar limb profile, a beads burst covers the Baily's beads window
# plus this margin on either side, ...
BEADS_WINDOW_MARGIN_S = 0.5
# ... but never longer than this, nor than the longest burst the camera test
# measured (an untested camera keeps CONTACT_BURST_S): a longer burst can
# overflow the camera buffer and keep the camera busy far longer than planned.
MAX_BEADS_BURST_S = 5.0
# A longer beads burst also moves the diamond ring burst next to it (earlier
# before C2, later after C3).  It is shortened when it would move the diamond
# ring burst by more than this.
DIAMOND_RING_SHIFT_MAX_S = 2.0

# The camera test takes two bursts back to back, to separate the time per second
# of shooting from the fixed overhead: in seconds for Canon and Sony, in frames
# for Nikon (100 frames is 5 s on a 20 fps Z 8).
TEST_BURSTS_S = (1.0, MAX_BEADS_BURST_S)
NIKON_TEST_BURSTS_FRAMES = (10, 100)

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
    # Busy time per second of shooting: more than 1 when the camera empties its
    # buffer to the card slower than it fills it (Canon and Sony; a Nikon's is in
    # its measured frame rate).
    burst_busy_per_s: float = 1.0
    # Longest burst, in seconds of shooting, these numbers were measured for
    burst_max_s: float = CONTACT_BURST_S


DEFAULT_PROFILE = TimingProfile()


def planning_profile(vendor: Optional[str], picture_overhead_s: Optional[float] = None,
                     burst_overhead_s: Optional[float] = None, burst_fps: Optional[float] = None,
                     burst_busy_per_s: Optional[float] = None,
                     burst_max_s: Optional[float] = None) -> TimingProfile:
    """Overheads to plan with, from the ones measured on a camera (None: not measured).

    A measured picture overhead is used when it is longer than the default.  A
    measured burst is planned with its own overhead plus a margin, also when
    that is shorter than the default (see BURST_MARGIN_FACTOR), and a Nikon with
    its measured frame rate.  A measured busy time per second of shooting is
    used when it is more than 1.
    """
    picture = max(PICTURE_OVERHEAD_S, picture_overhead_s or 0.0)
    if burst_overhead_s is not None:
        burst = BURST_MARGIN_FACTOR * max(0.0, burst_overhead_s) + BURST_MARGIN_S
    else:
        burst = BURST_OVERHEAD_S
    fps = burst_fps if vendor == "Nikon" and burst_fps else NIKON_BURST_FPS
    busy_per_s = 1.0 if vendor == "Nikon" else max(1.0, burst_busy_per_s or 1.0)
    longest = min(MAX_BEADS_BURST_S, max(CONTACT_BURST_S, burst_max_s or CONTACT_BURST_S))
    return TimingProfile(picture_overhead_s=round(picture, 2), burst_overhead_s=round(burst, 2),
                         nikon_burst_fps=round(fps, 1), burst_busy_per_s=round(busy_per_s, 2),
                         burst_max_s=round(longest, 1))


@dataclass(frozen=True)
class BurstFit:
    """What two test bursts tell about a camera (see fit_test_bursts)."""

    overhead_s: float                  # fixed busy time on top of the shooting
    fps: Optional[float] = None        # Nikon frame rate; None: not measured
    busy_per_s: Optional[float] = None  # Canon/Sony busy time per second of shooting; None: not measured
    max_s: Optional[float] = None      # seconds of shooting of the long burst


def nikon_burst_fit(short: Tuple[int, float], long: Tuple[int, float]) -> Tuple[Optional[float], float]:
    """Frame rate and overhead of a Nikon from two bursts with a different number of frames.

    Args:
        - short, long: (frames, seconds the camera was busy) of each burst

    Returns: Frames per second (None when the two bursts do not give a plausible
             rate; NIKON_BURST_FPS is then assumed) and the overhead of the long
             burst in seconds on top of its shooting time.
    """
    (short_frames, short_s), (long_frames, long_s) = short, long
    fps = None
    if long_frames > short_frames and long_s - short_s > 0.1:
        fps = (long_frames - short_frames) / (long_s - short_s)
        if not 1.0 <= fps <= 120.0:
            fps = None
    overhead = long_s - long_frames / (fps or NIKON_BURST_FPS)
    return (round(fps, 1) if fps else None), round(max(0.0, overhead), 2)


def fit_test_bursts(vendor: Optional[str], short: Tuple[float, float], long: Tuple[float, float]) -> BurstFit:
    """Busy time of the camera's bursts from a short and a long test burst.

    Args:
        - vendor: 'Canon', 'Nikon', 'Sony' or None
        - short, long: (burst parameter, seconds the camera was busy) of each burst;
                       the parameter is frames for Nikon, seconds for the others

    For Canon and Sony the busy time per second of shooting is the difference of
    the two; the overhead is chosen so that both measured bursts are covered.
    """
    if vendor == "Nikon":
        fps, overhead = nikon_burst_fit((int(short[0]), short[1]), (int(long[0]), long[1]))
        return BurstFit(overhead, fps=fps, max_s=round(long[0] / (fps or NIKON_BURST_FPS), 1))
    (short_d, short_s), (long_d, long_s) = short, long
    busy_per_s = None
    if long_d > short_d:
        busy_per_s = (long_s - short_s) / (long_d - short_d)
        if not 0.5 <= busy_per_s <= 20.0:
            busy_per_s = None
    used = max(1.0, busy_per_s or 1.0)
    overhead = max(short_s - used * short_d, long_s - used * long_d, 0.0)
    return BurstFit(round(overhead, 2), busy_per_s=(round(busy_per_s, 2) if busy_per_s else None),
                    max_s=float(long_d))


def burst_param_for_s(vendor: Optional[str], seconds: float, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """take_burst parameter that shoots for this many seconds: frames for Nikon, seconds otherwise."""
    if vendor == "Nikon":
        return max(1, round(seconds * profile.nikon_burst_fps))
    return round(seconds, 1)


# A script line that carries the timing measured on a camera, for the check that
# SEW runs when the script is loaded:
#   # timing: Nikon Z 8; picture_overhead_s=2; burst_overhead_s=1.9; nikon_burst_fps=19.6; burst_busy_per_s=1;
#             burst_max_s=5
TIMING_DIRECTIVE = "# timing:"


def timing_directive(camera_name: str, profile: TimingProfile) -> str:
    """The script line that records the timing a script was planned with for camera_name."""
    return (f"{TIMING_DIRECTIVE} {camera_name}; picture_overhead_s={profile.picture_overhead_s:g}; "
            f"burst_overhead_s={profile.burst_overhead_s:g}; nikon_burst_fps={profile.nikon_burst_fps:g}; "
            f"burst_busy_per_s={profile.burst_busy_per_s:g}; burst_max_s={profile.burst_max_s:g}")


def parse_timing_directives(lines) -> Dict[str, TimingProfile]:
    """The timing per camera name recorded in a script (see timing_directive).

    Lines that are not a valid timing directive are ignored.
    """
    profiles = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.lower().startswith(TIMING_DIRECTIVE):
            continue
        fields = [f.strip() for f in stripped[len(TIMING_DIRECTIVE):].split(";")]
        if not fields[0]:
            continue
        values = {}
        try:
            for item in fields[1:]:
                if item:
                    key, value = item.split("=", 1)
                    values[key.strip()] = float(value)
            profile = TimingProfile(**values)
        except (ValueError, TypeError):
            continue
        if (min(profile.picture_overhead_s, profile.burst_overhead_s) < 0
                or min(profile.nikon_burst_fps, profile.burst_busy_per_s, profile.burst_max_s) <= 0):
            continue
        profiles[fields[0]] = profile
    return profiles


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
    return burst_shooting_s(vendor, burst_param, profile) * profile.burst_busy_per_s + profile.burst_overhead_s


def hdr_shot_overhead_s(profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Overhead per HDR frame: the default, or longer on a camera measured to be slower."""
    return max(HDR_SHOT_OVERHEAD_S, profile.picture_overhead_s - HDR_SHOT_SAVING_S)


def hdr_duration_s(start_shutter_speed: str, stops: int, sequence: str = HDR_ROUND_TRIP,
                   profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Busy time of a take_hdr: ramp up to the longest exposure (and back down for a round trip)."""
    start_s = _exposure_s(start_shutter_speed)
    offsets = hdr_offsets(stops, sequence)
    return (sum(start_s * 2 ** k for k in offsets) + len(offsets) * hdr_shot_overhead_s(profile)
            + HDR_FIXED_OVERHEAD_S)


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
# A Sony shoots within 0.2 to 0.3 s when its settings do not change (measured on
# an A7R IIIA, discussion #192), as they do not after a prepare_camera.
BURST_LEAD_BY_VENDOR_S = {"Sony": 0.3}


def burst_lead_s(vendor: Optional[str]) -> float:
    """Seconds from a take_burst command until the camera starts shooting."""
    return BURST_LEAD_BY_VENDOR_S.get(vendor, BURST_LEAD_S)


@dataclass(frozen=True)
class ContactBurstPlan:
    """When the diamond ring and Baily's beads bursts around C2 and C3 start.

    The bursts follow the order of the phenomena: before C2 the diamond ring is
    followed by the beads, after C3 the beads are followed by the diamond ring.
    The burst starts are in tenths of a second; when the Baily's beads window
    is known, a beads burst can start after C2 or before C3, which shows as a
    negative value.  The buffers and the first totality shot are whole seconds.
    """

    burst_param: float           # script parameter of the diamond ring bursts: frames for Nikon, seconds otherwise
    burst_s: float               # estimated time a diamond ring burst keeps the camera busy
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
    # The beads bursts: script parameter, seconds of shooting and estimated busy time.
    # Longer than the diamond ring bursts when they cover a long Baily's beads window.
    c2_beads_param: float = 0.0
    c2_beads_shooting_s: float = 0.0
    c2_beads_s: float = 0.0
    c3_beads_param: float = 0.0
    c3_beads_shooting_s: float = 0.0
    c3_beads_s: float = 0.0

    @property
    def c3_first_start(self) -> float:
        """Seconds after C3 (negative: before C3) of the first command of the C3 sequence."""
        return self.c3_prepare_start if self.c3_prepare_start is not None else self.c3_beads_start


def prepare_duration_s(switch_s: float, profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Busy time of a prepare_camera that changes the drive mode: the configuration plus the change."""
    return profile.picture_overhead_s + switch_s


def beads_burst_start(window: Tuple[float, float], shooting_s: float, lead_s: float = BURST_LEAD_S) -> float:
    """When to start a beads burst so its shooting is centred on the Baily's beads window.

    Args:
        - window: Start and end of the window, in seconds relative to the contact (negative: before it)
        - shooting_s: Time the shutter is held during the burst
        - lead_s: Seconds from the command until the camera starts shooting (see burst_lead_s)

    Returns: Start of the take_burst command in seconds relative to the contact, to a tenth of a second.
    """
    centre = (window[0] + window[1]) / 2
    return round(centre - shooting_s / 2 - lead_s, 1)


def beads_burst_seconds(window: Tuple[float, float], profile: TimingProfile = DEFAULT_PROFILE) -> float:
    """Seconds of shooting that cover a Baily's beads window, within what the camera was measured for.

    Between CONTACT_BURST_S and the shorter of MAX_BEADS_BURST_S and the
    longest burst of the camera test (profile.burst_max_s), to a tenth of a second.
    """
    wanted = window[1] - window[0] + 2 * BEADS_WINDOW_MARGIN_S
    longest = min(MAX_BEADS_BURST_S, max(CONTACT_BURST_S, profile.burst_max_s))
    return round(min(longest, max(CONTACT_BURST_S, wanted)), 1)


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
                              seconds relative to the contact.  The beads bursts are centred on them
                              and, on a tested camera, cover them (see beads_burst_seconds);
                              without both, the bursts start at C2-4 s and C3+1 s.

    Every burst shoots CONTACT_BURST_S, except a beads burst that covers its
    window.  Such a burst is shortened when it would move the diamond ring burst
    next to it by more than DIAMOND_RING_SHIFT_MAX_S; the diamond ring burst
    always starts once the beads burst is estimated to have finished.

    The C2 diamond ring burst follows the partial-phase pictures and the C3 beads
    burst follows the totality shots, so both start in another drive mode than
    the shot before.  On a camera that is slow to change drive mode (see
    MODE_SWITCH_S), a prepare_camera changes the mode before each of them, so
    the bursts shoot at the planned time however long the change takes.
    """
    lead_s = burst_lead_s(vendor)
    burst_param = burst_param_for_s(vendor, CONTACT_BURST_S, profile)
    burst_s = burst_duration_s(vendor, burst_param, profile)
    burst_whole_s = math.ceil(burst_s)
    switch_s = mode_switch_s(vendor) if bursts_enabled else 0.0
    beads_timed = beads_c2 is not None and beads_c3 is not None

    def beads(window, seconds, fixed_start):
        """(param, shooting s, busy s, start relative to the contact) of a beads burst."""
        param = burst_param_for_s(vendor, seconds, profile) if window is not None else burst_param
        shooting = burst_shooting_s(vendor, param, profile)
        start = beads_burst_start(window, shooting, lead_s) if window is not None else fixed_start
        return param, shooting, burst_duration_s(vendor, param, profile), start

    def c2_diamond(c2_beads):
        return round(-c2_beads[3] + burst_whole_s, 1)

    def c3_diamond(c3_beads):
        return round(c3_beads[3] + math.ceil(c3_beads[2]), 1)

    def fitted(window, fixed_start, diamond_start):
        """The beads burst that covers its window without moving the diamond ring burst too far."""
        standard = beads(window, CONTACT_BURST_S, fixed_start)
        if window is None:
            return standard
        seconds = beads_burst_seconds(window, profile)
        while True:
            burst = beads(window, seconds, fixed_start)
            if (seconds <= CONTACT_BURST_S
                    or abs(diamond_start(burst) - diamond_start(standard)) <= DIAMOND_RING_SHIFT_MAX_S):
                return burst
            seconds = round(seconds - 0.1, 1)

    c2_beads = fitted(beads_c2 if beads_timed else None, -C2_BEADS_START_S, c2_diamond)
    c3_beads = fitted(beads_c3 if beads_timed else None, C3_BEADS_START_S, c3_diamond)
    c2_beads_start = -c2_beads[3]
    c3_beads_start = c3_beads[3]
    c2_diamond_start = c2_diamond(c2_beads)
    c3_diamond_start = c3_diamond(c3_beads)

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
        totality_first_shot = max(3, math.ceil(c2_beads[2] - c2_beads_start))
    else:
        c2_buffer = CONTACT_BUFFER_S
        c3_buffer = CONTACT_BUFFER_S
        totality_first_shot = 3

    return ContactBurstPlan(
        burst_param, burst_s, c2_diamond_start, c2_beads_start, c3_beads_start, c3_diamond_start,
        c2_buffer, c3_buffer, totality_first_shot, beads_timed and bursts_enabled, switch_s,
        c2_prepare_start, c3_prepare_start,
        c2_beads_param=c2_beads[0], c2_beads_shooting_s=round(c2_beads[1], 2), c2_beads_s=c2_beads[2],
        c3_beads_param=c3_beads[0], c3_beads_shooting_s=round(c3_beads[1], 2), c3_beads_s=c3_beads[2])
