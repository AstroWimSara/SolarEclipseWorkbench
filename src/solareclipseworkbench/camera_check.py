"""Check a photography script against the camera that is going to run it.

Problems that otherwise only show up during the eclipse, or afterwards on the
memory card, can be found with the camera on the table:

* settings the camera does not offer: an unknown ISO leaves the previous ISO in
  place, a shutter speed is silently rounded to the nearest one available, an
  aperture the lens does not have is ignored;
* camera state: mode dial, focus mode, battery, card space, sleep timer;
* a camera name in the script that does not match the connected camera, in which
  case every command for it is skipped;
* a camera clock that cannot be set correctly;
* commands that follow each other faster than this camera can execute them.

The settings check only reads from the camera.  The full test also sets the
camera clock and takes a test picture and a test burst to measure how long they
really take, and checks the timing of the whole script with those durations.
"""

import csv
import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Dict, List, Optional, Tuple

from solareclipseworkbench import scripts
from solareclipseworkbench.bracketing import (
    DEFAULT_FRAMES, exposure_step, format_ev, hdr_offsets, is_native, native_brackets, parse_bracket,
    parse_hdr_sequence,
)
from solareclipseworkbench.sensors import pixel_size_for_model, sensor_for_model
from solareclipseworkbench.command_timing import (
    DEFAULT_PROFILE,
    CONTACT_BURST_S,
    NIKON_TEST_BURSTS_FRAMES,
    TEST_BURSTS_S,
    BurstFit,
    TimingProfile,
    burst_duration_s,
    burst_param_for_s,
    fit_test_bursts,
    parse_timing_directives,
    planning_profile,
    vendor_from_name,
)

OK, INFO, WARNING, ERROR = "ok", "info", "warning", "error"

CAMERA_COMMANDS = ("take_picture", "take_burst", "take_bracket", "take_hdr", "prepare_camera")

# Assumed size of one RAW file, to estimate the card space a script needs.
RAW_FILE_MB = 40
# Assumed frame rate of Canon and Sony bursts (Nikon bursts are given in frames).
BURST_FPS = 8
MIN_BATTERY_PERCENT = 50


@dataclass
class CheckItem:
    """One line of the test report."""

    status: str          # OK, INFO, WARNING or ERROR
    title: str
    detail: str = ""


@dataclass
class ScriptCommand:
    """A camera command from a (converted) script."""

    func: str
    ref: str
    sign: str
    offset: str
    camera: str
    args: List[str]        # script fields after the offset, without the description
    description: str

    @property
    def shutter(self) -> str:
        return self.args[1].strip()

    @property
    def aperture(self) -> str:
        return self.args[2].strip()

    @property
    def iso(self) -> str:
        return self.args[3].strip()

    @property
    def when(self) -> str:
        return f"{self.ref}{self.sign}{self.offset}"


@dataclass
class TestReport:
    items: List[CheckItem] = field(default_factory=list)
    profile: Optional[TimingProfile] = None    # measured timing, when the full test ran

    def add(self, status: str, title: str, detail: str = "") -> None:
        self.items.append(CheckItem(status, title, detail))
        log = {ERROR: logging.error, WARNING: logging.warning}.get(status, logging.info)
        log("Camera test: %s%s", title, f" ({detail})" if detail else "")

    @property
    def worst(self) -> str:
        order = [OK, INFO, WARNING, ERROR]
        return max((item.status for item in self.items), key=order.index, default=OK)


# --- Script ------------------------------------------------------------------

def parse_commands(lines) -> List[ScriptCommand]:
    """Camera commands from converted script lines (loops already expanded)."""
    commands = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = next(csv.reader([line], skipinitialspace=True))
        except (csv.Error, StopIteration):
            continue
        if len(parts) < 9 or parts[0].strip() not in CAMERA_COMMANDS:
            continue
        parts = [p.strip() for p in parts]
        commands.append(ScriptCommand(parts[0], parts[1], parts[2], parts[3], parts[4], parts[4:-1], parts[-1]))
    return commands


def load_commands(script_text: str, reference_moments: dict) -> List[ScriptCommand]:
    """Camera commands of a script, with for loops expanded as SEW does it."""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="sew_test_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_text)
        converted = scripts.convert_script(path, reference_moments)
        return parse_commands(converted.getvalue().splitlines())
    finally:
        os.remove(path)


def _shutter_seconds(value: str) -> Optional[float]:
    value = str(value).strip().rstrip("s")
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            return float(num) / float(den)
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def _f_number(value: str) -> Optional[float]:
    try:
        return float(str(value).strip().lower().replace("f/", "").replace("f", ""))
    except ValueError:
        return None


def _choices(widget) -> List[str]:
    try:
        return [str(widget.get_choice(i)) for i in range(widget.count_choices())]
    except Exception:
        return []


def _widget(config, *names):
    for name in names:
        try:
            return config.get_child_by_name(name)
        except Exception:
            continue
    return None


def read_brackets(config, vendor: Optional[str]) -> List[str]:
    """The brackets the camera takes itself ('<EV step> <frames>'), see bracketing.native_brackets."""
    choices = {}
    for name in ("aeb", "aebracketingstep", "aebracketingpattern", "capturemode"):
        widget = _widget(config, name)
        if widget is not None:
            choices[name] = _choices(widget)
    return native_brackets(vendor, choices)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _describe_offset(seconds: float) -> str:
    """'12 s', '5 min', '3 h', '4 days' or '46 years', with + for ahead and - for behind."""
    sign = "+" if seconds >= 0 else "-"
    s = abs(seconds)
    # Years and days only from two of them on, so 36 h does not show as "2 days".
    for unit, size, minimum in (("years", 365.25 * 86400, 2), ("days", 86400, 2), ("h", 3600, 1), ("min", 60, 1)):
        if s >= minimum * size:
            return f"{sign}{s / size:.0f} {unit}"
    return f"{sign}{s:.0f} s"


