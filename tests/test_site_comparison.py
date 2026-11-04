"""Compare candidate sites: totality, Sun altitude, Baily's beads windows and cloud cover side by side."""

import datetime
import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from solareclipseworkbench import site_comparison
from solareclipseworkbench.location_ui import ConfigManager
from solareclipseworkbench.site_comparison import (ARCHIVE_URL, FORECAST_URL, CloudForecast, Site, SiteResult,
                                                   fetch_cloud_cover, forecast_source, format_comparison,
                                                   parse_cloud_cover, site_result)

UTC = datetime.timezone.utc
C2 = datetime.datetime(2027, 8, 2, 8, 45, 7, tzinfo=UTC)


def moment(time_utc, altitude=38.2, azimuth=95.0):
    return SimpleNamespace(time_utc=time_utc, time_local=time_utc.astimezone(datetime.timezone(datetime.timedelta(hours=2))),
                           apparent_altitude=altitude, azimuth=azimuth)


def total_moments(duration_s=279.9, mean_s=278.3, c3_status="solved"):
    c3 = C2 + datetime.timedelta(seconds=duration_s)
    moments = {
        "C1": moment(C2 - datetime.timedelta(hours=1)),
        "C2": moment(C2),
        "MAX": moment(C2 + datetime.timedelta(seconds=duration_s / 2)),
        "C3": moment(c3),
        "C4": moment(c3 + datetime.timedelta(hours=1)),
        "duration": datetime.timedelta(seconds=duration_s),
        "duration_mean": datetime.timedelta(seconds=mean_s),
        "BEADS_C2_STATUS": "solved",
        "BEADS_C2_START": moment(C2 - datetime.timedelta(seconds=1.9)),
        "BEADS_C2_END": moment(C2 + datetime.timedelta(seconds=4.6)),
        "BEADS_C3_STATUS": c3_status,
    }
    if c3_status == "solved":
        moments["BEADS_C3_START"] = moment(c3 - datetime.timedelta(seconds=0.8))
        moments["BEADS_C3_END"] = moment(c3 + datetime.timedelta(seconds=2.9))
    return moments


# ---------------------------------------------------------------------------
# Local circumstances
# ---------------------------------------------------------------------------

def test_site_result_of_a_total_eclipse():
    result = site_result(Site("Tarifa", -5.6, 36.0, 50), total_moments(), 1.0257, "Total")
    assert result.is_total and result.limb_corrected
    assert result.totality == datetime.timedelta(seconds=279.9)
    assert result.sun_altitude == pytest.approx(38.2)
    assert result.beads["C2"].start == pytest.approx(-1.9)
    assert result.beads["C2"].end == pytest.approx(4.6)
    assert result.beads["C2"].describe("C2") == "C2-1.9 s to C2+4.6 s (6.5 s)"
    assert result.beads["C3"].describe("C3") == "C3-0.8 s to C3+2.9 s (3.7 s)"


def test_unresolved_beads_window_and_no_limb_profile():
    moments = total_moments(c3_status="unresolved")
    result = site_result(Site("Edge", 0, 0, 0), moments, 1.0, "Total")
    assert result.beads["C3"].describe("C3") == "unresolved"

    for key in [k for k in moments if k.startswith("BEADS") or k == "duration_mean"]:
        del moments[key]
    result = site_result(Site("No limb", 0, 0, 0), moments, 1.0, "Total")
    assert not result.limb_corrected
    assert result.beads["C2"].describe("C2") == "-"


def test_partial_and_no_eclipse():
    moments = total_moments()
    partial = {k: moments[k] for k in ("C1", "MAX", "C4")}
    result = site_result(Site("North", 4.7, 50.9, 20), partial, 0.908, "Partial")
    assert not result.is_total
    assert result.sun_altitude is not None
    assert site_comparison.describe_totality(result) == "none (partial, mag. 0.908)"

    # The calculation can return a MAX without an eclipse: no Sun altitude is shown for it
    result = site_result(Site("Far", -104.7, 24.0, 1900), partial, 0, "No eclipse")
    assert result.sun_altitude is None
    assert site_comparison.describe_totality(result) == "no eclipse"


