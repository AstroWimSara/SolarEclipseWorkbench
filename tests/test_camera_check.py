"""Tests for checking a script against the connected camera (wizard 'Test with Camera')."""

import threading
import time
from datetime import datetime
from types import SimpleNamespace

import gphoto2
import gphoto2 as gp
import pytest
import pytz

from solareclipseworkbench import camera as cam_module
from solareclipseworkbench import camera_check, hardware_problems
from solareclipseworkbench.camera_check import ERROR, INFO, OK, WARNING, check_script_with_cameras

C2 = datetime(2026, 8, 12, 18, 29, 37, tzinfo=pytz.utc)
REFERENCE_MOMENTS = {
    "C1": SimpleNamespace(time_utc=datetime(2026, 8, 12, 17, 34, 34, tzinfo=pytz.utc)),
    "C2": SimpleNamespace(time_utc=C2),
    "MAX": SimpleNamespace(time_utc=datetime(2026, 8, 12, 18, 30, 26, tzinfo=pytz.utc)),
    "C3": SimpleNamespace(time_utc=datetime(2026, 8, 12, 18, 31, 15, tzinfo=pytz.utc)),
    "C4": SimpleNamespace(time_utc=datetime(2026, 8, 12, 19, 22, 0, tzinfo=pytz.utc)),
}

SHUTTERS_1000D = ["30", "15", "1", "0.5", "1/60", "1/1000", "1/2000", "1/3200", "1/4000"]


class Widget:
    def __init__(self, value, choices=(), widget_type=gp.GP_WIDGET_RADIO):
        self.value, self.choices, self.widget_type = value, list(choices), widget_type

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value

    def get_type(self):
        return self.widget_type

    def count_choices(self):
        return len(self.choices)

    def get_choice(self, i):
        return self.choices[i]


class FakeCanon:
    """A Canon EOS 1000D: no 1/8000, ISO up to 1600, no remote release for bursts."""

    vendor = "Canon"

    def __init__(self, name="Canon EOS 1000D", clock="datetime", clock_value=None):
        self.name = name
        self._usb_lock = threading.RLock()
        self.widgets = {
            "iso": Widget("100", ["Auto", "100", "200", "400", "800", "1600"]),
            "shutterspeed": Widget("1/1000", SHUTTERS_1000D),
            "aperture": Widget("2.8", ["2.8", "4", "5.6", "8"]),
            "autoexposuremodedial": Widget("Manual"),
            "focusmode": Widget("Manual"),
            "batterylevel": Widget("100%"),
            clock: Widget(int(time.time()) if clock_value is None else clock_value,
                          widget_type=gp.GP_WIDGET_DATE if clock_value is None or isinstance(clock_value, int)
                          else gp.GP_WIDGET_TEXT),
        }
        self.disconnected = False

    def get_config(self):
        widgets = self.widgets

        class Config:
            def get_child_by_name(self, name):
                if name not in widgets:
                    raise gphoto2.GPhoto2Error(-2)
                return widgets[name]
        return Config()

    def set_config(self, config):
        pass

    def get_storageinfo(self):
        return [SimpleNamespace(freekbytes=30 * 1024 * 1024)]

    def disconnect(self):
        self.disconnected = True


def _script(camera, lines):
    return "\n".join(line.replace("CAM", camera) for line in lines) + "\n"


SCRIPT_1000D = _script("Canon EOS 1000D", [
    'take_picture, C2, -, 0:10:00.0, CAM, 1/4000, 2.8, 100, "Partial"',
    'take_picture, C3, +, 0:26:20.0, CAM, 1/4400, 2.8, 100, "Partial with an odd speed"',
    'take_picture, C2, +, 0:00:50.0, CAM, 1/40, 2.8, 400, "Background during totality"',
    'take_picture, C2, +, 0:01:00.0, CAM, 1/40, 1.8, 3200, "Too bright lens, too high ISO"',
])


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(cam_module, "get_auto_power_off", lambda camera: None)
    cam_module._clock_sync_disabled.clear()
    hardware_problems.clear()
    yield
    hardware_problems.clear()


def _titles(report, status):
    return [item.title for item in report.items if item.status == status]


def test_settings_the_camera_does_not_have_are_reported():
    report = check_script_with_cameras(SCRIPT_1000D, REFERENCE_MOMENTS, {"Canon EOS 1000D": FakeCanon()},
                                       "Canon EOS 1000D")
    assert any("ISO not available: 3200" in t for t in _titles(report, ERROR))
    rounding = next(i for i in report.items if i.title.startswith("Some shutter speeds"))
    assert rounding.status == WARNING and "1/4400 → 1/4000" in rounding.detail
    assert any("f/1.8" in t for t in _titles(report, WARNING))
    assert report.worst == ERROR