def _limited(parts: List[str], limit: int = 8) -> str:
    shown = "; ".join(parts[:limit])
    return shown + (f"; and {len(parts) - limit} more" if len(parts) > limit else "")


def estimate_frames(commands: List[ScriptCommand], vendor: Optional[str]) -> int:
    """Number of pictures the script will take."""
    frames = 0
    for cmd in commands:
        if cmd.func == "take_burst":
            try:
                param = float(cmd.args[4])
            except (IndexError, ValueError):
                param = 2
            frames += int(param) if vendor == "Nikon" else int(math.ceil(param * BURST_FPS))
        elif cmd.func == "take_hdr":
            try:
                frames += len(hdr_offsets(int(cmd.args[4]),
                                          parse_hdr_sequence(cmd.args[5] if len(cmd.args) > 5 else None)))
            except (IndexError, ValueError):
                frames += 15
        elif cmd.func == "take_bracket":
            try:
                frames += parse_bracket(cmd.args[4]).frames
            except (IndexError, ValueError):
                frames += DEFAULT_FRAMES
        elif cmd.func == "prepare_camera":
            continue  # takes no picture
        else:
            frames += 1
    return frames


# --- Settings check (read only) ---------------------------------------------

def check_settings(camera, commands: List[ScriptCommand], report: TestReport) -> None:
    """Compare the script's ISO, shutter speeds and apertures with what the camera offers."""
    config = camera.get_config()
    name = getattr(camera, "name", "camera")

    isos: Dict[str, int] = {}
    shutters: Dict[str, int] = {}
    apertures: Dict[str, int] = {}
    for cmd in commands:
        isos[cmd.iso] = isos.get(cmd.iso, 0) + 1
        shutters[cmd.shutter] = shutters.get(cmd.shutter, 0) + 1
        apertures[cmd.aperture] = apertures.get(cmd.aperture, 0) + 1

    # ISO
    iso_choices = _choices(_widget(config, "iso")) if _widget(config, "iso") is not None else []
    if not iso_choices:
        report.add(WARNING, "ISO could not be checked", f"{name} does not list its ISO values over USB")
    else:
        missing = [iso for iso in isos if iso not in iso_choices]
        if missing:
            report.add(ERROR, "ISO not available: " + ", ".join(missing),
                       f"{_count(sum(isos[i] for i in missing), 'command')} would keep the previous ISO.  "
                       f"Available: {', '.join(iso_choices)}")
        else:
            report.add(OK, "All ISO values are available", ", ".join(sorted(isos, key=lambda v: float(v))))

    # Shutter speeds
    ss_widget = _widget(config, "shutterspeed", "shutterspeed2")
    ss_choices = [(c, _shutter_seconds(c)) for c in _choices(ss_widget)] if ss_widget is not None else []
    ss_choices = [(c, s) for c, s in ss_choices if s and s > 0]
    if not ss_choices:
        report.add(WARNING, "Shutter speeds could not be checked",
                   f"{name} does not list its shutter speeds over USB (is the mode dial at M?)")
    else:
        rounded = []    # (stops off, text)
        for speed, n in shutters.items():
            wanted = _shutter_seconds(speed)
            if not wanted or wanted <= 0:
                rounded.append((99.0, f"{speed} is not a valid shutter speed ({_count(n, 'command')})"))
                continue
            choice, seconds = min(ss_choices, key=lambda cs: abs(math.log(cs[1] / wanted)))
            stops = abs(math.log2(seconds / wanted))
            # More than about 1/10 stop off counts as a different shutter speed.
            if stops > 0.1:
                rounded.append((stops, f"{speed} → {choice} ({stops:.1f} stop, {_count(n, 'command')})"))
        if rounded:
            rounded.sort(key=lambda r: -r[0])
            report.add(WARNING, "Some shutter speeds will be rounded by the camera",
                       f"Largest differences first: {_limited([text for _, text in rounded])}.  "
                       f"Available: {', '.join(c for c, _ in ss_choices)}")
        else:
            report.add(OK, "All shutter speeds are available", _count(len(shutters), "distinct speed"))
        check_exposure_step([c for c, _ in ss_choices], getattr(camera, "vendor", None) or vendor_from_name(name),
                            report)

    # Aperture
    ap_widget = _widget(config, "aperture", "f-number")
    ap_choices = {_f_number(c): c for c in _choices(ap_widget)} if ap_widget is not None else {}
    ap_choices.pop(None, None)
    ap_choices.pop(0.0, None)
    wanted_apertures = sorted({a for a in apertures if _f_number(a)}, key=_f_number)
    if not ap_choices:
        report.add(INFO, "Aperture cannot be set over USB",
                   f"No lens aperture is reported (manual lens or telescope?).  "
                   f"Set f/{', f/'.join(wanted_apertures)} by hand.")
    else:
        missing = [a for a in wanted_apertures if _f_number(a) not in ap_choices]
        if missing:
            report.add(WARNING, "Aperture not available with this lens: f/" + ", f/".join(missing),
                       "The camera keeps its current aperture for these commands.  "
                       f"Available: {', '.join(ap_choices[k] for k in sorted(ap_choices))}")
        else:
            report.add(OK, "All apertures are available", "f/" + ", f/".join(wanted_apertures))

    check_brackets(config, getattr(camera, "vendor", None) or vendor_from_name(name), commands, report)


