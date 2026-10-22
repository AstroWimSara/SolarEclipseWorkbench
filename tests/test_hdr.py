"""take_hdr: round-trip or one-way sequence, speeds chosen in EV (Issue #159)."""

import csv
import io
from unittest.mock import MagicMock

import pytest

from solareclipseworkbench import camera as cam
from solareclipseworkbench import scripts, utils
from solareclipseworkbench.bracketing import (
    HDR_ONE_WAY,
    HDR_ROUND_TRIP,
    hdr_native_bracket,
    hdr_offsets,
    hdr_speeds,
    native_brackets,
    parse_hdr_sequence,
)
from solareclipseworkbench.camera_check import ScriptCommand, estimate_frames
from solareclipseworkbench.command_timing import (HDR_FIXED_OVERHEAD_S, HDR_SHOT_OVERHEAD_S, TimingProfile,
                                                  hdr_duration_s)
from solareclipseworkbench.wizard import SummaryPage

THIRDS = ["1/4000", "1/3200", "1/2500", "1/2000", "1/1600", "1/1250", "1/1000", "1/800", "1/640", "1/500",
          "1/400", "1/320", "1/250", "1/200", "1/160", "1/125", "1/100", "1/80", "1/60", "1/50", "1/40",
          "1/30", "1/25", "1/20", "1/15", "1/13", "1/10", "1/8", "1/6", "1/5", "1/4", "0.3", "0.4", "0.5",
          "0.6", "0.8", "1", "bulb"]
HALVES = ["1/4000", "1/3000", "1/2000", "1/1500", "1/1000", "1/750", "1/500", "1/350", "1/250", "1/180",
          "1/125", "1/90", "1/60", "1/45", "1/30", "1/20", "1/15", "1/10", "1/8", "1/6", "1/4", "0.3",
          "0.5", "0.7", "1"]
SECONDS = cam._parse_shutter_speed_seconds


# --- Sequence -------------------------------------------------------------------

@pytest.mark.parametrize("text, sequence", [
    (None, HDR_ROUND_TRIP), ("", HDR_ROUND_TRIP), ("round-trip", HDR_ROUND_TRIP), (" One-Way ", HDR_ONE_WAY),
    ('"one-way"', HDR_ONE_WAY), ("down-up-down", HDR_ROUND_TRIP), ("down-up", HDR_ONE_WAY),
])
def test_sequence_names(text, sequence):
    assert parse_hdr_sequence(text) == sequence


def test_unknown_sequence_is_rejected():
    with pytest.raises(ValueError):
        parse_hdr_sequence("both-ways")


def test_round_trip_takes_the_longest_exposure_once():
    assert hdr_offsets(4) == [0, 1, 2, 3, 4, 3, 2, 1, 0]


def test_one_way_stops_at_the_longest_exposure():
    assert hdr_offsets(4, HDR_ONE_WAY) == [0, 1, 2, 3, 4]


# --- Shutter speeds in EV ----------------------------------------------------------

def test_speeds_on_a_third_stop_camera():
    speeds, stops = hdr_speeds(THIRDS, 1 / 1000, 3, HDR_ROUND_TRIP, SECONDS)
    assert stops == 3
    assert speeds == ["1/1000", "1/500", "1/250", "1/125", "1/250", "1/500", "1/1000"]


def test_speeds_on_a_half_stop_camera():
    """Moving 3 places per stop, as take_hdr used to, gives 1.5 stops per frame here."""
    speeds, _ = hdr_speeds(HALVES, 1 / 1000, 3, HDR_ONE_WAY, SECONDS)
    assert speeds == ["1/1000", "1/500", "1/250", "1/125"]


def test_speeds_are_clamped_to_the_slowest_speed():
    speeds, stops = hdr_speeds(THIRDS, 1 / 8, 6, HDR_ONE_WAY, SECONDS)
    assert stops == 3
    assert speeds == ["1/8", "1/4", "0.5", "1"]


# --- Camera bracketing for a one-way sequence ----------------------------------------

SONY = native_brackets("Sony", {"capturemode": ["Bracketing C 1.0 Steps 3 Pictures",
                                                "Bracketing C 1.0 Steps 5 Pictures"]})


def test_one_way_with_matching_sony_mode():
    assert hdr_native_bracket(4, HDR_ONE_WAY, SONY) == "1 5"
    assert hdr_native_bracket(2, HDR_ONE_WAY, SONY) == "1 3"


def test_no_camera_bracket_for_round_trip_odd_stops_or_missing_mode():
    assert hdr_native_bracket(4, HDR_ROUND_TRIP, SONY) is None
    assert hdr_native_bracket(3, HDR_ONE_WAY, SONY) is None
    assert hdr_native_bracket(6, HDR_ONE_WAY, SONY) is None


# --- Timing and frame count -------------------------------------------------------

def test_round_trip_duration_is_unchanged():
    start = 1 / 1000
    ramp = sum(start * 2 ** k for k in range(5)) + sum(start * 2 ** k for k in range(3, -1, -1))
    assert hdr_duration_s("1/1000", 4) == pytest.approx(ramp + 9 * HDR_SHOT_OVERHEAD_S + HDR_FIXED_OVERHEAD_S)


def test_a_slower_camera_gets_more_time_per_frame():
    # EOS R: 2.35 s per picture, an 8-frame one-way HDR from 1/640 took 15.7 s
    eos_r = TimingProfile(picture_overhead_s=2.35)
    assert hdr_duration_s("1/640", 7, HDR_ONE_WAY, eos_r) == pytest.approx(255 / 640 + 8 * 1.85 + HDR_FIXED_OVERHEAD_S)
    assert hdr_duration_s("1/640", 7, HDR_ONE_WAY, eos_r) > 15.7


