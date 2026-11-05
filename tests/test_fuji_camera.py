"""FujiCamera: exposure, shooting and clock on a Fuji body, where a failure is silent.

Most faults here give normal-looking frames at the wrong settings, or a clock
sync that reports success without moving the camera clock.  They only show up
when the card is read.  The SDK is a MagicMock, so no camera is needed.
"""

import math
import time
from unittest.mock import MagicMock

import pytest

from fujixsdk._constants import ERRCODE_BUSY, ERRCODE_PARAM, SHUTTER_SPEED_NAMES
from fujixsdk._errors import BusyError, ParamError

from solareclipseworkbench import camera as camera_mod
from solareclipseworkbench import fuji_camera, hardware_problems
from solareclipseworkbench.camera import CameraError, CameraSettings, SdkDetection
from solareclipseworkbench.fuji_camera import FujiCamera

XT4 = fuji_camera.MEASURED_SPEEDS_S["X-T4"]


@pytest.fixture(autouse=True)
def _clean():
    hardware_problems.clear()
    yield
    hardware_problems.clear()


@pytest.fixture
def _quick_backoff(monkeypatch):
    # The real backoff is a third of a second; the tests only check the shape
    # of the waiting, not its duration.
    monkeypatch.setattr(fuji_camera, 'BUSY_BACKOFF_S', 0.001)
    monkeypatch.setattr(fuji_camera, 'EXPOSURE_BUDGET_S', 0.05)


def _camera(model="X-T4"):
    sdk = MagicMock()
    sdk.get_buffer_capacity.return_value = (0, 32)
    sdk.drain_buffer.return_value = 0
    cam = FujiCamera(sdk, f"Fuji Fujifilm {model}", "/sdk", "ENUM:0", model=model)
    return cam, sdk


def _busy():
    return BusyError(ERRCODE_BUSY, 'Camera is busy')


def _seconds(value):
    return fuji_camera._speed_name_seconds(SHUTTER_SPEED_NAMES[value])


# ------------------------------------------------------------------ configure


def test_configure_raises_when_a_setting_is_rejected():
    camera, sdk = _camera()
    sdk.set_shutter_speed.side_effect = RuntimeError("busy")

    with pytest.raises(CameraError, match="shutter speed"):
        camera.configure(shutter_speed="1/2000")


def test_configure_reports_every_failure_not_just_the_first():
    camera, sdk = _camera()
    sdk.set_iso.side_effect = RuntimeError("nope")
    sdk.set_shutter_speed.side_effect = RuntimeError("busy")

    with pytest.raises(CameraError) as exc:
        camera.configure(iso=200, shutter_speed="1/2000")

    assert "ISO" in str(exc.value)
    assert "shutter speed" in str(exc.value)


def test_configure_tries_the_remaining_settings_after_one_fails():
    camera, sdk = _camera()
    sdk.set_iso.side_effect = RuntimeError("nope")

    with pytest.raises(CameraError):
        camera.configure(iso=200, shutter_speed="1/2000")

    assert sdk.set_shutter_speed.called


def test_configure_rejects_a_value_the_camera_cannot_express():
    camera, _ = _camera()

    with pytest.raises(CameraError, match="not a value"):
        camera.configure(iso="not-a-number")


def test_configure_succeeds_quietly_when_everything_applies():
    camera, sdk = _camera()

    camera.configure(iso=200, aperture="5.6")

    assert sdk.set_iso.called
    sdk.set_aperture.assert_called_once_with(560)


def test_a_telescope_without_aperture_is_not_a_failure():
    camera, sdk = _camera()

    camera.configure(aperture="-", iso=200)

    assert not sdk.set_aperture.called


def test_a_refused_setting_is_sent_again_with_the_next_configure():
    camera, sdk = _camera()
    sdk.set_iso.side_effect = [RuntimeError("busy"), None]

    with pytest.raises(CameraError):
        camera.configure(iso=400, shutter_speed="1/200")
    camera.configure(shutter_speed="1/200")

    assert sdk.set_iso.call_count == 2


