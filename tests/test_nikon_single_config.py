"""Nikon take_picture, take_burst and prepare_camera read only the settings they need.

gp_camera_get_config reads every setting of the camera; on a Nikon Z6 III that
took about a second before every shot, so pictures were released 1.3 s after
their scheduled time.  take_picture, take_burst and prepare_camera now read each setting
with gp_camera_get_single_config and write back only the changed ones.
"""
from contextlib import ExitStack
from unittest.mock import patch

import gphoto2
import pytest

import solareclipseworkbench.camera as cam
from solareclipseworkbench.camera import CameraSettings, prepare_camera, take_burst, take_picture

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
    def __init__(self, vendor="Nikon"):
        self.vendor = vendor
        self.name = f"{vendor} Test"
        self._camera = object()
        self._usb_lock = _DummyLock()
        self.captures = 0

    def capture(self, *args):
        self.captures += 1


def _nikon_settings(shutter="1/13", iso="100", f_number="f/8", capture_mode="Single Shot"):
    return {
        'expprogram': _Widget("M", ["M", "P", "A", "S"]),
        'autoiso': _Widget("Off"),
        'iso': _Widget(iso),
        'shutterspeed': _Widget(shutter, ["1/250", "1/13", "1/6", "1/3"]),
        'capturetarget': _Widget("Memory card", ["Internal RAM", "Memory card"]),
        'f-number': _Widget(f_number, ["f/5.6", "f/8"]),
        'capturemode': _Widget(capture_mode, ["Single Shot", "Continuous Low Speed"]),
    }


class _FakeNikon:
    """Settings on the camera, with a log of the single-setting reads and writes."""

    def __init__(self, settings):
        self.settings = settings
        self.reads = []
        self.writes = []

    def get_single_config(self, target, name, context):
        self.reads.append(name)
        if name not in self.settings:
            raise gphoto2.GPhoto2Error(gphoto2.GP_ERROR_BAD_PARAMETERS)
        # A fresh widget, as gphoto2 hands out: changing it does not change the camera
        return _Widget(self.settings[name].value, self.settings[name].choices)

    def set_single_config(self, target, name, widget, context):
        self.writes.append((name, widget.value))
        self.settings[name].value = widget.value
        return gphoto2.GP_OK


def _check_result(value):
    """Like gphoto2.check_result: a negative error code raises."""
    if isinstance(value, int) and not isinstance(value, bool) and value < gphoto2.GP_OK:
        raise gphoto2.GPhoto2Error(value)
    return value


def _fake_gphoto(stack, nikon):
    """Patch gphoto2 so settings come from *nikon*; return the full get_config mock."""
    def set_value(widget, value):
        widget.value = value

    stack.enter_context(patch.object(cam.gp, 'check_result', side_effect=_check_result))
    stack.enter_context(patch.object(cam.gp, 'gp_context_new', return_value=object()))
    stack.enter_context(patch.object(cam.gp, 'gp_camera_get_single_config', side_effect=nikon.get_single_config))
    stack.enter_context(patch.object(cam.gp, 'gp_camera_set_single_config', side_effect=nikon.set_single_config))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_get_value', side_effect=lambda w: w.value))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_set_value', side_effect=set_value))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_count_choices', side_effect=lambda w: len(w.choices)))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_get_choice', side_effect=lambda w, i: w.choices[i]))
    stack.enter_context(patch.object(cam.gp, 'gp_widget_get_range',
                                     side_effect=gphoto2.GPhoto2Error(gphoto2.GP_ERROR_BAD_PARAMETERS)))
    stack.enter_context(patch.object(cam.gp, 'gp_camera_trigger_capture', return_value=gphoto2.GP_OK))
    stack.enter_context(patch.object(cam, '_aperture_verified', {"Nikon Test": {"f/8"}}))
    stack.enter_context(patch.object(cam, '_drain_camera_events'))
    stack.enter_context(patch.object(cam, '_wait_for_capture_complete'))
    stack.enter_context(patch.object(cam, '_find_memory_card_choice', return_value="Memory card"))
    return stack.enter_context(patch.object(cam.gp, 'gp_camera_get_config'))


def test_take_picture_does_not_read_the_whole_configuration():
    nikon = _FakeNikon(_nikon_settings())
    with ExitStack() as stack:
        get_config = _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/13", "8", 100))
    get_config.assert_not_called()
    assert nikon.writes == []
    assert set(nikon.reads) == {'expprogram', 'autoiso', 'iso', 'shutterspeed', 'capturetarget',
                                'f-number', 'capturemode'}
    assert len(nikon.reads) == len(set(nikon.reads))


def test_only_the_changed_shutter_speed_is_written():
    nikon = _FakeNikon(_nikon_settings(shutter="1/250"))
    with ExitStack() as stack:
        _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/6", "8", 100))
    assert nikon.writes == [('shutterspeed', "1/6")]


def test_exposure_mode_is_written_before_the_shutter_speed():
    settings = _nikon_settings(shutter="1/250", iso="400")
    settings['expprogram'].value = "A"
    nikon = _FakeNikon(settings)
    with ExitStack() as stack:
        _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/6", "5.6", 100))
    assert nikon.writes == [('expprogram', "M"), ('iso', "100"), ('shutterspeed', "1/6"),
                            ('f-number', "f/5.6")]


