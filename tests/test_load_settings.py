"""Saved settings are restored at the next start, also for a location at sea level (altitude 0)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui
from solareclipseworkbench.gui import SolarEclipseController, SolarEclipseModel, SolarEclipseView


@pytest.fixture(scope="module")
def app():
    # Reuse a QApplication if another test already made one
    return QApplication.instance() or QApplication(sys.argv)


def write_settings(path, **values):
    settings = QSettings(str(path / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()


@pytest.fixture
def start(app, tmp_path, monkeypatch):
    """ Start the app with ~ pointing to tmp_path, so the settings are read from there. """

    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(SolarEclipseController, "set_reference_moments", lambda self: None)
    controllers = []

    def _start():
        controller = SolarEclipseController(SolarEclipseModel(), SolarEclipseView(), is_simulator=False,
                                            low_cpu_mode=False)
        controllers.append(controller)
        return controller

    yield _start
    for controller in controllers:
        # Stop the timers, so they do not fire on a deleted view in later tests
        for timer in (controller.time_display_timer, controller._problem_timer, controller.visualization_timer):
            timer.stop()
        controller.view.deleteLater()


def test_location_at_sea_level_is_restored(start, tmp_path):
    write_settings(tmp_path, longitude=11.00403, latitude=35.02012, altitude=0.0, eclipse_date="02 Aug 2027",
                   date_format="dd Month yyyy", time_format="24 hours")

    controller = start()

    assert controller.model.is_location_set
    assert (controller.model.longitude, controller.model.latitude, controller.model.altitude) == \
           (11.00403, 35.02012, 0.0)
    assert controller.view.altitude_label.text() == "0.0"
    assert controller.view.eclipse_date.text() == "02 Aug 2027"


def test_missing_location_is_not_read_as_zero(start, tmp_path):
    write_settings(tmp_path, eclipse_date="02 Aug 2027", date_format="dd Month yyyy", time_format="24 hours")

    controller = start()

    assert not controller.model.is_location_set
    assert controller.view.longitude_label.text() == ""