# ------------------------------------------------------------- ISO and speed


def test_the_same_iso_is_written_once_not_on_every_frame():
    camera, sdk = _camera()

    for _ in range(4):
        camera.configure(iso=400)

    assert sdk.set_iso.call_count == 1


def test_a_changed_iso_is_written_again():
    camera, sdk = _camera()

    camera.configure(iso=100)
    camera.configure(iso=100)
    camera.configure(iso=800)

    assert sdk.set_iso.call_count == 2


def test_a_refused_iso_is_retried_on_the_next_frame():
    camera, sdk = _camera()
    sdk.set_iso.side_effect = RuntimeError("XSDK error 0x00001006: Camera is busy")

    for _ in range(3):
        with pytest.raises(CameraError, match="ISO"):
            camera.configure(iso=400)

    assert sdk.set_iso.call_count == 3


def test_the_same_shutter_speed_is_not_written_twice(_quick_backoff):
    # The body refuses the write with 0x1006 while it writes the previous frame,
    # so a write of the speed it already has only costs time.
    cam, sdk = _camera()

    cam.configure(shutter_speed='1/200')
    cam.configure(shutter_speed='1/200')

    assert sdk.set_shutter_speed.call_count == 1


def test_a_changed_shutter_speed_is_still_written(_quick_backoff):
    cam, sdk = _camera()

    cam.configure(shutter_speed='1/200')
    cam.configure(shutter_speed='1/500')

    assert sdk.set_shutter_speed.call_count == 2


# ------------------------------------------------------- waiting out a busy body


def test_a_body_still_writing_is_waited_out_not_reported_as_a_failure(_quick_backoff):
    # The X-T4 refuses exposure changes with 0x1006 for about a second after a frame.
    cam, sdk = _camera()
    sdk.set_iso.side_effect = [_busy(), _busy(), None]

    cam.configure(iso=400)

    assert sdk.set_iso.call_count == 3
    assert cam._applied_iso == 400


def test_a_value_the_body_rejects_outright_is_not_retried(_quick_backoff):
    # Waiting cannot make an unsupported value supported.
    cam, sdk = _camera()
    sdk.set_iso.side_effect = ParamError(ERRCODE_PARAM, 'Invalid parameter')

    with pytest.raises(CameraError):
        cam.configure(iso=400)

    assert sdk.set_iso.call_count == 1


def test_waiting_stops_at_the_budget_so_the_next_frame_is_not_missed(_quick_backoff):
    cam, sdk = _camera()
    sdk.set_iso.side_effect = _busy
    sdk.set_shutter_speed.side_effect = _busy

    started = time.monotonic()
    with pytest.raises(CameraError):
        cam.configure(iso=400, shutter_speed='1/200')
    elapsed = time.monotonic() - started

    # One budget for the whole call, not one per setting.
    assert elapsed < fuji_camera.EXPOSURE_BUDGET_S * 2, elapsed


def test_a_busy_body_does_not_leave_a_stale_iso_remembered(_quick_backoff):
    cam, sdk = _camera()
    sdk.set_iso.side_effect = _busy

    with pytest.raises(CameraError):
        cam.configure(iso=400)

    assert cam._applied_iso is None


def test_a_busy_body_does_not_leave_a_stale_speed_remembered(_quick_backoff):
    cam, sdk = _camera()
    sdk.set_shutter_speed.side_effect = _busy

    with pytest.raises(CameraError):
        cam.configure(shutter_speed='1/200')

    assert cam._applied_speed is None


def test_a_long_exposure_extends_the_wait_for_the_next_setting():
    # The body takes no setting until the frame in progress is written.
    cam, _ = _camera()
    cam._applied_speed = fuji_camera._parse_shutter_speed('2')
    fired = time.monotonic()
    cam._note_frame_fired()

    assert cam._frame_busy_until >= fired + 2.0 + fuji_camera.FRAME_WRITE_S - 0.1


