"""prepare_camera sets the camera up for the next command without taking a picture.

A Sony takes about 4 s to change its capture mode (discussion #192).  Done ahead
of the C2 and C3 sequences, that change no longer delays their first burst.
"""
import io
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

import solareclipseworkbench.camera as cam
from solareclipseworkbench import hardware_problems, scripts
from solareclipseworkbench.camera import CameraSettings, parse_prepare_mode, prepare_camera
from solareclipseworkbench.utils import schedule_command

from test_unchanged_settings import _Camera, _fake_gphoto, _sony_config

SONY = "Sony ILCE-7RM3A"


def _prepare(config, mode, vendor="Sony"):
    with ExitStack() as stack:
        set_config = _fake_gphoto(stack, config)
        stack.enter_context(patch.object(cam, '_find_capturemode_choice',
                                         side_effect=lambda w, want_continuous, **kw:
                                         "Continuous Shooting" if want_continuous else "Single Shooting"))
        trigger = stack.enter_context(patch.object(cam.gp, 'gp_camera_trigger_capture'))
        prepare_camera(_Camera(vendor), CameraSettings("Sony Test", "1/30", "8", 400), mode)
    trigger.assert_not_called()
    return set_config


def test_sony_switches_to_continuous_shooting_without_a_picture():
    config = _sony_config(shutter="1/800", capture_mode="Single Shooting")
    config['capturemode'].choices.append("Continuous Shooting")
    set_config = _prepare(config, "burst")
    assert config['capturemode'].value == "Continuous Shooting"
    assert config['shutterspeed'].value == "1/30"
    assert set_config.call_count == 2      # exposure, then capture mode


def test_sony_switches_to_the_bracketing_mode():
    config = _sony_config(capture_mode="Single Shooting")
    _prepare(config, '"Bracketing C 3.0 Steps 5 Pictures"')
    assert config['capturemode'].value == "Bracketing C 3.0 Steps 5 Pictures"


def test_a_prepared_sony_is_left_alone():
    set_config = _prepare(_sony_config(), "Bracketing C 3.0 Steps 5 Pictures")
    set_config.assert_not_called()


def test_other_brands_only_get_their_exposure():
    config = _sony_config(shutter="1/800", capture_mode="Single Shooting")
    _prepare(config, "burst", vendor="Canon")
    assert config['shutterspeed'].value == "1/30"
    assert config['capturemode'].value == "Single Shooting"


@pytest.mark.parametrize("mode, expected", [("burst", "burst"), (" Single ", "single"), ('"1 5"', "1 5")])
def test_prepare_modes(mode, expected):
    assert parse_prepare_mode(mode) == expected


def test_an_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        parse_prepare_mode("continuous")


def test_script_line_survives_conversion():
    line = 'prepare_camera, C2, -, 0:00:20.0, Sony ILCE-7RM3A, 1/100, 8, 400, "1 5", "Prepare for C2"'
    out = scripts.convert_command(line, "C2", "-", "0:00:20.0", "", io.StringIO())
    assert out.getvalue().strip() == ('prepare_camera, C2, -, 0:00:20.0, Sony ILCE-7RM3A, 1/100, 8, 400, '
                                      '"1 5", "Prepare for C2"')


def _schedule(line):
    c2 = datetime.now(timezone.utc) + timedelta(hours=1)
    moments = {"C2": SimpleNamespace(time_utc=c2)}
    camera = object()
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    hardware_problems.drain()
    try:
        window = schedule_command(scheduler, moments, line, {SONY: camera}, None, None, None)
        jobs = scheduler.get_jobs()
    finally:
        scheduler.shutdown(wait=False)
    return window, jobs, camera, hardware_problems.drain()


def test_scheduled_with_camera_settings_and_mode():
    window, jobs, camera, problems = _schedule(
        f'prepare_camera, C2, -, 0:00:20.0, {SONY}, 1/100, 8, 400, burst, "Prepare for C2"')
    assert problems == []
    assert len(jobs) == 1
    assert jobs[0].func is prepare_camera
    assert jobs[0].args[0] is camera
    assert jobs[0].args[1].shutter_speed == "1/100"
    assert jobs[0].args[2] == "burst"
    assert window.mode == "burst"


def test_an_invalid_mode_is_reported_when_the_script_is_loaded():
    _, jobs, _, problems = _schedule(
        f'prepare_camera, C2, -, 0:00:20.0, {SONY}, 1/100, 8, 400, continuous, "Prepare for C2"')
    assert jobs == []
    assert len(problems) == 1 and "prepare_camera" in str(problems[0])