def test_a_camera_at_the_default_overhead_keeps_the_default_estimate():
    # EOS 80D: planned at the 2 s default per picture, about 1.4 s per HDR frame
    assert hdr_duration_s("1/1000", 4, profile=TimingProfile(picture_overhead_s=2.0)) == pytest.approx(
        hdr_duration_s("1/1000", 4))


def test_busy_estimate_uses_the_camera_profile():
    profile = TimingProfile(picture_overhead_s=2.35)
    busy = utils.estimate_busy_s("take_hdr", ["cam", "1/640", "6.3", "100", "7", "one-way"], profile=profile)
    assert busy == pytest.approx(hdr_duration_s("1/640", 7, HDR_ONE_WAY, profile))


def test_one_way_is_shorter():
    assert hdr_duration_s("1/1000", 4, HDR_ONE_WAY) < hdr_duration_s("1/1000", 4)


def test_estimate_frames():
    def hdr(*fields):
        return ScriptCommand("take_hdr", "C2", "+", "0:00:30.0", "cam", ["cam", "1/1000", "5.6", "400", *fields], "")

    assert estimate_frames([hdr("4"), hdr("4", "one-way")], "Canon") == 9 + 5


def test_busy_estimate_uses_the_sequence():
    one_way = utils.estimate_busy_s("take_hdr", ["cam", "1/1000", "5.6", "400", "4", "one-way"])
    assert one_way == pytest.approx(hdr_duration_s("1/1000", 4, HDR_ONE_WAY))


# --- Script file ---------------------------------------------------------------------

def _convert(line):
    out = io.StringIO()
    scripts.convert_command(line, "C2", "+", "0:00:30.0", "", out)
    return next(csv.reader([out.getvalue().strip()], skipinitialspace=True))


def test_script_without_sequence_reads_as_before():
    parts = _convert('take_hdr, C2, +, 0:00:30.0, cam, 1/1000, 5.6, 400, 7, "HDR"')
    assert parts[4:] == ["cam", "1/1000", "5.6", "400", "7", "HDR"]


def test_script_with_sequence_keeps_it():
    parts = _convert('take_hdr, C2, +, 0:00:30.0, cam, 1/1000, 5.6, 400, 7, one-way, "HDR"')
    assert parts[4:] == ["cam", "1/1000", "5.6", "400", "7", "one-way", "HDR"]


@pytest.mark.parametrize("fields, message", [
    ("7, both-ways", "not understood"),
    ("0", "at least 1"),
    ("seven", "at least 1"),
])
def test_invalid_hdr_is_reported_when_the_script_is_loaded(monkeypatch, fields, message):
    reported = []
    monkeypatch.setattr(utils.hardware_problems, "report", lambda *a, **kw: reported.append(a))
    line = f'take_hdr, C2, +, 0:00:30.0, cam, 1/1000, 5.6, 400, {fields}, "HDR"'
    assert utils.schedule_command(None, {}, line, {}, None, None, None) is None
    assert len(reported) == 1 and message in reported[0][1]


def test_virtual_camera_takes_one_capture_per_frame(monkeypatch):
    virtual = cam.VirtualCamera()
    captures = []
    monkeypatch.setattr(virtual, "capture", lambda *a, **kw: captures.append(1))
    settings = cam.CameraSettings("VirtualCamera", "1/1000", "5.6", 400)
    cam.take_hdr.__wrapped__(virtual, settings, 4, HDR_ONE_WAY)
    cam.take_hdr.__wrapped__(virtual, settings, 4)
    assert len(captures) == 5 + 9


# --- Wizard --------------------------------------------------------------------------

FIELDS = {
    'eclipse_name': '2026 Spain Total Solar Eclipse', 'eclipse_date': 'August 12, 2026', 'eclipse_type': 'Total',
    'location': 'Valencia, Spain', 'latitude': '39.47', 'longitude': '-0.38', 'altitude': '16',
    'camera_name': 'Canon EOS R5', 'focal_length': 600, 'aperture_min': 5.6, 'aperture_max': 32,
    'preferred_iso': 400, 'iso_min': 100, 'iso_max': 6400, 'filter_value': '5.0',
    'c1_c4': False, 'equispaced': False, 'diamond': False, 'bailys': False, 'corona': False,
    'chromosphere': False, 'prominences': False, 'sync_enabled': False, 'voice_enabled': False,
    'hdr_burst': True, 'hdr_stops': 4, 'hdr_start_auto': False, 'hdr_start_speed': '1/1000',
    'hdr_iso_auto': True,
}


def _hdr_rows(**fields):
    wizard = MagicMock()
    values = dict(FIELDS, **fields)
    wizard.field.side_effect = lambda key: values.get(key)
    page = SummaryPage()
    page.wizard = lambda: wizard
    return [next(csv.reader([line], skipinitialspace=True)) for line in page._generate_script().split('\n')
            if line.startswith('take_hdr')]


def test_wizard_round_trip_line_is_unchanged():
    (row,) = _hdr_rows(hdr_one_way=False)
    assert row[8:] == ["4", "HDR at maximum eclipse"]


def test_wizard_one_way_line():
    (row,) = _hdr_rows(hdr_one_way=True)
    assert row[8:] == ["4", "one-way", "HDR at maximum eclipse"]
