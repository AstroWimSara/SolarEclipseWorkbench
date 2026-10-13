"""`Save` reports its outcome in the status bar and the log (Issue #181)."""

import logging
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.gui import SolarEclipseView


@pytest.fixture(scope="module")
def app():
    # Reuse a QApplication if another test already made one
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def view(app, tmp_path):
    view = SolarEclipseView()
    view.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    yield view
    view.deleteLater()


def set_location(view, longitude="4.70", latitude="50.88", altitude="20.0"):
    view.longitude_label.setText(longitude)
    view.latitude_label.setText(latitude)
    view.altitude_label.setText(altitude)


def test_save_reports_success_in_status_bar_and_log(view, tmp_path, caplog):
    set_location(view)

    with caplog.at_level(logging.INFO):
        assert view.save_settings()

    message = view.statusBar().currentMessage()
    assert message.startswith("Settings saved to")
    assert str(tmp_path / "sew.ini") in message
    assert "Settings saved to" in caplog.text
    assert QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat).value("longitude") is not None


def test_save_warns_when_the_location_is_not_set(view, caplog):
    set_location(view, altitude="")

    with caplog.at_level(logging.WARNING):
        assert view.save_settings()

    message = view.statusBar().currentMessage()
    assert "without the location" in message
    assert "altitude" in message
    assert any(record.levelno == logging.WARNING and "without the location" in record.message
               for record in caplog.records)
    assert view.settings.value("longitude") is None


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_save_reports_a_settings_file_that_cannot_be_written(view, tmp_path, caplog):
    read_only = tmp_path / "read_only"
    read_only.mkdir()
    read_only.chmod(0o500)
    view.settings = QSettings(str(read_only / "sew.ini"), QSettings.Format.IniFormat)
    set_location(view)

    try:
        with caplog.at_level(logging.ERROR):
            assert not view.save_settings()
    finally:
        read_only.chmod(0o700)

    assert view.statusBar().currentMessage().startswith("Could not save the settings")
    assert "Could not save the settings" in caplog.text
