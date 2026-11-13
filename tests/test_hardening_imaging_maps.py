"""Hardening of the imaging slice: the maps work offline and with a damaged tile cache."""

import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import tile_map


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _png() -> bytes:
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


class _Response:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


def _fetch(monkeypatch, tmp_path, answer: bytes):
    monkeypatch.setattr(tile_map, "CACHE_DIR", tmp_path)
    fetcher = tile_map._TileFetcher()
    ready, failed, asked = [], [], []
    fetcher.tile_ready.connect(lambda *args: ready.append(args))
    fetcher.tile_failed.connect(lambda *args: failed.append(args))

    def get(url, timeout):
        asked.append(url)
        return _Response(answer)

    fetcher._session.get = get
    fetcher._fetch(5, 1, 2)
    fetcher.shutdown()
    return ready, failed, asked


def test_an_html_page_with_status_200_is_not_cached(app, monkeypatch, tmp_path):
    """A captive portal at the site answers every tile with its log-in page."""
    ready, failed, _ = _fetch(monkeypatch, tmp_path, b"<html>Log in to the hotel wifi</html>")
    assert not ready and failed
    assert not (tmp_path / "5" / "1" / "2.png").exists()


def test_a_damaged_cached_tile_is_fetched_again(app, monkeypatch, tmp_path):
    cached = tmp_path / "5" / "1" / "2.png"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(_png()[:20])            # cut short when the program stopped while writing it
    png = _png()
    ready, failed, asked = _fetch(monkeypatch, tmp_path, png)
    assert asked and ready and not failed
    assert cached.read_bytes() == png
    assert not list(cached.parent.glob("*.part"))


def test_a_tile_that_does_not_decode_counts_as_unavailable(app):
    widget = tile_map.TileMap()
    widget.set_location(4.7, 50.9)
    widget._on_tile_ready(widget.zoom(), 1, 2, b"\x89PNG\r\n\x1a\nnot really")
    assert (widget.zoom(), 1, 2) in widget._unavailable
    widget.close()


def test_path_map_opens_without_the_land_polygons(app, monkeypatch):
    """Offline on a fresh install, the land polygons cannot be downloaded: the location dialog must still open."""
    from solareclipseworkbench import path_map_ui

    def offline():
        raise ConnectionError("no network")

    monkeypatch.setattr(path_map_ui, "_land", offline)
    widget = path_map_ui.EclipsePathWidget()
    widget.set_eclipse_date(None)
    widget.plot_location(-5.85, 43.36, 230)
    assert widget.map.observer == (43.36, -5.85)
