"""Cameras set to 1/2 EV exposure steps (Issue #169)."""

import pytest

from solareclipseworkbench import camera as cam
from solareclipseworkbench.bracketing import (
    STANDARD_STEPS,
    BracketSpec,
    bracket_deviation,
    bracket_exposures,
    exposure_step,
    nearest_shutter_choices,
)
from solareclipseworkbench.camera_check import OK, WARNING, TestReport as Report, check_exposure_step

THIRDS = ["1/4000", "1/3200", "1/2500", "1/2000", "1/1600", "1/1250", "1/1000", "1/800", "1/640", "1/500",
          "1/400", "1/320", "1/250", "1/200", "1/160", "1/125", "1/100", "1/80", "1/60", "1/50", "1/40",
          "1/30", "1/25", "1/20", "1/15", "1/13", "1/10", "1/8", "1/6", "1/5", "1/4", "0.3", "0.4", "0.5",
          "0.6", "0.8", "1", "1.3", "1.6", "2", "2.5", "3.2", "4", "5", "6", "8", "10", "13", "15", "20",
          "25", "30", "bulb"]
HALVES = ["1/4000", "1/3000", "1/2000", "1/1500", "1/1000", "1/750", "1/500", "1/350", "1/250", "1/180",
          "1/125", "1/90", "1/60", "1/45", "1/30", "1/20", "1/15", "1/10", "1/8", "1/6", "1/4", "0.3",
          "0.5", "0.7", "1", "1.5", "2", "3", "4", "6", "8", "10", "15", "20", "30", "bulb"]
FULL = ["1/4000", "1/2000", "1/1000", "1/500", "1/250", "1/125", "1/60", "1/30", "1/15", "1/8"]
SECONDS = cam._parse_shutter_speed_seconds


@pytest.mark.parametrize("choices, step", [(THIRDS, 1 / 3), (HALVES, 1 / 2), (FULL, 1.0)])
def test_exposure_step_from_the_shutter_speeds(choices, step):
    assert exposure_step(choices, SECONDS) == pytest.approx(step)


def test_short_list_gives_no_step():
    assert exposure_step(["1/125", "1/60", "1/30"], SECONDS) is None


def test_third_stop_bracket_on_a_half_stop_camera_is_off():
    spec = BracketSpec(1 / 3, 5)
    speeds = nearest_shutter_choices(HALVES, bracket_exposures(1 / 60, spec), SECONDS)
    assert bracket_deviation(speeds, 1 / 60, spec.ev_offsets(), SECONDS) > 0.17


def test_full_stop_bracket_on_a_half_stop_camera_is_exact():
    spec = BracketSpec(1.0, 5)
    speeds = nearest_shutter_choices(HALVES, bracket_exposures(1 / 60, spec), SECONDS)
    assert speeds == ["1/250", "1/125", "1/60", "1/30", "1/15"]
    assert bracket_deviation(speeds, 1 / 60, spec.ev_offsets(), SECONDS) < 0.1


def test_half_stops_are_offered_for_untested_cameras():
    assert 0.5 in STANDARD_STEPS and 1.5 in STANDARD_STEPS


@pytest.mark.parametrize("vendor", ["Canon", "Nikon"])
def test_half_stops_are_fine_for_canon_and_nikon(vendor):
    report = Report()
    check_exposure_step(HALVES, vendor, report)
    assert [(i.status, i.title) for i in report.items] == [(OK, "Exposure step 1/2 EV")]


def test_sony_with_half_stops_is_warned():
    report = Report()
    check_exposure_step(HALVES, "Sony", report)
    assert report.items[0].status == WARNING
    assert "1/3 EV" in report.items[0].title


def test_sony_with_third_stops_is_fine():
    report = Report()
    check_exposure_step(THIRDS, "Sony", report)
    assert report.items[0].status == OK
