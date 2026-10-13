"""The bracket of a take_bracket command: how far apart the frames are and how many there are.

A script gives the bracket as ``"<EV step> <frames>"``, the same for every camera brand, e.g.
``"1 3"`` (3 frames, 1 EV apart), ``"0.7 5"`` or ``"1 2/3 5"``.  The frames are centred on the
exposure of the command: ``"1 3"`` at 1/60 takes 1/125, 1/60 and 1/30.

Older forms are still accepted:

- ``"+/- 1 2/3"`` (the Canon AEB syntax): 5 frames, 1 2/3 EV apart.
- A Sony bracketing capture mode, e.g. ``"Bracketing C 0.3 Steps 5 Pictures"``: passed to the
  camera as is.

Decimal steps that are the usual camera rounding of thirds (0.3, 0.7, 1.3, ...) are read as thirds.

No gphoto2 here: the scheduler, the timing estimates and the wizard use this as well.
"""

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

# Number of frames of the old '+/- <step>' form, which had no frame count.
DEFAULT_FRAMES = 5
MIN_FRAMES = 3
MAX_FRAMES = 9
MAX_EV_STEP = 3.0

# EV steps and numbers of frames to offer when the camera's own options are not known.
STANDARD_STEPS = (1 / 3, 1 / 2, 2 / 3, 1.0, 4 / 3, 3 / 2, 5 / 3, 2.0, 7 / 3, 5 / 2, 8 / 3, 3.0)
STANDARD_FRAMES = (3, 5, 7, 9)
# Canon sets the number of AEB frames in a custom function, not over USB.
CANON_FRAMES = (3, 5, 7)

_SONY_MODE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:EV\s*)?Steps?\s+(\d+)\s*Pictures?", re.IGNORECASE)


@dataclass(frozen=True)
class BracketSpec:
    """A bracket: ``frames`` exposures, ``ev_step`` EV apart, centred on the base exposure."""

    ev_step: float
    frames: int
    mode_name: Optional[str] = None     # Sony capture mode given literally in the script

    def ev_offsets(self) -> List[float]:
        """EV offset of each frame from the base exposure, darkest first."""
        half = self.frames // 2
        return [k * self.ev_step for k in range(-half, half + 1)]

    def describe(self) -> str:
        return f"{self.frames} frames, {format_ev(self.ev_step)} EV apart"


def snap_ev(ev: float) -> float:
    """Read the decimal rounding of a third or half stop (0.3, 0.7, 1.3, 0.5, ...) as that exact value."""
    thirds = round(ev * 3)
    if abs(ev * 3 - thirds) < 0.15:
        return thirds / 3
    halves = round(ev * 2)
    if abs(ev * 2 - halves) < 0.1:
        return halves / 2
    return ev


def parse_ev(text: str) -> float:
    """Parse an EV step: '1', '0.7', '2/3' or '1 2/3'.

    Raises:
        ValueError: If the text is not a positive EV step of at most 3 EV.
    """
    parts = text.replace("+/-", " ").replace("EV", " ").replace("ev", " ").split()
    if not 1 <= len(parts) <= 2:
        raise ValueError(f"'{text}' is not an EV step")
    total = 0.0
    for i, part in enumerate(parts):
        try:
            if "/" in part:
                if i != len(parts) - 1:
                    raise ValueError
                num, den = part.split("/", 1)
                total += int(num) / int(den)
            else:
                if i != 0:
                    raise ValueError
                total += float(part)
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"'{text}' is not an EV step") from None
    if not (math.isfinite(total) and 0 < total <= MAX_EV_STEP + 1e-6):
        raise ValueError(f"EV step '{text}' must be more than 0 and at most {MAX_EV_STEP:g}")
    return snap_ev(total)


def format_ev(ev: float) -> str:
    """Format an EV step the way cameras show it: '1/3', '1 2/3', '1/2', '2'."""
    for den in (3, 2):
        n = round(ev * den)
        if abs(ev * den - n) < 1e-6:
            whole, rest = divmod(n, den)
            if rest == 0:
                return str(whole)
            return f"{whole} {rest}/{den}" if whole else f"{rest}/{den}"
    return f"{ev:g}"


