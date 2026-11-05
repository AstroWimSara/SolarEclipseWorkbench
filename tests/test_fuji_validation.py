"""validate_for_eclipse must name the settings that cost frames.

Each of these is a camera state measured on an X-T4 that costs frames: auto
ISO, autofocus, a JPEG beside the RAW, a drive mode the SDK cannot release in.
"""

from unittest.mock import MagicMock

from fujixsdk import _constants as C
from fujixsdk._errors import XSDKError
from fujixsdk.camera import BatteryInfo, MediaCapacity, ShutterCount
from fujixsdk.eclipse import EclipseShooter, validate_for_eclipse


def _camera(**overrides):
    """A camera that passes every check, before overrides are applied."""
    defaults = dict(
        get_ae_mode=lambda: C.AE_OFF,
        get_focus_mode=lambda: C.SDK_FOCUS_MANUAL,
        get_iso=lambda: 200,
        get_drive_mode=lambda: C.DRIVE_MODE_CH,
        get_exposure_bias=lambda: 0,
        get_image_quality=lambda: C.IMAGE_QUALITY_RAW,
        get_wb_mode=lambda: C.WB_DAYLIGHT,
        get_long_exposure_nr=lambda: C.OFF,
        # The info section reads these too; they raise no issues but must not
        # blow up the checks above.
        get_shutter_speed=lambda: (C.SHUTTER_1_1000, 0),
        get_aperture=lambda: 800,
        get_buffer_capacity=lambda: (0, 32),
        # The real shapes: the body reports a coarse battery state rather than
        # a percentage, and the card calls take a slot.
        get_battery_info=lambda: BatteryInfo(
            body=C.POWERCAPACITY_80, grip=C.POWERCAPACITY_EMPTY,
            grip2=C.POWERCAPACITY_EMPTY, body_ratio=80, grip_ratio=0,
            grip2_ratio=0),
        get_media_status=lambda slot=1: C.MEDIASTATUS_OK,
        get_media_capacity=lambda slot=1: MediaCapacity(
            blank_frames=940, remaining_sectors=32 * 1024 * 1024,
            sector_size=512, card_size=64 * 1000 ** 3),
        get_shutter_count=lambda: ShutterCount(current=18955, total=18955,
                                               exchanges=0),
    )
    defaults.update(overrides)
    cam = MagicMock()
    for name, fn in defaults.items():
        setattr(cam, name, MagicMock(side_effect=lambda *a, fn=fn, **k: fn(*a, **k)))
    cam.camera_mode = 0x0001
    return cam


def _find(issues, setting):
    return [i for i in issues if i.setting == setting]


def test_clean_camera_raises_nothing_actionable():
    issues = validate_for_eclipse(_camera())
    actionable = [i for i in issues if i.severity in ("error", "warning")]
    assert actionable == [], [i.message for i in actionable]


# ------------------------------------------------------------------------ ISO


def test_auto_iso_is_an_error():
    # Measured: get_iso() returns -3, ISO_AUTO_3.  Every ISO in the script is
    # then ignored and the body meters off a black sky instead.
    issues = validate_for_eclipse(_camera(get_iso=lambda: C.ISO_AUTO_3))
    found = _find(issues, "ISO")
    assert found, "auto ISO was not reported at all"
    assert found[0].severity == "error"
    assert "Auto" in found[0].current


def test_fixed_iso_is_accepted():
    assert _find(validate_for_eclipse(_camera(get_iso=lambda: 100)), "ISO") == []


# ----------------------------------------------------------------- drive mode


def test_stills_drive_mode_is_not_treated_as_single_frame():
    # Measured: an X-T4 with the drive dial physically on CH still reads back
    # DRIVE_MODE_S.  That value means stills rather than single-frame drive, so
    # it cannot be an error.  The dial is stated as a thing to check by eye.
    issues = validate_for_eclipse(_camera(get_drive_mode=lambda: C.DRIVE_MODE_S))
    found = _find(issues, "Drive Mode")
    assert found and found[0].severity == "info"
    assert "verify" in found[0].expected.lower()


def test_the_drive_dial_is_asked_for_on_s():
    # The SDK releases one frame at a time and is refused on CH.
    issues = validate_for_eclipse(_camera(get_drive_mode=lambda: C.DRIVE_MODE_S))
    assert _find(issues, "Drive Mode")[0].expected.startswith("S")
    issues = validate_for_eclipse(_camera(get_drive_mode=lambda: C.DRIVE_MODE_MOVIE))
    assert _find(issues, "Drive Mode")[0].expected == "S"


