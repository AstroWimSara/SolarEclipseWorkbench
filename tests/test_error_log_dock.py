"""The Error Log dock lists each warning and error of the run, and the Panels menu counts the new ones
(Issue #211)."""

import logging
import os
import sys
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QToolButton

from solareclipseworkbench.gui import (DOCK_STATE_VERSION, ERROR_LOG_MAX_ROWS, ErrorLogDock, ErrorLogHandler,
                                       SolarEclipseView)
from solareclipseworkbench.logging_setup import file_handlers_only


@pytest.fixture(scope="module")
def app():
    # Reuse a QApplication if another test already made one
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def view(app, tmp_path, monkeypatch, caplog):
    # The settings file of the application is in the home directory: never touch the real one
    monkeypatch.setenv("HOME", str(tmp_path))
    # Let INFO records reach the handlers, so that the dock itself must leave them out
    caplog.set_level(logging.DEBUG)
    view = SolarEclipseView()
    view.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    view.show()
    app.processEvents()
    yield view
    view.deleteLater()


def _wait_for_rows(app, dock: ErrorLogDock, rows: int, timeout: float = 2.0):
    end = time.monotonic() + timeout
    while dock.table.rowCount() < rows and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _row(dock: ErrorLogDock, row: int) -> list:
    return [dock.table.item(row, column).text() for column in range(dock.table.columnCount())]


def test_a_warning_from_a_worker_thread_appears_in_the_dock(view, app):
    thread = threading.Thread(target=lambda: logging.getLogger("camera").warning("The camera does not answer"))
    thread.start()
    thread.join()

    _wait_for_rows(app, view.error_log_dock, 1)

    when, level, message = _row(view.error_log_dock, 0)
    assert level == "WARNING"
    assert message == "The camera does not answer"
    assert len(when) == len("12:34:56")


def test_the_lines_are_in_the_order_in_which_they_were_logged(view, app):
    thread = threading.Thread(target=lambda: logging.warning("First, from a worker thread"))
    thread.start()
    thread.join()
    logging.warning("Second, from the GUI thread")
    _wait_for_rows(app, view.error_log_dock, 2)

    assert [_row(view.error_log_dock, row)[2] for row in range(2)] == ["First, from a worker thread",
                                                                      "Second, from the GUI thread"]


def test_info_does_not_appear_and_error_does(view, app):
    logging.getLogger("scheduler").info("A picture is taken")
    logging.getLogger("scheduler").error("A command is in the past")
    _wait_for_rows(app, view.error_log_dock, 1)

    assert view.error_log_dock.table.rowCount() == 1
    assert _row(view.error_log_dock, 0)[1:] == ["ERROR", "A command is in the past"]


def test_only_the_first_line_of_a_message_is_in_the_table(view, app):
    logging.warning("First line\nSecond line")
    _wait_for_rows(app, view.error_log_dock, 1)

    assert _row(view.error_log_dock, 0)[2] == "First line"
    assert view.error_log_dock.table.item(0, 2).toolTip() == "First line\nSecond line"


def test_the_oldest_rows_are_removed_above_the_limit(view, app):
    for index in range(ERROR_LOG_MAX_ROWS + 5):
        logging.warning("Problem %d", index)
    app.processEvents()

    assert view.error_log_dock.table.rowCount() == ERROR_LOG_MAX_ROWS
    assert _row(view.error_log_dock, 0)[2] == "Problem 5"
    assert _row(view.error_log_dock, ERROR_LOG_MAX_ROWS - 1)[2] == f"Problem {ERROR_LOG_MAX_ROWS + 4}"


def test_clear_empties_the_dock(view, app):
    logging.warning("A problem")
    _wait_for_rows(app, view.error_log_dock, 1)

    view.error_log_dock.clear_button.click()

    assert view.error_log_dock.table.rowCount() == 0
    assert view.error_log_dock.toggleViewAction().text() == "Error Log"


