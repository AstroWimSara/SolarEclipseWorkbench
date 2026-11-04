"""The eclipse path on the location map (#68, #81).

The path has to agree with the local circumstances the rest of the application uses: a point just inside a limit
sees totality, a point just outside does not, and the observer's distance from the centre line has to match the
duration of totality there.
"""

import datetime
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from solareclipseworkbench import eclipse_path as ep
from solareclipseworkbench import solar_eclipse as se

DATE_2024 = "2024-04-08"
DATE_2026 = "2026-08-12"
# Upcoming (the selector lists the eclipses from today on); Luxor is close to its centre line.
DATE_2027 = "2027-08-02"
LUXOR = (25.69, 32.64)


@pytest.fixture(scope="module")
def path_2024():
    return ep.compute_eclipse_path(DATE_2024)


@pytest.fixture(scope="module")
def path_2026():
    return ep.compute_eclipse_path(DATE_2026)


def _central_duration(lat, lon, date):
    r = se.get_local_circumstances(lat, lon, 0, date)
    if r["type"] not in ("Total", "Annular"):
        return 0.0
    return abs(r["ut_third_contact"] - r["ut_second_contact"]) * 3600


# --- Fixes in solar_eclipse -------------------------------------------------------------------------------------

def test_centre_line_duration_and_width_2024():
    """Greatest duration 2024-04-08 is 4m28s with a path ~198 km wide (NASA); before the fix it came out ~2m40s."""
    e = se.get_element_coeffs(DATE_2024)
    start, end = ep._central_time_range(e)
    samples = [se.compute_central_lat_lon_for_time(e, e["T0"] + start + (end - start) * k / 200)
               for k in range(1, 200)]
    longest = max(samples, key=lambda c: abs(c["duration"]))
    assert abs(longest["duration"]) == pytest.approx(268, abs=3)
    assert longest["width"] == pytest.approx(197, abs=4)
    assert longest["lat"] == pytest.approx(25.5, abs=1)
    assert longest["lon"] == pytest.approx(-104, abs=1.5)


def test_umbra_outline_has_the_umbral_radius():
    """Every outline point lies at |L2'| from the shadow axis (the correction used to be applied cumulatively)."""
    e = se.get_element_coeffs(DATE_2024)
    t = 0.3
    be = se.get_elements(e, t, 0, 0, 0)
    for q in range(0, 360, 45):
        p = se.compute_outline_point(be, q, umbra=True)
        o = se.get_elements(e, t, p["lat"], -p["lon"], 0)
        assert math.hypot(o["u"], o["v"]) == pytest.approx(abs(o["L2p"]), rel=1e-3)


# --- The path ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("date, eclipse_type, duration, width", [
    (DATE_2024, "T", 267, 196),
    (DATE_2026, "T", 137, 290),
    ("2027-08-02", "T", 382, 256),
    ("2023-10-14", "A", 320, 193),
])
def test_greatest_duration_on_the_centre_line(date, eclipse_type, duration, width):
    path = ep.compute_eclipse_path(date)
    assert path.eclipse_type == eclipse_type
    longest = max(path.central, key=lambda p: p.duration)
    assert longest.duration == pytest.approx(duration, abs=4)
    assert longest.width == pytest.approx(width, abs=5)


def test_partial_eclipse_has_no_path():
    path = ep.compute_eclipse_path("2025-03-29")
    assert path.is_empty
    assert ep.path_polygons(path) == []
    assert ep.locate_observer(path, 50.88, 4.70) is None
    assert "no path" in ep.describe_observer(path, None, "Partial", 0)


