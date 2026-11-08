"""Shared pytest setup for the root-level and tests/ suites."""

import logging
import os
import sys

import pytest

# Run Qt headless unless the caller explicitly asked for a display platform
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Never download the 72 MB lunar limb profile from a test: tests that need it
# are skipped when it is not installed
os.environ.setdefault("SEW_NO_LIMB_DOWNLOAD", "1")


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Create one QApplication for the whole session.

    Qt allows only one application object per process, and widgets need a
    QApplication (not a QCoreApplication), so create it before any test can.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def remove_error_log_handlers():
    """Remove the Error Log handler of each main window that a test did not close.

    A main window adds this handler to the root logger, and removes it only when the window closes.
    """
    yield
    gui = sys.modules.get("solareclipseworkbench.gui")
    if gui is not None:
        root = logging.getLogger()
        for handler in [handler for handler in root.handlers if isinstance(handler, gui.ErrorLogHandler)]:
            root.removeHandler(handler)