def parse_bracket(text: str) -> BracketSpec:
    """Parse the bracket field of a take_bracket command (see the module docstring).

    Raises:
        ValueError: With a message that can be shown to the user as is.
    """
    s = str(text).strip().strip('"').strip()
    if not s:
        raise ValueError("The bracket is empty: give the EV step and the number of frames, e.g. \"1 3\"")

    if s.startswith("+/-"):
        return BracketSpec(parse_ev(s[3:]), DEFAULT_FRAMES)

    if re.search(r"[A-Za-z]", s):
        match = _SONY_MODE.search(s) or re.search(r"(\d+\.\d+)\D+?(\d+)", s)
        if not match:
            raise ValueError(f"Bracket \"{s}\" is not understood: give the EV step and the number of "
                             f"frames, e.g. \"1 3\"")
        return BracketSpec(snap_ev(float(match.group(1))), int(match.group(2)), mode_name=s)

    tokens = s.split()
    try:
        if len(tokens) < 2:
            raise ValueError
        frames = int(tokens[-1])
    except ValueError:
        raise ValueError(f"Bracket \"{s}\" is not understood: give the EV step and the number of frames, "
                         f"e.g. \"1 3\" or \"1 2/3 5\"") from None
    ev_step = parse_ev(" ".join(tokens[:-1]))
    if frames % 2 == 0 or not MIN_FRAMES <= frames <= MAX_FRAMES:
        raise ValueError(f"Bracket \"{s}\": the number of frames must be 3, 5, 7 or 9, not {frames}")
    return BracketSpec(ev_step, frames)


def match_ev_choice(choices: Sequence[str], ev_step: float) -> Optional[str]:
    """The camera choice (e.g. Canon '+/- 2/3', Nikon '2/3 EV') for this EV step, or None."""
    for choice in choices:
        try:
            if abs(parse_ev(choice) - ev_step) < 0.02:
                return choice
        except ValueError:
            continue
    return None


def match_sony_mode(choices: Sequence[str], spec: BracketSpec) -> Optional[str]:
    """The Sony continuous bracketing capture mode for this bracket, or None.

    Single bracketing ('Bracketing S ...') needs one shutter press per frame, so only the
    continuous modes ('Bracketing C ...') are used.
    """
    for choice in choices:
        if not choice.lower().startswith("bracketing c"):
            continue
        match = _SONY_MODE.search(choice)
        if (match and int(match.group(2)) == spec.frames
                and abs(snap_ev(float(match.group(1))) - spec.ev_step) < 0.02):
            return choice
    return None


def bracket_exposures(base_s: float, spec: BracketSpec) -> List[float]:
    """Exposure time in seconds of each frame, darkest first."""
    return [base_s * 2 ** offset for offset in spec.ev_offsets()]


def nearest_shutter_choices(choices: Sequence[str], exposures_s: Sequence[float], seconds) -> List[str]:
    """For each exposure, the camera shutter speed closest to it in stops.

    Args:
        choices: Shutter speed choices of the camera.
        exposures_s: Wanted exposure times in seconds.
        seconds: Function parsing a choice to seconds (<= 0 for 'bulb' and the like).
    """
    usable = [(c, seconds(c)) for c in choices]
    usable = [(c, s) for c, s in usable if s > 0]
    if not usable:
        raise ValueError("The camera reports no shutter speeds")
    return [min(usable, key=lambda cs: abs(math.log2(cs[1] / exposure)))[0] for exposure in exposures_s]


def bracket_text(ev_step: float, frames: int) -> str:
    """The bracket as written in a script, e.g. '1 2/3 5'."""
    return f"{format_ev(ev_step)} {frames}"


def native_brackets(vendor: Optional[str], choices: dict) -> List[str]:
    """The brackets the camera takes itself, as '<EV step> <frames>' texts, smallest step first.

    Args:
        vendor: 'Canon', 'Nikon' or 'Sony'.
        choices: Choices of the camera widgets 'aeb' (Canon), 'aebracketingstep' and
                 'aebracketingpattern' (Nikon) and 'capturemode' (Sony); missing ones are skipped.

    Canon brackets are listed with 3, 5 and 7 frames: the camera menu sets which one it takes.
    """
    pairs = set()

    def steps_of(widget_choices):
        for choice in widget_choices:
            try:
                yield parse_ev(choice)
            except ValueError:
                continue

    if vendor == "Canon":
        pairs = {(ev, n) for ev in steps_of(choices.get("aeb", [])) for n in CANON_FRAMES}
    elif vendor == "Nikon":
        frames = set()
        for pattern in choices.get("aebracketingpattern", []):
            match = re.match(r"\s*(\d+)\s*images?", pattern, re.IGNORECASE)
            if match:
                frames.add(int(match.group(1)))
        frames = {n for n in frames if n % 2 == 1 and MIN_FRAMES <= n <= MAX_FRAMES}
        pairs = {(ev, n) for ev in steps_of(choices.get("aebracketingstep", [])) for n in frames}
    elif vendor == "Sony":
        for mode in choices.get("capturemode", []):
            match = _SONY_MODE.search(mode)
            if mode.lower().startswith("bracketing c") and match:
                n = int(match.group(2))
                if n % 2 == 1 and MIN_FRAMES <= n <= MAX_FRAMES:
                    pairs.add((snap_ev(float(match.group(1))), n))
    return [bracket_text(ev, n) for ev, n in sorted(pairs)]


