"""A camera that libgphoto2 does not know yet is detected as "USB PTP Class Camera".

Its vendor is then taken from the manufacturer and model the camera reports over
PTP, so e.g. a Sony A7 V still gets the Sony handling (drive modes, storage info).
"""
import gphoto2 as gp
import pytest

from solareclipseworkbench.camera import (
    CanonCamera, GPhotoCameraAdapter, NikonCamera, SonyCamera, _detect_vendor, _wrap_camera,
)


@pytest.fixture(autouse=True)
def fake_widgets(monkeypatch):
    """Read config values from a plain dict instead of a gphoto2 widget tree."""
    def get_child_by_name(config, name):
        if name not in config:
            return [gp.GP_ERROR_BAD_PARAMETERS, None]
        return [gp.GP_OK, config[name]]

    monkeypatch.setattr(gp, 'gp_widget_get_child_by_name', get_child_by_name)
    monkeypatch.setattr(gp, 'gp_widget_get_value', lambda widget: [gp.GP_OK, widget])


def _config(**values):
    """A camera config with e.g. manufacturer='Sony Corporation'."""
    return dict(values)


def test_model_name_decides_when_it_names_the_vendor():
    config = _config(manufacturer='Sony Corporation')
    assert _detect_vendor('Canon EOS 80D', config) == 'Canon'
    assert _detect_vendor('Nikon Z 6', None) == 'Nikon'
    assert _detect_vendor('Sony Alpha-A7r III (PC Control)', None) == 'Sony'


def test_generic_ptp_camera_uses_reported_manufacturer():
    assert _detect_vendor('USB PTP Class Camera',
                          _config(manufacturer='Sony Corporation', cameramodel='ILCE-7M5')) == 'Sony'
    assert _detect_vendor('USB PTP Class Camera', _config(manufacturer='Canon Inc.')) == 'Canon'
    assert _detect_vendor('USB PTP Class Camera', _config(manufacturer='Nikon Corporation')) == 'Nikon'
    assert _detect_vendor('USB PTP Class Camera', _config(manufacturer='SONY')) == 'Sony'


def test_generic_ptp_camera_uses_sony_model_code():
    assert _detect_vendor('USB PTP Class Camera', _config(cameramodel='ILCE-7M5')) == 'Sony'


def test_unknown_manufacturer_or_no_config_stays_generic():
    assert _detect_vendor('USB PTP Class Camera', _config(manufacturer='Fujifilm')) is None
    assert _detect_vendor('USB PTP Class Camera', _config()) is None
    assert _detect_vendor('USB PTP Class Camera', None) is None


def test_wrap_camera_picks_adapter_by_vendor_and_keeps_name():
    sony = _wrap_camera(object(), 'USB PTP Class Camera', 'Sony', 'USB PTP Class Camera')
    assert type(sony) is SonyCamera
    assert sony.vendor == 'Sony'
    assert sony.name == 'USB PTP Class Camera'
    assert type(_wrap_camera(object(), 'Canon EOS 80D', 'Canon', 'Canon EOS 80D')) is CanonCamera
    assert type(_wrap_camera(object(), 'Nikon Z 6', 'Nikon', 'Nikon Z 6')) is NikonCamera
    generic = _wrap_camera(object(), 'USB PTP Class Camera', None, 'USB PTP Class Camera')
    assert type(generic) is GPhotoCameraAdapter
    assert generic.vendor is None