def test_burst_mode_left_over_is_switched_back_to_single():
    nikon = _FakeNikon(_nikon_settings(capture_mode="Continuous Low Speed"))
    with ExitStack() as stack:
        _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/13", "8", 100))
    assert nikon.writes == [('capturemode', "Single Shot")]


def test_missing_setting_is_skipped():
    settings = _nikon_settings(shutter="1/250")
    del settings['autoiso']
    nikon = _FakeNikon(settings)
    with ExitStack() as stack:
        _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/6", "8", 100))
    assert nikon.writes == [('shutterspeed', "1/6")]


def test_refused_setting_does_not_stop_the_others():
    nikon = _FakeNikon(_nikon_settings(shutter="1/250", iso="400"))
    refused = nikon.set_single_config

    def set_single_config(target, name, widget, context):
        if name == 'iso':
            return gphoto2.GP_ERROR_NOT_SUPPORTED
        return refused(target, name, widget, context)

    nikon.set_single_config = set_single_config
    with ExitStack() as stack:
        _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/6", "8", 100))
    assert nikon.settings['shutterspeed'].value == "1/6"
    assert nikon.settings['iso'].value == "400"


def test_refused_exposure_mode_is_tried_once_per_shot():
    """A mode dial at A refuses M: one write, not one per set_config (aperture after exposure)."""
    settings = _nikon_settings(shutter="1/250", f_number="f/5.6")
    settings['expprogram'].value = "A"
    nikon = _FakeNikon(settings)
    accept = nikon.set_single_config

    def set_single_config(target, name, widget, context):
        if name == 'expprogram':
            nikon.writes.append((name, widget.value))
            return gphoto2.GP_ERROR_BAD_PARAMETERS
        return accept(target, name, widget, context)

    nikon.set_single_config = set_single_config
    with ExitStack() as stack:
        _fake_gphoto(stack, nikon)
        take_picture(_Camera(), CameraSettings("Nikon Test", "1/6", "8", 100))
    assert [name for name, _ in nikon.writes].count('expprogram') == 1
    assert nikon.settings['shutterspeed'].value == "1/6"
    assert nikon.settings['f-number'].value == "f/8"


def test_prepare_camera_reads_single_settings_on_a_nikon():
    nikon = _FakeNikon(_nikon_settings(shutter="1/250"))
    with ExitStack() as stack:
        get_config = _fake_gphoto(stack, nikon)
        prepare_camera(_Camera(), CameraSettings("Nikon Test", "1/6", "8", 100), "single")
    get_config.assert_not_called()
    assert nikon.writes == [('shutterspeed', "1/6")]


@pytest.mark.parametrize("vendor", ["Canon", "Sony"])
def test_other_brands_still_read_the_whole_configuration(vendor):
    with ExitStack() as stack:
        get_config = _fake_gphoto(stack, _FakeNikon({}))
        stack.enter_context(patch.object(cam.gp, 'gp_widget_get_child_by_name',
                                         side_effect=gphoto2.GPhoto2Error(gphoto2.GP_ERROR_BAD_PARAMETERS)))
        stack.enter_context(patch.object(cam, '_set_gp_config'))
        adapt_camera_settings(_Camera(vendor), CameraSettings(f"{vendor} Test", "1/6", "8", 100),
                              single_config=True)
    get_config.assert_called_once()


def _burst_settings(**kwargs):
    settings = _nikon_settings(**kwargs)
    settings['capturemode'] = _Widget("Single Shot", ["Single Shot", "Burst", "Continuous Low Speed"])
    settings['burstnumber'] = _Widget(1)
    return settings


def test_burst_does_not_read_the_whole_configuration():
    nikon = _FakeNikon(_burst_settings())
    camera = _Camera()
    with ExitStack() as stack:
        get_config = _fake_gphoto(stack, nikon)
        take_burst(camera, CameraSettings("Nikon Test", "1/13", "8", 100), 20)
    get_config.assert_not_called()
    assert camera.captures == 1
    assert nikon.writes == [('capturemode', "Burst"), ('burstnumber', 20), ('burstnumber', 1)]


def test_burst_with_refused_release_mode_needs_no_new_read():
    """A Z 8 refuses the release mode over USB; the number of frames is still set."""
    settings = _burst_settings()
    settings['stillcapturemode'] = _Widget(1)
    nikon = _FakeNikon(settings)
    accept = nikon.set_single_config

    def set_single_config(target, name, widget, context):
        if name in ('capturemode', 'stillcapturemode'):
            nikon.writes.append((name, widget.value))
            return gphoto2.GP_ERROR_NOT_SUPPORTED
        return accept(target, name, widget, context)

    nikon.set_single_config = set_single_config
    camera = _Camera()
    with ExitStack() as stack:
        get_config = _fake_gphoto(stack, nikon)
        take_burst(camera, CameraSettings("Nikon Test", "1/13", "8", 100), 20)
    get_config.assert_not_called()
    names = [name for name, _ in nikon.writes]
    assert names.count('capturemode') == 1 and names.count('stillcapturemode') == 1
    assert ('burstnumber', 20) in nikon.writes
    assert nikon.settings['burstnumber'].value == 1
    assert camera.captures == 1
