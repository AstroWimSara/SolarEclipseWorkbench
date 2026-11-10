"""The panes of the main window are docks: the Panels menu, Reset layout and the saved layout (Issue #211)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QByteArray, QSettings, Qt
from PyQt6.QtWidgets import QApplication, QDockWidget

from solareclipseworkbench.gui import DOCK_STATE_KEY, DOCK_STATE_VERSION, SolarEclipseView

TOP = Qt.DockWidgetArea.TopDockWidgetArea
LEFT = Qt.DockWidgetArea.LeftDockWidgetArea
RIGHT = Qt.DockWidgetArea.RightDockWidgetArea

DEFAULT_AREAS = {
    "time_place_dock": TOP,
    "moments_dock": TOP,
    "camera_dock": TOP,
    "plot_dock": LEFT,
}

# Hidden in the default layout (see tests/test_error_log_dock.py)
HIDDEN_DOCKS = {"error_log_dock"}


@pytest.fixture(scope="module")
def app():
    # Reuse a QApplication if another test already made one
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    # The settings file of the application is in the home directory: never touch the real one
    monkeypatch.setenv("HOME", str(tmp_path))
    return str(tmp_path / "sew.ini")


def _view(app, settings_file):
    view = SolarEclipseView()
    view.settings = QSettings(settings_file, QSettings.Format.IniFormat)
    view.show()
    app.processEvents()
    return view


@pytest.fixture
def view(app, settings_file):
    view = _view(app, settings_file)
    yield view
    view.deleteLater()


def _docks(view):
    return {dock.objectName(): dock for dock in view.findChildren(QDockWidget)}


def _assert_default_layout(view):
    for name, area in DEFAULT_AREAS.items():
        dock = getattr(view, name)
        assert view.dockWidgetArea(dock) == area, name
        assert not dock.isFloating(), name
        assert not dock.isHidden(), name


def test_every_dock_has_an_object_name(view):
    assert set(_docks(view)) == set(DEFAULT_AREAS) | HIDDEN_DOCKS


def test_the_default_layout_is_the_window_without_docks(view):
    _assert_default_layout(view)
    # In the top row: date, time and place, then the reference moments, then the cameras
    xs = [getattr(view, name).geometry().x() for name in ("time_place_dock", "moments_dock", "camera_dock")]
    assert xs == sorted(xs)
    assert view.plot_dock.widget() is view.eclipse_visualization
    # The jobs table and the exposure buttons above it are the central widget
    central = view.centralWidget()
    for widget in (view.jobs_table, view.exposure_darker_button, view.exposure_brighter_button, view.camera_banner):
        assert central.isAncestorOf(widget)


def test_the_panels_menu_has_one_checkable_action_per_dock(view, app):
    menu = view.panels_button.menu()
    checkable = [action for action in menu.actions() if action.isCheckable()]
    assert checkable == [dock.toggleViewAction() for dock in
                         (view.time_place_dock, view.moments_dock, view.camera_dock, view.plot_dock,
                          view.error_log_dock)]
    assert [action.isChecked() for action in checkable] == [True, True, True, True, False]
    assert view.reset_layout_action in menu.actions()

    view.camera_dock.toggleViewAction().trigger()
    app.processEvents()
    assert view.camera_dock.isHidden()
    assert not view.camera_dock.toggleViewAction().isChecked()

    view.camera_dock.toggleViewAction().trigger()
    app.processEvents()
    assert not view.camera_dock.isHidden()


def test_reset_layout_shows_every_dock_in_its_default_area(view, app):
    view.camera_dock.hide()
    view.plot_dock.setFloating(True)
    view.addDockWidget(RIGHT, view.time_place_dock)
    view.tabifyDockWidget(view.moments_dock, view.camera_dock)
    view.save_layout_settings()
    app.processEvents()

    view.reset_layout_action.trigger()
    app.processEvents()

    _assert_default_layout(view)
    assert not view.settings.contains(DOCK_STATE_KEY)


def test_no_dock_can_be_made_so_small_that_it_disappears(view, app):
    view.resizeDocks([view.plot_dock], [1], Qt.Orientation.Horizontal)
    view.resizeDocks([view.moments_dock], [1], Qt.Orientation.Vertical)
    app.processEvents()
    for name in DEFAULT_AREAS:
        dock = getattr(view, name)
        assert dock.width() > 100 and dock.height() > 100, name


def test_a_hidden_dock_stays_hidden_after_a_restart(app, view, settings_file):
    view.camera_dock.hide()
    view.addDockWidget(RIGHT, view.plot_dock)
    view.save_layout_settings()
    view.settings.sync()

    other = SolarEclipseView()
    other.settings = QSettings(settings_file, QSettings.Format.IniFormat)
    other.restore_layout_settings()
    other.show()
    app.processEvents()

    assert other.camera_dock.isHidden()
    assert other.dockWidgetArea(other.plot_dock) == RIGHT
    assert not other.moments_dock.isHidden()
    other.deleteLater()


@pytest.mark.parametrize("saved", [QByteArray(b"not a saved layout"), "not a saved layout", ""])
def test_a_saved_layout_that_cannot_be_restored_gives_the_default_layout(view, app, saved):
    view.settings.setValue(DOCK_STATE_KEY, saved)
    view.addDockWidget(RIGHT, view.plot_dock)
    view.camera_dock.hide()

    view.restore_layout_settings()
    app.processEvents()

    _assert_default_layout(view)


def test_a_saved_layout_of_another_version_gives_the_default_layout(view, app):
    view.camera_dock.hide()
    view.settings.setValue(DOCK_STATE_KEY, view.saveState(DOCK_STATE_VERSION + 1))

    view.restore_layout_settings()
    app.processEvents()

    _assert_default_layout(view)


def test_an_old_splitter_position_is_ignored(view, app):
    view.settings.setValue("output_splitter_state", QByteArray(b"\x00\x00\x00\xff\x00\x00\x00\x01"))

    view.restore_layout_settings()
    app.processEvents()

    _assert_default_layout(view)
