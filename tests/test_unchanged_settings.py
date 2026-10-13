"""Settings the camera already has are not sent again.

Each set_config is a USB round-trip, and around C2 and C3 every round-trip delays
the shot (discussion #192: about a second per bracket on a Sony A7R IIIA).
"""
from contextlib import ExitStack
from unittest.mock import patch

import gphoto2

import solareclipseworkbench.camera as cam
from solareclipseworkbench.camera import CameraSettings, _set_widget_if_changed, take_bracket

adapt_camera_settings = getattr(cam, '__adapt_camera_settings')


class _Widget:
    def __init__(self, value, choices=()):
        self.value = value
        self.choices = list(choices)


class _DummyLock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


class _Camera:
    def __init__(self, vendor):
        self.vendor = vendor
        self.name = f"{vendor} Test"
        self._camera = object()
        self._usb_lock = _DummyLock()


def _sony_config(shutter="1/30", iso="400", f_number="f/8", capture_mode="Bracketing C 3.0 Steps 5 Pictures"):
    return {
        'shutterspeed': _Widget(shutter, ["1/2000", "1/800", "1/250", "1/30", "1/4", "2"]),
        'iso': _Widget(iso),
        'f-number': _Widget(f_number, ["f/5.6", "f/8"]),
        'capturemode': _Widget(capture_mode, ["Single Shooting", "Bracketing C 3.0 Steps 5 Pictures"]),
        'bulb': _Widget(0),
    }


def _get_child(config, name):
    if name not in config:
        raise gphoto2.GPhoto2Error(-2)
    return config[name]


def _fake_gphoto(stack, config):
    """Patch gphoto2 so widgets come from *config*; return the set_config mock."""
    def set_value(widget, value):
        widget.value = value

    stack.enter_context(patch.object(cam.gp, 'check_result', side_effect=lambda v: v))
    stack.enter_context(patch.object(cam.gp, 'gp_context_new', return_value=object()))
    stack.enter_context(patch.object(cam.gp, 'gp_camera_get_config', return_value=config))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_get_child_by_name', side_effect=_get_child))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_get_value', side_effect=lambda w: w.value))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_set_value', side_effect=set_value))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_count_choices', side_effect=lambda w: len(w.choices)))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_get_choice', side_effect=lambda w, i: w.choices[i]))
    stack.enter_context(patch.object(cam, '_aperture_verified', {"Sony Test": {"f/8"}}))
    return stack.enter_context(patch.object(cam, '_set_gp_config'))


def test_value_already_set_is_not_queued():
    widget = _Widget("400")
    with patch.object(cam.gp, 'check_result', side_effect=lambda v: v), \
         patch.object(cam.gp, 'gp_widget_get_value', side_effect=lambda w: w.value), \
         patch.object(cam.gp, 'gp_widget_set_value') as set_value:
        assert _set_widget_if_changed(widget, "400") is False
        assert _set_widget_if_changed(widget, "800") is True
    set_value.assert_called_once_with(widget, "800")


def test_unreadable_value_is_queued_anyway():
    with patch.object(cam.gp, 'gp_widget_get_value', side_effect=gphoto2.GPhoto2Error(-2)), \
         patch.object(cam.gp, 'gp_widget_set_value') as set_value:
        assert _set_widget_if_changed(object(), "400") is True
    set_value.assert_called_once()


def test_unchanged_exposure_sends_no_set_config():
    with ExitStack() as stack:
        set_config = _fake_gphoto(stack, _sony_config())
        adapt_camera_settings(_Camera("Sony"), CameraSettings("Sony Test", "1/30", "8.0", 400))
    set_config.assert_not_called()


def test_changed_shutter_speed_is_sent_once():
    config = _sony_config(shutter="1/800")
    with ExitStack() as stack:
        set_config = _fake_gphoto(stack, config)
        adapt_camera_settings(_Camera("Sony"), CameraSettings("Sony Test", "1/30", "8.0", 400))
    assert set_config.call_count == 1
    assert config['shutterspeed'].value == "1/30"


def test_changed_aperture_is_sent():
    config = _sony_config(f_number="f/5.6")
    with ExitStack() as stack:
        set_config = _fake_gphoto(stack, config)
        adapt_camera_settings(_Camera("Sony"), CameraSettings("Sony Test", "1/30", "8.0", 400))
    assert set_config.call_count == 1
    assert config['f-number'].value == "f/8"


def test_sony_bracket_in_the_same_mode_only_presses_the_bulb():
    config = _sony_config()
    with ExitStack() as stack:
        set_config = _fake_gphoto(stack, config)
        stack.enter_context(patch.object(cam.time, 'sleep'))
        stack.enter_context(patch.object(cam, '_drain_camera_events'))
        take_bracket(_Camera("Sony"), CameraSettings("Sony Test", "1/30", "8", 400),
                     "Bracketing C 3.0 Steps 5 Pictures")
    # Bulb on and bulb off: no exposure or capture mode round-trips
    assert set_config.call_count == 2


def test_sony_bracket_after_a_single_shot_switches_mode():
    config = _sony_config(shutter="1/800", capture_mode="Single Shooting")
    with ExitStack() as stack:
        set_config = _fake_gphoto(stack, config)
        stack.enter_context(patch.object(cam.time, 'sleep'))
        stack.enter_context(patch.object(cam, '_drain_camera_events'))
        take_bracket(_Camera("Sony"), CameraSettings("Sony Test", "1/30", "8", 400),
                     "Bracketing C 3.0 Steps 5 Pictures")
    # Exposure, capture mode, bulb on, bulb off
    assert set_config.call_count == 4
    assert config['capturemode'].value == "Bracketing C 3.0 Steps 5 Pictures"
