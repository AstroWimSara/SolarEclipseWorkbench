"""A camera driven through a vendor SDK, as camera.py sees it.

Such a camera is a BaseCamera without a gphoto2 object.  It applies the
exposure with apply_settings, and shoots bursts and ladders itself.  It is
detected before gphoto2, and gphoto2 leaves its bodies alone.
"""

import pytest

from solareclipseworkbench import camera as camera_mod
from solareclipseworkbench import hardware_problems
from solareclipseworkbench.bracketing import HDR_ONE_WAY, HDR_ROUND_TRIP
from solareclipseworkbench.camera import BaseCamera, CameraSettings, SdkDetection


class _SdkCamera(BaseCamera):
    """Records what camera.py asks of it."""

    def __init__(self, name="Fuji Fujifilm X-T4"):
        super().__init__(name=name)
        self.calls = []

    def connect(self):
        pass

    def disconnect(self):
        pass

    def configure(self, **kwargs):
        pass

    def capture(self):
        self.calls.append(("capture",))

    def apply_settings(self, settings):
        self.calls.append(("apply", settings.shutter_speed, settings.aperture, settings.iso))

    def shoot_burst(self, seconds):
        self.calls.append(("burst", seconds))
        return 1

    def shoot_ladder(self, exposures_s, drop_repeats=True):
        self.calls.append(("ladder", list(exposures_s), drop_repeats))
        return len(exposures_s)


@pytest.fixture(autouse=True)
def _no_compensation():
    camera_mod.set_exposure_compensation(0)
    hardware_problems.clear()
    yield
    camera_mod.set_exposure_compensation(0)
    hardware_problems.clear()


def _settings(speed="1/100"):
    return CameraSettings("Fuji Fujifilm X-T4", speed, "-", 200)


# ------------------------------------------------------------------- commands


def test_a_picture_applies_the_settings_then_captures():
    cam = _SdkCamera()

    camera_mod.take_picture(cam, _settings())

    assert cam.calls == [("apply", "1/100", "-", 200), ("capture",)]


def test_a_burst_is_shot_by_the_camera_for_its_seconds():
    cam = _SdkCamera()

    camera_mod.take_burst(cam, _settings(), 2.5)

    assert cam.calls[-1] == ("burst", 2.5)


def test_a_bracket_is_a_ladder_around_the_command_exposure_darkest_first():
    cam = _SdkCamera()

    camera_mod.take_bracket(cam, _settings("1/100"), "1 3")

    _, exposures, drop_repeats = cam.calls[-1]
    assert exposures == pytest.approx([1 / 200, 1 / 100, 1 / 50])
    assert drop_repeats is True


def test_the_exposure_compensation_moves_the_whole_ladder():
    cam = _SdkCamera()
    camera_mod.set_exposure_compensation(1)

    camera_mod.take_bracket(cam, _settings("1/100"), "1 3")

    _, exposures, _ = cam.calls[-1]
    assert exposures[1] == pytest.approx(1 / 50, rel=0.05)


@pytest.mark.parametrize("sequence,expected", [
    (HDR_ROUND_TRIP, [1 / 1000, 1 / 500, 1 / 250, 1 / 500, 1 / 1000]),
    (HDR_ONE_WAY, [1 / 1000, 1 / 500, 1 / 250]),
])
def test_an_hdr_sequence_keeps_its_repeats(sequence, expected):
    cam = _SdkCamera()

    camera_mod.take_hdr(cam, _settings("1/1000"), 2, sequence)

    _, exposures, drop_repeats = cam.calls[-1]
    assert exposures == pytest.approx(expected)
    assert drop_repeats is False


def test_a_camera_without_the_hooks_still_takes_the_virtual_path():
    cam = camera_mod.VirtualCamera()
    cam.connect()

    camera_mod.take_bracket(cam, _settings(), "1 3")


# ------------------------------------------------------------------ detection


@pytest.fixture
def _bus(monkeypatch):
    """gphoto2 sees a Fuji body and a Canon body.  Records which ones it opens."""
    claimed = []
    monkeypatch.setattr(camera_mod, "get_cameras",
                        lambda: [("Fuji Fujifilm X-T4", "usb:001,005"), ("Canon EOS 80D", "usb:001,006")])

    def _open(model_name, port, alias=None):
        claimed.append(model_name)
        return _SdkCamera(model_name)

    monkeypatch.setattr(camera_mod, "get_camera_by_port", _open)
    return claimed


def test_gphoto2_leaves_the_bodies_of_an_sdk_alone(_bus, monkeypatch):
    fuji = _SdkCamera()
    monkeypatch.setattr(camera_mod, "_sdk_backends",
                        [lambda: SdkDetection({fuji.name: fuji}, ("fuji",))])

    cameras = camera_mod.get_camera_dict()

    assert _bus == ["Canon EOS 80D"]
    assert cameras["Fuji Fujifilm X-T4"] is fuji
    assert "Canon EOS 80D" in cameras


def test_a_body_the_sdk_could_not_open_is_still_left_alone(_bus, monkeypatch):
    # gphoto2 cannot shoot an X body tethered, and its claim locks the SDK out.
    monkeypatch.setattr(camera_mod, "_sdk_backends", [lambda: SdkDetection({}, ("fuji",))])

    cameras = camera_mod.get_camera_dict()

    assert _bus == ["Canon EOS 80D"]
    assert "Fuji Fujifilm X-T4" not in cameras


def test_a_failing_sdk_does_not_stop_gphoto2(_bus, monkeypatch):
    def _broken():
        raise RuntimeError("library missing")

    monkeypatch.setattr(camera_mod, "_sdk_backends", [_broken])

    cameras = camera_mod.get_camera_dict()

    assert "Canon EOS 80D" in cameras
    assert any("SDK failed" in str(p) for p in hardware_problems.peek())
