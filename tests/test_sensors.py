"""Test Camera works out the pixel size from the camera model (sensors.SENSORS).

gphoto2 names a camera but not its sensor size, and the pixel size decides how
soon the Moon's bite shows after first contact (contact_visibility).
"""
import pytest

from solareclipseworkbench.camera_check import CameraProfile, check_camera, read_camera_profile
from solareclipseworkbench.sensors import pixel_size_for_model, sensor_for_model

from test_camera_check import FakeCanon


@pytest.mark.parametrize("model, pixel_size", [
    ("Sony ILCE-7RM3A (PC Control)", 4.51),     # discussion #192
    ("Sony Alpha-A7r III", 4.51),
    ("Sony Alpha-A7r IV", 3.76),
    ("Sony Alpha-A7 III", 5.93),
    ("Canon EOS R", 5.36),
    ("Canon EOS R5", 4.39),
    ("Canon EOS R6 Mark II", 5.98),
    ("Canon EOS 80D", 3.75),
    ("Nikon Z 8", 4.35),
    ("Nikon Z 6_2", 5.94),
    ("Nikon DSC D850", 4.35),
    ("Fuji Fujifilm X-T4", 3.77),
    ("Fuji Fujifilm X-H2S", 3.77),
    ("Fuji Fujifilm X-T5", 3.04),
])
def test_known_models(model, pixel_size):
    assert pixel_size_for_model(model) == pixel_size


@pytest.mark.parametrize("model", [
    "Canon EOS R6 Mark III",    # not an EOS R6 (nor a Mark II)
    "Canon EOS R5 Mark II",
    "Sony ILCE-9M3",            # not an A9
    "Nikon DSC D7100",
    "Fuji Fujifilm X-T50",      # not an X-T5
    "",
])
def test_a_model_that_is_not_listed_gets_no_value(model):
    assert pixel_size_for_model(model) is None


def test_similar_names_get_their_own_sensor():
    assert sensor_for_model("Canon EOS R50") == (22.3, 6000)
    assert sensor_for_model("Nikon DSC D7500") != sensor_for_model("Nikon DSC D750")
    assert sensor_for_model("Nikon Z 50") != sensor_for_model("Nikon Z 5")


def test_test_camera_reports_the_pixel_size():
    profile = read_camera_profile(FakeCanon(name="Canon EOS R5"))
    assert profile.pixel_size_um == 4.39
    report, _ = check_camera(FakeCanon(name="Canon EOS R5"))
    assert any(item.title == "Pixel size 4.39 µm" for item in report.items)


def test_an_unknown_model_asks_for_the_pixel_size():
    profile = read_camera_profile(FakeCanon())          # EOS 1000D, not listed
    assert profile.pixel_size_um is None
    report, _ = check_camera(FakeCanon())
    assert any(item.title.startswith("Pixel size not known") for item in report.items)


def test_a_profile_saved_before_keeps_loading():
    old = CameraProfile(camera="Canon EOS R5").to_dict()
    del old["pixel_size_um"]
    assert CameraProfile.from_dict(old).pixel_size_um is None
    assert CameraProfile.from_dict(CameraProfile(camera="x", pixel_size_um=4.39).to_dict()).pixel_size_um == 4.39
