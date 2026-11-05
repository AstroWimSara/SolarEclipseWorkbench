"""The choice between the commands in words and as in the script, in the jobs table."""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.camera import CameraSettings, set_exposure_compensation, take_picture
from solareclipseworkbench.gui import (DEFAULT_JOBS_COMMAND_STYLE, JOBS_COMMAND_STYLE_KEY, JobsTableColumnNames,
                                       JobsTableModel, SolarEclipseController, SolarEclipseView, job_command_string,
                                       job_command_text)
from solareclipseworkbench.notifications import voice_prompt

CAMERA = "VirtualCamera"


def _settings(speed="1/1000", aperture="8", iso=200):
    return CameraSettings(CAMERA, speed, aperture, iso)


def _job(func, *args):
    return SimpleNamespace(func=func, args=list(args), name="description")


@pytest.fixture(autouse=True)
def _no_compensation():
    set_exposure_compensation(0)
    yield
    set_exposure_compensation(0)


def test_unknown_commands_fall_back_to_the_script_text():
    def dome_open():
        pass

    voice = _job(voice_prompt, "C2")
    assert job_command_text(voice, "words") == "Voice prompt: C2"
    assert job_command_text(voice, "script") == job_command_string(voice) == "voice_prompt(C2)"

    unknown = _job(dome_open)
    assert job_command_text(unknown, "words") == job_command_string(unknown)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def view(app):
    view = SolarEclipseView()
    yield view
    view.deleteLater()


@pytest.fixture
def jobs_model(view):
    scheduler = BackgroundScheduler(timezone=timezone.utc)
    run_date = datetime.now(timezone.utc) + timedelta(hours=1)
    scheduler.add_job(take_picture, trigger=DateTrigger(run_date=run_date),
                      args=[object(), _settings()], name="Partial phase")
    scheduler.start(paused=True)
    try:
        controller = SimpleNamespace(
            view=view,
            model=SimpleNamespace(longitude=4.7, latitude=50.9, gps_time_offset=timedelta(0)),
        )
        yield JobsTableModel(scheduler, controller)
    finally:
        scheduler.shutdown(wait=False)


WORDS = "Picture at 1/1000 s, f/8, ISO 200 (VirtualCamera)"
SCRIPT = 'take_picture("VirtualCamera", 1/1000, 8, 200)'


def _command(model, role=Qt.ItemDataRole.DisplayRole):
    return model.data(model.index(0, model.command_column), role)


def test_the_default_style_is_in_words(view, jobs_model):
    assert DEFAULT_JOBS_COMMAND_STYLE == "words"
    assert view.jobs_command_style == "words"
    assert view.jobs_command_style_combo.currentText() == "In words"
    assert _command(jobs_model) == WORDS


def test_the_tooltip_shows_the_other_style(view, jobs_model):
    assert _command(jobs_model, Qt.ItemDataRole.ToolTipRole) == SCRIPT

    view.set_jobs_command_style("script")
    jobs_model.update_commands()
    assert _command(jobs_model, Qt.ItemDataRole.ToolTipRole) == WORDS


def test_choosing_a_style_redraws_the_table_and_saves_the_choice(view, jobs_model, tmp_path):
    view.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    controller = SimpleNamespace(view=view, jobs_model=jobs_model)
    view.jobs_command_style_combo.currentIndexChanged.connect(
        lambda index: SolarEclipseController.on_jobs_command_style_changed(controller, index))

    view.jobs_command_style_combo.setCurrentIndex(view.jobs_command_style_combo.findData("script"))
    assert _command(jobs_model) == SCRIPT
    assert view.settings.value(JOBS_COMMAND_STYLE_KEY) == "script"
    assert jobs_model._data.loc[0, JobsTableColumnNames.COMMAND.value] == SCRIPT

    view.jobs_command_style_combo.setCurrentIndex(view.jobs_command_style_combo.findData("words"))
    assert _command(jobs_model) == WORDS
    assert view.settings.value(JOBS_COMMAND_STYLE_KEY) == "words"


def test_the_style_is_restored_from_the_settings(app, view, tmp_path):
    view.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    view.set_jobs_command_style("script")
    view.save_layout_settings()
    view.settings.sync()

    other = SolarEclipseView()
    other.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    other.restore_layout_settings()
    assert other.jobs_command_style == "script"
    other.deleteLater()


def test_an_unknown_saved_style_selects_the_default(view, tmp_path):
    view.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    view.settings.setValue(JOBS_COMMAND_STYLE_KEY, "something else")
    view.restore_layout_settings()
    assert view.jobs_command_style == DEFAULT_JOBS_COMMAND_STYLE
