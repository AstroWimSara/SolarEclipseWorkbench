"""LiveViewWindow shows a frame with the focus tools of live_view_tools."""

import threading

import pytest
from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui


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


def test_frames_are_shared_with_the_phone_dashboard_only_when_asked(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        window._on_frame(_disc_jpeg())
        window._poll_frame()
        assert window.phone_frame() == (None, 0, None)

        window.share_with_phone = True
        window._on_frame(_disc_jpeg())
        window._poll_frame()
        jpeg, frame_id, age = window.phone_frame()
        assert jpeg[:2] == b"\xff\xd8" and frame_id == 1 and age < 5
        # The zoomed part is what the phone gets, like the window shows
        window._zoom_combo.setCurrentText("5x")
        window._on_frame(_disc_jpeg())
        window._poll_frame()
        jpeg, frame_id, _ = window.phone_frame()
        assert frame_id == 2 and QImage.fromData(jpeg).size().width() == 64

        assert window.phone_status() == "active"
        window.set_totality_paused(True)
        assert window.phone_status() == "paused"
    finally:
        window.close()


def test_the_phone_gets_the_histogram_and_loupe_also_when_they_are_off_here(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        window._loupe_box.setChecked(False)
        window._histogram_box.setChecked(False)
        window.share_with_phone = True
        window._on_frame(_disc_jpeg())
        window._poll_frame()

        tools, png = window.phone_tools()
        histogram = tools["histogram"]
        assert len(histogram["bins"]) == 128 and max(histogram["bins"]) == 1.0
        # Most of the frame is the black sky, and the white disc is in the top bins
        assert histogram["black"] > 50 and histogram["bins"][-1] > 0
        assert png[:4] == b"\x89PNG"
        assert QImage.fromData(png).width() == gui.live_view_tools.LoupeWidget.PATCH_PX
        assert tools["loupe"]["share"] == 1.0

        # A tap on the phone moves the loupe like a click in the window
        window.set_zoom_centre_from_phone(0.25, 0.75)
        assert (window._zoom_centre.x(), window._zoom_centre.y()) == pytest.approx((0.25, 0.75))
        window._on_frame(_disc_jpeg())
        window._poll_frame()
        assert window.phone_tools()[0]["loupe"]["x"] == pytest.approx(0.25)
    finally:
        window.close()


def test_the_keys_toggle_the_crosshair_and_the_loupe(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        assert window._crosshair_box.isChecked() and not window._loupe_box.isChecked()
        QTest.keyClick(window, Qt.Key.Key_C)
        assert not window._crosshair_box.isChecked()
        QTest.keyClick(window, Qt.Key.Key_L)
        assert window._loupe_box.isChecked() and not window._loupe.isHidden()
        # A key on a check box or a button goes on to the window
        QTest.keyClick(window._histogram_box, Qt.Key.Key_C)
        assert window._crosshair_box.isChecked()
        QTest.keyClick(window._toggle_btn, Qt.Key.Key_L)
        assert not window._loupe_box.isChecked()
        # Ctrl+C is not C
        QTest.keyClick(window, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert window._crosshair_box.isChecked()
    finally:
        window.close()


def test_a_combo_box_keeps_the_letter_keys(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        window._peaking_box.setChecked(True)
        # L selects "Low" in the sensitivity box, and does not turn on the loupe
        QTest.keyClick(window._peaking_sensitivity_combo, Qt.Key.Key_L)
        assert window._peaking_sensitivity_combo.currentData() == "low"
        assert not window._loupe_box.isChecked()
        # F selects "Fit" in the zoom box, and does not fill the screen
        window._zoom_combo.setCurrentText("5x")
        QTest.keyClick(window._zoom_combo, Qt.Key.Key_F)
        assert window._zoom_combo.currentText() == "Fit"
        assert not window.isFullScreen()
    finally:
        window.close()


def test_full_screen_with_the_keys_and_the_button(qapp, no_gphoto):
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        window.show()
        QTest.keyClick(window, Qt.Key.Key_F)
        assert window.isFullScreen()
        assert window._fullscreen_btn.text() == "Leave full screen"
        QTest.keyClick(window, Qt.Key.Key_F)
        assert not window.isFullScreen()

        window._fullscreen_btn.click()
        assert window.isFullScreen()
        QTest.keyClick(window, Qt.Key.Key_Escape)
        assert not window.isFullScreen()
        assert window._fullscreen_btn.text() == "Full screen"
        # Esc out of full screen does nothing
        QTest.keyClick(window, Qt.Key.Key_Escape)
        assert not window.isFullScreen() and window.isVisible()
    finally:
        window.close()


def test_the_window_shows_the_frame_rate(qapp, no_gphoto, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(gui.time, "monotonic", lambda: clock[0])
    window = gui.LiveViewWindow(_GphotoLike())
    try:
        window._poll_frame()
        assert window._fps_label.text() == "FPS: --"
        for _ in range(5):
            window._on_frame(_disc_jpeg())
            window._poll_frame()
            clock[0] += 0.5
        assert window._fps_label.text() == "FPS: 2.0"
        # No frames come: the rate goes away when the last frames leave the window
        clock[0] += 10.0
        window._poll_frame()
        assert window._fps_label.text() == "FPS: --"
    finally:
        window.close()