def is_native(bracket: str, native: Sequence[str]) -> bool:
    """Whether the camera takes this bracket itself (otherwise it is taken in software)."""
    spec = parse_bracket(bracket)
    for option in native:
        other = parse_bracket(option)
        if other.frames == spec.frames and abs(other.ev_step - spec.ev_step) < 0.02:
            return True
    return False


# --- take_hdr sequences ---------------------------------------------------------
# A take_hdr ramps the exposure from its start (shortest) exposure up by a number of
# full stops, 1 EV per frame.  'round-trip' comes back down again (the longest exposure
# is taken once), 'one-way' stops at the longest exposure.

HDR_ROUND_TRIP = "round-trip"
HDR_ONE_WAY = "one-way"
HDR_SEQUENCES = (HDR_ROUND_TRIP, HDR_ONE_WAY)
_HDR_ALIASES = {"down-up-down": HDR_ROUND_TRIP, "down-up": HDR_ONE_WAY}


def parse_hdr_sequence(text: Optional[str]) -> str:
    """The take_hdr sequence: 'round-trip' (also when not given) or 'one-way'.

    Raises:
        ValueError: With a message that can be shown to the user as is.
    """
    s = (text or "").strip().strip('"').strip().lower()
    if not s:
        return HDR_ROUND_TRIP
    s = _HDR_ALIASES.get(s, s)
    if s not in HDR_SEQUENCES:
        raise ValueError(f"HDR sequence \"{text}\" is not understood: use \"{HDR_ROUND_TRIP}\" or \"{HDR_ONE_WAY}\"")
    return s


def hdr_offsets(stops: int, sequence: str = HDR_ROUND_TRIP) -> List[int]:
    """EV offset of each frame from the start exposure, in the order they are taken."""
    up = list(range(stops + 1))
    if sequence == HDR_ONE_WAY:
        return up
    return up + up[-2::-1]


def hdr_native_bracket(stops: int, sequence: str, native: Sequence[str]) -> Optional[str]:
    """The camera bracket ('1 <frames>') that takes a one-way HDR in one go, or None.

    Only a one-way sequence with an even number of stops is a bracket centred on its
    middle exposure; a round trip takes exposures twice, which a bracket cannot.
    """
    if sequence != HDR_ONE_WAY or stops % 2 or not MIN_FRAMES <= stops + 1 <= MAX_FRAMES:
        return None
    bracket = bracket_text(1.0, stops + 1)
    return bracket if is_native(bracket, native) else None


def hdr_speeds(choices: Sequence[str], start_s: float, stops: int, sequence: str, seconds):
    """Camera shutter speeds of a take_hdr, in the order they are taken.

    Stops are counted in EV, not in positions of the shutter speed list, so the
    sequence is right whatever exposure step (1/3 or 1/2 EV) the camera uses.

    Args:
        choices: Shutter speed choices of the camera.
        start_s: Start (shortest) exposure in seconds.
        stops: Number of full stops wanted.
        sequence: HDR_ROUND_TRIP or HDR_ONE_WAY.
        seconds: Function parsing a choice to seconds (<= 0 for 'bulb' and the like).

    Returns:
        The speeds, and the number of stops used: fewer than wanted when the camera
        has no speed that many stops longer than the start.
    """
    slowest_s = max(seconds(c) for c in choices)
    stops = min(stops, max(0, int(math.floor(math.log2(slowest_s / start_s) + 0.1))))
    offsets = hdr_offsets(stops, sequence)
    return nearest_shutter_choices(choices, [start_s * 2 ** k for k in offsets], seconds), stops


# --- Exposure step of the camera ---------------------------------------------------

def exposure_step(choices: Sequence[str], seconds) -> Optional[float]:
    """The exposure step of the camera (1/3, 1/2 or 1 EV), from its shutter speed choices.

    Cameras list their shutter speeds in the exposure step they are set to, so the
    number of speeds per stop gives the step.  None when the list is too short to tell.

    Args:
        choices: Shutter speed choices of the camera.
        seconds: Function parsing a choice to seconds (<= 0 for 'bulb' and the like).
    """
    values = sorted({s for s in (seconds(c) for c in choices) if s > 0})
    if len(values) < 7:
        return None
    per_stop = (len(values) - 1) / math.log2(values[-1] / values[0])
    for step in (1 / 3, 1 / 2, 1.0):
        if abs(per_stop * step - 1) < 0.15:
            return step
    return None


def bracket_deviation(speeds: Sequence[str], base_s: float, offsets: Sequence[float], seconds) -> float:
    """How far (in EV) the chosen shutter speeds are from the wanted offsets, at most."""
    return max(abs(math.log2(seconds(speed) / base_s) - offset) for speed, offset in zip(speeds, offsets))