def test_camera_name_that_does_not_match_the_script_is_an_error():
    """SEW skips every command for a camera it cannot find by name."""
    script = SCRIPT_1000D.replace("Canon EOS 1000D", "Left body")
    report = check_script_with_cameras(script, REFERENCE_MOMENTS, {"Canon EOS 1000D": FakeCanon()}, "Left body")
    assert any("connected camera is called 'Canon EOS 1000D'" in t for t in _titles(report, ERROR))
    # The other checks still ran with the connected camera.
    assert any(t.startswith("ISO not available") for t in _titles(report, ERROR))


def test_no_camera_connected():
    report = check_script_with_cameras(SCRIPT_1000D, REFERENCE_MOMENTS, {}, "Canon EOS 1000D")
    assert _titles(report, ERROR) == ["No camera is connected"]


def test_unreadable_clock_is_a_warning_in_the_settings_check():
    camera = FakeCanon(clock="d034", clock_value="garbage")
    report = check_script_with_cameras(SCRIPT_1000D, REFERENCE_MOMENTS, {"Canon EOS 1000D": camera},
                                       "Canon EOS 1000D")
    assert any("clock reads 'garbage'" in t for t in _titles(report, WARNING))


def test_canon_without_remote_release_takes_single_pictures_for_bursts():
    script = _script("Canon EOS 1000D", ['take_burst, C2, -, 0:00:04.0, CAM, 1/4000, 2.8, 100, 2, "Beads"'])
    report = check_script_with_cameras(script, REFERENCE_MOMENTS, {"Canon EOS 1000D": FakeCanon()},
                                       "Canon EOS 1000D")
    assert "No continuous bursts on this camera" in _titles(report, INFO)


def test_full_test_finds_a_camera_that_is_slower_than_planned(monkeypatch):
    """The wizard spaces C2 bursts for ~8 s; a body that needs 10 s per burst drops the second one."""
    clock = {"now": 0.0}
    monkeypatch.setattr(camera_check, "_clock", lambda: clock["now"])

    def fake_picture(camera, settings):
        clock["now"] += 1.5

    def fake_burst(camera, settings, duration):
        clock["now"] += duration + 8.0

    monkeypatch.setattr(cam_module, "take_picture", fake_picture)
    monkeypatch.setattr(cam_module, "take_burst", fake_burst)
    camera = FakeCanon("Canon EOS R")
    camera.widgets["eosremoterelease"] = Widget("None")
    script = _script("Canon EOS R", [
        'take_picture, C2, -, 0:10:00.0, CAM, 1/4000, 2.8, 100, "Partial"',
        'take_burst, C2, -, 0:00:12.0, CAM, 1/60, 2.8, 100, 2, "C2 diamond ring"',
        'take_burst, C2, -, 0:00:04.0, CAM, 1/4000, 2.8, 100, 2, "Pre-C2 beads"',
    ])

    settings_only = check_script_with_cameras(script, REFERENCE_MOMENTS, {"Canon EOS R": camera}, "Canon EOS R")
    assert any(t.startswith("All 3 camera commands fit") for t in _titles(settings_only, OK))

    full = check_script_with_cameras(script, REFERENCE_MOMENTS, {"Canon EOS R": camera}, "Canon EOS R", full=True)
    assert full.profile.burst_overhead_s == pytest.approx(1.5 * 8.0 + 1.0)
    skipped = next(i for i in full.items if "would be skipped" in i.title)
    assert skipped.status == ERROR and "Pre-C2 beads" in skipped.detail
    assert "Camera clock set and verified" in _titles(full, OK)


# --- Camera profile and fitting the script to the camera -----------------------

from solareclipseworkbench.camera_check import (  # noqa: E402
    CameraProfile, ExposureLimits, adapt_script_lines, check_camera, fit_exposure, read_camera_profile,
)
from solareclipseworkbench.command_timing import DEFAULT_PROFILE, contact_burst_plan  # noqa: E402

PROFILE_1000D = CameraProfile(
    "Canon EOS 1000D", "Canon",
    shutter_speeds=["30", "15", "8", "4", "2", "1", "0.5", "1/4", "1/8", "1/15", "1/30", "1/60", "1/125",
                    "1/250", "1/500", "1/1000", "1/2000", "1/4000"],
    isos=[100, 200, 400, 800, 1600], apertures=[2.8, 4, 5.6, 8, 11, 16, 22])


