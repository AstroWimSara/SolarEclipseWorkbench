"""Focus and framing tools for the live view window.

The tools work on the JPEG frames that any camera gives for live view: a
gphoto2 camera, a camera driven through a vendor SDK, or the virtual camera.

- Focus peaking: the pixels on a sharp edge get a colour.  The edges come from a
  Laplacian of the grey frame.
- Focus score: the mean absolute Laplacian of the frame.  A sharper image gives
  a higher score.  A graph shows the recent scores and the highest one.
- Loupe: a small part of the frame at its own pixels, magnified without
  smoothing.
- Histogram: the luminance of the frame, with the part that is clipped and the
  part that is black.
- Crosshair: lines with a gap and a ring at the centre of the frame, so the
  Sun can be centred in the ring.
- Frame rate: the number of frames per second that the window shows.

The calculations are functions without Qt widgets, so a test can check them on
a synthetic image.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

# ----------------------------------------------------------------------
# Focus peaking and focus score
# ----------------------------------------------------------------------

#: Colours for focus peaking.  Red is the default.  A filtered Sun or a Sun near
#: the horizon can be red itself, so the other colours are also available.
PEAKING_COLOURS = {
    "red": QColor(255, 0, 0, 180),
    "cyan": QColor(0, 255, 255, 200),
    "yellow": QColor(255, 255, 0, 200),
    "white": QColor(255, 255, 255, 220),
}
DEFAULT_PEAKING_COLOUR = "red"

#: The absolute Laplacian that a pixel must exceed to get the peaking colour.
#: A lower threshold shows more edges.  This finds the limb of a filtered disc
#: with low contrast.  A higher threshold shows only the strongest edges.
PEAKING_SENSITIVITY = {"high": 12, "normal": 30, "low": 60}
DEFAULT_PEAKING_SENSITIVITY = "normal"

#: The smallest image that the tools work on, in pixels per side.
MIN_SIDE_PX = 8


def grey_pixels(img: QImage) -> Optional[np.ndarray]:
    """The grey values of an image as a (height, width) uint8 array.

    Returns None for an image smaller than MIN_SIDE_PX on a side.
    """
    w, h = img.width(), img.height()
    if w < MIN_SIDE_PX or h < MIN_SIDE_PX:
        return None
    grey = img.convertToFormat(QImage.Format.Format_Grayscale8)
    ptr = grey.bits()
    ptr.setsize(grey.bytesPerLine() * h)
    # Copy the pixels: the buffer belongs to `grey`, which is freed on return.
    rows = np.frombuffer(ptr, dtype=np.uint8).reshape(h, grey.bytesPerLine())
    return rows[:, :w].copy()


def laplacian_of(grey: np.ndarray) -> np.ndarray:
    """The 4-neighbour Laplacian of a grey array, without the border pixels.

    The result is (height - 2, width - 2).  int16 holds the full range, from
    -1020 to +1020.
    """
    g = grey.astype(np.int16)
    return (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
            - 4 * g[1:-1, 1:-1])


def laplacian(img: QImage) -> Optional[np.ndarray]:
    """The Laplacian of an image, or None when the image is too small."""
    grey = grey_pixels(img)
    return None if grey is None else laplacian_of(grey)


def focus_score(lap: np.ndarray) -> float:
    """The mean absolute Laplacian.  A sharper image gives a higher score."""
    return float(np.mean(np.abs(lap)))


def peaking_mask(lap: np.ndarray, threshold: int) -> np.ndarray:
    """True for each pixel of the full image that is on an edge.

    The border pixels have no Laplacian, so they are always False.
    """
    h, w = lap.shape[0] + 2, lap.shape[1] + 2
    mask = np.zeros((h, w), dtype=bool)
    mask[1:-1, 1:-1] = np.abs(lap) > threshold
    return mask


def peaking_overlay(lap: np.ndarray, colour: QColor, threshold: int) -> QImage:
    """A transparent image with the edge pixels in the peaking colour."""
    mask = peaking_mask(lap, threshold)
    h, w = mask.shape
    overlay = np.zeros((h, w, 4), dtype=np.uint8)
    overlay[mask] = (colour.red(), colour.green(), colour.blue(), colour.alpha())
    return QImage(overlay.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


def paint_peaking(img: QImage, lap: np.ndarray, colour: QColor, threshold: int) -> QImage:
    """A copy of the image with the edge pixels painted in the peaking colour."""
    out = img.convertToFormat(QImage.Format.Format_RGB32)
    painter = QPainter(out)
    painter.drawImage(0, 0, peaking_overlay(lap, colour, threshold))
    painter.end()
    return out


# ----------------------------------------------------------------------
# Histogram
# ----------------------------------------------------------------------

#: A pixel at this grey value or above counts as clipped.  The tone curve of
#: the JPEG makes the top of the range round off before 255, so 255 alone shows
#: a clipped disc too late.
CLIPPED_FROM = 250

#: A pixel below this grey value counts as black.
BLACK_BELOW = 6


def luminance_histogram(grey: np.ndarray) -> tuple[np.ndarray, float, float]:
    """The 256 bins of a grey array, and the percentage clipped and black."""
    bins = np.bincount(grey.reshape(-1), minlength=256).astype(float)
    total = float(grey.size) or 1.0
    clipped = 100.0 * bins[CLIPPED_FROM:].sum() / total
    black = 100.0 * bins[:BLACK_BELOW].sum() / total
    return bins, clipped, black


def histogram_summary(bins: np.ndarray, columns: int = 128) -> list[float]:
    """The histogram on a log scale in *columns* columns from 0 to 1, as the widget draws it.

    Each column is the highest bin it covers, so a narrow peak (the disc) is not averaged away.
    """
    log_bins = np.log1p(np.asarray(bins, dtype=float))
    peak = log_bins.max() or 1.0
    edges = np.linspace(0, len(log_bins), columns + 1).astype(int)
    return [round(float(log_bins[lo:max(lo + 1, hi)].max() / peak), 3) for lo, hi in zip(edges[:-1], edges[1:])]


class HistogramWidget(QWidget):
    """The luminance histogram of the preview, on a log scale.

    The histogram is of the JPEG that the camera sends for live view, not of
    the RAW file.  The JPEG has a tone curve, so the RAW can have more room in
    the highlights than this shows.  Through a solar filter the disc is the
    only bright object, so the top of the histogram is the disc.
    """

    _HEIGHT = 74

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(self._HEIGHT)
        self.setMinimumWidth(200)
        self._bins: Optional[np.ndarray] = None
        self._clipped = 0.0
        self._black = 0.0

    def set_image(self, img: QImage) -> None:
        grey = grey_pixels(img)
        if grey is None:
            return
        self._bins, self._clipped, self._black = luminance_histogram(grey)
        self.update()

    def clear(self) -> None:
        self._bins = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 24))
        w, h = self.width(), self.height()
        if self._bins is None or w < 16:
            painter.setPen(QColor(120, 120, 130))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Histogram: no frame")
            painter.end()
            return

        # A log scale, because the disc is a small part of a black frame.  On a
        # linear scale the black peak hides the disc.
        bins = np.log1p(self._bins)
        peak = bins.max() or 1.0
        base = h - 18
        painter.setPen(QColor(210, 210, 220))
        for x in range(w):
            lo = x * 256 // w
            hi = max(lo + 1, (x + 1) * 256 // w)
            bar = int(bins[lo:hi].max() / peak * (base - 2))
            if bar > 0:
                painter.drawLine(x, base, x, base - bar)

        painter.setPen(QColor(90, 90, 100))
        painter.drawLine(0, base, w, base)
        painter.setPen(QColor(200, 80, 90) if self._clipped > 0.05 else QColor(150, 150, 160))
        painter.drawText(6, h - 4, f"clipped {self._clipped:.2f}%")
        painter.setPen(QColor(150, 150, 160))
        painter.drawText(w - 96, h - 4, f"black {self._black:.1f}%")
        painter.end()


# ----------------------------------------------------------------------
# Focus score graph
# ----------------------------------------------------------------------

class FocusScoreGraph(QWidget):
    """A line graph of the recent focus scores, with the highest score.

    The current score is green when it is within 5 % of the highest score,
    and yellow when it is not.
    """

    HISTORY = 200
    NEAR_PEAK = 0.95

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._scores: list[float] = []
        self._peak = 0.0
        self.setFixedHeight(36)
        self.setMinimumWidth(200)

    @property
    def scores(self) -> list[float]:
        return list(self._scores)

    @property
    def peak(self) -> float:
        return self._peak

    def set_score(self, score: float) -> None:
        self._scores.append(score)
        self._peak = max(self._peak, score)
        if len(self._scores) > self.HISTORY:
            self._scores.pop(0)
        self.update()

    def reset(self) -> None:
        self._scores.clear()
        self._peak = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(20, 20, 20))

        if len(self._scores) < 2 or self._peak <= 0:
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, "Focus score: --")
            painter.end()
            return

        text_w = 70
        graph_w = w - text_w - 4
        margin = 3
        graph_h = h - 2 * margin
        n = len(self._scores)

        painter.setPen(QPen(QColor(255, 60, 60, 100), 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, margin, graph_w, margin)

        painter.setPen(QPen(QColor(0, 200, 0), 1))
        step = graph_w / max(n - 1, 1)
        for i in range(1, n):
            y0 = int(h - margin - self._scores[i - 1] / self._peak * graph_h)
            y1 = int(h - margin - self._scores[i] / self._peak * graph_h)
            painter.drawLine(int((i - 1) * step), y0, int(i * step), y1)

        score = self._scores[-1]
        near_peak = score > self._peak * self.NEAR_PEAK
        painter.setPen(QColor(0, 255, 0) if near_peak else QColor(255, 200, 0))
        painter.drawText(graph_w + 4, 0, text_w, h // 2, Qt.AlignmentFlag.AlignVCenter, f"{score:.1f}")
        painter.setPen(QColor(255, 80, 80))
        painter.drawText(graph_w + 4, h // 2, text_w, h // 2, Qt.AlignmentFlag.AlignVCenter,
                         f"pk {self._peak:.1f}")
        painter.end()


# ----------------------------------------------------------------------
# Loupe
# ----------------------------------------------------------------------

def crop_rect(width: int, height: int, centre: QPointF, side_w: int, side_h: int) -> QRect:
    """A rectangle of side_w by side_h around a normalised centre, inside the image."""
    side_w = max(1, min(side_w, width))
    side_h = max(1, min(side_h, height))
    cx = int(centre.x() * width)
    cy = int(centre.y() * height)
    x = max(0, min(width - side_w, cx - side_w // 2))
    y = max(0, min(height - side_h, cy - side_h // 2))
    return QRect(x, y, side_w, side_h)


def loupe_patch(img: QImage, centre: QPointF, side_px: int = 96) -> tuple[Optional[QImage], Optional[float]]:
    """The part of the frame around the centre at its own pixels, and its focus score.

    Returns (None, None) when the frame is too small.
    """
    side = min(side_px, img.width(), img.height())
    if side < MIN_SIDE_PX:
        return None, None
    patch = img.copy(crop_rect(img.width(), img.height(), centre, side, side))
    lap = laplacian(patch)
    return patch, (None if lap is None else focus_score(lap))


class LoupeWidget(QWidget):
    """A part of the frame at its own pixels, magnified without smoothing.

    The preview is scaled down to fit the window.  A scaled-down soft edge and
    a scaled-down sharp edge look almost the same.  The loupe shows a small
    part of the frame without that scaling, so the sharpness of an edge can be
    judged.  The magnification uses the nearest pixel, because smoothing makes
    an edge look softer than it is.

    The part is around the zoom centre: click the limb in the preview to show
    the limb in the loupe.  The score is of this part only.
    """

    #: The side of the part of the frame, in frame pixels.
    PATCH_PX = 96

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._score: Optional[float] = None
        self._peak = 0.0
        self.setFixedSize(180, 180)
        self.setToolTip("The part of the frame at the zoom centre, at its own pixels and magnified "
                        "without smoothing.  Click the preview to move it.")

    def reset(self) -> None:
        self._pixmap = None
        self._score = None
        self._peak = 0.0
        self.update()

    def set_image(self, img: QImage, centre: QPointF) -> None:
        """Take the part of the frame around the centre, and its focus score."""
        patch, score = loupe_patch(img, centre, self.PATCH_PX)
        if patch is None:
            return
        view = min(self.width(), self.height()) - 2
        self._pixmap = QPixmap.fromImage(patch).scaled(
            view, view, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        self._score = score
        if score is not None:
            self._peak = max(self._peak, score)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), QColor(20, 20, 20))
        if self._pixmap is None:
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(0, 0, self.width(), self.height(), Qt.AlignmentFlag.AlignCenter, "Loupe")
            painter.end()
            return

        x = (self.width() - self._pixmap.width()) // 2
        y = (self.height() - self._pixmap.height()) // 2
        painter.drawPixmap(x, y, self._pixmap)

        if self._score is not None:
            # The score as a part of the highest score of this patch, so the
            # direction of the focus change is clear.
            share = self._score / self._peak if self._peak > 0 else 0.0
            painter.fillRect(0, self.height() - 16, self.width(), 16, QColor(0, 0, 0, 150))
            painter.setPen(QColor(0, 255, 0) if share > FocusScoreGraph.NEAR_PEAK else QColor(255, 200, 0))
            painter.drawText(0, self.height() - 16, self.width(), 16, Qt.AlignmentFlag.AlignCenter,
                             f"{self._score:.1f}   {share * 100:.0f}% of best")
        painter.end()


# ----------------------------------------------------------------------
# Crosshair
# ----------------------------------------------------------------------

#: Half the width of the open gap at the centre of the crosshair, in pixels.
#: The lines do not cover the Sun that they centre.
CROSSHAIR_GAP_PX = 14

#: The radius of the ring around the gap, in pixels.  A disc is easier to
#: centre in a ring than on crossed lines.
CROSSHAIR_RING_PX = 34


def draw_crosshair(pixmap: QPixmap) -> None:
    """Draw the crosshair at the centre of the pixmap.

    Each line is drawn two times: a wide dark line, then a thin light line on
    it.  Thus the crosshair shows on a black sky and on a white disc.
    """
    width, height = pixmap.width(), pixmap.height()
    if width <= 0 or height <= 0:
        return
    cx, cy = width // 2, height // 2
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for colour, thickness in ((QColor(0, 0, 0, 160), 3), (QColor(255, 255, 255, 220), 1)):
        painter.setPen(QPen(colour, thickness))
        painter.drawLine(0, cy, cx - CROSSHAIR_GAP_PX, cy)
        painter.drawLine(cx + CROSSHAIR_GAP_PX, cy, width, cy)
        painter.drawLine(cx, 0, cx, cy - CROSSHAIR_GAP_PX)
        painter.drawLine(cx, cy + CROSSHAIR_GAP_PX, cx, height)
        painter.drawEllipse(QPoint(cx, cy), CROSSHAIR_RING_PX, CROSSHAIR_RING_PX)
    painter.end()


# ----------------------------------------------------------------------
# Frame rate
# ----------------------------------------------------------------------

class FrameRate:
    """The frames per second of the last frames, from the times they arrived.

    The rate uses the frames of the last `window_s` seconds.  Thus it follows a
    change of rate, and it goes to None some seconds after the frames stop.
    """

    def __init__(self, window_s: float = 5.0):
        self._window_s = window_s
        self._times: deque = deque()

    def add(self, t: float) -> None:
        """Count a frame that arrived at time t [s]."""
        self._times.append(t)

    def rate(self, now: float) -> Optional[float]:
        """Frames per second at time now [s], or None with fewer than two frames in the window."""
        while self._times and now - self._times[0] > self._window_s:
            self._times.popleft()
        if len(self._times) < 2 or self._times[-1] <= self._times[0]:
            return None
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])


# ----------------------------------------------------------------------
# Click to set the zoom centre
# ----------------------------------------------------------------------

def click_to_source(nx: float, ny: float, shown: QRect, source_w: int, source_h: int) -> QPointF:
    """A click on the shown part of a frame, as a normalised point of the full frame.

    nx and ny are the click position in the shown pixmap, from 0 to 1.
    `shown` is the part of the frame that the pixmap shows.
    """
    sx = (shown.x() + nx * shown.width()) / max(1, source_w)
    sy = (shown.y() + ny * shown.height()) / max(1, source_h)
    return QPointF(min(1.0, max(0.0, sx)), min(1.0, max(0.0, sy)))


class ClickableImageLabel(QLabel):
    """A QLabel that sends the position of a left click on its pixmap.

    The position is normalised to the pixmap, from 0 to 1 on each axis.  A
    click outside the pixmap is moved to its nearest edge.
    """

    clicked = pyqtSignal(float, float)

    def mousePressEvent(self, event):
        pm = self.pixmap()
        if event.button() == Qt.MouseButton.LeftButton and pm is not None and not pm.isNull():
            x_off = (self.width() - pm.width()) / 2
            y_off = (self.height() - pm.height()) / 2
            nx = (event.position().x() - x_off) / max(1, pm.width())
            ny = (event.position().y() - y_off) / max(1, pm.height())
            self.clicked.emit(min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny)))
        super().mousePressEvent(event)
