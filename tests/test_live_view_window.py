"""LiveViewWindow: the focus tools, and the stop of an SDK preview before a camera job.

A camera that a vendor SDK drives refuses settings and the shutter release in
live view, so its preview must stop before each scheduled camera job.  The
camera is a fake with the three preview source methods.
"""

import datetime
import threading

import pytest
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui
from test_live_view_preview_source import _FakeSdkCamera, _wait_for


# ---------------------------------------------------------------- next camera job


class _Job:
    def __init__(self, job_id, seconds, now):
        self.id = job_id
        self.next_run_time = None if seconds is None else now + datetime.timedelta(seconds=seconds)


NOW = datetime.datetime(2030, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)


def test_the_next_camera_job_skips_jobs_without_a_camera():
    jobs = [_Job("voice", 2, NOW), _Job("shot", 20, NOW), _Job("later", 60, NOW)]

    gap = gui.seconds_to_next_camera_job(jobs, lambda job: job.id != "voice", now=NOW)

    assert gap == pytest.approx(20)


def test_without_a_predicate_every_job_counts():
    jobs = [_Job("voice", 2, NOW), _Job("shot", 20, NOW)]
    assert gui.seconds_to_next_camera_job(jobs, now=NOW) == pytest.approx(2)


def test_no_camera_job_gives_none():
    assert gui.seconds_to_next_camera_job([], now=NOW) is None
    assert gui.seconds_to_next_camera_job([_Job("done", None, NOW)], now=NOW) is None


def test_a_job_that_is_due_now_gives_zero():
    assert gui.seconds_to_next_camera_job([_Job("late", -0.5, NOW)], now=NOW) == 0.0


# ---------------------------------------------------------------- the window


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _GphotoLike:
    """A camera that LiveViewWindow previews through gphoto2, never reached here."""

    name = "Fake gphoto2 camera"

    def __init__(self):
        self._camera = object()
        self._usb_lock = threading.RLock()


@pytest.fixture
def no_gphoto(monkeypatch):
    # The window of a gphoto2 camera reads its preview sizes; there is no camera
    monkeypatch.setattr(gui, "get_live_view_sizes", lambda camera: None)
    monkeypatch.setattr(gui.LiveViewThread, "start", lambda self: None)


def test_the_window_stops_an_sdk_preview_when_a_camera_job_is_due(qapp):
    camera = _FakeSdkCamera()
    window = gui.LiveViewWindow(camera)
    try:
        assert camera.started.wait(2.0)
        window.set_camera_job_due(False)
        assert not camera.stopped.is_set()

        window.set_camera_job_due(True)
        assert camera.stopped.wait(2.0)
        assert window._toggle_btn.text() == "Enable Live View"
        assert "camera job" in window._status_label.text()
    finally:
        window.close()


def test_the_window_keeps_an_sdk_preview_off_while_the_job_is_due(qapp):
    camera = _FakeSdkCamera()
    window = gui.LiveViewWindow(camera)
    try:
        window.set_camera_job_due(True)
        window._on_toggle()
        assert window._user_enabled
        window.set_camera_job_due(True)
        assert not window._user_enabled
    finally:
        window.close()


def test_the_window_does_not_stop_a_gphoto2_preview_for_a_job(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        window.set_camera_job_due(True)
        assert window._user_enabled
    finally:
        window.close()


def test_the_window_offers_no_preview_size_for_an_sdk_camera(qapp, monkeypatch):
    def _fail(camera):
        raise AssertionError("get_live_view_sizes was called for an SDK camera")

    monkeypatch.setattr(gui, "get_live_view_sizes", _fail)
    window = gui.LiveViewWindow(_FakeSdkCamera())
    try:
        assert not window._size_combo.isEnabled()
    finally:
        window.close()


def test_the_window_shows_why_the_preview_source_stopped(qapp):
    camera = _FakeSdkCamera(fail_start=RuntimeError("no PC priority"))
    window = gui.LiveViewWindow(camera)
    try:
        assert _wait_for(lambda: window._thread.is_paused)
        window._poll_frame()
        assert "no PC priority" in window._status_label.text()
        assert not window._user_enabled
    finally:
        window.close()


def test_closing_the_window_stops_the_preview_source(qapp):
    camera = _FakeSdkCamera()
    window = gui.LiveViewWindow(camera)
    assert camera.started.wait(2.0)
    window.close()
    assert camera.stopped.wait(2.0)


def _disc_jpeg() -> bytes:
    img = QImage(320, 240, QImage.Format.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    painter = QPainter(img)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(110, 70, 100, 100)
    painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.ReadWrite)
    img.save(buf, "JPEG")
    return bytes(buf.data())


def test_the_window_renders_a_frame_with_every_tool_on(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        for box in (window._peaking_box, window._loupe_box, window._histogram_box, window._crosshair_box):
            box.setChecked(True)

        window._on_frame(_disc_jpeg())
        window._poll_frame()

        assert window._last_image is not None
        assert window._focus_graph.scores and window._focus_graph.scores[-1] > 0
        assert window._histogram._bins is not None
        assert window._loupe._pixmap is not None
        assert not window._image_label.pixmap().isNull()

        # At 5x the view is the 64 x 48 pixels at the centre of the 320 x 240 frame
        window._zoom_combo.setCurrentText("5x")
        assert window._shown_rect.getRect() == (128, 96, 64, 48)
        # A click on its top-left corner moves the zoom centre there
        window._on_image_clicked(0.0, 0.0)
        assert (window._zoom_centre.x(), window._zoom_centre.y()) == pytest.approx((0.4, 0.4))
    finally:
        window.close()


def test_the_tool_boxes_show_and_hide_their_widgets(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        assert window._crosshair_box.isChecked()
        assert not window._peaking_colour_combo.isEnabled()
        window._peaking_box.setChecked(True)
        assert window._peaking_colour_combo.isEnabled()
        window._loupe_box.setChecked(True)
        assert not window._loupe.isHidden()
        window._loupe_box.setChecked(False)
        assert window._loupe.isHidden()
    finally:
        window.close()