def test_movie_mode_stays_an_error():
    issues = validate_for_eclipse(_camera(get_drive_mode=lambda: C.DRIVE_MODE_MOVIE))
    assert _find(issues, "Drive Mode")[0].severity == "error"


# ----------------------------------------------------------------- focus mode


def test_unreadable_focus_mode_is_reported_not_swallowed():
    # An X-T4 can return 0x1002 for focus mode with a lens attached.  The
    # setting most likely to refuse the release must still be mentioned.
    def boom():
        raise XSDKError(0x1002, "Invalid parameter", 0)

    issues = validate_for_eclipse(_camera(get_focus_mode=boom))
    found = _find(issues, "Focus Mode")
    assert found, "an unreadable focus mode was reported as no problem"
    assert found[0].severity == "warning"
    assert "unreadable" in found[0].current


def test_autofocus_is_still_an_error():
    issues = validate_for_eclipse(_camera(get_focus_mode=lambda: C.SDK_FOCUS_AFS))
    assert _find(issues, "Focus Mode")[0].severity == "error"


# --------------------------------------------------------------- image quality


def test_raw_plus_jpeg_is_an_error():
    # Measured: a JPEG beside the RAW puts two entries in the buffer per frame
    # and takes the rate from 1.85 fps to 0.61.
    issues = validate_for_eclipse(
        _camera(get_image_quality=lambda: C.IMAGE_QUALITY_FINE_PLUS_RAW))
    found = _find(issues, "Image Quality")
    assert found and found[0].severity == "error"
    assert "RAW" in found[0].expected


def test_jpeg_only_is_an_error():
    issues = validate_for_eclipse(_camera(get_image_quality=lambda: C.IMAGE_QUALITY_FINE))
    assert _find(issues, "Image Quality")[0].severity == "error"


def test_raw_alone_is_accepted():
    assert _find(validate_for_eclipse(_camera()), "Image Quality") == []


def test_unreadable_image_quality_is_reported():
    def boom():
        raise XSDKError(0x1002, "Invalid parameter", 0)

    found = _find(validate_for_eclipse(_camera(get_image_quality=boom)), "Image Quality")
    assert found and found[0].severity == "warning"
    assert "unreadable" in found[0].current


# ---------------------------------------------------------------- buffer drain


def test_buffer_is_drained_before_it_fills():
    # Nothing else empties the volatile buffer, so without this a run stops at
    # the 32nd frame however many the script asked for.

    cam = MagicMock()
    cam.get_buffer_capacity.return_value = (24, 32)      # 75% of 32
    shooter = EclipseShooter(cam)
    shooter._keep_buffer_clear()
    cam.drain_buffer.assert_called_once()


def test_buffer_is_left_alone_when_it_has_room():
    cam = MagicMock()
    cam.get_buffer_capacity.return_value = (5, 32)
    shooter = EclipseShooter(cam)
    shooter._keep_buffer_clear()
    cam.drain_buffer.assert_not_called()


def test_an_api_the_body_does_not_have_is_not_a_warning():
    """The X-T4 cannot report its image quality or its battery.  Saying so as a
    warning every session teaches the reader to skip warnings that do matter.

    0x1013 is the body saying it has no such API - confirmed against
    GetDeviceInfoEx, whose list of implemented codes omits CheckBatteryInfo
    however supported the manual claims the model is.
    """

    def unimplemented():
        raise XSDKError(0x1013, "API not found in model module")

    issues = validate_for_eclipse(_camera(get_image_quality=unimplemented))
    quality = _find(issues, "Image Quality")

    assert quality, "the setting disappeared instead of being stated"
    assert quality[0].severity == "info", "still warning about a missing API"
    assert quality[0].current == "not available on this body"


def test_a_failure_that_is_not_a_missing_api_still_warns():
    # The distinction is the point: busy, or a dead handle, is a real problem
    # and must not be filed away as a fact about the model.

    def busy():
        raise XSDKError(0x1006, "Camera is busy")

    issues = validate_for_eclipse(_camera(get_image_quality=busy))
    quality = _find(issues, "Image Quality")

    assert quality[0].severity == "warning"
    assert "0x1006" in quality[0].current


def test_the_focus_mode_keeps_the_same_distinction():
    def unimplemented():
        raise XSDKError(0x1013, "API not found in model module")

    issues = validate_for_eclipse(_camera(get_focus_mode=unimplemented))
    focus = _find(issues, "Focus Mode")

    assert focus[0].severity == "info"
    assert focus[0].expected == "MF"
