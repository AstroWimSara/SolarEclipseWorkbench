"""LiveViewWindow shows a frame with the focus tools of live_view_tools."""

import threading

import pytest
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QPainter
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
