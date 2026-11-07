"""The Camera(s) button says why it is off, and the no-camera dialog says how to use the VirtualCamera."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from skyfield.units import Angle

from solareclipseworkbench import gui, hardware_problems
from solareclipseworkbench.gui import (CAMERA_LOCKED_TOOLTIP, CAMERA_TOOLTIP, SolarEclipseController,
                                       SolarEclipseModel, SolarEclipseView)
from solareclipseworkbench.reference_moments import ReferenceMomentInfo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(app, tmp_path, monkeypatch):
    hardware_problems.clear()
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    controller = SolarEclipseController(SolarEclipseModel(), SolarEclipseView(), is_simulator=False,
                                        low_cpu_mode=False)
    yield controller
    for timer in (controller.time_display_timer, controller._problem_timer, controller.visualization_timer):
        timer.stop()
    if controller.scheduler is not None and controller.scheduler.running:
        controller.scheduler.shutdown(wait=False)
    controller.view.deleteLater()
    hardware_problems.clear()


def _load_script(controller, tmp_path, monkeypatch):
    # The jobs table shows local times, so it needs a location
    controller.model.longitude, controller.model.latitude = 4.7, 50.9
    c2 = datetime.now(timezone.utc) + timedelta(hours=1)
    controller.model.reference_moments = {"C2": ReferenceMomentInfo(c2, Angle(degrees=250.0), 8.7, timezone.utc)}
    script = tmp_path / "script.txt"
    script.write_text('voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"\n')
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(script), ""))
    controller.update(controller.view.file_action)


def test_the_enabled_button_says_what_it_does(controller):
    assert controller.view.camera_action.isEnabled()
    assert controller.view.camera_action.toolTip() == CAMERA_TOOLTIP


def test_the_disabled_button_says_why_and_how_to_turn_it_on(controller, tmp_path, monkeypatch):
    _load_script(controller, tmp_path, monkeypatch)

    assert not controller.view.camera_action.isEnabled()
    assert controller.view.camera_action.toolTip() == CAMERA_LOCKED_TOOLTIP
    assert "Stop" in CAMERA_LOCKED_TOOLTIP


def test_stop_gives_the_button_its_normal_tooltip_again(controller, tmp_path, monkeypatch):
    _load_script(controller, tmp_path, monkeypatch)

    controller.update(controller.view.shutdown_scheduler_action)

    assert controller.view.camera_action.isEnabled()
    assert controller.view.camera_action.toolTip() == CAMERA_TOOLTIP


def test_the_no_camera_dialog_names_the_flags_for_the_virtual_camera(controller, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *args: shown.append(text))

    controller._open_live_view()

    assert len(shown) == 1
    assert "sew --sim --virtual-camera" in shown[0]
