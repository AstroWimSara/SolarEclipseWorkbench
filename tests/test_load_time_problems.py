"""Problems found while a script is loaded are shown then, not after the run.

Loading a script starts its schedule, and once a run is in progress camera
problems only go in the window title.  A bad bracket, or commands whose time has
already passed, must still reach the user while the script can be fixed.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from skyfield.units import Angle

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.gui import SolarEclipseController
from solareclipseworkbench.reference_moments import ReferenceMomentInfo
from solareclipseworkbench.utils import schedule_commands


@pytest.fixture(autouse=True)
def no_problems():
    hardware_problems.clear()
    yield
    hardware_problems.clear()


@pytest.fixture
def scheduler():
    scheduler = BackgroundScheduler()
    yield scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _moments(c2):
    return {"C2": ReferenceMomentInfo(c2, Angle(degrees=250.0), 8.7, timezone.utc)}


def _script(tmp_path, *lines):
    path = tmp_path / "script.txt"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_commands_already_past_are_reported(tmp_path, scheduler):
    c2 = datetime.now(timezone.utc) + timedelta(seconds=30)
    filename = _script(
        tmp_path,
        'voice_prompt, C2, -, 0:02:00.0, C2_IN_5_SECONDS, "two minutes before"',
        'voice_prompt, C2, -, 0:01:00.0, C2_IN_5_SECONDS, "one minute before"',
        'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"',
    )

    schedule_commands(filename, scheduler, _moments(c2), {}, None, None, None)

    problems = hardware_problems.peek()
    assert len(problems) == 1
    assert problems[0].severity == "warning"
    assert problems[0].message.startswith("2 command(s) of the script are already past")
    assert '"two minutes before"' in problems[0].detail and '"one minute before"' in problems[0].detail
    # Still scheduled, so a later LAST line keeps its reference
    assert len(scheduler.get_jobs()) == 3


def test_a_script_in_the_future_reports_nothing(tmp_path, scheduler):
    c2 = datetime.now(timezone.utc) + timedelta(minutes=5)
    filename = _script(tmp_path, 'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"')

    schedule_commands(filename, scheduler, _moments(c2), {}, None, None, None)

    assert hardware_problems.count() == 0


def _controller(run_in_progress):
    return SimpleNamespace(_run_in_progress=lambda: run_in_progress, view=SimpleNamespace(setWindowTitle=None))


def test_script_problems_are_shown_when_the_script_is_loaded():
    hardware_problems.report("Script", 'Bracket "1 4" is not understood')
    with patch("solareclipseworkbench.gui.QMessageBox.critical") as critical:
        SolarEclipseController._show_camera_problems(_controller(True), script_loaded=True)
    critical.assert_called_once()
    assert critical.call_args.args[1] == "Script problem"
    assert hardware_problems.count() == 0


def test_problems_during_a_run_wait_for_the_end_of_the_run():
    hardware_problems.report("Canon EOS 80D", "The camera did not respond")
    titles = []
    controller = SimpleNamespace(_run_in_progress=lambda: True, view=SimpleNamespace(setWindowTitle=titles.append))
    with patch("solareclipseworkbench.gui.QMessageBox.critical") as critical:
        SolarEclipseController._show_camera_problems(controller)
    critical.assert_not_called()
    assert "1 camera problem(s)" in titles[0]
    assert hardware_problems.count() == 1
