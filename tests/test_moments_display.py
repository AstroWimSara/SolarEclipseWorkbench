"""The limb correction has to be visible in the times, not just in the model.

The C2 and C3 rows show the limb-corrected contacts when the correction is on,
because that is what an eclipse script schedules against.  The bead windows are
shown too: a contact burst is aimed at a window, not at a contact.

The site constants below are on the 2026 centre line, chosen because the
correction is worth whole seconds there and the assertions have something to
bite on.
"""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from astropy.time import Time
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import limb_correction
from solareclipseworkbench.gui import (LIMB_CORRECTION_LOCKED_TOOLTIP,
                                       LIMB_CORRECTION_TOOLTIP,
                                       SolarEclipseController, SolarEclipseView)
from solareclipseworkbench.reference_moments import calculate_reference_moments

# A site where the limb correction is known to be worth seconds.
LON, LAT, ALT = -4.5289, 42.0095, 740.0
ECLIPSE = Time("2026-08-12 00:00:00")

# The limb blob is a 72 MB release asset rather than part of the checkout, so
# everything that needs a real solve is skipped when it is not installed.
needs_limb_profile = pytest.mark.skipif(
    limb_correction.load_default_limb() is None,
    reason=f"lunar limb profile not installed ({limb_correction.BAND_FILE})")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app):
    widget = SolarEclipseView()
    yield widget
    widget.deleteLater()
    limb_correction.set_enabled(True)


def _shown(view, enabled: bool) -> None:
    limb_correction.set_enabled(enabled)
    moments, magnitude, kind = calculate_reference_moments(LON, LAT, ALT, ECLIPSE)
    view.show_reference_moments(moments, magnitude, kind)


@needs_limb_profile
def test_the_correction_moves_the_contact_times_on_screen(view):
    _shown(view, True)
    corrected_c2 = view.c2_time_utc_label.text()
    corrected_c3 = view.c3_time_utc_label.text()

    _shown(view, False)
    assert view.c2_time_utc_label.text() != corrected_c2
    assert view.c3_time_utc_label.text() != corrected_c3


@needs_limb_profile
def test_the_bead_windows_are_shown_with_their_duration(view):
    _shown(view, True)

    for label in (view.beads_c2_label, view.beads_c3_label):
        text = label.text()
        assert " - " in text, text
        assert text.endswith("s)"), text


def test_the_bead_rows_say_why_they_are_empty(view):
    _shown(view, False)

    # A blank here would read like a solve that failed rather than a correction
    # that is switched off.
    assert view.beads_c2_label.text() == "correction off"
    assert view.beads_c3_label.text() == "correction off"


def test_an_unresolved_window_is_not_reported_as_a_missing_profile(view):
    limb_correction.set_enabled(True)
    now = datetime.now(timezone.utc)
    horizon = SimpleNamespace(time_utc=now, time_local=now)
    view.show_reference_moments(
        {"duration": timedelta(), "sunrise": horizon, "sunset": horizon,
         "BEADS_C2_STATUS": "unresolved",
         "BEADS_C3_STATUS": "unresolved"},
        1.0, "Total")

    assert view.beads_c2_label.text() == "capture window unresolved"
    assert view.beads_c3_label.text() == "capture window unresolved"


def test_pending_jobs_lock_the_limb_correction_setting(view):
    controller = object.__new__(SolarEclipseController)
    controller.view = view

    controller._set_limb_correction_locked(True)
    assert not view.limb_correction_checkbox.isEnabled()
    assert view.limb_correction_checkbox.toolTip() == LIMB_CORRECTION_LOCKED_TOOLTIP

    controller._set_limb_correction_locked(False)
    assert view.limb_correction_checkbox.isEnabled()
    assert view.limb_correction_checkbox.toolTip() == LIMB_CORRECTION_TOOLTIP


def test_pending_jobs_reject_a_programmatic_correction_change(view):
    controller = object.__new__(SolarEclipseController)
    controller.view = view
    controller.scheduler = SimpleNamespace(get_jobs=lambda: [object()])
    limb_correction.set_enabled(True)
    view.limb_correction_checkbox.setChecked(False)

    controller.on_limb_correction_toggled(False)

    assert limb_correction.is_enabled()
    assert view.limb_correction_checkbox.isChecked()