def check_exposure_step(shutter_speeds: List[str], vendor: Optional[str], report: TestReport) -> None:
    """Report the exposure step the camera is set to (1/3 or 1/2 EV), seen from its shutter speeds."""
    step = exposure_step(shutter_speeds, lambda c: _shutter_seconds(c) or 0)
    if step is None:
        return
    if vendor == "Sony" and step > 0.4:
        report.add(WARNING, f"Exposure step {format_ev(step)} EV: set the camera to 1/3 EV steps",
                   "Sony shutter speeds are not set reliably over USB (gphoto2) in 1/2 EV steps.")
    else:
        report.add(OK, f"Exposure step {format_ev(step)} EV",
                   "Brackets and HDR sequences use the shutter speed closest to each exposure.")


def check_brackets(config, vendor: Optional[str], commands: List[ScriptCommand], report: TestReport) -> None:
    """Check that the camera takes the brackets of the script itself."""
    brackets = {}
    for cmd in commands:
        if cmd.func == "take_bracket" and len(cmd.args) > 4:
            brackets[cmd.args[4]] = brackets.get(cmd.args[4], 0) + 1
    if not brackets:
        return

    def quoted(texts):
        return ", ".join(f'"{t}"' for t in texts)

    specs = {}
    for bracket in brackets:
        try:
            specs[bracket] = parse_bracket(bracket)
        except ValueError:
            pass
    invalid = [b for b in brackets if b not in specs]
    if invalid:
        report.add(ERROR, "Bracket not understood: " + quoted(invalid),
                   'Give the EV step and the number of frames, e.g. "1 3".  These brackets will not be taken.')

    native = read_brackets(config, vendor)
    software = [b for b in specs if not is_native(b, native)]
    if software:
        offered = f"The camera offers: {', '.join(native)}." if native else "The camera offers no bracketing over USB."
        report.add(WARNING, "The camera does not take every bracket itself",
                   f"{quoted(software)} will be taken in software: one picture per frame, which takes longer.  "
                   + offered)
    elif specs:
        report.add(OK, "The camera takes every bracket itself", quoted(specs))

    if vendor == "Canon" and specs:
        # With 5 set, an EOS 80D shoots 0, -2, -1, +1, +2 steps: a 3-frame bracket is 0, -2, -1
        frames = sorted({spec.frames for spec in specs.values()})
        if len(frames) == 1:
            report.add(INFO, "Check the number of bracketed shots on the camera",
                       f"Canon sets it in a custom function, not over USB.  The script uses "
                       f"{frames[0]} frames: set the camera to {frames[0]}.")
        else:
            report.add(WARNING, "The brackets use different numbers of frames",
                       f"The script uses {' and '.join(map(str, frames))} frames, but Canon sets the number of "
                       f"bracketed shots in a custom function, not over USB, so it is the same for every bracket.  "
                       f"A bracket with fewer frames than that setting is not centred: with 5 set, a 3-frame "
                       f"bracket is 0, -2 and -1 steps (or -2, -1 and 0, depending on the bracketing sequence).  "
                       f"Use the same number of frames for every bracket.")


