"""The scheduled commands of the jobs table, in words.

A script line gives a command as a list of fields, e.g.
``take_bracket, C2, +, 0:00:05.0, VirtualCamera, 1/1000, 8, 200, 1 5``.  This module
turns a scheduled job into a short sentence, e.g.
``Bracket of 5 frames, 1 EV apart, around 1/1000 s, f/8, ISO 200 (VirtualCamera)``.

The shutter speed in the sentence is the speed the camera will use: when an exposure
compensation is set in the GUI, the compensated speed is shown, followed by the
compensation.

describe_job() returns None for a command it does not know and for a job it cannot
read.  The caller then shows the command as it is written in the script.  This
module never raises, because the jobs table must stay visible during a run.

No Qt here: the module only reads the jobs, so it can be tested on its own.
"""

import logging
from typing import Optional

from solareclipseworkbench.bracketing import HDR_ONE_WAY, HDR_ROUND_TRIP, hdr_offsets, parse_bracket
from solareclipseworkbench.camera import (_parse_shutter_speed_seconds, compensated_shutter_speed,
                                          get_exposure_compensation)

LOGGER = logging.getLogger(__name__)

# Names of the reference moments in a voice prompt, which stay in capitals
_MOMENT_NAMES = ("C1", "C2", "C3", "C4", "MAX")


def _number(value) -> str:
    """A number of seconds without trailing zeros, e.g. 3.0 -> '3', 0.50 -> '0.5'."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value).strip()


def _speed(shutter_speed, ev: int) -> str:
    """The shutter speed the camera will use, with the compensation when one is set."""
    scripted = str(shutter_speed).strip()
    used = compensated_shutter_speed(scripted, ev)
    text = f"{used} s" if _parse_shutter_speed_seconds(used) > 0 else used
    if used != scripted:
        text += f" ({ev:+d} EV)"
    return text


def _aperture(aperture) -> str:
    text = str(aperture).strip()
    if not text or text == "-":
        return ""
    return text if text.lower().startswith("f") else f"f/{text}"


def _iso(iso) -> str:
    text = str(iso).strip()
    return "" if not text or text == "-" else f"ISO {text}"


def _exposure(settings, ev: int, after_speed: str = "") -> str:
    """Shutter speed, aperture and ISO, e.g. '1/1000 s, f/8, ISO 200'.

    *after_speed* is put between the shutter speed and the aperture.
    """
    parts = [_speed(settings.shutter_speed, ev), after_speed, _aperture(settings.aperture),
             _iso(settings.iso)]
    return ", ".join(part for part in parts if part)


def _camera(settings) -> str:
    name = str(getattr(settings, "camera_name", "") or "").strip()
    return f" ({name})" if name else ""


def _bracket(steps) -> str:
    """The bracket in words, e.g. '5 frames, 1 EV apart'.  A bracket that cannot be read is shown as written."""
    try:
        return parse_bracket(steps).describe()
    except ValueError:
        return str(steps).strip()


def _voice_prompt(notification) -> str:
    """A voice prompt in words, e.g. C2_IN_10_SECONDS -> 'Voice prompt: C2 in 10 seconds'."""
    words = [word if word in _MOMENT_NAMES else word.lower()
             for word in str(notification).strip().split("_") if word]
    return "Voice prompt: " + " ".join(words)


def _camera_command(name: str, args: list, ev: int) -> Optional[str]:
    settings = args[1]
    camera = _camera(settings)

    if name == "take_picture":
        return f"Picture at {_exposure(settings, ev)}{camera}"

    if name == "take_burst":
        return f"Burst for {_number(args[2])} s at {_exposure(settings, ev)}{camera}"

    if name == "take_bracket":
        return f"Bracket of {_bracket(args[2])}, around {_exposure(settings, ev)}{camera}"

    if name == "take_hdr":
        stops = int(args[2])
        sequence = args[3] if len(args) > 3 else HDR_ROUND_TRIP
        frames = len(hdr_offsets(stops, sequence))
        route = "longer" if sequence == HDR_ONE_WAY else "longer and back"
        return f"HDR of {frames} frames from {_exposure(settings, ev, f'{stops} stops {route}')}{camera}"

    if name == "prepare_camera":
        mode = str(args[2]).strip()
        if mode == "single":
            purpose = "single pictures"
        elif mode == "burst":
            purpose = "a burst"
        else:
            purpose = f"a bracket of {_bracket(mode)}"
        return f"Set up {_exposure(settings, ev)} for {purpose}{camera}"

    return None


def _relay_command(name: str, values: list) -> Optional[str]:
    if name == "relay_shoot":
        return "Relay: take one frame"
    if name == "relay_burst":
        if len(values) > 1:
            return f"Relay: a frame every {_number(values[1])} s for {_number(values[0])} s"
        return f"Relay: hold the shutter for {_number(values[0])} s"
    if name == "relay_bulb":
        return f"Relay: bulb exposure of {_number(values[0])} s"
    if name == "relay_arm":
        return "Relay: hold the half press"
    if name == "relay_release":
        return "Relay: release the shutter"
    return None


MOUNT_COMMANDS = {
    "mount_track": "Mount: track the sun",
    "mount_stop": "Mount: stop tracking",
    "mount_park": "Mount: park",
}


def _describe_job(job, ev: int) -> Optional[str]:
    name = job.func.__name__
    args = list(job.args or ())

    if name in ("take_picture", "take_burst", "take_bracket", "take_hdr", "prepare_camera"):
        return _camera_command(name, args, ev)

    if name.startswith("relay_"):
        # The first argument is the relay itself, the others are the values from the script
        return _relay_command(name, [str(arg).strip() for arg in args[1:]])

    if name in MOUNT_COMMANDS:
        return MOUNT_COMMANDS[name]

    if name == "sync_cameras":
        return "Check the cameras and set their clocks"

    if name == "voice_prompt":
        return _voice_prompt(args[0])

    if name == "execute_command":
        return "Run: " + ", ".join(str(arg) for arg in args).strip()

    return None


def describe_job(job, ev: Optional[int] = None) -> Optional[str]:
    """Return a scheduled job in words, or None when the command is not known.

    Args:
        - job: Scheduled job (an APScheduler job, or anything with func and args)
        - ev: Exposure compensation [EV]; defaults to the compensation set in the GUI

    Returns: The command in words, or None for an unknown command or a job that cannot be read.
    """
    try:
        if ev is None:
            ev = get_exposure_compensation()
        return _describe_job(job, ev)
    except Exception:
        LOGGER.debug("Could not describe the job %r in words", job, exc_info=True)
        return None