@pytest.mark.parametrize("date", [DATE_2024, DATE_2026])
def test_limits_agree_with_local_circumstances(date):
    """A few km inside a limit there is totality, a few km outside there is not."""
    path = ep.compute_eclipse_path(date)
    assert path.north and path.south
    north_mean = sum(p[0] for p in path.north) / len(path.north)
    south_mean = sum(p[0] for p in path.south) / len(path.south)
    assert north_mean > south_mean

    for limit in (path.north, path.south):
        for k in range(len(limit) // 10, len(limit) * 9 // 10, len(limit) // 6):
            lat, lon = limit[k]
            centre = min(path.central, key=lambda p: ep.haversine_km(lat, lon, p.lat, p.lon))
            # Step 3 km towards / away from the centre line, measured on the ground (matters near the pole).
            x, y = ep._local_xy(lat, lon, centre.lat, centre.lon)
            norm = math.hypot(x, y)
            dlat = math.degrees(3 * y / norm / ep.EARTH_RADIUS_KM)
            dlon = math.degrees(3 * x / norm / (ep.EARTH_RADIUS_KM * math.cos(math.radians(lat))))
            outside = _central_duration(lat - dlat, lon - dlon, date)
            inside = _central_duration(lat + dlat, lon + dlon, date)
            assert outside == 0.0, (lat, lon)
            assert inside > 0.0, (lat, lon)


def test_limits_reach_the_sunset_end(path_2026):
    """Valencia sees ~57 s of totality at sunset, so the southern limit must run on past it to the Balearic Sea."""
    assert max(p[1] for p in path_2026.south) > 1.5


def test_path_polygons_cover_the_path(path_2024):
    polygons = ep.path_polygons(path_2024)
    assert len(polygons) > 100
    for polygon in polygons:
        lons = [p[0] for p in polygon]
        assert max(lons) - min(lons) <= 180


# --- The observer -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, lat, lon, inside, side", [
    ("Oviedo", 43.36, -5.85, True, "north"),
    ("Valencia", 39.47, -0.38, True, "south"),
    ("Madrid", 40.42, -3.70, False, "south"),
    ("Reykjavik", 64.15, -21.94, True, "north"),
])
def test_observer_in_2026_path(path_2026, name, lat, lon, inside, side):
    where = ep.locate_observer(path_2026, lat, lon)
    assert where.inside is inside, name
    assert where.side == side, name
    # Duration off the centre line follows centre * sqrt(1 - (d / half width)^2) closely.
    expected = where.centre_duration_s * math.sqrt(max(0.0, 1 - (where.distance_km / where.half_width_km) ** 2))
    assert _central_duration(lat, lon, DATE_2026) == pytest.approx(expected, abs=4), name


def test_observer_distance_2024(path_2024):
    # Cleveland lies just south of the centre line, which crossed Lake Erie.
    where = ep.locate_observer(path_2024, 41.50, -81.69)
    assert where.side == "south"
    assert where.distance_km == pytest.approx(15.5, abs=2)
    assert where.inside


def test_describe_observer_inside_and_outside(path_2026):
    where = ep.locate_observer(path_2026, 43.36, -5.85)
    text = ep.describe_observer(path_2026, where, "Total", 107)
    assert "km north of the centre line" in text
    assert "Totality here: 1m47s" in text

    where = ep.locate_observer(path_2026, 40.42, -3.70)
    text = ep.describe_observer(path_2026, where, "Partial", 0)
    assert "outside the path" in text
    assert "no totality" in text


def test_split_at_dateline():
    runs = ep.split_at_dateline([(0, 170), (0, 179), (0, -179), (0, -170)])
    assert runs == [[(0, 170), (0, 179)], [(0, -179), (0, -170)]]


def test_format_duration():
    assert ep.format_duration(107.4) == "1m47s"
    assert ep.format_duration(59.6) == "1m00s"


# --- The widget -------------------------------------------------------------------------------------------------

def test_path_widget_shows_the_observer_summary():
    from PyQt6.QtWidgets import QApplication
    from solareclipseworkbench.path_map_ui import EclipsePathWidget

    _app = QApplication.instance() or QApplication([])
    widget = EclipsePathWidget()
    widget.set_eclipse_date(None)
    assert "Choose an eclipse" in widget.info.text()
    assert widget.eclipse_combobox.currentIndex() == -1

    widget.set_eclipse_date(DATE_2026)
    widget.plot_location(-5.85, 43.36, 230)
    assert "north of the centre line" in widget.info.text()
    assert "Totality here" in widget.info.text()
    # Zoomed to the path, not the whole world.
    x0, x1 = widget.map.ax.get_xlim()
    assert x1 - x0 < 300


