"""Main window layout: resizable plot beside the jobs table (Issue #182) and aligned reference-moment rows (Issue #190)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QGridLayout, QGroupBox, QLabel

from solareclipseworkbench.gui import SolarEclipseView


@pytest.fixture(scope="module")
def app():
    # Reuse a QApplication if another test already made one
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def view(app):
    view = SolarEclipseView()
    yield view
    view.deleteLater()


def test_plot_width_is_saved_and_restored(view, app, tmp_path):
    settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    view.resize(1500, 1000)
    view.show()
    app.processEvents()

    view.settings = settings
    view.resizeDocks([view.plot_dock], [300], Qt.Orientation.Horizontal)
    app.processEvents()
    saved_width = view.plot_dock.width()
    view.save_layout_settings()
    settings.sync()

    other = SolarEclipseView()
    other.resize(1500, 1000)
    other.show()
    app.processEvents()
    other.settings = QSettings(str(tmp_path / "sew.ini"), QSettings.Format.IniFormat)
    other.restore_layout_settings()

    assert other.plot_dock.width() == saved_width
    other.deleteLater()


def test_layout_settings_are_skipped_without_a_settings_file(view):
    # The view only gets `settings` once the controller loads them; neither call may fail before that
    view.save_layout_settings()
    view.restore_layout_settings()


def test_reference_moment_values_are_vertically_centred_like_their_row_titles(view):
    for group_box in view.findChildren(QGroupBox):
        layout = group_box.layout()
        if not isinstance(layout, QGridLayout):
            continue
        for index in range(layout.count()):
            label = layout.itemAt(index).widget()
            if isinstance(label, QLabel):
                assert label.alignment() & Qt.AlignmentFlag.AlignVCenter, label.text()
