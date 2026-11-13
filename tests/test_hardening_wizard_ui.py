"""Hardening of the wizard, the location widget and the Compare sites window.

Each test is a case that used to raise in a Qt slot (which aborts the wizard)
or gave a wrong result without saying so.
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWizard

from solareclipseworkbench import location_ui, site_comparison
from solareclipseworkbench.location_ui import ConfigManager, LocationWidget
from solareclipseworkbench.site_comparison import Site


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ConfigManager, "_save_failure_reported", True)
    return ConfigManager()


class _SlowElevation(QThread):
    """Answers with the latitude as the elevation, after a while."""
    finished = pyqtSignal(float)
    error = pyqtSignal(str)

    def __init__(self, latitude, longitude):
        super().__init__()
        self.latitude = latitude

    def run(self):
        time.sleep(0.2)
        self.finished.emit(float(self.latitude))


def test_a_second_elevation_lookup_does_not_release_the_running_one(app, config, monkeypatch):
    """Two picks on the map within the lookup time: the first QThread used to be released while running."""
    monkeypatch.setattr(location_ui, "ElevationWorker", _SlowElevation)
    widget = LocationWidget(config)
    widget._start_elevation_lookup(11.0, 1.0)
    first = widget._elevation_worker
    widget._start_elevation_lookup(22.0, 2.0)
    assert first in widget._retired_workers
    for _ in range(100):
        app.processEvents()
        if widget._elevation_worker is None and not first.isRunning():
            break
        time.sleep(0.01)
    app.processEvents()
    # Only the answer for the last spot is used
    assert widget.altitude_edit.text() == "22.0"
    first.wait()
    widget.close()


def test_return_in_the_search_field_during_a_search_starts_no_second_one(app, config, monkeypatch):
    if not location_ui.GEOPY_AVAILABLE:
        pytest.skip("geopy not installed")
    widget = LocationWidget(config)
    running = MagicMock()
    running.isRunning.return_value = True
    widget._geocoding_worker = running
    widget.address_search_edit.setText("Burgos")
    started = MagicMock()
    monkeypatch.setattr(location_ui, "GeocodingWorker", started)
    widget._search_address()
    started.assert_not_called()
    assert widget._geocoding_worker is running
    widget._geocoding_worker = None
    widget.close()


def test_coordinates_with_a_decimal_comma(app, config):
    widget = LocationWidget(config)
    widget.longitude_edit.setText("-4,35")
    widget.latitude_edit.setText("50,85")
    widget.altitude_edit.setText("100")
    assert widget.get_coordinates() == pytest.approx((-4.35, 50.85, 100.0))
    widget.close()


def test_a_cloud_cover_answer_of_another_shape_does_not_raise():
    import datetime
    moment = datetime.datetime(2026, 8, 12, 18, 30, tzinfo=datetime.timezone.utc)
    today = datetime.date(2026, 8, 10)
    for answer in ([1, 2], {"hourly": {"time": ["not a time"], "cloud_cover": [5]}},
                   {"hourly": {"time": ["2026-08-12T18:00"], "cloud_cover": ["x"]}}):
        response = MagicMock()
        response.json.return_value = answer
        forecast = site_comparison.fetch_cloud_cover(42.0, -4.5, moment, today=today,
                                                     get=lambda *a, **k: response)
        assert forecast.error


def test_compare_sites_reads_a_decimal_comma_and_saves_utf8(app, config, tmp_path, monkeypatch):
    from solareclipseworkbench import sites_ui
    window = sites_ui.SiteComparisonWindow(lambda: ("2026-08-12", None), config_manager=config)
    window.add_site(Site("Café ☀ Burgos", -3.7, 42.34, 860))
    window.table.item(0, sites_ui.COL_LAT).setText("42,5")
    assert window._site(0).latitude == pytest.approx(42.5)

    window.results[window._row_id(0)] = site_comparison.SiteResult(window._site(0), eclipse_type="Total")
    target = tmp_path / "sites.txt"
    monkeypatch.setattr(sites_ui.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.save_text()
    assert "Café ☀ Burgos" in target.read_text(encoding="utf-8")
    window.close()


def test_a_saved_camera_with_odd_values_loads(app, config):
    from solareclipseworkbench.wizard import EquipmentPage
    config.config["cameras"].append({"name": "Old camera", "focal_length": 400.0, "aperture_min": "5.6"})
    wizard = QWizard()
    wizard.config_manager = config
    page = EquipmentPage(wizard)
    page._on_camera_selected("Old camera")      # used to raise TypeError in QSpinBox.setValue(float)
    assert page.focal_length_spin.value() == 400
    assert page.aperture_min_spin.value() == pytest.approx(5.6)
    assert page.aperture_max_spin.value() == pytest.approx(8.0)


def _script(longitude, latitude):
    from solareclipseworkbench.wizard import SummaryPage
    fields = {
        'eclipse_name': 'Total Solar Eclipse 2026', 'eclipse_date': '2026-08-12', 'eclipse_type': 'Total',
        'location': 'Somewhere', 'latitude': str(latitude), 'longitude': str(longitude), 'altitude': '0',
        'camera_name': 'Canon EOS R5', 'focal_length': 600, 'aperture_min': 5.6, 'aperture_max': 32,
        'preferred_iso': 400, 'iso_min': 100, 'iso_max': 6400, 'filter_value': '5.0',
        'c1_c4': True, 'equispaced': True, 'seconds_value': 60,
        'diamond': True, 'bailys': True, 'corona': True, 'chromosphere': True, 'prominences': True,
        'sync_enabled': False, 'voice_enabled': False,
    }
    wizard = MagicMock()
    wizard.field.side_effect = fields.get
    wizard.camera_profiles = {}
    wizard.config_manager = None
    page = SummaryPage()
    page.wizard = lambda: wizard
    return page, page._generate_script()


@pytest.mark.parametrize("longitude, latitude", [(151.2, -33.9),     # nothing of the eclipse
                                                 (-120.0, 40.0)])    # C1/MAX/C4 given, negative magnitude
def test_no_eclipse_at_the_location_gives_no_shots_and_a_warning(app, longitude, latitude):
    """The partial shots used to be written for an uneclipsed Sun, and C2/C3 shots from the global type."""
    page, script = _script(longitude, latitude)
    commands = [line for line in script.split("\n") if line and not line.startswith("#")]
    assert commands == [], script
    assert "WARNING: The eclipse is not visible from this location" in script
    assert page._location_warning


def test_location_page_checks_and_normalises_the_coordinates(app, config, monkeypatch):
    """A decimal comma used to make the script fall back to placeholders without a word."""
    from solareclipseworkbench import wizard as wizard_module
    warnings = []
    monkeypatch.setattr(wizard_module.QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    wizard = QWizard()
    wizard.config_manager = config
    page = wizard_module.EclipseConfigPage(wizard)
    lw = page.location_widget
    lw.longitude_edit.setText("-4,5289")
    lw.latitude_edit.setText("42,0095")
    lw.altitude_edit.setText("740")
    assert page.validatePage()
    assert (lw.longitude_edit.text(), lw.latitude_edit.text()) == ("-4.5289", "42.0095")
    assert not warnings

    lw.latitude_edit.setText("95")
    assert not page.validatePage()
    lw.latitude_edit.setText("4x")
    assert not page.validatePage()
    assert len(warnings) == 2


def test_a_failing_script_generation_does_not_escape_the_summary_page(app, monkeypatch):
    """initializePage() is called by Qt: an exception there aborted the wizard."""
    from solareclipseworkbench import wizard as wizard_module
    errors = []
    monkeypatch.setattr(wizard_module.QMessageBox, "critical", lambda *args: errors.append(args[1:]))
    wizard = MagicMock()
    wizard.field.side_effect = lambda name: ""
    page = wizard_module.SummaryPage()
    page.wizard = lambda: wizard

    def broken():
        raise RuntimeError("boom")
    page._generate_script = broken
    page.initializePage()
    assert "boom" in page.script_preview.toPlainText()
    assert errors and errors[0][0] == "Script Generation Failed"


def test_unhandled_errors_are_logged_and_shown(app, monkeypatch, caplog):
    from solareclipseworkbench import wizard as wizard_module
    shown = []
    monkeypatch.setattr(wizard_module.QMessageBox, "critical", lambda *args: shown.append(args[1:]))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)    # restored after the test
    wizard_module._keep_running_on_unhandled_errors()
    try:
        raise KeyError("missing")
    except KeyError:
        sys.excepthook(*sys.exc_info())
    assert shown and shown[0][0] == "Unexpected Error"
    assert any("Unhandled KeyError" in r.getMessage() for r in caplog.records)
