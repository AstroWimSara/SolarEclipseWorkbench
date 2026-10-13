"""Shared pytest setup for the root-level and tests/ suites."""

import os
import sys

import pytest

# Run Qt headless unless the caller explicitly asked for a display platform
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Create one QApplication for the whole session.

    Qt allows only one application object per process, and widgets need a
    QApplication (not a QCoreApplication), so create it before any test can.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app
