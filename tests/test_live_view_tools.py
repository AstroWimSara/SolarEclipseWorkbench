"""The numbers behind the live view tools: Laplacian, focus score, peaking and histogram.

A wrong focus score makes a soft focus look like the best one.  The images are
synthetic, so no camera is needed.
"""

import numpy as np
import pytest
from PyQt6.QtCore import QPointF, QRect
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import live_view_tools as tools


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _image(grey: np.ndarray) -> QImage:
    """A QImage of a uint8 grey array."""
    grey = np.ascontiguousarray(grey, dtype=np.uint8)
    h, w = grey.shape
    return QImage(grey.data, w, h, w, QImage.Format.Format_Grayscale8).copy()


def _disc(size=64, radius=20, blur=0):
    """A white disc on black, with an edge `blur` pixels wide."""
    y, x = np.mgrid[:size, :size]
    r = np.hypot(x - size / 2, y - size / 2)
    if blur == 0:
        return np.where(r <= radius, 255, 0).astype(np.uint8)
    return (np.clip((radius + blur / 2 - r) / blur, 0, 1) * 255).astype(np.uint8)


def test_grey_pixels_round_trip():
    grey = np.arange(10 * 12, dtype=np.uint8).reshape(10, 12)
    np.testing.assert_array_equal(tools.grey_pixels(_image(grey)), grey)


def test_a_small_image_gives_no_laplacian():
    assert tools.laplacian(_image(np.zeros((4, 20), np.uint8))) is None


def test_the_laplacian_of_a_flat_image_is_zero():
    lap = tools.laplacian_of(np.full((10, 10), 128, np.uint8))
    assert lap.shape == (8, 8)
    assert not lap.any()


def test_the_laplacian_of_a_single_bright_pixel():
    grey = np.zeros((5, 5), np.uint8)
    grey[2, 2] = 255
    lap = tools.laplacian_of(grey)
    assert lap[1, 1] == -4 * 255
    assert lap[0, 1] == lap[1, 0] == lap[1, 2] == lap[2, 1] == 255
    assert lap[0, 0] == 0


def test_the_laplacian_does_not_overflow():
    grey = np.zeros((3, 3), np.uint8)
    grey[0, 1] = grey[2, 1] = grey[1, 0] = grey[1, 2] = 255
    assert tools.laplacian_of(grey)[0, 0] == 4 * 255


def test_a_sharp_disc_scores_higher_than_a_soft_one():
    sharp = tools.focus_score(tools.laplacian_of(_disc(blur=0)))
    soft = tools.focus_score(tools.laplacian_of(_disc(blur=6)))
    assert sharp > soft > 0


def test_peaking_marks_the_edge_and_not_the_flat_parts():
    lap = tools.laplacian_of(_disc(radius=20))
    mask = tools.peaking_mask(lap, tools.PEAKING_SENSITIVITY["normal"])
    assert mask.shape == (64, 64)
    assert mask.any()
    assert not mask[32, 32], "the flat centre of the disc is marked"
    assert not mask[0, 0] and not mask[2, 2], "the black sky is marked"
    assert mask[32, 32 + 20] or mask[32, 32 + 19] or mask[32, 32 + 21], "the limb is not marked"
    assert not mask[0, :].any() and not mask[:, -1].any(), "the border has no Laplacian"


def test_a_higher_sensitivity_marks_more_pixels():
    lap = tools.laplacian_of(_disc(blur=4))
    counts = [tools.peaking_mask(lap, tools.PEAKING_SENSITIVITY[name]).sum()
              for name in ("low", "normal", "high")]
    assert counts[0] < counts[1] < counts[2]


def test_the_overlay_has_the_peaking_colour_on_the_edges_only(qapp):
    lap = tools.laplacian_of(_disc())
    colour = QColor(0, 255, 255, 200)
    overlay = tools.peaking_overlay(lap, colour, 30)
    mask = tools.peaking_mask(lap, 30)
    y, x = np.argwhere(mask)[0]
    assert overlay.pixelColor(int(x), int(y)).getRgb() == (0, 255, 255, 200)
    assert overlay.pixelColor(0, 0).alpha() == 0


def test_paint_peaking_keeps_the_size(qapp):
    img = _image(_disc())
    out = tools.paint_peaking(img, tools.laplacian(img), tools.PEAKING_COLOURS["red"], 30)
    assert (out.width(), out.height()) == (64, 64)


def test_the_histogram_counts_clipped_and_black_pixels():
    grey = np.zeros((10, 10), np.uint8)
    grey[0, :] = 255        # 10 % clipped
    grey[1, :5] = 250       # 5 % more clipped
    grey[2, :] = 128
    bins, clipped, black = tools.luminance_histogram(grey)
    assert bins.sum() == 100
    assert clipped == pytest.approx(15.0)
    assert black == pytest.approx(75.0)


def test_the_crop_stays_inside_the_image():
    rect = tools.crop_rect(100, 80, QPointF(1.0, 0.0), 20, 20)
    assert rect == QRect(80, 0, 20, 20)
    rect = tools.crop_rect(100, 80, QPointF(0.5, 0.5), 20, 20)
    assert rect == QRect(40, 30, 20, 20)


def test_a_click_on_a_zoomed_view_maps_to_the_full_frame():
    shown = QRect(100, 50, 200, 100)
    centre = tools.click_to_source(0.5, 0.5, shown, 400, 200)
    assert (centre.x(), centre.y()) == pytest.approx((0.5, 0.5))
    corner = tools.click_to_source(0.0, 1.0, shown, 400, 200)
    assert (corner.x(), corner.y()) == pytest.approx((0.25, 0.75))


def test_the_focus_graph_keeps_the_peak_and_a_limited_history(qapp):
    graph = tools.FocusScoreGraph()
    for score in range(tools.FocusScoreGraph.HISTORY + 10):
        graph.set_score(float(score))
    assert len(graph.scores) == tools.FocusScoreGraph.HISTORY
    assert graph.peak == tools.FocusScoreGraph.HISTORY + 9
    graph.reset()
    assert graph.scores == [] and graph.peak == 0.0


def test_the_frame_rate_of_frames_at_known_times():
    rate = tools.FrameRate(window_s=5.0)
    assert rate.rate(0.0) is None
    rate.add(0.0)
    assert rate.rate(0.0) is None, "one frame has no rate"
    for t in (0.5, 1.0, 1.5, 2.0):
        rate.add(t)
    assert rate.rate(2.0) == pytest.approx(2.0)


def test_the_frame_rate_follows_a_change_and_stops_with_the_frames():
    rate = tools.FrameRate(window_s=5.0)
    for i in range(20):
        rate.add(i * 0.1)
    assert rate.rate(1.9) == pytest.approx(10.0)
    # One frame per second from t = 2 s: the frames of the first two seconds leave the window
    for t in range(2, 12):
        rate.add(float(t))
    assert rate.rate(11.0) == pytest.approx(1.0)
    # No frames after t = 11 s: the last frames leave the window, and the rate goes away
    assert rate.rate(14.5) == pytest.approx(1.0)
    assert rate.rate(15.5) is None


def test_the_crosshair_leaves_the_centre_open(qapp):
    pixmap = QPixmap(200, 200)
    pixmap.fill(QColor(0, 0, 0))
    tools.draw_crosshair(pixmap)
    img = pixmap.toImage()
    assert img.pixelColor(100, 100).lightness() == 0, "the gap is covered"
    assert img.pixelColor(100, 10).lightness() > 0, "no vertical line"
    assert img.pixelColor(10, 100).lightness() > 0, "no horizontal line"
