"""Re-pinning the observing site by double-clicking the map.

The coordinates that come out of an address search are the address, not the
field the tripod stands in.  The map is the one place where that difference is
visible, so it is also where it gets corrected.
"""

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from solareclipseworkbench.location_ui import ConfigManager, LocationWidget, moved_location_name
from solareclipseworkbench.tile_map import TileMap, deg2num, distance_metres, num2deg

SITE = (-2.929, 41.764)


@pytest.fixture
def tile_map():
    widget = TileMap()
    widget.resize(800, 500)
    widget.set_location(*SITE)
    yield widget
    widget.close()


@pytest.fixture
def location_widget(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    widget = LocationWidget(ConfigManager())
    yield widget
    widget.close()


def _double_click(widget, point):
    widget.mouseDoubleClickEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, QPointF(point), QPointF(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def _drag(widget, start, end):
    for kind, point, button in ((QMouseEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton),
                                (QMouseEvent.Type.MouseMove, end, Qt.MouseButton.NoButton),
                                (QMouseEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton)):
        event = QMouseEvent(kind, QPointF(point), QPointF(point), button,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: widget.mousePressEvent,
         QMouseEvent.Type.MouseMove: widget.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[kind](event)


def test_projection_round_trips(tile_map):
    x, y = deg2num(*SITE, 14)
    longitude, latitude = num2deg(x, y, 14)

    assert longitude == pytest.approx(SITE[0], abs=1e-9)
    assert latitude == pytest.approx(SITE[1], abs=1e-9)


def test_the_centre_of_the_view_is_the_marker_until_it_is_dragged(tile_map):
    centre = QPoint(tile_map.width() // 2, tile_map.height() // 2)

    longitude, latitude = tile_map.position_at(centre)

    assert (longitude, latitude) == pytest.approx(SITE, abs=1e-9)


def test_a_double_click_reports_the_spot_under_the_cursor(tile_map):
    picked = []
    tile_map.location_picked.connect(lambda lon, lat: picked.append((lon, lat)))
    point = QPoint(tile_map.width() // 2 + 100, tile_map.height() // 2)

    _double_click(tile_map, point)

    assert len(picked) == 1
    longitude, latitude = picked[0]
    assert longitude > SITE[0], "a spot to the right of centre is further east"
    assert latitude == pytest.approx(SITE[1], abs=1e-9)
    # 100 px at zoom 14 is a few hundred metres, not a different valley.
    assert 100 < distance_metres(*SITE, longitude, latitude) < 2000


def test_dragging_moves_the_view_without_moving_the_marker(tile_map):
    _drag(tile_map, QPoint(400, 250), QPoint(300, 250))

    centre = tile_map.position_at(QPoint(tile_map.width() // 2, tile_map.height() // 2))
    assert centre[0] > SITE[0], "dragging left looks further east"
    # The site itself has not moved: it is simply drawn off to one side now.
    assert (tile_map._longitude, tile_map._latitude) == pytest.approx(SITE, abs=1e-9)
    assert tile_map._marker_point().x() < tile_map.width() // 2

    tile_map.centre_on_marker()
    assert tile_map.position_at(QPoint(tile_map.width() // 2,
                                       tile_map.height() // 2)) == pytest.approx(SITE, abs=1e-9)


def test_a_double_click_after_dragging_picks_where_it_was_clicked(tile_map):
    picked = []
    tile_map.location_picked.connect(lambda lon, lat: picked.append((lon, lat)))
    _drag(tile_map, QPoint(400, 250), QPoint(300, 250))

    _double_click(tile_map, QPoint(400, 250))

    longitude, latitude = picked[0]
    assert longitude == pytest.approx(tile_map.position_at(QPoint(400, 250))[0], abs=1e-9)
    assert longitude > SITE[0], "the pick follows the dragged view, not the old centre"


def test_a_tile_that_cannot_be_fetched_is_not_asked_for_again(tile_map):
    """Offline, every repaint would otherwise be another round of failing requests."""
    asked = []
    tile_map._fetcher.request = lambda zoom, x, y: asked.append((zoom, x, y))

    tile_map._tile(14, 8100, 6000)
    assert asked == [(14, 8100, 6000)]

    tile_map._on_tile_failed(14, 8100, 6000)
    tile_map._tile(14, 8100, 6000)
    assert len(asked) == 1, "a failed tile was requested again on the next paint"

    # Any change of view is a fresh chance that the network is back.
    tile_map.set_zoom(tile_map.zoom() + 1)
    tile_map.set_zoom(tile_map.zoom() - 1)
    tile_map._tile(14, 8100, 6000)
    assert len(asked) == 2


def test_picking_a_spot_works_without_any_tiles(tile_map):
    """The map may be blank in the field; the coordinates are still arithmetic."""
    picked = []
    tile_map.location_picked.connect(lambda lon, lat: picked.append((lon, lat)))
    tile_map._fetcher.request = lambda zoom, x, y: None
    tile_map._tiles.clear()

    _drag(tile_map, QPoint(400, 250), QPoint(350, 250))
    _double_click(tile_map, QPoint(400, 250))

    assert picked and picked[0] == pytest.approx(tile_map.position_at(QPoint(400, 250)), abs=1e-9)


def test_a_failed_elevation_lookup_keeps_the_altitude_that_is_there(location_widget):
    """Offline the old altitude is the only one there is, and beats sea level."""
    location_widget.altitude_edit.setText("1200")

    location_widget._on_elevation_error("no route to host")

    assert location_widget.altitude_edit.text() == "1200"


def test_an_empty_altitude_still_falls_back_to_sea_level(location_widget):
    location_widget.altitude_edit.clear()

    location_widget._on_elevation_error("no route to host")

    assert location_widget.altitude_edit.text() == "0.0"


def test_a_picked_spot_keeps_the_old_altitude_until_the_lookup_answers(location_widget):
    """Leaving a saved location empties the fields, which took the altitude with it."""
    lookups = []
    location_widget._start_elevation_lookup = lambda lat, lon: lookups.append((lat, lon))
    location_widget._config_manager.add_location("Calle Torrecilla", 41.764, -2.929, 1200.0)
    location_widget.reload_saved_locations()
    location_widget.location_combo.setCurrentText("Calle Torrecilla (Saved)")
    assert location_widget.altitude_edit.text() == "1200.0"

    location_widget.set_picked_location(-2.908787, 41.753340, name="Somewhere (moved)")

    assert location_widget.altitude_edit.text() == "1200.0", "the field went empty offline"
    assert lookups == [(41.753340, -2.908787)]
    assert location_widget.location_combo.currentText() == "Custom"
    assert location_widget.location_name_edit.text() == "Somewhere (moved)"


def test_a_moved_location_says_so_once(tile_map):
    assert moved_location_name("Calle Torrecilla") == "Calle Torrecilla (moved)"
    # Moving it twice must not stack suffixes.
    assert moved_location_name("Calle Torrecilla (moved)") == "Calle Torrecilla (moved)"
    assert moved_location_name("") == "Custom pin (moved)"