def test_profile_is_read_from_the_camera_and_survives_saving():
    profile = read_camera_profile(FakeCanon())
    assert profile.isos == [100, 200, 400, 800, 1600]             # "Auto" left out
    assert profile.apertures == [2.8, 4.0, 5.6, 8.0]
    assert "1/4000" in profile.shutter_speeds
    assert profile.continuous_burst is False                       # no eosremoterelease
    assert CameraProfile.from_dict(profile.to_dict()) == profile


def test_too_short_exposure_is_compensated_with_iso_before_aperture():
    limits = ExposureLimits(100, 1600, 2.8, 8)
    fitted = fit_exposure("1/8000", 200, "2.8", PROFILE_1000D, limits)
    assert (fitted.shutter, fitted.iso, fitted.aperture) == ("1/4000", 100, "2.8")
    assert fitted.error_stops == pytest.approx(0.0)


def test_lens_is_stopped_down_only_as_far_as_needed():
    fitted = fit_exposure("1/8000", 100, "2.8", PROFILE_1000D, ExposureLimits(100, 1600, 2.8, 8))
    assert (fitted.shutter, fitted.aperture) == ("1/4000", "4")


def test_camera_limit_is_reported_when_nothing_else_is_allowed():
    """Lens fixed at f/2.8 and ISO 100 at its minimum: 1/8000 cannot be had on a 1/4000 camera."""
    fitted = fit_exposure("1/8000", 100, "2.8", PROFILE_1000D, ExposureLimits(100, 1600, 2.8, 2.8))
    assert fitted.shutter == "1/4000" and fitted.error_stops == pytest.approx(1.0)
    assert "1.0 stop overexposed: camera limit" in fitted.note


def test_available_setting_is_left_alone():
    fitted = fit_exposure("1/1000", 100, "2.8", PROFILE_1000D, ExposureLimits(100, 1600, 2.8, 8))
    assert fitted.note == "" and fitted.shutter == "1/1000"


def test_aperture_the_lens_does_not_have_moves_to_the_nearest_one():
    rf = CameraProfile("Canon EOS R", "Canon", shutter_speeds=["1/8000", "1/6400", "1/4000"],
                       isos=[100, 200], apertures=[5.6, 6.3, 7.1])
    fitted = fit_exposure("1/8000", 100, "6.0", rf, ExposureLimits(100, 1600, 6.0, 6.0))
    assert fitted.aperture == "6.3"


def test_script_lines_are_rewritten_with_a_note_and_other_cameras_are_untouched():
    lines = [
        "# header",
        'take_picture, C2, -, 0:10:00.0, Canon EOS 1000D, 1/8000, 2.8, 200, "Partial #1"',
        'take_picture, C2, -, 0:09:50.0, Canon EOS 1000D, 1/1000, 2.8, 100, "Partial #2"',
        'take_picture, C2, -, 0:09:50.0, Canon EOS R, 1/8000, 6.0, 100, "Other camera"',
        'take_hdr, MAX, -, 0:00:14.0, Canon EOS 1000D, 1/5000, 2.8, 400, 7, "HDR"',
    ]
    adapted, summary = adapt_script_lines(lines, "Canon EOS 1000D", PROFILE_1000D, ExposureLimits(100, 1600, 2.8, 8))
    assert adapted[1] == ('take_picture, C2, -, 0:10:00.0, Canon EOS 1000D, 1/4000, 2.8, 100, '
                          '"Partial #1 [1/8000 → 1/4000; ISO 200 → 100]"')
    assert adapted[2] == lines[2] and adapted[3] == lines[3]
    # take_hdr steps through the camera's speeds itself: only its start speed is fitted
    assert ", 1/4000, 2.8, 400, 7," in adapted[4]
    assert summary.changed == 2


def test_measured_durations_are_used_for_planning_with_a_margin_for_bursts():
    slow = CameraProfile("cam", "Canon", picture_overhead_s=3.0, burst_overhead_s=9.0)
    quick = CameraProfile("cam", "Canon", picture_overhead_s=0.5, burst_overhead_s=1.0)
    # 2 s burst + 1.5 x 9 + 1 = 16.5 s; 2 s + 1.5 x 1 + 1 = 4.5 s (untested: 2 + 6 = 8 s)
    assert contact_burst_plan("Canon", True, slow.timing_profile()).c2_diamond_start == 4 + 17
    assert contact_burst_plan("Canon", True, quick.timing_profile()).c2_diamond_start == 4 + 5
    # A picture is never planned below the default
    assert quick.timing_profile().picture_overhead_s == DEFAULT_PROFILE.picture_overhead_s


