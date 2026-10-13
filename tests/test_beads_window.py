"""The Baily's beads window.

It has to agree with the reference moments it sits next to: "C2 +0.00 s" in the
window is the C2 row, and the corrections it states are the ones the rows show.
Solving happens in the background, so a slow solve for an old location must not
overwrite a newer one.
"""

import time
from datetime import timedelta

import pytest
from astropy.time import Time
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import limb_correction
from solareclipseworkbench.limb_ui import BeadsPanel, contact_hours
from solareclipseworkbench.reference_moments import calculate_reference_moments

# On the 2026 centre line, where the correction is worth whole seconds
LON, LAT, ALT = -4.5289, 42.0095, 740.0
DATE = "2026-08-12"

needs_limb_profile = pytest.mark.skipif(
    limb_correction.load_default_limb(download=False) is None,
    reason=f"lunar limb profile not installed ({limb_correction.band_file()})")


def _wait_for_solve(panel, timeout_s=60.0):
    deadline = time.monotonic() + timeout_s
    while panel.solution is None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert panel.solution is not None, panel.summary.text()


@pytest.fixture(scope="module")
def solved_panel():
    limb_correction.set_enabled(True)
    panel = BeadsPanel()
    panel.set_context(DATE, LON, LAT, ALT)
    _wait_for_solve(panel)
    yield panel
    panel.close()
    panel.deleteLater()


@needs_limb_profile
def test_the_slider_is_centred_on_the_c2_shown_in_the_reference_moments(solved_panel):
    moments, _, _ = calculate_reference_moments(LON, LAT, ALT, Time(DATE))
    solution = solved_panel.solution

    centre = solution.to_utc(contact_hours(solution, "C2"))

    assert abs((centre - moments["C2"].time_utc).total_seconds()) < 0.01
    assert solved_panel.time_label.text().startswith(centre.strftime("%H:%M:%S"))


@needs_limb_profile
def test_the_stated_corrections_are_the_ones_the_rows_show(solved_panel):
    moments, _, _ = calculate_reference_moments(LON, LAT, ALT, Time(DATE))
    c2 = (moments["C2"].time_utc - moments["C2_MEAN"].time_utc).total_seconds()
    c3 = (moments["C3"].time_utc - moments["C3_MEAN"].time_utc).total_seconds()

    text = solved_panel.summary.text()

    assert f"C2 {c2:+.1f}s" in text, text
    assert f"C3 {c3:+.1f}s" in text, text
    assert f"totality {c3 - c2:+.1f}s" in text, text


@needs_limb_profile
@pytest.mark.parametrize("mode", ["Profile", "Preview"])
@pytest.mark.parametrize("contact", ["C2", "C3"])
def test_both_drawings_render_around_both_contacts(solved_panel, mode, contact):
    solved_panel.mode_box.setCurrentText(mode)
    solved_panel.contact_box.setCurrentText(contact)
    for value in (solved_panel.slider.minimum(), 0, solved_panel.slider.maximum()):
        solved_panel.slider.setValue(value)
        assert not solved_panel.view.grab().isNull()
    solved_panel.mode_box.setCurrentText("Profile")
    solved_panel.contact_box.setCurrentText("C2")


@needs_limb_profile
def test_live_counts_down_to_the_beads_and_then_follows_the_clock(solved_panel):
    solution = solved_panel.solution
    solved_panel.follow_live()
    try:
        last_bead = solution.to_utc(solution.c2_limb)

        solved_panel.set_current_time(last_bead - timedelta(minutes=5))
        assert solved_panel.view.countdown in ("C2 beads in 4:34", "C2 beads in 4:35")

        solved_panel.set_current_time(last_bead - timedelta(seconds=2))
        assert solved_panel.view.countdown is None
        assert solved_panel.view.live_hours is not None
        assert solved_panel.time_label.text() == "C2 -2.0 s"
    finally:
        solved_panel.follow_box.setCurrentText("Free")


@needs_limb_profile
def test_an_unsolved_bead_window_does_not_break_the_summary(solved_panel):
    window = solved_panel.solution.windows["C3"]
    solved_panel.solution.windows["C3"] = limb_correction.BeadWindow(
        window.start, window.end, False, window.max_arc_deg, window.search_limit_seconds)
    try:
        solved_panel.refresh()
        assert "/-s" in solved_panel.summary.text()
    finally:
        solved_panel.solution.windows["C3"] = window
        solved_panel.refresh()


def test_a_solve_for_an_older_location_is_ignored(monkeypatch):
    panel = BeadsPanel()
    monkeypatch.setattr("solareclipseworkbench.limb_ui.solve_limb", lambda *args: None)
    panel.set_context(DATE, LON, LAT, ALT)
    stale = panel._context
    panel.set_context(DATE, 0.0, 0.0, 0.0)

    panel._on_solved(stale, object())

    assert panel.solution is None
    assert panel.summary.text() == "Solving the lunar limb profile..."
    panel.deleteLater()