def test_compare_site_keeps_errors(monkeypatch):
    import solareclipseworkbench.reference_moments as reference_moments

    def broken(*args):
        raise ValueError("no ephemeris")
    monkeypatch.setattr(reference_moments, "calculate_reference_moments", broken)
    result = site_comparison.compare_site(Site("X", 0, 0, 0), "2027-08-02")
    assert result.error == "no ephemeris"


def test_format_comparison_puts_the_longest_totality_first():
    short = site_result(Site("Cadiz", -6.3, 36.5, 10), total_moments(250.0), 1.02, "Total")
    long = site_result(Site("Tarifa", -5.6, 36.0, 50), total_moments(279.9), 1.03, "Total")
    text = format_comparison([short, long], "2027-08-02", [CloudForecast(error="no forecast yet (from 2027-07-18)"),
                                                            CloudForecast(12, 5, 3, 10, source="forecast")])
    lines = text.splitlines()
    assert lines[4].startswith("Tarifa") and "4m39.9s" in lines[4] and "12% (low 5%, mid 3%, high 10%)" in lines[4]
    assert lines[5].startswith("Cadiz") and "(-29.9 s)" in lines[5] and "no forecast yet" in lines[5]
    assert "Open-Meteo forecast" in text


# ---------------------------------------------------------------------------
# Cloud cover
# ---------------------------------------------------------------------------

def test_forecast_source_by_date():
    today = datetime.date(2026, 11, 4)
    at = lambda day: datetime.datetime.combine(day, datetime.time(10), tzinfo=UTC)
    assert forecast_source(at(today + datetime.timedelta(days=15)), today)[0] == FORECAST_URL
    url, reason = forecast_source(at(datetime.date(2027, 8, 2)), today)
    assert url is None and reason == "no forecast yet (from 2027-07-18)"
    assert forecast_source(at(today - datetime.timedelta(days=5)), today)[0] == FORECAST_URL
    assert forecast_source(at(datetime.date(2026, 8, 12)), today) == (ARCHIVE_URL, "ERA5 archive")


def hourly(day="2027-08-02", total=None):
    total = total or [10 * h % 100 for h in range(24)]
    return {"hourly": {"time": [f"{day}T{h:02d}:00" for h in range(24)],
                       "cloud_cover": total, "cloud_cover_low": [0] * 24,
                       "cloud_cover_mid": [50] * 24, "cloud_cover_high": [None] * 24}}


def test_parse_cloud_cover_interpolates_to_the_moment():
    at = datetime.datetime(2027, 8, 2, 8, 45, tzinfo=UTC)          # between 08:00 (80%) and 09:00 (90%)
    forecast = parse_cloud_cover(hourly(), at, at - datetime.timedelta(hours=1), at + datetime.timedelta(hours=1),
                                 "forecast")
    assert forecast.total == pytest.approx(87.5)
    assert forecast.low == 0 and forecast.mid == 50 and forecast.high is None
    assert forecast.describe() == "88% (low 0%, mid 50%)"
    assert [t.hour for t, _ in forecast.hourly] == [7, 8, 9, 10]


def test_parse_cloud_cover_errors():
    at = datetime.datetime(2027, 8, 2, 8, 45, tzinfo=UTC)
    assert parse_cloud_cover({"error": True, "reason": "out of range"}, at).describe() == "out of range"
    assert parse_cloud_cover({"hourly": {}}, at).error == "no hourly data"
    assert parse_cloud_cover(hourly(day="2027-08-03"), at).error == "no cloud cover for this hour"


class FakeGet:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, url, params, timeout):
        self.calls.append((url, params))
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(json=lambda: answer)


def test_fetch_cloud_cover_requests_utc_hours_and_handles_failures():
    at = datetime.datetime(2027, 8, 2, 8, 45, tzinfo=UTC)
    get = FakeGet({FORECAST_URL: hourly()})
    forecast = fetch_cloud_cover(36.0, -5.6, at, today=datetime.date(2027, 7, 31), get=get)
    assert forecast.total == pytest.approx(87.5) and forecast.source == "forecast"
    url, params = get.calls[0]
    assert params["timezone"] == "UTC" and params["start_date"] == params["end_date"] == "2027-08-02"
    assert "cloud_cover_low" in params["hourly"]

    # Too far ahead: no request at all
    get = FakeGet({})
    assert fetch_cloud_cover(36.0, -5.6, at, today=datetime.date(2026, 11, 4), get=get).error.startswith("no forecast")
    assert get.calls == []

    get = FakeGet({FORECAST_URL: OSError("offline")})
    forecast = fetch_cloud_cover(36.0, -5.6, at, today=datetime.date(2027, 7, 31), get=get)
    assert forecast.error == "no connection (OSError)"


