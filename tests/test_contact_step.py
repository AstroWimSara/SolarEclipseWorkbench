"""The C1 and C4 shots are spaced so the shot after C1 (before C4) shows the Moon's bite.

Nothing is visible at first contact itself.  How soon the bite shows depends on
the image scale: tens of seconds with a short lens, a few with a telescope
(discussion #192: at 75 mm a burst around C1 could not show it).
"""
import copy
import csv
from datetime import date, datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from astropy.time import Time

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.contact_visibility import (
    contact_step_s, pixel_scale_arcsec, sun_diameter_arcsec, visible_depth_arcsec,
)
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.utils import schedule_commands

from test_wizard_beads import LAT, LON, ALT, _script

# Discussion #192: Bodega Winery, Spain, 2026-08-12
SITE = ("2026-08-12", 41.34186, -1.11663, 682.0)


def test_pixel_scale():
    # Sony A7R III (4.5 µm) at 75 mm: about 12 arcseconds per pixel
    assert pixel_scale_arcsec(75, 4.5) == pytest.approx(12.38, abs=0.01)


def test_the_bite_must_beat_both_the_pixels_and_the_seeing():
    assert visible_depth_arcsec(75, 4.5) == pytest.approx(2 * 12.38, abs=0.05)
    assert visible_depth_arcsec(4000, 3.0) == 3.0          # seeing-limited


def test_sun_diameter_follows_the_earth_sun_distance():
    assert sun_diameter_arcsec(date(2026, 1, 4)) > 1950 > 1890 > sun_diameter_arcsec(date(2026, 7, 4))


def test_short_lens_waits_tens_of_seconds():
    steps = contact_step_s(*SITE, focal_length_mm=75, pixel_size_um=4.5)
    assert 35 <= steps["C1"] <= 55
    assert 30 <= steps["C4"] <= 50


def test_longer_focal_length_shows_the_bite_sooner():
    short = contact_step_s(*SITE, focal_length_mm=75, pixel_size_um=4.5)
    long = contact_step_s(*SITE, focal_length_mm=400, pixel_size_um=4.5)
    telescope = contact_step_s(*SITE, focal_length_mm=2000, pixel_size_um=3.76)
    assert short["C1"] > long["C1"] > telescope["C1"] >= 1
    assert short["C4"] > long["C4"] > telescope["C4"] >= 1


def test_no_eclipse_at_the_location():
    # Sydney does not see the 2026-08-12 eclipse
    assert contact_step_s("2026-08-12", -33.87, 151.21, 0, 75, 4.5) is None


# --- The wizard ------------------------------------------------------------------

def _offsets(script, reference):
    """Seconds relative to the reference of every take_picture line written against it."""
    result = {}
    for line in script.split('\n'):
        if line.startswith('take_picture') and f', {reference}, ' in line:
            fields = next(csv.reader([line], skipinitialspace=True))
            h, m, s = fields[3].split(':')
            seconds = (int(h) * 60 + int(m)) * 60 + float(s)
            result[fields[-1]] = seconds if fields[2] == '+' else -seconds
    return result


def _first_partial_after_c1(script, moments):
    """Seconds after C1 of the first partial-phase shot (written against C2)."""
    c2_offsets = _offsets(script, "C2")
    partials = [s for name, s in c2_offsets.items() if name.startswith("Partial C1-C2")]
    gap = (moments["C2"].time_utc - moments["C1"].time_utc).total_seconds()
    return min(partials) + gap


@pytest.fixture(scope="module")
def moments():
    result, _, _ = calculate_reference_moments(LON, LAT, ALT, Time("2026-08-12"))
    return result


def test_automatic_step_with_a_short_lens(moments):
    script = _script("Canon EOS R5", focal_length=75, pixel_size=4.5)
    expected = contact_step_s("2026-08-12", LAT, LON, ALT, 75, 4.5)

    c1 = _offsets(script, "C1")
    assert c1 == {f"First contact (C1-{expected['C1']}s)": -expected["C1"], "First contact (C1)": 0,
                  f"First contact (C1+{expected['C1']}s)": expected["C1"]}
    assert f"# Shots {expected['C1']}s apart: when the Moon's bite is visible at 75 mm" in script
    # The partial phase starts after the C1 + step shot
    assert _first_partial_after_c1(script, moments) > expected["C1"]


def test_manual_step(moments):
    script = _script("Canon EOS R5", focal_length=75, pixel_size=4.5, contact_step_auto=False, contact_step=20)
    assert set(_offsets(script, "C1").values()) == {-20, 0, 20}
    assert "# Shots 20s apart: set in the wizard" in script
    assert _first_partial_after_c1(script, moments) > 20


def test_a_step_is_never_shorter_than_a_picture():
    script = _script("Canon EOS R5", contact_step_auto=False, contact_step=1)
    assert min(abs(s) for s in _offsets(script, "C1").values() if s) >= 2


@pytest.mark.parametrize("focal_length", [75, 600])
def test_a_script_with_contact_steps_loads_without_warnings(moments, focal_length, tmp_path):
    path = tmp_path / "script.txt"
    path.write_text(_script("Sony ILCE-7RM3A", focal_length=focal_length, pixel_size=4.5))

    shift = datetime.now(timezone.utc) + timedelta(hours=3) - moments["C1"].time_utc
    future = {}
    for name, value in moments.items():
        if hasattr(value, "time_utc"):
            value = copy.copy(value)
            value.time_utc = value.time_utc + shift
        future[name] = value

    hardware_problems.drain()
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    try:
        schedule_commands(str(path), scheduler, future, {"Sony ILCE-7RM3A": object()}, None, None, None)
    finally:
        scheduler.shutdown(wait=False)
    assert [str(problem) for problem in hardware_problems.drain()] == []