def test_eclipse_choices_list_a_past_eclipse_first():
    """A past eclipse loaded from the settings is not upcoming, but must still be selectable on the map."""
    from solareclipseworkbench.path_map_ui import eclipse_choices

    choices = eclipse_choices(5, "%d/%m/%Y", include=DATE_2024)
    assert len(choices) == 6
    assert choices[0] == ("08/04/2024 - T - 4m 28s", DATE_2024)
    # Already upcoming: not listed twice.
    upcoming = eclipse_choices(5, "%d/%m/%Y")
    assert eclipse_choices(5, "%d/%m/%Y", include=upcoming[2][1]) == upcoming


def test_choosing_another_eclipse_redraws_the_path():
    from PyQt6.QtWidgets import QApplication
    from solareclipseworkbench.path_map_ui import EclipsePathWidget

    _app = QApplication.instance() or QApplication([])
    widget = EclipsePathWidget(date_format="%d/%m/%Y")
    widget.set_eclipse_date(DATE_2024)
    widget.plot_location(LUXOR[1], LUXOR[0], 80)
    assert widget.eclipse_combobox.currentData() == DATE_2024
    assert "outside the path" in widget.info.text()

    emitted = []
    widget.eclipse_changed.connect(emitted.append)
    widget.eclipse_combobox.setCurrentIndex(widget.eclipse_combobox.findData(DATE_2027))
    assert emitted == [DATE_2027]
    assert widget.selected_eclipse_date() == DATE_2027
    assert "Totality here" in widget.info.text()
    assert widget.map.path is widget.path and not widget.path.is_empty


@pytest.fixture
def controller(tmp_path, monkeypatch):
    import sys
    from PyQt6.QtWidgets import QApplication
    from solareclipseworkbench import gui

    _app = QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(gui.SolarEclipseController, "set_reference_moments", lambda self: None)
    ctrl = gui.SolarEclipseController(gui.SolarEclipseModel(), gui.SolarEclipseView(), is_simulator=False,
                                      low_cpu_mode=False)
    yield ctrl
    for timer in (ctrl.time_display_timer, ctrl._problem_timer, ctrl.visualization_timer):
        timer.stop()
    ctrl.view.deleteLater()


def _location_popup(controller, eclipse):
    from astropy.time import Time
    from solareclipseworkbench.gui import LocationPopup

    controller.model.set_eclipse_date(Time(eclipse))
    popup = LocationPopup(controller)
    popup.location_widget.set_coordinates(LUXOR[1], LUXOR[0], 80)
    return popup


def test_ok_in_the_location_window_takes_over_the_chosen_eclipse(controller):
    from solareclipseworkbench.gui import DATE_FORMATS

    popup = _location_popup(controller, DATE_2024)
    popup.location_plot.eclipse_combobox.setCurrentIndex(popup.location_plot.eclipse_combobox.findData(DATE_2027))
    popup.accept_location()

    assert controller.model.eclipse_date.strftime("%Y-%m-%d") == DATE_2027
    expected = datetime.datetime(2027, 8, 2).strftime(DATE_FORMATS[controller.view.date_format])
    assert controller.view.eclipse_date.text() == expected
    assert controller.model.latitude == pytest.approx(LUXOR[0])


def test_ok_without_changing_the_eclipse_keeps_the_date(controller):
    popup = _location_popup(controller, DATE_2024)
    label_before = controller.view.eclipse_date.text()
    popup.accept_location()
    assert controller.model.eclipse_date.strftime("%Y-%m-%d") == DATE_2024
    assert controller.view.eclipse_date.text() == label_before