def test_the_panels_menu_counts_new_problems_until_the_dock_is_shown(view, app):
    entry = view.error_log_dock.toggleViewAction()
    assert entry.text() == "Error Log"
    assert view.panels_button.text() == "Panels"
    width = view.panels_button.width()
    for index in range(3):
        logging.warning("Problem %d", index)
    app.processEvents()
    assert entry.text() == "Error Log (3)"
    assert view.panels_button.text() == "Panels (3)"
    # The text fits: the button is as wide as before
    assert view.panels_button.width() == width
    assert view.panels_button.width() >= view.panels_button.sizeHint().width()

    entry.trigger()
    app.processEvents()

    assert view.error_log_dock.isVisible()
    assert entry.text() == "Error Log"
    assert view.panels_button.text() == "Panels"

    # A problem that comes in while the dock is visible is not new
    logging.warning("Another problem")
    app.processEvents()
    assert view.error_log_dock.table.rowCount() == 4
    assert entry.text() == "Error Log"


def test_there_is_no_separate_error_log_button(view, app):
    texts = [widget.text() for widget in view.toolbar.findChildren(QToolButton) if widget.isVisible()]
    assert not [text for text in texts if text.startswith("Error Log")]


def test_the_dock_is_hidden_by_default_and_in_the_panels_menu(view, app):
    dock = view.error_log_dock
    assert dock.objectName() == "error_log_dock"
    assert dock.isHidden()
    assert view.dockWidgetArea(dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert dock.toggleViewAction() in view.panels_button.menu().actions()

    dock.toggleViewAction().trigger()
    app.processEvents()
    assert dock.isVisible()


def test_reset_layout_hides_the_dock_at_the_bottom(view, app):
    view.show_error_log()
    view.error_log_dock.setFloating(True)
    app.processEvents()

    view.reset_layout_action.trigger()
    app.processEvents()

    assert view.error_log_dock.isHidden()
    assert not view.error_log_dock.isFloating()
    assert view.dockWidgetArea(view.error_log_dock) == Qt.DockWidgetArea.BottomDockWidgetArea


def test_a_layout_saved_without_the_error_log_restores_with_the_dock_hidden(view, app):
    # A layout of the same version that was saved before the Error Log dock existed
    view.removeDockWidget(view.error_log_dock)
    view.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, view.plot_dock)
    state = view.saveState(DOCK_STATE_VERSION)
    view.reset_layout()
    app.processEvents()

    assert view.restoreState(state, DOCK_STATE_VERSION)
    app.processEvents()

    assert view.dockWidgetArea(view.plot_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert view.error_log_dock.isHidden()
    assert view.dockWidgetArea(view.error_log_dock) == Qt.DockWidgetArea.BottomDockWidgetArea


def test_a_shown_error_log_is_shown_after_a_restart(view, app):
    view.show_error_log()
    app.processEvents()
    view.save_layout_settings()

    other = SolarEclipseView()
    other.settings = view.settings
    other.restore_layout_settings()
    other.show()
    app.processEvents()

    assert other.error_log_dock.isVisible()
    assert other.dockWidgetArea(other.error_log_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    other.deleteLater()
def test_the_handler_is_removed_when_the_window_closes(view, app, monkeypatch):
    handler = view.error_log_dock.handler
    assert handler in logging.getLogger().handlers
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    assert view.close()

    assert handler not in logging.getLogger().handlers


def test_a_record_for_a_deleted_dock_is_ignored(app, monkeypatch):
    dock = ErrorLogDock()
    handler = dock.handler
    sip.delete(dock)
    monkeypatch.setattr(handler, "handleError", lambda record: pytest.fail("the record gives a logging error"))

    handler.handle(logging.makeLogRecord({"levelno": logging.WARNING, "levelname": "WARNING", "msg": "A problem"}))


def test_the_handler_stays_while_the_console_is_silenced():
    handler = ErrorLogHandler.__new__(ErrorLogHandler)
    console = logging.StreamHandler()
    assert file_handlers_only([console, handler]) == [handler]
