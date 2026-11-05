"""The camera check (wizard 'Test Camera...' and 'Verify with Camera...') on a Fuji body.

The body is a FujiCamera on a MagicMock SDK, so no camera is needed.  The SDK
answers as an X-T4 does: no list of shutter speeds, no battery API, no card
capacity.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytz

from fujixsdk import _constants as C
from fujixsdk._errors import XSDKError
from fujixsdk.camera import BatteryInfo

from solareclipseworkbench import camera as cam_module
from solareclipseworkbench import camera_check, fuji_camera, hardware_problems
from solareclipseworkbench.camera import SdkDetection
from solareclipseworkbench.camera_check import (
    ERROR, INFO, OK, WARNING, check_camera, check_script_with_cameras, check_settings, parse_commands,
    read_camera_profile,
)
from solareclipseworkbench.fuji_camera import FujiCamera

NAME = "Fuji Fujifilm X-T4"

# The speeds the SDK table holds that an X-T4 refuses with 0x2003.
REFUSED = ["1/6000", "1/3000", "1/1500", "1/750", "1/350", "1/180", "1/90", "1/45", "1/1.5"]

C2 = datetime(2030, 6, 1, 12, 0, 0, tzinfo=pytz.utc)
REFERENCE_MOMENTS = {
    "C1": SimpleNamespace(time_utc=datetime(2030, 6, 1, 11, 0, 0, tzinfo=pytz.utc)),
    "C2": SimpleNamespace(time_utc=C2),
    "MAX": SimpleNamespace(time_utc=datetime(2030, 6, 1, 12, 1, 0, tzinfo=pytz.utc)),
    "C3": SimpleNamespace(time_utc=datetime(2030, 6, 1, 12, 2, 0, tzinfo=pytz.utc)),
    "C4": SimpleNamespace(time_utc=datetime(2030, 6, 1, 13, 0, 0, tzinfo=pytz.utc)),
}

SCRIPT = "\n".join(line.replace("CAM", NAME) for line in [
    'take_picture, C2, -, 0:10:00.0, CAM, 1/1000, 5.6, 200, "Partial"',
    'take_picture, C2, -, 0:05:00.0, CAM, 1/180, 5.6, 200, "A speed the body refuses"',
    'take_burst, C2, -, 0:00:30.0, CAM, 1/1000, 5.6, 200, 2, "Diamond ring"',
    'take_picture, C2, +, 0:00:30.0, CAM, 1/60, 5.6, 3200, "An ISO the body does not list"',
]) + "\n"


def _not_implemented():
    raise XSDKError(0x1013, "API not found in model module")


def _sdk(**overrides):
    """An SDK camera that answers as an X-T4 with a clean set-up."""
    sdk = MagicMock()
    answers = dict(
        get_ae_mode=lambda: C.AE_OFF,
        get_focus_mode=lambda: C.SDK_FOCUS_MANUAL,
        get_iso=lambda: 200,
        get_supported_iso=lambda: [C.ISO_AUTO, 160, 200, 400, 800, 1600, 12800],
        get_supported_shutter_speeds=lambda: [],
        get_shutter_speed=lambda: (C.SHUTTER_1_1000, 0),
        get_aperture=lambda: 560,
        get_drive_mode=lambda: C.DRIVE_MODE_S,
        get_exposure_bias=lambda: 0,
        get_image_quality=_not_implemented,
        get_wb_mode=lambda: C.WB_DAYLIGHT,
        get_long_exposure_nr=lambda: C.OFF,
        get_buffer_capacity=lambda: (0, 32),
        get_battery_info=_not_implemented,
        get_media_status=lambda slot=1: C.MEDIASTATUS_OK,
        get_media_capacity=lambda slot=1: _not_implemented(),
        get_shutter_count=_not_implemented,
    )
    answers.update(overrides)
    for name, answer in answers.items():
        setattr(sdk, name, MagicMock(side_effect=lambda *a, answer=answer, **k: answer(*a, **k)))
    sdk.camera_mode = 0x0001
    sdk.lens_info = SimpleNamespace(product_name="XF16-80mmF4", model="")
    return sdk


def _camera(**overrides):
    return FujiCamera(_sdk(**overrides), NAME, "/sdk", "ENUM:0", model="X-T4")


def _titles(report, status):
    return [item.title for item in report.items if item.status == status]


def _item(report, start):
    return next(item for item in report.items if item.title.startswith(start))


@pytest.fixture(autouse=True)
def _clean():
    cam_module._clock_sync_disabled.clear()
    hardware_problems.clear()
    yield
    hardware_problems.clear()


# ------------------------------------------------------------------ choices


def test_the_shutter_speed_widget_lists_the_speeds_the_body_takes():
    widget = _camera().get_config().get_child_by_name("shutterspeed")
    choices = [widget.get_choice(i) for i in range(widget.count_choices())]

    assert {"1/8000", "1/4000", "1/1000", "1/200", "1/160", "1", "30"} <= set(choices)
    assert not set(REFUSED) & set(choices)
    # Written as a script writes them, so the check compares like with like
    assert not any(c.endswith('"') for c in choices)


def test_a_refused_speed_stays_out_when_the_body_lists_it():
    every_speed = [value for value in C.SHUTTER_SPEED_NAMES if value > 0]
    camera = _camera(get_supported_shutter_speeds=lambda: every_speed)

    assert not set(REFUSED) & set(camera.offered_speeds())
    assert "1/1000" in camera.offered_speeds()


def test_the_iso_widget_lists_the_fixed_values():
    widget = _camera().get_config().get_child_by_name("iso")

    assert [widget.get_choice(i) for i in range(widget.count_choices())] == [
        "160", "200", "400", "800", "1600", "12800"]


def test_the_settings_check_reads_the_choices():
    report = camera_check.TestReport()
    check_settings(_camera(), parse_commands(SCRIPT.splitlines()), report)

    assert "ISO not available: 3200" in _titles(report, ERROR)
    rounded = _item(report, "Some shutter speeds will be rounded")
    assert rounded.status == WARNING
    assert "1/180 → 1/200" in rounded.detail
    assert "Exposure step 1/3 EV" in _titles(report, OK)


def test_a_refused_speed_is_reported_as_the_speed_the_body_takes():
    """The check names the speed that FujiCamera really sets for 1/180."""
    camera = _camera()
    report = camera_check.TestReport()
    check_settings(camera, parse_commands(SCRIPT.splitlines()), report)

    camera.configure(shutter_speed="1/180")

    set_to = camera._sdk_cam.set_shutter_speed.call_args.args[0]
    assert fuji_camera._script_speed(set_to) == "1/200"
    assert "1/180 → 1/200" in _item(report, "Some shutter speeds").detail


def test_an_aperture_without_choices_is_not_called_a_manual_lens():
    report = camera_check.TestReport()
    check_settings(_camera(), parse_commands(SCRIPT.splitlines()), report)

    assert "Apertures could not be checked" in _titles(report, INFO)
    assert "Aperture cannot be set over USB" not in _titles(report, INFO)


def test_the_profile_has_the_speeds_and_isos_and_no_continuous_burst():
    profile = read_camera_profile(_camera())

    assert profile.vendor == "Fuji"
    assert "1/8000" in profile.shutter_speeds and "1/180" not in profile.shutter_speeds
    assert profile.isos == [160, 200, 400, 800, 1600, 12800]
    assert profile.continuous_burst is False


# ------------------------------------------------------------------ camera state


def test_a_body_without_the_battery_api_is_info_not_a_crash():
    report, _ = check_camera(_camera())

    assert "The camera does not report its battery level" in _titles(report, INFO)
    assert not any(t.startswith("Battery") for t in _titles(report, WARNING))


def test_a_low_battery_is_a_warning():
    low = BatteryInfo(body=C.POWERCAPACITY_PREEND, grip=C.POWERCAPACITY_EMPTY, grip2=C.POWERCAPACITY_EMPTY,
                      body_ratio=0, grip_ratio=0, grip2_ratio=0)
    report, _ = check_camera(_camera(get_battery_info=lambda: low))

    assert any(t.startswith("Battery at") for t in _titles(report, WARNING))


def test_the_shooting_mode_is_read_from_the_body():
    report, _ = check_camera(_camera(get_ae_mode=lambda: C.AE_APERTURE_PRIORITY))

    mode = _item(report, "Shooting mode is 'Aperture Priority'")
    assert mode.status == ERROR
    assert "aperture ring" in mode.detail
    assert "Shooting mode is Manual" in _titles(check_camera(_camera())[0], OK)


def test_autofocus_is_a_warning_and_an_unread_focus_mode_too():
    report, _ = check_camera(_camera(get_focus_mode=lambda: C.SDK_FOCUS_AFS))
    assert "Focus mode is 'AF-S', not Manual" in _titles(report, WARNING)

    report, _ = check_camera(_camera(get_focus_mode=_not_implemented))
    assert "The focus mode could not be read" in _titles(report, WARNING)


def test_card_space_auto_power_off_and_clock_are_info():
    report, _ = check_camera(_camera())

    infos = _titles(report, INFO)
    assert "Auto power off cannot be read over USB" in infos
    assert "The camera clock is not accessible over USB" in infos
    assert not any("could not be checked" in t for t in _titles(report, WARNING))


def test_bursts_are_reported_as_single_frames():
    report, _ = check_camera(_camera())

    assert "No continuous bursts over the Fujifilm SDK" in _titles(report, INFO)
    assert "Continuous bursts are supported" not in _titles(report, OK)

    script_report = check_script_with_cameras(SCRIPT, REFERENCE_MOMENTS, {NAME: _camera()}, NAME)
    assert "No continuous bursts over the Fujifilm SDK" in _titles(script_report, INFO)


def test_no_burst_line_for_a_script_without_bursts():
    script = "".join(line + "\n" for line in SCRIPT.splitlines() if "take_burst" not in line)
    report = check_script_with_cameras(script, REFERENCE_MOMENTS, {NAME: _camera()}, NAME)

    assert "No continuous bursts over the Fujifilm SDK" not in _titles(report, INFO)


def test_the_body_settings_the_sdk_checks_are_in_the_report():
    report, _ = check_camera(_camera(get_image_quality=lambda: C.IMAGE_QUALITY_FINE_PLUS_RAW))

    assert any(t.startswith("Image Quality:") for t in _titles(report, ERROR))
    assert any(t.startswith("Drive Mode:") for t in _titles(report, INFO))
    # Shooting mode, focus and battery have their own lines
    assert not any(t.startswith(("AE Mode", "Focus Mode", "Battery:")) for t in _titles(report, INFO))


# ------------------------------------------------------------------ full test


class _Clock:
    """Time for the camera check and for FujiCamera together."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(camera_check, "_clock", fake.monotonic)
    monkeypatch.setattr(fuji_camera, "time", SimpleNamespace(monotonic=fake.monotonic, sleep=fake.sleep))
    return fake


