"""FujiCamera live view: PC priority while it runs, camera priority after it.

A body left in PC priority, or a body that gets SDK calls after it has left the
USB bus, fails the next frames of the script.  The SDK is a MagicMock, so no
camera is needed.
"""

from unittest.mock import MagicMock

import pytest

import fujixsdk
from fujixsdk._errors import CommunicationError

from solareclipseworkbench import fuji_camera
from solareclipseworkbench.camera import CameraError, has_preview_source
from solareclipseworkbench.fuji_camera import FujiCamera

LIVE_JPEG = b"\xff\xd8live\xff\xd9"


class _Unblock:
    """Stands in for fujixsdk.recovery.unblock, and records the priorities asked for."""

    def __init__(self, granted=True):
        self.granted = granted
        self.calls = []

    def __call__(self, camera, priority, allow_shot=True, why=""):
        self.calls.append((priority, allow_shot))
        return self.granted


@pytest.fixture
def unblock(monkeypatch):
    fake = _Unblock()
    monkeypatch.setattr(fuji_camera.sdk_recovery, "unblock", fake)
    return fake


def _camera():
    sdk = MagicMock()
    sdk.vanished = False
    sdk.still_on_bus.return_value = True
    info = MagicMock()
    info.format = fujixsdk.IMAGEFORMAT_LIVE
    info.data_size = len(LIVE_JPEG)
    sdk.read_image_info.return_value = info
    sdk.read_image.return_value = LIVE_JPEG
    cam = FujiCamera(sdk, "Fuji Fujifilm X-T4", "/sdk", "ENUM:0", model="X-T4")
    return cam, sdk


def _priorities(sdk):
    return [c.args[0] for c in sdk.set_priority.call_args_list]


def test_a_fuji_body_is_a_preview_source():
    cam, _ = _camera()
    assert has_preview_source(cam)


def test_start_takes_pc_priority_without_a_flush_shot(unblock):
    cam, sdk = _camera()

    cam.start_preview()

    assert unblock.calls == [(fujixsdk.PRIORITY_PC, False)]
    sdk.start_live_view.assert_called_once()


def test_a_frame_is_the_jpeg_of_the_stream(unblock):
    cam, _ = _camera()
    cam.start_preview()

    assert cam.read_preview_frame() == LIVE_JPEG


def test_stop_gives_camera_priority_back(unblock):
    cam, sdk = _camera()
    cam.start_preview()

    cam.stop_preview()

    sdk.stop_live_view.assert_called_once()
    assert _priorities(sdk) == [fujixsdk.PRIORITY_CAMERA]
    assert cam.read_preview_frame() is None


def test_start_fails_when_the_body_refuses_pc_priority(unblock):
    unblock.granted = False
    cam, sdk = _camera()

    with pytest.raises(CameraError, match="PC priority"):
        cam.start_preview()
    sdk.start_live_view.assert_not_called()


def test_a_stream_that_does_not_start_gives_priority_back(unblock):
    cam, sdk = _camera()
    sdk.start_live_view.side_effect = RuntimeError("refused")

    with pytest.raises(RuntimeError):
        cam.start_preview()

    assert _priorities(sdk) == [fujixsdk.PRIORITY_CAMERA]
    assert cam._preview is None


def test_a_vanished_body_gets_no_call_on_stop(unblock):
    cam, sdk = _camera()
    cam.start_preview()
    sdk.vanished = True
    sdk.reset_mock()

    cam.stop_preview()

    sdk.stop_live_view.assert_not_called()
    sdk.set_priority.assert_not_called()
    sdk.still_on_bus.assert_not_called()


def test_a_body_gone_from_the_bus_gets_no_call_on_stop(unblock):
    cam, sdk = _camera()
    cam.start_preview()
    sdk.still_on_bus.return_value = False

    cam.stop_preview()

    sdk.stop_live_view.assert_not_called()
    sdk.set_priority.assert_not_called()
    assert sdk.vanished is True


def test_a_vanished_body_does_not_start_a_preview(unblock):
    cam, sdk = _camera()
    sdk.vanished = True

    with pytest.raises(CameraError, match="USB bus"):
        cam.start_preview()
    assert unblock.calls == []


def test_a_body_that_leaves_when_it_gets_priority_back_is_marked_vanished(unblock):
    cam, sdk = _camera()
    cam.start_preview()
    sdk.set_priority.side_effect = CommunicationError(0x2001, "gone")

    cam.stop_preview()

    assert sdk.vanished is True


def test_the_stream_stops_when_the_last_user_stops(unblock):
    cam, sdk = _camera()
    cam.start_preview()
    cam.start_preview()

    cam.stop_preview()
    sdk.stop_live_view.assert_not_called()
    assert cam.read_preview_frame() == LIVE_JPEG

    cam.stop_preview()
    sdk.stop_live_view.assert_called_once()
    assert unblock.calls == [(fujixsdk.PRIORITY_PC, False)]


def test_a_stream_of_a_closed_session_gets_no_call(unblock):
    cam, old_sdk = _camera()
    cam.start_preview()
    cam._sdk_cam = MagicMock()

    with pytest.raises(CameraError, match="rebuilt"):
        cam.read_preview_frame()
    cam.stop_preview()

    old_sdk.stop_live_view.assert_not_called()
    old_sdk.set_priority.assert_not_called()


def test_stop_applies_the_held_back_settings_when_the_camera_keeps_them(unblock):
    cam, sdk = _camera()
    cam.apply_pending = MagicMock()
    cam.start_preview()

    cam.stop_preview()

    cam.apply_pending.assert_called_once()


def test_stop_without_a_preview_does_nothing(unblock):
    cam, sdk = _camera()
    cam.apply_pending = MagicMock()

    cam.stop_preview()

    sdk.set_priority.assert_not_called()
    cam.apply_pending.assert_not_called()
