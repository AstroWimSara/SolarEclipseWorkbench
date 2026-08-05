"""Slippy-map widget showing the observing site on OpenStreetMap tiles.

Tiles are fetched in the background and cached on disk, so a site that was
looked at once stays visible without a network connection.
"""

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from solareclipseworkbench.constants import EARTH_RADIUS

logger = logging.getLogger(__name__)

TILE_SIZE = 256
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "SolarEclipseWorkbench/1.0 (https://github.com/mrosseel/SolarEclipseWorkbench)"
CACHE_DIR = Path.home() / ".sew_tile_cache"

MIN_ZOOM = 2
MAX_ZOOM = 19
DEFAULT_ZOOM = 14

# Metres per pixel at the equator, zoom 0.
EQUATOR_METRES = 40075016.686


def deg2num(longitude: float, latitude: float, zoom: int) -> Tuple[float, float]:
    """Return the fractional tile coordinates of a position at the given zoom level."""

    n = 2.0 ** zoom
    lat_rad = math.radians(max(min(latitude, 85.05112878), -85.05112878))
    x = (longitude + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def distance_metres(longitude1: float, latitude1: float,
                    longitude2: float, latitude2: float) -> float:
    """Great-circle distance between two positions [degrees], in metres."""

    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(longitude2 - longitude1)
    a = (math.sin(d_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 2 * EARTH_RADIUS * math.asin(math.sqrt(a))


def num2deg(x: float, y: float, zoom: int) -> Tuple[float, float]:
    """Return the (longitude, latitude) of fractional tile coordinates."""

    n = 2.0 ** zoom
    longitude = x / n * 360.0 - 180.0
    latitude = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return longitude, latitude


class _TileFetcher(QObject):
    """Downloads tiles off the GUI thread and hands them back through a signal."""

    tile_ready = pyqtSignal(int, int, int, bytes)

    def __init__(self):
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._pending = set()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def request(self, zoom: int, x: int, y: int) -> None:
        key = (zoom, x, y)
        if key in self._pending:
            return
        self._pending.add(key)
        self._pool.submit(self._fetch, zoom, x, y)

    def _fetch(self, zoom: int, x: int, y: int) -> None:
        try:
            path = CACHE_DIR / str(zoom) / str(x) / f"{y}.png"
            if path.exists():
                self.tile_ready.emit(zoom, x, y, path.read_bytes())
                return

            response = self._session.get(TILE_URL.format(z=zoom, x=x, y=y), timeout=10)
            response.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            self.tile_ready.emit(zoom, x, y, response.content)
        except Exception as exc:
            logger.debug(f"Could not load map tile {zoom}/{x}/{y}: {exc}")
        finally:
            self._pending.discard((zoom, x, y))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)


class TileMap(QWidget):
    """Map of the observing site, with a crosshair marker and a scale bar.

    Scroll or use +/- to zoom, drag to look around, and double-click to pick a
    different spot: the site is rarely the address that was geocoded, and the
    field it is actually in is visible on the map.
    """

    zoom_changed = pyqtSignal(int)

    #: A spot the user double-clicked, as (longitude, latitude) in degrees.  The
    #: map does not move the marker itself: whoever owns the coordinates decides
    #: whether to accept the pick.
    location_picked = pyqtSignal(float, float)

    def __init__(self, parent=None, zoom: int = DEFAULT_ZOOM):
        super().__init__(parent)

        self._zoom = zoom
        self._longitude: Optional[float] = None
        self._latitude: Optional[float] = None
        # Where the view is centred, which is the marker until the map is dragged.
        self._centre_longitude: Optional[float] = None
        self._centre_latitude: Optional[float] = None
        self._drag_origin: Optional[QPoint] = None
        self._tiles: Dict[Tuple[int, int, int], QPixmap] = {}
        self._label = ""

        self._fetcher = _TileFetcher()
        self._fetcher.tile_ready.connect(self._on_tile_ready)

        self.setMinimumHeight(300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_location(self, longitude: float, latitude: float, label: str = "") -> None:
        """Put the marker at the given position [degrees] and centre the view on it."""

        self._longitude = longitude
        self._latitude = latitude
        self._centre_longitude = longitude
        self._centre_latitude = latitude
        self._label = label
        self.update()

    def centre_on_marker(self) -> None:
        """Bring the marker back into view after the map has been dragged away."""

        self._centre_longitude = self._longitude
        self._centre_latitude = self._latitude
        self.update()

    def position_at(self, point: QPoint) -> Optional[Tuple[float, float]]:
        """The (longitude, latitude) under a widget pixel, or None with no location set."""

        if self._centre_longitude is None or self._centre_latitude is None:
            return None

        centre_x, centre_y = deg2num(self._centre_longitude, self._centre_latitude, self._zoom)
        x = centre_x + (point.x() - self.width() / 2.0) / TILE_SIZE
        y = centre_y + (point.y() - self.height() / 2.0) / TILE_SIZE
        return num2deg(x, y, self._zoom)

    def set_zoom(self, zoom: int) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self.zoom_changed.emit(zoom)
        self.update()

    def zoom(self) -> int:
        return self._zoom

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self._zoom + (1 if steps > 0 else -1))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and self._centre_longitude is not None:
            here = event.position().toPoint()
            delta = here - self._drag_origin
            self._drag_origin = here

            centre_x, centre_y = deg2num(self._centre_longitude, self._centre_latitude, self._zoom)
            self._centre_longitude, self._centre_latitude = num2deg(
                centre_x - delta.x() / TILE_SIZE, centre_y - delta.y() / TILE_SIZE, self._zoom)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            picked = self.position_at(event.position().toPoint())
            if picked is not None:
                self.location_picked.emit(*picked)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_zoom(self._zoom + 1)
        elif event.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.set_zoom(self._zoom - 1)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._fetcher.shutdown()
        super().closeEvent(event)

    def _on_tile_ready(self, zoom: int, x: int, y: int, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self._tiles[(zoom, x, y)] = pixmap
            if zoom == self._zoom:
                self.update()

    def _tile(self, zoom: int, x: int, y: int) -> Optional[QPixmap]:
        """Return a cached tile, requesting it from the network when it is missing."""

        key = (zoom, x, y)
        if key not in self._tiles:
            self._fetcher.request(zoom, x, y)
            return None
        return self._tiles[key]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#dfe6ec"))

        if self._longitude is None or self._latitude is None:
            painter.setPen(QColor("#555555"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No location set")
            return

        self._draw_tiles(painter)
        self._draw_marker(painter)
        self._draw_scale_bar(painter)
        self._draw_overlay_text(painter)

    def _draw_tiles(self, painter: QPainter) -> None:
        width, height = self.width(), self.height()
        n = 2 ** self._zoom

        centre_x, centre_y = deg2num(self._centre_longitude, self._centre_latitude, self._zoom)
        left = centre_x * TILE_SIZE - width / 2.0
        top = centre_y * TILE_SIZE - height / 2.0

        first_x = math.floor(left / TILE_SIZE)
        first_y = math.floor(top / TILE_SIZE)
        last_x = math.floor((left + width) / TILE_SIZE)
        last_y = math.floor((top + height) / TILE_SIZE)

        missing = False
        for tile_x in range(first_x, last_x + 1):
            for tile_y in range(first_y, last_y + 1):
                if tile_y < 0 or tile_y >= n:
                    continue
                target = QRect(int(tile_x * TILE_SIZE - left), int(tile_y * TILE_SIZE - top),
                               TILE_SIZE, TILE_SIZE)
                pixmap = self._tile(self._zoom, tile_x % n, tile_y)
                if pixmap is None:
                    missing = True
                    continue
                painter.drawPixmap(target, pixmap)

        if missing:
            painter.setPen(QColor("#777777"))
            painter.drawText(QRect(0, 0, width, 20), Qt.AlignmentFlag.AlignCenter,
                             "loading map tiles…")

    def _marker_point(self) -> QPoint:
        """Where the marker sits on screen, which is the centre until the map is dragged."""

        centre_x, centre_y = deg2num(self._centre_longitude, self._centre_latitude, self._zoom)
        marker_x, marker_y = deg2num(self._longitude, self._latitude, self._zoom)
        return QPoint(int(self.width() / 2 + (marker_x - centre_x) * TILE_SIZE),
                      int(self.height() / 2 + (marker_y - centre_y) * TILE_SIZE))

    def _draw_marker(self, painter: QPainter) -> None:
        marker = self._marker_point()

        painter.setPen(QPen(QColor(255, 255, 255, 200), 3))
        painter.drawLine(marker.x() - 20, marker.y(), marker.x() + 20, marker.y())
        painter.drawLine(marker.x(), marker.y() - 20, marker.x(), marker.y() + 20)

        painter.setPen(QPen(QColor("#d00000"), 1.5))
        painter.drawLine(marker.x() - 20, marker.y(), marker.x() + 20, marker.y())
        painter.drawLine(marker.x(), marker.y() - 20, marker.x(), marker.y() + 20)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(marker, 8, 8)

        if not self.rect().contains(marker):
            painter.setPen(QColor("#d00000"))
            painter.drawText(QRect(0, self.height() // 2 - 10, self.width(), 20),
                             Qt.AlignmentFlag.AlignCenter, "the marker is off this view")

    def _draw_scale_bar(self, painter: QPainter) -> None:
        """Draw a bar whose length is a round number of metres at this latitude."""

        metres_per_pixel = (EQUATOR_METRES * math.cos(math.radians(self._centre_latitude)) /
                            (TILE_SIZE * 2 ** self._zoom))

        for metres in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000):
            pixels = metres / metres_per_pixel
            if pixels >= 80:
                break

        text = f"{metres} m" if metres < 1000 else f"{metres // 1000} km"
        x0, y0 = 12, self.height() - 16

        painter.setPen(QPen(QColor(255, 255, 255, 220), 4))
        painter.drawLine(x0, y0, x0 + int(pixels), y0)
        painter.setPen(QPen(QColor("#202020"), 2))
        painter.drawLine(x0, y0, x0 + int(pixels), y0)
        painter.drawLine(x0, y0 - 4, x0, y0 + 4)
        painter.drawLine(x0 + int(pixels), y0 - 4, x0 + int(pixels), y0 + 4)
        painter.drawText(x0 + int(pixels) + 6, y0 + 4, text)

    def _draw_overlay_text(self, painter: QPainter) -> None:
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)

        lines = [f"{abs(self._latitude):.5f}° {'N' if self._latitude >= 0 else 'S'}   "
                 f"{abs(self._longitude):.5f}° {'E' if self._longitude >= 0 else 'W'}",
                 f"zoom {self._zoom} — scroll to zoom, drag to move, double-click to re-pin"]
        if self._label:
            lines.insert(0, self._label)

        metrics = painter.fontMetrics()
        width = max(metrics.horizontalAdvance(line) for line in lines) + 14
        box = QRect(8, 8, min(width, self.width() - 16), 16 * len(lines) + 8)
        painter.fillRect(box, QColor(255, 255, 255, 200))
        painter.setPen(QColor("#202020"))
        for index, line in enumerate(lines):
            painter.drawText(box.adjusted(6, 4 + index * 16, -4, 0), Qt.AlignmentFlag.AlignTop, line)

        attribution = "© OpenStreetMap contributors"
        rect = QRect(self.width() - metrics.horizontalAdvance(attribution) - 12, self.height() - 34,
                     metrics.horizontalAdvance(attribution) + 8, 16)
        painter.fillRect(rect, QColor(255, 255, 255, 190))
        painter.setPen(QColor("#404040"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, attribution)
