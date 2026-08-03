"""The limb correction has to be visible in the times, not just in the model.

The C2 and C3 rows show the limb-corrected contacts when the correction is on,
because that is what an eclipse script schedules against.  The bead windows are
shown too: a contact burst is aimed at a window, not at a contact.

The site constants below are on the 2026 centre line, chosen because the
correction is worth whole seconds there and the assertions have something to
bite on.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from astropy.time import Time
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import limb_correction
from solareclipseworkbench.gui import SolarEclipseView
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
