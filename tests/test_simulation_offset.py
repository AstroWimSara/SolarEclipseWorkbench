"""The simulator moves the countdowns, and the scheduler and the countdowns use the same offset."""

import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from apscheduler.schedulers.background import BackgroundScheduler
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui
from solareclipseworkbench.gui import SimulatorPopup, SolarEclipseController, SolarEclipseModel, SolarEclipseView
from solareclipseworkbench.utils import simulation_offset

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=pytz.utc)
C2 = datetime(2026, 8, 12, 18, 30, tzinfo=pytz.utc)


def _moments(c2_utc=C2):
    return {"C2": SimpleNamespace(time_utc=c2_utc)}


def _noop():
    pass


def test_the_reference_moment_comes_after_the_given_minutes():
    offset = simulation_offset(_moments(), "C2", 2, NOW)

    assert NOW + timedelta(minutes=2) + offset == C2


def test_a_reference_moment_in_the_past_works_the_same_way():
    offset = simulation_offset(_moments(), "C2", -5, NOW)

    assert NOW - timedelta(minutes=5) + offset == C2


def test_no_reference_moment_gives_no_offset():
    assert simulation_offset(_moments(), None, 2, NOW) == timedelta(0)
    assert simulation_offset(_moments(), "", 2, NOW) == timedelta(0)


def test_a_reference_moment_that_does_not_exist_gives_no_offset():
    # A partial eclipse has no C3, and no moments are known before a location and a date are set
    assert simulation_offset(_moments(), "C3", 2, NOW) == timedelta(0)
    assert simulation_offset(None, "C2", 2, NOW) == timedelta(0)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(app, tmp_path, monkeypatch):
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    controller = SolarEclipseController(SolarEclipseModel(), SolarEclipseView(is_simulator=True),
                                        is_simulator=True, low_cpu_mode=False)
    yield controller
    for timer in (controller.time_display_timer, controller._problem_timer, controller.visualization_timer):
        timer.stop()
    if controller.scheduler is not None and controller.scheduler.running:
        controller.scheduler.shutdown(wait=False)
    controller.view.deleteLater()


def _simulate(controller, minutes, before_after, moment):
    popup = SimulatorPopup(controller)
    popup.offset_minutes.setText(str(minutes))
    popup.before_after_combobox.setCurrentText(before_after)
    popup.reference_moment_combobox.setCurrentText(moment)
    popup.accept_starting_time()
    popup.deleteLater()


def test_the_simulator_moves_the_countdowns(controller):
    c2 = datetime.now(pytz.utc) + timedelta(days=3)
    controller.model.reference_moments = _moments(c2)

    _simulate(controller, 2, "before", "C2")

    simulated_now = datetime.now(pytz.utc) + controller.view.eclipse_visualization.offset
    assert abs(c2 - timedelta(minutes=2) - simulated_now) < timedelta(seconds=5)


def test_the_offset_stays_while_a_script_has_jobs(controller):
    controller.model.reference_moments = _moments(datetime.now(pytz.utc) + timedelta(days=3))
    scheduler = BackgroundScheduler()
    scheduler.add_job(_noop, "date", run_date=datetime.now(pytz.utc) + timedelta(hours=1))
    scheduler.start()
    controller.scheduler = scheduler
    scheduled_offset = timedelta(minutes=-17)
    controller.view.eclipse_visualization.set_offset(scheduled_offset)

    _simulate(controller, 2, "before", "C2")

    assert controller.view.eclipse_visualization.offset == scheduled_offset
    # The new simulation is kept for the next script
    assert controller.sim_reference_moment == "C2"
    assert controller.sim_offset_minutes == 2