def _timed_camera(clock, release_s=0.75, settings_s=0.0):
    """A body that takes release_s per frame and settings_s to write its ISO."""
    def set_iso(value):
        clock.now += settings_s

    camera = _camera(set_iso=set_iso)
    shooter = MagicMock()

    def release():
        clock.now += release_s
        return True

    shooter.shoot_fast.side_effect = release
    camera._shooter = shooter
    return camera, shooter


def test_the_full_test_runs_through_the_fuji_hooks(clock):
    camera, shooter = _timed_camera(clock)

    report, profile = check_camera(camera, full=True)

    assert profile.full_test
    assert profile.clock_settable is False
    assert "The camera clock is not accessible over USB" in _titles(report, INFO)
    assert not any("clock" in t.lower() for t in _titles(report, ERROR))
    # One test picture, then a 1 s and a 5 s burst of single frames
    assert shooter.shoot_fast.call_count == 1 + 2 + 7
    assert "Test bursts kept the camera busy for 1.5 s and 5.2 s" in _titles(report, OK)
    assert profile.burst_overhead_s == 0.5
    assert profile.continuous_burst is False


def test_a_quick_test_picture_keeps_the_default_overhead(clock):
    camera, _ = _timed_camera(clock)

    report, profile = check_camera(camera, full=True)

    assert profile.picture_overhead_s == pytest.approx(0.75, abs=0.01)
    assert report.profile.picture_overhead_s == 2.0
    assert report.profile.burst_overhead_s == pytest.approx(1.5 * 0.5 + 1.0)


def test_a_slow_test_picture_replaces_the_default_overhead(clock):
    camera, _ = _timed_camera(clock, settings_s=2.0)

    report = check_script_with_cameras(SCRIPT, REFERENCE_MOMENTS, {NAME: camera}, NAME, full=True)

    assert report.profile.picture_overhead_s == pytest.approx(2.75 - 0.001, abs=0.01)
    assert any(t.startswith("Test picture (1/1000, f/5.6, ISO 200) took 2.8 s") for t in _titles(report, INFO))
    assert "The camera clock is not accessible over USB" in _titles(report, INFO)


# ------------------------------------------------------------------ detection


def test_sdk_detection_merges_the_backends_and_survives_a_failing_one(monkeypatch):
    body = SimpleNamespace(name=NAME)

    def broken():
        raise RuntimeError("library missing")

    monkeypatch.setattr(cam_module, "_sdk_backends", [broken, lambda: SdkDetection({NAME: body}, ("fuji",))])

    found = cam_module.detect_sdk_cameras()

    assert found.cameras == {NAME: body}
    assert found.claims("Fuji Fujifilm X-T4")
    assert not found.claims("Nikon DSC Z 8")
    assert any("SDK failed" in str(p) for p in hardware_problems.peek())
