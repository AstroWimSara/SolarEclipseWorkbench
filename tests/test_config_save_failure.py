"""A configuration that cannot be saved is reported, once per session.

It used to be printed to the terminal only (seen on macOS with a
~/.sew_wizard_config.json the user could not write to), so camera test results
were lost without the user noticing.
"""
import logging
from unittest.mock import patch

import pytest

import solareclipseworkbench.location_ui as location_ui
from solareclipseworkbench.location_ui import ConfigManager


@pytest.fixture
def unwritable_config(tmp_path, monkeypatch):
    """A ConfigManager whose file is a directory, so saving it fails."""
    monkeypatch.setattr(ConfigManager, '_save_failure_reported', False)
    manager = ConfigManager.__new__(ConfigManager)
    manager.config_file = tmp_path / "config_dir"
    manager.config_file.mkdir()
    manager.config = manager._default_config()
    return manager


def test_save_failure_is_logged_and_reported_once(unwritable_config, caplog):
    with patch.object(location_ui, '_report_save_failure') as report, \
            caplog.at_level(logging.WARNING):
        unwritable_config.save_config()
        unwritable_config.save_config()
        # The wizard and its pages have several ConfigManagers: still one message
        other = ConfigManager.__new__(ConfigManager)
        other.config_file, other.config = unwritable_config.config_file, unwritable_config.config
        other.save_config()
    report.assert_called_once()
    assert report.call_args.args[0] == unwritable_config.config_file
    assert sum('Could not save the configuration' in r.getMessage() for r in caplog.records) == 3


def test_report_without_application_does_not_fail(unwritable_config):
    with patch.object(location_ui.QApplication, 'instance', return_value=None):
        unwritable_config.save_config()
    assert ConfigManager._save_failure_reported


def test_successful_save_reports_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigManager, '_save_failure_reported', False)
    manager = ConfigManager.__new__(ConfigManager)
    manager.config_file = tmp_path / "config.json"
    manager.config = manager._default_config()
    with patch.object(location_ui, '_report_save_failure') as report:
        manager.save_config()
    report.assert_not_called()
    assert manager.config_file.exists()


def test_message_box_is_shown_from_the_event_loop(unwritable_config):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    with patch.object(location_ui.QMessageBox, 'warning') as warning:
        unwritable_config.save_config()
        warning.assert_not_called()
        app.processEvents()
    warning.assert_called_once()
    title, text = warning.call_args.args[1:3]
    assert title == "Settings not saved"
    assert str(unwritable_config.config_file) in text
