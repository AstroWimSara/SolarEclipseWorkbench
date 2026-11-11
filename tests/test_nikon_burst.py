"""Nikon take_burst: release mode and number of frames.

gp_camera_set_config returns an error code instead of raising.  On a Nikon whose
release mode is set with a dial or button (Z 8), the change to continuous is
refused; that used to go unnoticed, and the refused value stayed queued on the
config used to set the number of frames.
"""
import threading
import types

import gphoto2 as gp
import pytest

from solareclipseworkbench import camera as cam


class _Widget:
    def __init__(self, value, highest=None):
        self.value = value
        self.highest = highest


class _FakeNikon:
    """Camera values plus the configs handed out; set_config fails on a value the camera refuses."""

    def __init__(self, widgets, refused=(), highest_frames=None):
        self.values = dict(widgets)
        self.refused = set(refused)          # (widget, value) pairs the camera refuses
        self.highest_frames = highest_frames
        self.get_config_calls = 0
        self.frames_shot = []

    def config(self):
        self.get_config_calls += 1
        return types.SimpleNamespace(widgets={
            name: _Widget(value, self.highest_frames if name == "burstnumber" else None)
            for name, value in self.values.items()})

    def set_config(self, config):
        for name, widget in config.widgets.items():
            if (name, widget.value) in self.refused:
                return gp.GP_ERROR_NOT_SUPPORTED
        self.values.update({n: w.value for n, w in config.widgets.items()})
        return gp.GP_OK

    def capture(self, *args):
        self.frames_shot.append(self.values.get("burstnumber"))


def _range(widget):
    if widget.highest is None:
        return gp.GP_ERROR_BAD_PARAMETERS, 0, 0, 0
    return gp.GP_OK, 1.0, float(widget.highest), 1.0


def _child(config, name):
    if name not in config.widgets:
        return gp.GP_ERROR_BAD_PARAMETERS, None
    return gp.GP_OK, config.widgets[name]


def _burst(monkeypatch, nikon, frames=30):
    fake_gp = types.SimpleNamespace(
        check_result=gp.check_result,
        GP_CAPTURE_IMAGE=gp.GP_CAPTURE_IMAGE,
        gp_widget_get_child_by_name=_child,
        gp_widget_set_value=lambda w, v: setattr(w, "value", v) or gp.GP_OK,
        gp_widget_get_range=_range,
        gp_camera_get_config=lambda target, ctx: (gp.GP_OK, nikon.config()),
    )
    monkeypatch.setattr(cam, "gp", fake_gp)
    camera = types.SimpleNamespace(vendor="Nikon", name="Nikon Z 8", _camera=object(),
                                   _usb_lock=threading.RLock(), capture=nikon.capture)
    monkeypatch.setattr(cam, "__adapt_camera_settings", lambda c, s, **kw: (object(), nikon.config()))
    monkeypatch.setattr(cam, "_set_gp_config", lambda c, config, ctx: nikon.set_config(config))
    monkeypatch.setattr(cam, "_drain_camera_events", lambda *a, **k: None)
    cam.take_burst(camera, object(), frames)


def test_burst_sets_continuous_mode_and_frames_and_resets_frames(monkeypatch):
    nikon = _FakeNikon({"capturemode": "Single Shot", "burstnumber": 1})
    _burst(monkeypatch, nikon)
    assert nikon.frames_shot == [30]
    assert nikon.values == {"capturemode": "Burst", "burstnumber": 1}


def test_mirrorless_without_capturemode_does_not_read_the_config_again(monkeypatch):
    """No extra USB round trip before the shot when the first widget simply does not exist."""
    nikon = _FakeNikon({"stillcapturemode": 0, "burstnumber": 1})
    _burst(monkeypatch, nikon)
    assert nikon.frames_shot == [30]
    assert nikon.get_config_calls == 1       # only the one from adapting the camera settings


def test_refused_release_mode_is_logged_and_does_not_block_the_number_of_frames(monkeypatch, caplog):
    """Release mode set with a dial: the burst count must still reach the camera."""
    nikon = _FakeNikon({"capturemode": "Single Shot", "stillcapturemode": 0, "burstnumber": 1},
                       refused={("capturemode", "Burst"), ("stillcapturemode", 2)})
    _burst(monkeypatch, nikon)
    assert nikon.frames_shot == [30]
    assert "could not set a continuous release mode" in caplog.text


def test_more_frames_than_the_camera_takes_are_capped_with_a_warning(monkeypatch, caplog):
    nikon = _FakeNikon({"capturemode": "Single Shot", "burstnumber": 1}, highest_frames=20)
    _burst(monkeypatch, nikon)
    assert nikon.frames_shot == [20]
    assert "at most 20 frames per burst" in caplog.text


def test_refused_number_of_frames_is_logged(monkeypatch, caplog):
    nikon = _FakeNikon({"capturemode": "Single Shot", "burstnumber": 1}, refused={("burstnumber", 30)})
    _burst(monkeypatch, nikon)
    assert "could not set the burst to 30 frames" in caplog.text
