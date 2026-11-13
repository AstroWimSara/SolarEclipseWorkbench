"""Hardening of the camera commands: a failure must not leave the camera in a state
that spoils the later shots, nor take down the other cameras."""
import threading
import types
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import gphoto2
import pytest

import solareclipseworkbench.camera as cam
from solareclipseworkbench.camera import CameraSettings, take_bracket

from test_unchanged_settings import _Camera, _Widget, _fake_gphoto


def _run(camera, config, steps="1 3", shutter="1/60", **patches):
    with ExitStack() as stack:
        _fake_gphoto(stack, config)
        stack.enter_context(patch.object(cam, '__adapt_camera_settings', return_value=(object(), config)))
        stack.enter_context(patch.object(cam, '_drain_camera_events'))
        stack.enter_context(patch.object(cam, '_wait_for_capture_complete'))
        stack.enter_context(patch.object(cam, '_canon_shutter_speed', return_value=None))
        stack.enter_context(patch.object(cam.gp, 'gp_camera_trigger_capture', return_value=0))
        stack.enter_context(patch.object(cam.gp, 'gp_camera_set_config', return_value=0))
        for name, value in patches.items():
            stack.enter_context(patch.object(cam.gp, name, value))
        take_bracket(camera, CameraSettings(camera.name, shutter, "8", 100), steps)


def test_canon_aeb_is_turned_off_before_the_software_fallback():
    config = {
        'shutterspeed': _Widget("1/60", ["1/250", "1/125", "1/60", "1/30", "1/15"]),
        'aeb': _Widget("off", ["off", "+/- 1/3", "+/- 1"]),
    }
    camera = _Camera("Canon")
    camera.capture = MagicMock(side_effect=gphoto2.GPhoto2Error(-7))
    aeb_during_trigger = []

    def trigger(target, context):
        aeb_during_trigger.append(config['aeb'].value)
        return 0

    _run(camera, config, gp_camera_capture=MagicMock(side_effect=gphoto2.GPhoto2Error(-7)),
         gp_camera_trigger_capture=trigger)
    # The fallback takes every frame, none of them with AEB still on
    assert aeb_during_trigger == ["off"] * 3
    assert config['aeb'].value == "off"


def test_canon_aeb_is_turned_off_when_the_capture_fails_otherwise():
    config = {
        'shutterspeed': _Widget("1/60", ["1/250", "1/60", "1/15"]),
        'aeb': _Widget("off", ["off", "+/- 1"]),
    }
    camera = _Camera("Canon")
    camera.capture = MagicMock(side_effect=RuntimeError("unplugged"))
    with pytest.raises(RuntimeError):
        _run(camera, config, gp_camera_capture=MagicMock(side_effect=RuntimeError("unplugged")))
    assert config['aeb'].value == "off"


def _nikon_config(with_burst_number=True):
    config = {
        'shutterspeed2': _Widget("1/60", ["1/250", "1/125", "1/60", "1/30", "1/15"]),
        'bracketing': _Widget("Off", ["Off", "On"]),
        'bracketset': _Widget("AE only", ["AE only"]),
        'aebracketingstep': _Widget("1 EV", ["1/3 EV", "1 EV"]),
        'aebracketingpattern': _Widget("3 images", ["3 images (normal/under/over)"]),
    }
    if with_burst_number:
        config['burstnumber'] = _Widget(1)
    return config


def test_nikon_bracket_without_burst_number_resets_the_bracketing():
    # The reset used an unbound burst_number (UnboundLocalError) and left the bracketing on
    config = _nikon_config(with_burst_number=False)
    camera = _Camera("Nikon")
    camera.capture = MagicMock()
    _run(camera, config)
    camera.capture.assert_called_once()
    assert config['bracketing'].value == "Off"


def test_nikon_bracket_is_reset_after_a_failed_capture():
    config = _nikon_config()
    camera = _Camera("Nikon")
    camera.capture = MagicMock(side_effect=gphoto2.GPhoto2Error(-7))
    with pytest.raises(gphoto2.GPhoto2Error):
        _run(camera, config, gp_camera_capture=MagicMock(side_effect=gphoto2.GPhoto2Error(-7)))
    assert config['bracketing'].value == "Off"
    assert config['burstnumber'].value == 1


def test_bracket_with_unlisted_shutter_speeds_keeps_the_script_speed():
    # No parseable speed on the widget: the base speed was None and the Sony path crashed
    config = {
        'shutterspeed': _Widget("bulb", ["bulb"]),
        'capturemode': _Widget("Single Shooting", ["Single Shooting", "Bracketing C 1.0 Steps 3 Pictures"]),
        'bulb': _Widget(0),
    }
    camera = _Camera("Sony")
    with patch.object(cam.time, 'sleep') as sleep:
        _run(camera, config, shutter="1/70")
    assert sleep.call_args[0][0] == pytest.approx(1 / 140 + 1 / 70 + 1 / 35)


def test_battery_level_of_a_camera_that_stays_busy_gives_up():
    camera = types.SimpleNamespace(name="Busy", _camera=object())
    camera.get_config = MagicMock(side_effect=gphoto2.GPhoto2Error(-110))
    with patch.object(cam.time, 'sleep'), pytest.raises(cam.CameraError):
        cam.get_battery_level(camera)
    assert 1 < camera.get_config.call_count < 50


def test_sony_settings_of_a_camera_that_stays_busy_give_up():
    camera = types.SimpleNamespace(name="Busy", _camera=object())
    camera.get_config = MagicMock(side_effect=gphoto2.GPhoto2Error(-110))
    with patch.object(cam.time, 'sleep'):
        assert cam.get_sony_save_destination(camera) is None
        assert cam.get_sony_image_quality(camera) is None


def test_camera_that_cannot_be_opened_does_not_cost_the_others(monkeypatch):
    good = types.SimpleNamespace(name="Canon EOS R")
    monkeypatch.setattr(cam, "detect_sdk_cameras", lambda: cam.SdkDetection({}, ()))
    monkeypatch.setattr(cam, "detect_cameras", lambda: [("Nikon Z 6", "usb:001,002"), ("Canon EOS R", "usb:001,003")])

    def open_camera(model, port, alias=None):
        if model.startswith("Nikon"):
            raise cam.CameraError("Cannot claim USB device")
        return good

    monkeypatch.setattr(cam, "get_camera_by_port", open_camera)
    reported = []
    monkeypatch.setattr(cam.hardware_problems, "report", lambda source, message, **kw: reported.append(source))
    assert cam.get_camera_dict() == {"Canon EOS R": good}
    assert reported == ["Nikon Z 6"]


def test_canon_burst_fallback_does_not_compensate_twice(monkeypatch):
    # Without 'eosremoterelease' a burst is single pictures; each got the compensation again
    camera = types.SimpleNamespace(vendor="Canon", name="Canon EOS 1000D", _camera=object(),
                                   _usb_lock=threading.RLock())
    config = {'drivemode': _Widget("Single", ["Single", "Continuous"])}
    shots = []
    monkeypatch.setattr(cam, "__adapt_camera_settings", lambda c, s, **kw: (object(), config))
    monkeypatch.setattr(cam, "_drain_camera_events", lambda *a, **k: None)
    monkeypatch.setattr(cam.take_picture, "__wrapped__", lambda c, s: shots.append(s.shutter_speed))
    monkeypatch.setattr(cam, "_exposure_compensation_ev", 1)
    with ExitStack() as stack:
        _fake_gphoto(stack, config)
        cam.take_burst(camera, CameraSettings("Canon EOS 1000D", "1/500", "8", 100), 2)
    assert shots == ["1/250", "1/250"]