def test_the_wait_for_a_frame_is_capped(_quick_backoff, monkeypatch):
    monkeypatch.setattr(fuji_camera, 'MAX_EXPOSURE_WAIT_S', 0.05)
    cam, sdk = _camera()
    cam._frame_busy_until = time.monotonic() + 3600
    sdk.set_shutter_speed.side_effect = _busy

    started = time.monotonic()
    with pytest.raises(CameraError):
        cam.configure(shutter_speed='1/200')

    assert time.monotonic() - started < 1.0


def test_a_short_exposure_does_not_extend_anything():
    cam, _ = _camera()
    cam._applied_speed = fuji_camera._parse_shutter_speed('1/1000')
    fired = time.monotonic()
    cam._note_frame_fired()

    assert cam._frame_busy_until < fired + fuji_camera.FRAME_WRITE_S + 0.1


# ------------------------------------------------------- shutter speed names

HALF_A_SECOND = 500_000       # SHUTTER_SPEED_NAMES calls this '1/2"'


@pytest.mark.parametrize("written", ["0.5", "1/2", '0.5"', " 0.5 "])
def test_half_a_second_is_understood_however_it_is_written(written):
    assert fuji_camera._parse_shutter_speed(written) == HALF_A_SECOND


def test_decimal_seconds_agree_with_their_fractional_spelling():
    for decimal, fraction in (("0.25", "1/4"), ("0.125", "1/8"), ("2", "2")):
        assert fuji_camera._parse_shutter_speed(decimal) == fuji_camera._parse_shutter_speed(fraction)


def test_a_value_that_is_not_a_speed_is_refused():
    assert fuji_camera._parse_shutter_speed("gibberish") is None
    assert fuji_camera._parse_shutter_speed("0") is None


def test_an_off_grid_value_snaps_but_says_so(caplog):
    with caplog.at_level("WARNING"):
        assert fuji_camera._parse_shutter_speed("0.7") is not None
    assert "not on this camera's scale" in caplog.text


def test_a_speed_past_the_fast_end_is_clamped_with_a_warning(caplog):
    with caplog.at_level("WARNING"):
        value = fuji_camera._parse_shutter_speed("1/32000")
    assert _seconds(value) == pytest.approx(fuji_camera.FASTEST_SHUTTER_S, rel=0.05)
    assert "faster than" in caplog.text


def test_the_measured_scale_avoids_a_half_stop_speed_the_body_refuses():
    # The SDK table holds 1/750, which an X-T4 refuses with 0x2003.
    half_stop = next(v for v, n in SHUTTER_SPEED_NAMES.items() if n.rstrip('"') == "1/750")

    assert fuji_camera._parse_shutter_speed("1/750") == half_stop
    on_xt4 = fuji_camera._parse_shutter_speed("1/750", XT4)
    assert on_xt4 != half_stop
    assert any(math.isclose(_seconds(on_xt4), s, rel_tol=0.01) for s in XT4)


# ------------------------------------------------------------------- ladders


def test_a_ladder_is_shot_in_the_order_given():
    # A bracket comes shortest first: around a contact, the first frames go off
    # while the computed contact time can still be a second or two wrong.
    cam, sdk = _camera()

    taken = cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    written = [_seconds(call.args[0]) for call in sdk.set_shutter_speed.call_args_list]
    assert written == pytest.approx([1 / 2000, 1 / 500, 1 / 125], rel=0.05)
    assert taken == 3
    assert sdk.shoot_no_af.call_count == 3


def test_a_ladder_past_the_end_of_the_scale_does_not_take_the_same_frame_twice():
    cam, sdk = _camera()

    taken = cam.shoot_ladder([1 / 32000, 1 / 16000, 1 / 8000, 1 / 4000])

    assert taken == 2
    assert sdk.shoot_no_af.call_count == 2