def check_camera_state(camera, commands: List[ScriptCommand], report: TestReport) -> None:
    """Mode dial, focus, battery, card space, sleep timer, burst support and clock."""
    from solareclipseworkbench import camera as cam_module

    name = getattr(camera, "name", "camera")
    vendor = getattr(camera, "vendor", None) or vendor_from_name(name)

    def guarded(label, check):
        try:
            check()
        except Exception as e:
            report.add(WARNING, f"{label} could not be checked", str(e))

    def mode():
        shooting_mode = cam_module.get_shooting_mode(name, camera)
        if str(shooting_mode).lower() == "manual":
            report.add(OK, "Shooting mode is Manual")
        else:
            report.add(ERROR, f"Shooting mode is '{shooting_mode}', not Manual",
                       "Turn the mode dial to M, otherwise the camera chooses its own exposure.")

    def focus():
        focus_mode = cam_module.get_focus_mode(camera)
        if str(focus_mode).lower() == "manual":
            report.add(OK, "Focus mode is Manual")
        else:
            report.add(WARNING, f"Focus mode is '{focus_mode}', not Manual",
                       "Set the lens to MF: autofocus on the eclipse can fail and block the shot.")

    def battery():
        level = str(cam_module.get_battery_level(camera))
        try:
            percent = float(level.rstrip("%"))
        except ValueError:
            report.add(INFO, f"Battery: {level}")
            return
        if percent < MIN_BATTERY_PERCENT:
            report.add(WARNING, f"Battery at {level}", "Use a full battery (or mains power) for the eclipse.")
        else:
            report.add(OK, f"Battery at {level}")

    def space():
        free_gb = cam_module.get_free_space(camera)
        if not commands:
            if free_gb is not None and free_gb >= 0:
                report.add(OK, f"{free_gb:.1f} GB free on the card")
            return
        frames = estimate_frames(commands, vendor)
        needed_gb = frames * RAW_FILE_MB / 1024
        if free_gb is None or free_gb < 0:
            report.add(INFO, "Free card space is not reported by the camera",
                       f"The script takes about {frames} pictures (~{needed_gb:.0f} GB in RAW).")
        elif free_gb < needed_gb:
            report.add(WARNING, f"Card may be too small: {free_gb:.1f} GB free",
                       f"The script takes about {frames} pictures, ~{needed_gb:.1f} GB at {RAW_FILE_MB} MB "
                       "per RAW file.")
        else:
            report.add(OK, f"{free_gb:.1f} GB free on the card",
                       f"Enough for the ~{frames} pictures of the script.")

    def power_off():
        setting = cam_module.get_auto_power_off(camera)
        if setting is None:
            return
        label, raw, delay = setting
        if delay is not None and delay < cam_module.MIN_AUTO_POWER_OFF_S:
            report.add(WARNING, f"{label} is {raw}",
                       f"Set it to at least {int(cam_module.MIN_AUTO_POWER_OFF_S // 60)} minutes or disable it.")
        else:
            report.add(OK, f"{label}: {raw}")

    def burst():
        bursts = [c for c in commands if c.func == "take_burst"]
        if (commands and not bursts) or vendor != "Canon":
            return
        if _widget(camera.get_config(), "eosremoterelease") is None:
            report.add(INFO, "No continuous bursts on this camera",
                       "It cannot hold the shutter over USB, so each take_burst command takes single pictures "
                       "instead (one per second of burst).")
        else:
            report.add(OK, "Continuous bursts are supported")

    def clock():
        reading = cam_module.read_camera_clock(camera)
        if reading is None:
            report.add(INFO, "The camera clock is not accessible over USB",
                       "SEW cannot set it: set the date and time on the camera by hand.")
        elif not reading.readable:
            report.add(WARNING, f"The camera clock reads '{reading.raw}'",
                       "SEW does not understand this value and will not set the clock: "
                       "set the date and time on the camera by hand.")
        elif abs(reading.error_s) <= 2:
            report.add(OK, "Camera clock matches the computer clock",
                       reading.camera_time.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            status = WARNING if abs(reading.error_s) > 86400 else INFO
            report.add(status, f"Camera clock is {_describe_offset(reading.error_s)} off",
                       f"It shows {reading.camera_time:%Y-%m-%d %H:%M:%S}.  SEW sets it when the cameras are "
                       "connected; the full test checks that this works on this camera.")

    guarded("Shooting mode", mode)
    guarded("Focus mode", focus)
    guarded("Battery", battery)
    guarded("Card space", space)
    guarded("Auto power off", power_off)
    guarded("Burst support", burst)
    guarded("Camera clock", clock)


# --- Full test (changes the clock, takes pictures) ---------------------------

_clock = time.monotonic


def _timed(func: Callable, *args) -> float:
    start = _clock()
    func(*args)
    return _clock() - start


@dataclass
class BurstTest:
    """Two test bursts and what they tell about the camera (see measure_burst)."""

    vendor: Optional[str]
    short: Tuple[float, float]       # (burst parameter, seconds busy)
    long: Tuple[float, float]
    fit: BurstFit

    def planned(self) -> TimingProfile:
        return planning_profile(self.vendor, burst_overhead_s=self.fit.overhead_s, burst_fps=self.fit.fps,
                                burst_busy_per_s=self.fit.busy_per_s, burst_max_s=self.fit.max_s)

    def report(self, report: "TestReport", title: str) -> None:
        planned = self.planned()
        if self.vendor == "Nikon":
            measured = (f"{self.short[0]:g} frames took {self.short[1]:.1f} s and {self.long[0]:g} frames "
                        f"{self.long[1]:.1f} s: ")
            measured += (f"{self.fit.fps:g} frames per second" if self.fit.fps else
                         f"the frame rate could not be measured, {planned.nikon_burst_fps:g} frames per second "
                         "is assumed")
        else:
            measured = (f"{self.short[0]:g} s and {self.long[0]:g} s bursts kept the camera busy for "
                        f"{self.short[1]:.1f} s and {self.long[1]:.1f} s: ")
            measured += (f"{self.fit.busy_per_s:g} s per second of shooting" if self.fit.busy_per_s else
                         "the time per second of shooting could not be measured, 1 s is assumed")
        param = burst_param_for_s(self.vendor, CONTACT_BURST_S, planned)
        detail = (f"{measured}, plus {self.fit.overhead_s:.1f} s.  The script planning uses "
                  f"{burst_duration_s(self.vendor, param, planned):.1f} s for a {CONTACT_BURST_S:g} s burst "
                  f"(untested: {burst_duration_s(self.vendor, burst_param_for_s(self.vendor, CONTACT_BURST_S)):.1f} s)"
                  f"; beads bursts can be up to {planned.burst_max_s:g} s long.")
        report.add(OK, f"{title} kept the camera busy for {self.short[1]:.1f} s and {self.long[1]:.1f} s", detail)


def measure_burst(camera, settings, vendor: Optional[str]) -> BurstTest:
    """Time a short and a long test burst, back to back.

    The two separate the time per second of shooting (a Nikon's frame rate)
    from the fixed overhead, and the long one shows how the camera copes with
    the longest burst the wizard plans.  The long burst starts while the camera
    may still be writing the short one to the card, as around C2 and C3.
    """
    from solareclipseworkbench import camera as cam_module

    short_param, long_param = NIKON_TEST_BURSTS_FRAMES if vendor == "Nikon" else TEST_BURSTS_S
    short_s = _timed(cam_module.take_burst, camera, settings, short_param)
    long_s = _timed(cam_module.take_burst, camera, settings, long_param)
    short, long = (short_param, short_s), (long_param, long_s)
    return BurstTest(vendor, short, long, fit_test_bursts(vendor, short, long))


def run_active_test(camera, commands: List[ScriptCommand], report: TestReport) -> TimingProfile:
    """Set the camera clock and time one test picture and one test burst.

    Returns: Timing profile with the measured overheads (a picture never below the
             default, so a single quick shot cannot make the timing check
             optimistic; a burst from its two test bursts plus a margin, see
             planning_profile).
    """
    from solareclipseworkbench import camera as cam_module

    name = getattr(camera, "name", "camera")
    vendor = getattr(camera, "vendor", None) or vendor_from_name(name)

    # Clock
    try:
        if cam_module.set_time(camera):
            report.add(OK, "Camera clock set and verified")
        else:
            reading = cam_module.read_camera_clock(camera)
            shown = (reading.camera_time.strftime("%Y-%m-%d %H:%M:%S")
                     if reading is not None and reading.camera_time else "unknown")
            report.add(ERROR, "The camera clock could not be set reliably",
                       f"The clock now shows {shown}.  SEW will not set the clock of this camera; "
                       "set the date and time on the camera by hand.")
    except Exception as e:
        report.add(ERROR, "Setting the camera clock failed", str(e))

    picture_overhead = None
    burst = None

    # Test picture with the settings of the first take_picture in the script
    pictures = [c for c in commands if c.func == "take_picture"]
    if pictures:
        cmd = pictures[0]
        settings = cam_module.CameraSettings(name, cmd.shutter, cmd.aperture, int(cmd.iso))
        try:
            elapsed = _timed(cam_module.take_picture, camera, settings)
            exposure = _shutter_seconds(cmd.shutter) or 0.0
            picture_overhead = elapsed - exposure
            status = OK if elapsed - exposure <= DEFAULT_PROFILE.picture_overhead_s else INFO
            report.add(status, f"Test picture ({cmd.shutter}, f/{cmd.aperture}, ISO {cmd.iso}) took {elapsed:.1f} s",
                       f"{elapsed - exposure:.1f} s on top of the exposure; the script planning assumes "
                       f"{DEFAULT_PROFILE.picture_overhead_s:.1f} s.")
        except Exception as e:
            report.add(ERROR, "The test picture failed", str(e))

    # Test burst with the parameters of the first take_burst in the script
    bursts = [c for c in commands if c.func == "take_burst"]
    if bursts:
        cmd = bursts[0]
        settings = cam_module.CameraSettings(name, cmd.shutter, cmd.aperture, int(cmd.iso))
        try:
            burst = measure_burst(camera, settings, vendor)
            burst.report(report, "Test bursts")
        except Exception as e:
            report.add(ERROR, "The test burst failed", str(e))

    if burst is None:
        return planning_profile(vendor, picture_overhead)
    fit = burst.fit
    return planning_profile(vendor, picture_overhead, fit.overhead_s, fit.fps, fit.busy_per_s, fit.max_s)


# --- Timing ------------------------------------------------------------------

def check_timing(commands: List[ScriptCommand], reference_moments: dict, camera, report: TestReport,
                 profile: TimingProfile = DEFAULT_PROFILE, measured: bool = False) -> None:
    """Check that no command has to wait so long for the camera that it is skipped."""
    from solareclipseworkbench.utils import camera_busy_window, find_camera_conflicts

    windows = []
    last_time = None
    for cmd in commands:
        try:
            h, m, s = cmd.offset.split(":")
            delta = timedelta(hours=float(h), minutes=float(m), seconds=float(s))
            base = last_time if cmd.ref == "LAST" else reference_moments[cmd.ref].time_utc
        except (KeyError, ValueError, AttributeError):
            continue
        if base is None:
            continue
        start = base + delta if cmd.sign == "+" else base - delta
        last_time = start
        window = camera_busy_window(start, cmd.func, cmd.args, f'"{cmd.description}" at {cmd.when}', camera, profile)
        if window is not None:
            windows.append(window)

    basis = "the measured durations" if measured else "estimated durations"
    conflicts = find_camera_conflicts(windows)
    dropped = [c for c in conflicts if c.dropped]
    late = [c for c in conflicts if not c.dropped and c.wait_s > 0.5]
    if dropped:
        report.add(ERROR, f"{_count(len(dropped), 'command')} would be skipped ({basis})",
                   "; ".join(f"{c.window.description} waits {c.wait_s:.1f} s for {c.blocked_by.description}"
                             for c in dropped[:8]) + (" …" if len(dropped) > 8 else ""))
    if late:
        report.add(WARNING, f"{_count(len(late), 'command')} would be taken more than 0.5 s late ({basis})",
                   "; ".join(f"{c.window.description} by {c.wait_s:.1f} s" for c in late[:8])
                   + (" …" if len(late) > 8 else ""))
    if not dropped and not late:
        report.add(OK, f"All {_count(len(windows), 'camera command')} fit in time ({basis})")


# --- Entry point ---------------------------------------------------------------

def check_script_with_cameras(script_text: str, reference_moments: dict, cameras: dict, script_camera_name: str,
                             full: bool = False) -> TestReport:
    """Run the checks for the camera the script was written for.

    Args:
        - script_text: Script as generated by the wizard
        - reference_moments: Contact times for the observing location
        - cameras: Connected cameras, as returned by camera.get_camera_dict (name or alias -> camera)
        - script_camera_name: Camera name used in the script
        - full: Also set the clock, take a test picture and burst, and check the timing with measured durations

    Returns: The report.
    """
    report = TestReport()
    camera = (cameras or {}).get(script_camera_name)
    if camera is None:
        unique = list({id(c): c for c in (cameras or {}).values()}.values())
        if not unique:
            report.add(ERROR, "No camera is connected", "Connect the camera with USB, switch it on and try again.")
            return report
        names = ", ".join(f"'{n}'" for n in cameras)
        if len(unique) > 1:
            report.add(ERROR, f"None of the connected cameras is called '{script_camera_name}'",
                       f"Connected: {names}.  SEW skips every command for a camera it cannot find by name.")
            return report
        camera = unique[0]
        report.add(ERROR, f"The script uses '{script_camera_name}', but the connected camera is called {names}",
                   "SEW skips every command for a camera it cannot find by name.  Use the detected name, or map "
                   "this camera's serial number to the name with 'Detect Connected Camera'.  "
                   "The other checks below were run with the connected camera.")

    connected_name = getattr(camera, "name", "camera")
    all_commands = load_commands(script_text, reference_moments)
    commands = [c for c in all_commands if c.camera == script_camera_name]
    if not commands:
        report.add(ERROR, f"The script has no commands for '{script_camera_name}'")
        return report
    report.add(OK, f"Testing '{connected_name}' with {_count(len(commands), 'command')} of the script")

    try:
        check_settings(camera, commands, report)
    except Exception as e:
        report.add(ERROR, "The camera settings could not be read", str(e))
    check_camera_state(camera, commands, report)

    # The timing the wizard planned the script with, when it was fitted to a tested camera
    profile = parse_timing_directives(script_text.splitlines()).get(script_camera_name, DEFAULT_PROFILE)
    if full:
        profile = run_active_test(camera, commands, report)
        report.profile = profile
    check_timing(commands, reference_moments, camera, report, profile, measured=full)
    return report


# --- Camera profile: what the camera can do, measured before the script exists ---

@dataclass
class CameraProfile:
    """What a camera (with its current lens) offers and how fast it is.

    Measured with the camera connected, saved with the camera configuration of
    the wizard, and used to fit the generated script to the camera.
    """

    camera: str                                   # name of the connected camera
    vendor: Optional[str] = None
    shutter_speeds: List[str] = field(default_factory=list)   # camera choices, e.g. "1/4000", "0.5", "30"
    isos: List[int] = field(default_factory=list)
    apertures: List[float] = field(default_factory=list)      # empty: aperture not settable over USB
    continuous_burst: Optional[bool] = None
    clock_settable: Optional[bool] = None         # None: not tested
    picture_overhead_s: Optional[float] = None    # measured; None: not measured
    burst_overhead_s: Optional[float] = None
    burst_fps: Optional[float] = None             # measured Nikon frame rate; None: not measured
    burst_busy_per_s: Optional[float] = None      # measured Canon/Sony busy time per second of shooting
    burst_max_s: Optional[float] = None           # seconds of shooting of the longest test burst
    brackets: List[str] = field(default_factory=list)   # brackets the camera takes itself, e.g. "1 3"
    pixel_size_um: Optional[float] = None         # from the camera model (see sensors); None: not listed
    tested: str = ""                              # date and time of the test
    full_test: bool = False

    def timing_profile(self) -> TimingProfile:
        """Overheads to plan with: measured, with a margin for bursts (see planning_profile)."""
        return planning_profile(self.vendor, self.picture_overhead_s, self.burst_overhead_s, self.burst_fps,
                                self.burst_busy_per_s, self.burst_max_s)

    def shutter_range(self) -> str:
        speeds = sorted((s for s in (_shutter_seconds(c) for c in self.shutter_speeds) if s and s > 0))
        if not speeds:
            return "unknown"
        return f"{_format_seconds(speeds[0])} – {_format_seconds(speeds[-1])}"

    def summary(self) -> str:
        """One line for the wizard."""
        parts = [f"{self.tested} ({'full test' if self.full_test else 'settings only'})",
                 f"shutter {self.shutter_range()}"]
        if self.isos:
            parts.append(f"ISO {min(self.isos)}–{max(self.isos)}")
        parts.append(f"f/{_format_f(min(self.apertures))}–f/{_format_f(max(self.apertures))}" if self.apertures
                     else "aperture not settable over USB")
        if self.picture_overhead_s is not None:
            parts.append(f"picture {self.picture_overhead_s:.1f} s")
        if self.burst_overhead_s is not None:
            parts.append(f"burst +{self.burst_overhead_s:.1f} s")
        if self.burst_fps is not None:
            parts.append(f"{self.burst_fps:g} frames per second")
        if self.burst_busy_per_s is not None:
            parts.append(f"{self.burst_busy_per_s:g} s busy per second of burst")
        return ", ".join(parts)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["CameraProfile"]:
        if not isinstance(data, dict) or not data:
            return None
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        try:
            return cls(**known)
        except TypeError:
            return None


def _format_seconds(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:g} s"
    return f"1/{round(1 / seconds)}"


def _format_f(value: float) -> str:
    return f"{value:g}"


def read_camera_profile(camera) -> CameraProfile:
    """Read the settings the camera offers (nothing is changed)."""
    name = getattr(camera, "name", "camera")
    vendor = getattr(camera, "vendor", None) or vendor_from_name(name)
    config = camera.get_config()

    ss_widget = _widget(config, "shutterspeed", "shutterspeed2")
    speeds = [c.strip() for c in _choices(ss_widget)] if ss_widget is not None else []
    speeds = [c for c in speeds if (_shutter_seconds(c) or 0) > 0]

    iso_widget = _widget(config, "iso")
    isos = []
    for choice in _choices(iso_widget) if iso_widget is not None else []:
        try:
            isos.append(int(float(choice)))
        except ValueError:
            continue          # "Auto" and the like

    ap_widget = _widget(config, "aperture", "f-number")
    apertures = sorted({f for f in (_f_number(c) for c in _choices(ap_widget)) if f})

    if vendor == "Canon":
        continuous = _widget(config, "eosremoterelease") is not None
    else:
        continuous = True

    return CameraProfile(camera=name, vendor=vendor, shutter_speeds=speeds, isos=sorted(set(isos)),
                         apertures=apertures, continuous_burst=continuous,
                         brackets=read_brackets(config, vendor), pixel_size_um=pixel_size_for_model(name),
                         tested=time.strftime("%Y-%m-%d %H:%M"))


def check_camera(camera, full: bool = False) -> Tuple[TestReport, CameraProfile]:
    """Test a camera before a script is generated (wizard Equipment page).

    Reads what the camera offers and its state; with full=True also sets and
    verifies the clock and times a test picture and a test burst.

    Returns: The report and the camera profile.
    """
    from solareclipseworkbench import camera as cam_module

    report = TestReport()
    profile = read_camera_profile(camera)
    name = profile.camera
    report.add(OK, f"Connected to '{name}'")

    if profile.shutter_speeds:
        report.add(OK, f"Shutter speeds {profile.shutter_range()}", ", ".join(profile.shutter_speeds))
        check_exposure_step(profile.shutter_speeds, profile.vendor, report)
    else:
        report.add(WARNING, "The camera does not list its shutter speeds",
                   "Is the mode dial at M?  Without the list the script cannot be fitted to the camera.")
    if profile.isos:
        report.add(OK, f"ISO {min(profile.isos)}–{max(profile.isos)}", ", ".join(map(str, profile.isos)))
    else:
        report.add(WARNING, "The camera does not list its ISO values")
    if profile.apertures:
        report.add(OK, f"Aperture f/{_format_f(profile.apertures[0])}–f/{_format_f(profile.apertures[-1])} "
                       "with the mounted lens", ", ".join(f"f/{_format_f(a)}" for a in profile.apertures))
    else:
        report.add(INFO, "Aperture cannot be set over USB",
                   "Manual lens or telescope: the script keeps the aperture you enter; set it on the lens by hand.")
    if profile.continuous_burst:
        report.add(OK, "Continuous bursts are supported")
    if profile.brackets:
        detail = ", ".join(f'"{b}"' for b in profile.brackets)
        if profile.vendor == "Canon":
            detail += ".  The number of frames is set in the camera menu (Number of bracketed shots)."
        report.add(OK, f"The camera takes {_count(len(profile.brackets), 'bracket')} itself", detail)
    else:
        report.add(INFO, "The camera offers no bracketing over USB",
                   "take_bracket takes its frames in software: one picture per frame, slower than the camera.")

    sensor = sensor_for_model(name)
    if sensor is not None:
        report.add(OK, f"Pixel size {profile.pixel_size_um:.2f} µm",
                   f"{sensor[0]:g} mm sensor, {sensor[1]} pixels wide.  Used with the focal length to time "
                   "the first and fourth contact shots.")
    else:
        report.add(INFO, "Pixel size not known for this camera model",
                   "Enter it on the equipment page: the sensor width in mm divided by the image width in "
                   "pixels, times 1000.  It is used with the focal length to time the first and fourth "
                   "contact shots.")

    check_camera_state(camera, [], report)

    if full:
        try:
            profile.clock_settable = bool(cam_module.set_time(camera))
            if profile.clock_settable:
                report.add(OK, "Camera clock set and verified")
            else:
                report.add(ERROR, "The camera clock could not be set reliably",
                           "SEW will not set the clock of this camera; set the date and time on the camera by hand.")
        except Exception as e:
            report.add(ERROR, "Setting the camera clock failed", str(e))

        aperture = _format_f(profile.apertures[0]) if profile.apertures else "0"
        iso = min(profile.isos) if profile.isos else 100
        settings = cam_module.CameraSettings(name, "1/1000", aperture, iso)
        try:
            elapsed = _timed(cam_module.take_picture, camera, settings)
            profile.picture_overhead_s = round(max(0.0, elapsed - 0.001), 2)
            report.add(OK if profile.picture_overhead_s <= DEFAULT_PROFILE.picture_overhead_s else INFO,
                       f"Test picture took {elapsed:.1f} s",
                       f"The script planning assumes {DEFAULT_PROFILE.picture_overhead_s:.1f} s plus the exposure; "
                       "the measured time is used when it is longer.")
        except Exception as e:
            report.add(ERROR, "The test picture failed", str(e))

        try:
            burst = measure_burst(camera, settings, profile.vendor)
            profile.burst_overhead_s, profile.burst_fps = burst.fit.overhead_s, burst.fit.fps
            profile.burst_busy_per_s, profile.burst_max_s = burst.fit.busy_per_s, burst.fit.max_s
            burst.report(report, "Test bursts")
        except Exception as e:
            report.add(ERROR, "The test burst failed", str(e))
        profile.full_test = True

    report.profile = profile.timing_profile()
    return report, profile


# --- Fitting a script to the camera ------------------------------------------

@dataclass
class ExposureLimits:
    """The ISO and aperture range the photographer allows (wizard Equipment page)."""

    iso_min: int
    iso_max: int
    aperture_min: float     # widest (smallest f-number)
    aperture_max: float     # narrowest


@dataclass
class FittedExposure:
    shutter: str
    iso: int
    aperture: str
    error_stops: float      # + overexposed, - underexposed, compared with the planned exposure
    changes: List[str]

    @property
    def note(self) -> str:
        parts = list(self.changes)
        if abs(self.error_stops) > 1 / 3:
            parts.append(f"{abs(self.error_stops):.1f} stop {'over' if self.error_stops > 0 else 'under'}exposed: "
                         "camera limit")
        return "; ".join(parts)


# Changing ISO or aperture is only worth it when it brings the exposure this
# much closer (in stops) to the planned one; aperture changes cost a little more
# because they also change depth of field and sharpness.
_ISO_CHANGE_COST = 0.34
_APERTURE_CHANGE_COST = 0.4


def fit_exposure(shutter: str, iso: int, aperture: str, profile: CameraProfile, limits: ExposureLimits,
                 vary_iso_aperture: bool = True) -> FittedExposure:
    """Choose the camera setting that gives the planned exposure as closely as possible.

    The shutter speed is taken from the camera's own list.  When that is not
    enough (e.g. 1/8000 on a camera that stops at 1/4000), the ISO is lowered or
    raised and the lens stopped down or opened, within the photographer's limits,
    keeping the exposure the same.
    """
    wanted = _shutter_seconds(shutter)
    speeds = [(c.rstrip("s"), _shutter_seconds(c)) for c in profile.shutter_speeds]
    speeds = [(c, v) for c, v in speeds if v and v > 0]
    f_now = _f_number(aperture)
    if not wanted or not speeds:
        return FittedExposure(shutter, iso, aperture, 0.0, [])

    # Start from the nearest value the camera has: a value it does not offer is
    # not applied at all, so moving to the nearest one is not a choice.
    iso_base = min(profile.isos, key=lambda i: abs(math.log(i / iso))) if profile.isos and iso > 0 else iso
    f_base = f_now
    if profile.apertures and f_now:
        f_base = min(profile.apertures, key=lambda a: abs(math.log(a / f_now)))

    isos = {iso_base}
    apertures = {f_base}
    if vary_iso_aperture:
        isos |= {i for i in profile.isos if limits.iso_min <= i <= limits.iso_max}
        if f_now:
            apertures |= {a for a in profile.apertures if limits.aperture_min - 0.05 <= a <= limits.aperture_max + 0.05}

    best = None
    for a in sorted(apertures):
        for i in sorted(isos):
            needed = wanted * (iso / i) * ((a / f_now) ** 2 if f_now and a else 1.0)
            choice, seconds = min(speeds, key=lambda cs: abs(math.log(cs[1] / needed)))
            error = math.log2(seconds / needed)
            # Nominal f-numbers and shutter speeds are rounded (f/4 is really f/3.96),
            # so differences below 1/12 stop are noise.
            cost = (max(0.0, abs(error) - 1 / 12) + (_ISO_CHANGE_COST if i != iso_base else 0.0)
                    + (_APERTURE_CHANGE_COST if a != f_base else 0.0)
                    # among equally good settings, the one closest to the plan
                    + 0.05 * abs(math.log2(a / f_base) if a and f_base else 0.0)
                    + 0.05 * abs(math.log2(i / iso_base) if i and iso_base else 0.0))
            if best is None or cost < best[0] - 1e-9:
                best = (cost, choice, seconds, i, a, error)

    _, choice, seconds, new_iso, new_f, error = best
    changes = []
    same_speed = abs(math.log2(seconds / wanted)) < 0.02
    new_shutter = shutter if same_speed else choice
    if not same_speed:
        changes.append(f"{shutter} → {choice}")
    if new_iso != iso:
        changes.append(f"ISO {iso} → {new_iso}")
    new_aperture = aperture
    if f_now and abs(new_f - f_now) > 0.01:
        new_aperture = _format_f(new_f)
        changes.append(f"f/{aperture} → f/{new_aperture}")
    return FittedExposure(new_shutter, new_iso, new_aperture, error, changes)


@dataclass
class AdaptationSummary:
    changed: int = 0
    off_limit: List[str] = field(default_factory=list)    # descriptions of shots the camera cannot expose right

    def header_lines(self, profile: CameraProfile) -> List[str]:
        lines = [f"# Fitted to the camera tested on {profile.summary()}:",
                 f"#   {_count(self.changed, 'command')} adjusted to the shutter speeds, ISO values and apertures "
                 "the camera offers"]
        if self.off_limit:
            lines.append(f"#   {_count(len(self.off_limit), 'command')} cannot be exposed as planned "
                         "(see 'camera limit' in their description)")
        return lines


def adapt_script_lines(lines: List[str], camera_name: str, profile: CameraProfile,
                       limits: ExposureLimits) -> Tuple[List[str], AdaptationSummary]:
    """Fit every camera command of camera_name to the camera's own settings."""
    summary = AdaptationSummary()
    adapted = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            adapted.append(line)
            continue
        try:
            parts = [p.strip() for p in next(csv.reader([stripped], skipinitialspace=True))]
        except (csv.Error, StopIteration):
            adapted.append(line)
            continue
        if len(parts) < 9 or parts[0] not in CAMERA_COMMANDS or parts[4] != camera_name:
            adapted.append(line)
            continue
        try:
            iso = int(float(parts[7]))
        except ValueError:
            adapted.append(line)
            continue
        # take_hdr and take_bracket step through shutter speeds from their start
        # value, so only that value is fitted.
        # prepare_camera is fitted like the burst it prepares, so both end up on the same exposure.
        vary = parts[0] in ("take_picture", "take_burst", "prepare_camera")
        fitted = fit_exposure(parts[5], iso, parts[6], profile, limits, vary_iso_aperture=vary)
        note = fitted.note
        if not note:
            adapted.append(line)
            continue
        if fitted.changes:
            summary.changed += 1
        if abs(fitted.error_stops) > 1 / 3:
            summary.off_limit.append(parts[-1])
        indent = line[:len(line) - len(line.lstrip())]
        # Keep the bracket of a take_bracket quoted ("1 3")
        extra = [f'"{p}"' if " " in p else p for p in parts[8:-1]]
        fields = parts[:5] + [fitted.shutter, fitted.aperture, str(fitted.iso)] + extra
        description = f"{parts[-1]} [{note}]".replace('"', "'")
        adapted.append(indent + ", ".join(fields) + f', "{description}"')
    return adapted, summary