def test_a_past_day_without_forecast_falls_back_to_the_archive():
    at = datetime.datetime(2027, 8, 2, 8, 45, tzinfo=UTC)
    empty = hourly(total=[None] * 24)
    get = FakeGet({FORECAST_URL: empty, ARCHIVE_URL: hourly()})
    forecast = fetch_cloud_cover(36.0, -5.6, at, today=datetime.date(2027, 8, 4), get=get)
    assert forecast.source == "ERA5 archive" and forecast.total == pytest.approx(87.5)
    assert [url for url, _ in get.calls] == [FORECAST_URL, ARCHIVE_URL]


# ---------------------------------------------------------------------------
# Shortlist and window
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    manager = ConfigManager.__new__(ConfigManager)
    manager.config_file = tmp_path / "config.json"
    manager.config = manager._default_config()
    manager.add_location("Tarifa", 36.0, -5.6, 50)
    return manager


def test_candidate_sites_are_kept(config):
    assert config.get_candidate_sites() == []
    config.set_candidate_sites([Site("A", 1.5, 2.5, 3).to_dict()])
    reloaded = ConfigManager.__new__(ConfigManager)
    reloaded.config_file = config.config_file
    reloaded.config = reloaded._load_config()
    assert [Site.from_dict(d) for d in reloaded.get_candidate_sites()] == [Site("A", 1.5, 2.5, 3)]


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def wait_for(window):
    from PyQt6.QtWidgets import QApplication
    for _ in range(500):
        QApplication.processEvents()
        if not window._busy:
            QApplication.processEvents()
            return
        window._worker.wait(10)
    raise AssertionError("worker did not finish")


def test_window_compares_and_fetches(app, config, monkeypatch):
    from solareclipseworkbench import sites_ui

    durations = {"Current location": 250.0, "Tarifa": 279.9}
    monkeypatch.setattr(site_comparison, "compare_site",
                        lambda site, date: site_result(site, total_moments(durations[site.name]), 1.02, "Total"))
    monkeypatch.setattr(site_comparison, "fetch_cloud_cover_for",
                        lambda result: CloudForecast(70.0, 60, 10, 0, source="forecast"))
    used = []
    window = sites_ui.SiteComparisonWindow(lambda: ("2027-08-02", Site("Current location", -6.3, 36.5, 10)),
                                           used.append, config_manager=config)
    try:
        assert window.table.rowCount() == 1                 # starts with the current location
        window.saved_box.setCurrentText("Tarifa")
        window.add_saved_location()
        assert [d["name"] for d in config.get_candidate_sites()] == ["Current location", "Tarifa"]

        window.compare()
        wait_for(window)
        cell = lambda row, column: window.table.item(row, column).text()
        assert cell(1, sites_ui.COL_TOTALITY) == "4m39.9s"
        assert window.table.item(1, sites_ui.COL_TOTALITY).font().bold()
        assert cell(0, sites_ui.COL_TOTALITY) == "4m10.0s (-29.9 s)"
        assert cell(0, sites_ui.COL_BEADS_C2) == "C2-1.9 s to C2+4.6 s (6.5 s)"
        assert "Longest totality: Tarifa" in window.summary.text()

        window.fetch_forecasts()
        wait_for(window)
        assert cell(1, sites_ui.COL_CLOUDS) == "70% (low 60%, mid 10%, high 0%)"
        assert "Tarifa" in window.comparison_text().splitlines()[4]

        # Editing a coordinate clears that row's results only
        window.table.item(0, sites_ui.COL_LAT).setText("36.6")
        assert cell(0, sites_ui.COL_TOTALITY) == "" and cell(1, sites_ui.COL_TOTALITY) == "4m39.9s"
        assert config.get_candidate_sites()[0]["latitude"] == 36.6

        window.table.selectRow(1)
        window.use_selected()
        assert used == [Site("Tarifa", -5.6, 36.0, 50.0)]

        window.remove_selected()
        assert window.table.rowCount() == 1 and len(config.get_candidate_sites()) == 1
    finally:
        window.close()
        window.deleteLater()