def test_an_hdr_sequence_keeps_its_repeated_speeds():
    cam, sdk = _camera()

    taken = cam.shoot_ladder([1 / 1000, 1 / 500, 1 / 1000], drop_repeats=False)

    assert taken == 3


def test_a_ladder_that_is_cut_short_is_reported():
    cam, sdk = _camera()
    sdk.get_buffer_capacity.side_effect = [(0, 32), (0, 32), (32, 32), (32, 32)]
    sdk.drain_buffer.return_value = 0

    taken = cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    assert taken < 3
    assert any("cut short" in str(p) for p in hardware_problems.peek())


def test_a_ladder_leaves_configure_writing_the_speed_again():
    # The ladder writes speeds itself.  If configure still believed its last
    # speed was on the body, the next frame at that speed would be skipped.
    cam, sdk = _camera()
    cam.configure(shutter_speed='1/125')

    cam.shoot_ladder([1 / 2000, 1 / 125])
    sdk.set_shutter_speed.reset_mock()
    cam.configure(shutter_speed='1/125')

    assert sdk.set_shutter_speed.call_count == 1


# --------------------------------------------------------------- burst, single


def test_a_burst_takes_at_least_one_frame():
    cam, sdk = _camera()

    assert cam.shoot_burst(0) == 1
    assert sdk.shoot_no_af.call_count == 1


def test_a_burst_runs_for_its_duration():
    cam, sdk = _camera()

    started = time.monotonic()
    taken = cam.shoot_burst(0.05)

    assert time.monotonic() - started >= 0.05
    assert taken == sdk.shoot_no_af.call_count >= 1


def test_a_release_that_does_not_happen_is_an_error():
    cam, sdk = _camera()
    sdk.get_buffer_capacity.return_value = (32, 32)

    with pytest.raises(CameraError, match="did not release"):
        cam.capture()


def test_settings_that_fail_still_shoot_and_are_reported():
    cam, sdk = _camera()
    sdk.set_shutter_speed.side_effect = RuntimeError("refused")

    cam.apply_settings(CameraSettings(cam.name, "1/200", "-", 200))

    assert any("wrong exposure" in str(p) for p in hardware_problems.peek())


# ------------------------------------------------------------------ the clock


def test_the_clock_is_reported_as_not_settable_once():
    cam, _ = _camera()

    assert cam.sync_clock() is False
    assert cam.sync_clock() is False

    problems = [p for p in hardware_problems.peek() if "by hand" in str(p)]
    assert len(problems) == 1


def test_set_time_delegates_to_a_camera_that_owns_its_clock():
    cam, sdk = _camera()

    assert camera_mod.set_time(cam) is False
    assert any("by hand" in str(p) for p in hardware_problems.peek())


def test_the_clock_of_the_body_is_not_reported_as_in_sync():
    cam, _ = _camera()

    assert camera_mod.read_camera_clock(cam) is None


# ------------------------------------------------------------------ detection


def test_the_fuji_backend_is_registered():
    assert fuji_camera.detect_for_workbench in camera_mod._sdk_backends


def test_without_the_fuji_sdk_gphoto2_keeps_every_body(monkeypatch):
    monkeypatch.setattr(fuji_camera, "find_fuji_sdk_path", lambda: None)

    assert fuji_camera.detect_for_workbench() == SdkDetection({}, ())


def test_with_the_fuji_sdk_gphoto2_keeps_off_every_fuji_body(monkeypatch):
    monkeypatch.setattr(fuji_camera, "find_fuji_sdk_path", lambda: "/sdk")
    monkeypatch.setattr(fuji_camera, "detect_fuji", lambda path: fuji_camera.FujiDetection({}, 0))

    assert fuji_camera.detect_for_workbench().skip_gphoto == ("fuji",)
