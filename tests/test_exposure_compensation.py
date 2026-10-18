"""Exposure compensation from the GUI: all following shots brighter or darker.

When clouds or dust dim the Sun during the eclipse, one click makes every shot
still to come one stop brighter (or darker).  Only the shutter speed changes,
and only when the shot fires, so the scheduled jobs themselves stay as loaded.
"""
from types import SimpleNamespace

import pytest

import solareclipseworkbench.camera as cam
from solareclipseworkbench.camera import (CameraSettings, _serialised_on_camera, compensated_shutter_speed,
                                          get_exposure_compensation, set_exposure_compensation,
                                          MAX_EXPOSURE_COMPENSATION_EV)


class _DummyLock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


class _Camera:
    vendor = "Canon"
    name = "Canon Test"

    def __init__(self):
        self._usb_lock = _DummyLock()


@_serialised_on_camera
def _shot(camera, camera_settings, *args):
    return camera_settings, args


@pytest.fixture(autouse=True)
def _no_compensation():
    set_exposure_compensation(0)
    yield
    set_exposure_compensation(0)


@pytest.mark.parametrize("speed, ev, expected", [
    ("1/1000", 1, "1/500"),
    ("1/1000", -1, "1/2000"),
    ("1/1000", 2, "1/250"),
    ("1/3", 1, "0.6"),
    ("1", -1, "1/2"),
    ("2.5", 2, "10"),
    ("1/4000", -1, "1/8000"),
    ("1/1000", 0, "1/1000"),
])
def test_compensated_shutter_speed_is_a_standard_speed(speed, ev, expected):
    assert compensated_shutter_speed(speed, ev) == expected


def test_a_speed_that_is_not_a_number_is_left_alone():
    assert compensated_shutter_speed("bulb", 2) == "bulb"


def test_compensation_is_limited():
    assert set_exposure_compensation(99) == MAX_EXPOSURE_COMPENSATION_EV
    assert set_exposure_compensation(-99) == -MAX_EXPOSURE_COMPENSATION_EV
    assert get_exposure_compensation() == -MAX_EXPOSURE_COMPENSATION_EV


def test_without_compensation_the_scripted_settings_are_used():
    settings = CameraSettings("Canon Test", "1/1000", "8", 100)
    used, _ = _shot(_Camera(), settings)
    assert used is settings


def test_compensation_changes_only_the_shutter_speed_of_the_shot():
    settings = CameraSettings("Canon Test", "1/1000", "8", 100)
    set_exposure_compensation(1)
    used, args = _shot(_Camera(), settings, "1 3")

    assert (used.camera_name, used.shutter_speed, used.aperture, used.iso) == ("Canon Test", "1/500", "8", 100)
    assert args == ("1 3",)
    # The scheduled job keeps its scripted settings, so a later change starts from them again
    assert settings.shutter_speed == "1/1000"


def test_a_change_reaches_shots_already_scheduled():
    settings = CameraSettings("Canon Test", "1/1000", "8", 100)
    set_exposure_compensation(1)
    _shot(_Camera(), settings)
    set_exposure_compensation(-1)
    used, _ = _shot(_Camera(), settings)
    assert used.shutter_speed == "1/2000"


def test_commands_without_settings_are_unaffected():
    calls = []

    @_serialised_on_camera
    def _sync(camera, controller):
        calls.append(controller)

    set_exposure_compensation(2)
    controller = SimpleNamespace()
    _sync(_Camera(), controller)
    assert calls == [controller]


def test_jobs_table_shows_the_compensated_speed():
    from solareclipseworkbench.gui import job_command_string

    job = SimpleNamespace(func=cam.take_picture, args=[_Camera(), CameraSettings("Canon Test", "1/1000", "8", 100)])
    assert job_command_string(job) == 'take_picture("Canon Test", 1/1000, 8, 100)'
    set_exposure_compensation(1)
    assert job_command_string(job) == 'take_picture("Canon Test", 1/1000 → 1/500, 8, 100)'