def test_full_camera_test_measures_picture_and_burst(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(camera_check, "_clock", lambda: clock["now"])
    monkeypatch.setattr(cam_module, "take_picture", lambda c, s: clock.update(now=clock["now"] + 2.5))
    monkeypatch.setattr(cam_module, "take_burst", lambda c, s, d: clock.update(now=clock["now"] + d + 9.0))
    report, profile = check_camera(FakeCanon(), full=True)
    assert profile.full_test and profile.clock_settable
    assert profile.picture_overhead_s == pytest.approx(2.5, abs=0.01)
    assert profile.burst_overhead_s == pytest.approx(9.0)
    assert profile.burst_busy_per_s == pytest.approx(1.0)
    assert profile.burst_max_s == 5.0
    assert report.worst != ERROR


class FakeNikon(FakeCanon):
    vendor = "Nikon"

    def __init__(self, name="Nikon Z 8"):
        super().__init__(name)


def test_full_camera_test_measures_the_frame_rate_of_a_fast_nikon(monkeypatch):
    """Z 8 with a CFexpress card: 20 fps, 0.6 s overhead.  The C2/C3 bursts are spaced by that, plus a margin."""
    clock = {"now": 0.0}
    frames_asked = []
    monkeypatch.setattr(camera_check, "_clock", lambda: clock["now"])
    monkeypatch.setattr(cam_module, "take_picture", lambda c, s: clock.update(now=clock["now"] + 1.0))

    def fake_burst(camera, settings, frames):
        frames_asked.append(frames)
        clock["now"] += 0.6 + frames / 20

    monkeypatch.setattr(cam_module, "take_burst", fake_burst)
    report, profile = check_camera(FakeNikon(), full=True)
    assert frames_asked == [10, 100]
    assert profile.burst_fps == pytest.approx(20.0)
    assert profile.burst_overhead_s == pytest.approx(0.6)
    assert CameraProfile.from_dict(profile.to_dict()) == profile
    assert profile.burst_max_s == 5.0                    # 100 frames at 20 fps
    fast = contact_burst_plan("Nikon", True, profile.timing_profile())
    assert fast.burst_param == 40                         # 2 s at 20 fps
    assert fast.burst_s < contact_burst_plan("Nikon").burst_s
    assert fast.burst_s >= 0.6 + 2.0 + 1.0
    assert report.worst != ERROR


def test_timing_recorded_in_the_script_is_used_for_the_timing_check():
    """A script fitted to a quick camera must not be flagged with the default (longer) burst time."""
    camera = FakeCanon("Canon EOS R")
    camera.widgets["eosremoterelease"] = Widget("None")
    lines = [
        'take_burst, C2, -, 0:00:09.0, CAM, 1/60, 2.8, 100, 2, "C2 diamond ring"',
        'take_burst, C2, -, 0:00:04.0, CAM, 1/4000, 2.8, 100, 2, "Pre-C2 beads"',
    ]
    plain = check_script_with_cameras(_script("Canon EOS R", lines), REFERENCE_MOMENTS,
                                      {"Canon EOS R": camera}, "Canon EOS R")
    assert any("would be skipped" in i.title for i in plain.items)

    directive = "# timing: Canon EOS R; picture_overhead_s=2; burst_overhead_s=2; nikon_burst_fps=10"
    timed = check_script_with_cameras(_script("Canon EOS R", [directive] + lines), REFERENCE_MOMENTS,
                                      {"Canon EOS R": camera}, "Canon EOS R")
    assert not any("would be skipped" in i.title for i in timed.items)


def test_full_camera_test_measures_how_a_canon_copes_with_a_long_burst(monkeypatch):
    """A camera that empties its buffer slower than it fills it: 1.5 s busy per second of shooting."""
    clock = {"now": 0.0}
    asked = []
    monkeypatch.setattr(camera_check, "_clock", lambda: clock["now"])
    monkeypatch.setattr(cam_module, "take_picture", lambda c, s: clock.update(now=clock["now"] + 1.0))

    def fake_burst(camera, settings, seconds):
        asked.append(seconds)
        clock["now"] += 1.5 * seconds + 3.0

    monkeypatch.setattr(cam_module, "take_burst", fake_burst)
    report, profile = check_camera(FakeCanon("Canon EOS R"), full=True)
    assert asked == [1.0, 5.0]
    assert profile.burst_busy_per_s == pytest.approx(1.5)
    timing = profile.timing_profile()
    # The measured overhead with its margin, and the time per second of shooting
    assert timing.burst_overhead_s == pytest.approx(1.5 * 3.0 + 1.0)
    assert contact_burst_plan("Canon", True, timing).burst_s == pytest.approx(1.5 * 2 + 5.5)