def test_window_shortlist_survives_and_date_change_clears(app, config, monkeypatch):
    from solareclipseworkbench import sites_ui

    config.set_candidate_sites([Site("A", 1.0, 2.0, 3.0).to_dict()])
    monkeypatch.setattr(site_comparison, "compare_site",
                        lambda site, date: site_result(site, total_moments(), 1.02, "Total"))
    context = {"date": "2027-08-02"}
    window = sites_ui.SiteComparisonWindow(lambda: (context["date"], None), config_manager=config)
    try:
        assert window.table.rowCount() == 1 and window.table.item(0, sites_ui.COL_NAME).text() == "A"
        window.compare()
        wait_for(window)
        assert window.results
        context["date"] = "2028-07-22"
        window.refresh_context()
        assert not window.results and window.table.item(0, sites_ui.COL_TOTALITY).text() == ""
    finally:
        window.close()
        window.deleteLater()


def test_beads_comparison_leaves_out_sites_without_totality(app, config, monkeypatch):
    from solareclipseworkbench import sites_ui

    config.set_candidate_sites([Site("Total", -5.6, 36.0, 50).to_dict(), Site("Partial", -3.7, 40.4, 650).to_dict()])
    moments = total_moments()
    monkeypatch.setattr(site_comparison, "compare_site", lambda site, date: site_result(
        site, moments if site.name == "Total" else {k: moments[k] for k in ("C1", "MAX", "C4")},
        1.02, "Total" if site.name == "Total" else "Partial"))
    window = sites_ui.SiteComparisonWindow(lambda: ("2027-08-02", None), config_manager=config)
    try:
        # Not compared yet: every site goes, without a caption
        assert [(s[0], s[4]) for s in window.beads_sites()] == [("Total", ""), ("Partial", "")]
        window.compare()
        wait_for(window)
        sites = window.beads_sites()
        assert [s[0] for s in sites] == ["Total"]
        assert "C2-1.9 s to C2+4.6 s" in sites[0][4]
    finally:
        window.close()
        window.deleteLater()


from solareclipseworkbench import limb_correction

needs_limb_profile = pytest.mark.skipif(
    limb_correction.load_default_limb(download=False) is None,
    reason=f"lunar limb profile not installed ({limb_correction.band_file()})")


@needs_limb_profile
def test_beads_of_several_sites_move_together(app):
    import time
    from PyQt6.QtWidgets import QApplication
    from solareclipseworkbench.limb_ui import SLIDER_RANGE_S, BeadsComparisonWindow

    limb_correction.set_enabled(True)
    window = BeadsComparisonWindow()
    try:
        # Malaga lies near the southern limit in 2027: its C2 bead window starts about 13 s before C2
        window.set_sites("2027-08-02", [("Tarifa", -5.6, 36.0, 50, ""), ("Malaga", -4.42, 36.72, 20, ""),
                                        ("Madrid", -3.70, 40.42, 650, "")])
        deadline = time.monotonic() + 60
        while window._pending and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        assert window._pending == 0
        tarifa, malaga, madrid = window.views
        assert tarifa.solution is not None and malaga.solution is not None
        assert madrid.solution is None and madrid.countdown == "no totality or no limb profile"
        assert window.range_s >= 14 > SLIDER_RANGE_S

        window.slider.setValue(window.slider.maximum())
        assert tarifa.offset_s == malaga.offset_s == pytest.approx(window.range_s)
        window.contact_box.setCurrentText("C3")
        assert tarifa.contact == malaga.contact == "C3" and tarifa.offset_s == 0
        assert window.time_label.text() == "C3 +0.00 s"
        assert "C3 bead window" in window.captions[0].text()
    finally:
        window.close()
        window.deleteLater()
