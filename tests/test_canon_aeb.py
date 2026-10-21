"""Canon AEB stops at the end of the camera's sequence only when the camera shows it.

The number of AEB frames is a custom function that cannot be set over USB.  A
camera that reports the bracketed shutter speed shows where its sequence ends; an
EOS 80D always reports the dial speed, so it must take every frame of the script.
"""
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import solareclipseworkbench.camera as cam
from solareclipseworkbench.camera import CameraSettings, take_bracket

from test_unchanged_settings import _Camera, _Widget, _fake_gphoto


def _canon_config():
    return {
        'shutterspeed': _Widget("1/60", ["1/250", "1/125", "1/60", "1/30", "1/15"]),
        'aeb': _Widget("off", ["off", "+/- 1/3", "+/- 2/3", "+/- 1"]),
    }


def _bracket(reported_speeds, frames):
    """Run a Canon '1 <frames>' bracket; return (captures, config)."""
    config = _canon_config()
    camera = _Camera("Canon")
    camera.capture = MagicMock()
    with ExitStack() as stack:
        _fake_gphoto(stack, config)
        stack.enter_context(patch.object(cam, '__adapt_camera_settings', return_value=(object(), config)))
        stack.enter_context(patch.object(cam, '_canon_shutter_speed', side_effect=reported_speeds))
        stack.enter_context(patch.object(cam, '_drain_camera_events'))
        take_bracket(camera, CameraSettings("Canon Test", "1/60", "8", 100), f"1 {frames}")
    return camera.capture.call_count, config


def test_menu_set_to_the_bracket_takes_all_frames():
    # With 5 set, the sequence is 0, -2, -1, +1, +2: reported before frames 2 and 4
    captures, config = _bracket(["1/250", "1/30"], 5)
    assert captures == 5
    assert config['aeb'].value == "off"


def test_menu_set_lower_stops_at_the_end_of_the_sequence(caplog):
    # Before frame 4 the camera is back at the base exposure: its sequence is complete
    captures, _ = _bracket(["1/250", "1/60"], 5)
    assert captures == 3
    assert "AEB stopped after 3 frames instead of 5" in caplog.text


def test_camera_reporting_the_dial_speed_takes_all_frames(caplog):
    # EOS 80D: always the dial speed, so the end of its sequence cannot be seen
    captures, config = _bracket(["1/60"] * 5, 7)
    assert captures == 7
    assert "AEB stopped" not in caplog.text
    assert config['aeb'].value == "off"


def test_three_frames_need_no_readback():
    captures, _ = _bracket([], 3)
    assert captures == 3
