"""Choosing the solar radius in the main window (Issue #197)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui, solar_radius
from solareclipseworkbench.gui import SolarEclipseController, SolarEclipseModel, SolarEclipseView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(app, tmp_path, monkeypatch):
    solar_radius.set_radius_arcsec(solar_radius.DEFAULT_ARCSEC)
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    recomputed = []
    monkeypatch.setattr(SolarEclipseController, "set_reference_moments", lambda self: recomputed.append(1))
    controller = SolarEclipseController(SolarEclipseModel(), SolarEclipseView(), is_simulator=False,
                                        low_cpu_mode=False)
    controller.recomputed = recomputed
    yield controller
    for timer in (controller.time_display_timer, controller._problem_timer, controller.visualization_timer):
        timer.stop()
    controller.view.deleteLater()
    solar_radius.set_radius_arcsec(solar_radius.DEFAULT_ARCSEC)


def saved_radius(tmp_path):
    settings = QSettings(str(tmp_path / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)
    return settings.value(solar_radius.SETTINGS_KEY)


def select(controller, key):
    combo = controller.view.solar_radius_combo
    combo.setCurrentIndex(combo.findData(key))


def test_default_is_shown(controller):
    assert controller.view.solar_radius_combo.currentData() == "quaglia"
    assert not controller.view.solar_radius_spinbox.isEnabled()


def test_auwers_is_used_and_remembered(controller, tmp_path):
    select(controller, "auwers")
    assert solar_radius.get_radius_arcsec() == 959.63
    assert controller.view.solar_radius_spinbox.value() == 959.63
    assert float(saved_radius(tmp_path)) == 959.63


def test_custom_value(controller, tmp_path):
    select(controller, "custom")
    spinbox = controller.view.solar_radius_spinbox
    assert spinbox.isEnabled()
    # Nothing changes until a different value is entered
    assert solar_radius.get_radius_arcsec() == 959.95
    spinbox.setValue(959.99)
    assert solar_radius.get_radius_arcsec() == 959.99
    assert float(saved_radius(tmp_path)) == 959.99


def test_saved_custom_value_is_shown(app, controller):
    solar_radius.set_radius_arcsec(959.80)
    controller._show_solar_radius()
    assert controller.view.solar_radius_combo.currentData() == "custom"
    assert controller.view.solar_radius_spinbox.value() == pytest.approx(959.80)


def test_contacts_are_recomputed_when_location_and_date_are_set(controller, monkeypatch):
    controller.model.is_location_set = True
    controller.model.is_eclipse_date_set = True
    controller.recomputed.clear()
    select(controller, "auwers")
    assert controller.recomputed


def test_not_changed_during_a_run(controller, monkeypatch):
    monkeypatch.setattr(SolarEclipseController, "_run_in_progress", lambda self: True)
    select(controller, "auwers")
    assert solar_radius.get_radius_arcsec() == 959.95
    assert controller.view.solar_radius_combo.currentData() == "quaglia"


def test_locked_with_the_limb_correction(controller):
    controller._set_limb_correction_locked(True)
    assert not controller.view.solar_radius_combo.isEnabled()
    controller._set_limb_correction_locked(False)
    assert controller.view.solar_radius_combo.isEnabled()
