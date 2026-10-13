"""The take_bracket bracket: '<EV step> <frames>' for every brand, plus the older forms (Issue #161)."""

import pytest

from solareclipseworkbench import camera as cam
from solareclipseworkbench import utils
from solareclipseworkbench.bracketing import (
    BracketSpec,
    bracket_exposures,
    format_ev,
    match_ev_choice,
    match_sony_mode,
    nearest_shutter_choices,
    parse_bracket,
    parse_ev,
)
from solareclipseworkbench.camera_check import ScriptCommand, estimate_frames
from solareclipseworkbench.command_timing import bracket_duration_s, picture_duration_s

CANON_AEB = ["off", "+/- 1/3", "+/- 2/3", "+/- 1", "+/- 1 1/3", "+/- 1 2/3", "+/- 2",
             "+/- 2 1/3", "+/- 2 2/3", "+/- 3"]
SONY_MODES = ["Single Shooting", "Continuous Shooting Hi",
              "Bracketing S 0.3 Steps 3 Pictures", "Bracketing C 0.3 Steps 3 Pictures",
              "Bracketing C 0.7 Steps 5 Pictures", "Bracketing C 1.0 Steps 3 Pictures",
              "Bracketing C 1.0 Steps 5 Pictures", "Bracketing C 3.0 Steps 5 Pictures"]
SPEEDS = ["1/4000", "1/2000", "1/1000", "1/500", "1/250", "1/125", "1/60", "1/30", "1/15", "1/8",
          "1/4", "0.5", "1", "2", "4", "bulb"]


# --- Parsing ------------------------------------------------------------------

@pytest.mark.parametrize("text, ev, frames", [
    ("1 3", 1.0, 3),
    ("0.7 5", 2 / 3, 5),
    ("1 2/3 5", 5 / 3, 5),
    ("2/3 7", 2 / 3, 7),
    ("1.0 9", 1.0, 9),
    ("0.5 3", 0.5, 3),
    (' "1 3" ', 1.0, 3),
])
def test_ev_step_and_frames(text, ev, frames):
    spec = parse_bracket(text)
    assert spec.ev_step == pytest.approx(ev)
    assert spec.frames == frames
    assert spec.mode_name is None


@pytest.mark.parametrize("text, ev", [("+/- 1/3", 1 / 3), ("+/- 1", 1.0), ("+/- 1 2/3", 5 / 3), ("+/- 3", 3.0)])
def test_canon_syntax_still_means_five_frames(text, ev):
    spec = parse_bracket(text)
    assert spec.ev_step == pytest.approx(ev)
    assert spec.frames == 5


def test_sony_mode_name_is_kept():
    spec = parse_bracket("Bracketing C 3.0 Steps 5 Pictures")
    assert (spec.ev_step, spec.frames) == (3.0, 5)
    assert spec.mode_name == "Bracketing C 3.0 Steps 5 Pictures"


def test_sony_third_step_is_read_as_a_third():
    assert parse_bracket("Bracketing C 0.3 Steps 3 Pictures").ev_step == pytest.approx(1 / 3)


@pytest.mark.parametrize("text", [
    "", "1", "1 2/3", "1 4", "1 1", "1 11", "0 3", "4 3", "-1 3", "abc", "1 three", "1/0 3",
])
def test_invalid_brackets_are_rejected(text):
    with pytest.raises(ValueError):
        parse_bracket(text)


@pytest.mark.parametrize("ev, text", [(1 / 3, "1/3"), (2 / 3, "2/3"), (1.0, "1"), (5 / 3, "1 2/3"),
                                      (0.5, "1/2"), (1.5, "1 1/2"), (3.0, "3")])
def test_format_ev(ev, text):
    assert format_ev(ev) == text
    assert parse_ev(text) == pytest.approx(ev)


# --- Frames and exposures -----------------------------------------------------

def test_offsets_are_centred_darkest_first():
    assert BracketSpec(1.0, 5).ev_offsets() == [-2, -1, 0, 1, 2]
    assert BracketSpec(2 / 3, 3).ev_offsets() == pytest.approx([-2 / 3, 0, 2 / 3])


def test_exposures_of_a_bracket():
    assert bracket_exposures(1 / 60, BracketSpec(1.0, 3)) == pytest.approx([1 / 120, 1 / 60, 1 / 30])


def test_nearest_shutter_choices_by_stops():
    exposures = bracket_exposures(1 / 60, BracketSpec(1.0, 5))
    assert nearest_shutter_choices(SPEEDS, exposures, cam._parse_shutter_speed_seconds) == \
        ["1/250", "1/125", "1/60", "1/30", "1/15"]


def test_nearest_shutter_choices_clamp_at_the_fastest_speed():
    exposures = bracket_exposures(1 / 2000, BracketSpec(2.0, 3))
    assert nearest_shutter_choices(SPEEDS, exposures, cam._parse_shutter_speed_seconds) == \
        ["1/4000", "1/2000", "1/500"]


# --- Camera choices -----------------------------------------------------------

def test_canon_aeb_choice():
    assert match_ev_choice(CANON_AEB, parse_bracket("1 2/3 5").ev_step) == "+/- 1 2/3"
    assert match_ev_choice(CANON_AEB, parse_bracket("0.7 3").ev_step) == "+/- 2/3"


def test_no_choice_for_a_half_stop_on_a_third_stop_camera():
    assert match_ev_choice(CANON_AEB, 0.5) is None


def test_nikon_step_choice():
    assert match_ev_choice(["1/3 EV", "2/3 EV", "1 EV", "2 EV", "3 EV"], 2 / 3) == "2/3 EV"


def test_sony_continuous_mode_is_chosen():
    assert match_sony_mode(SONY_MODES, parse_bracket("1 5")) == "Bracketing C 1.0 Steps 5 Pictures"
    assert match_sony_mode(SONY_MODES, parse_bracket("0.3 3")) == "Bracketing C 0.3 Steps 3 Pictures"


def test_sony_without_matching_mode():
    assert match_sony_mode(SONY_MODES, parse_bracket("2 5")) is None
    assert match_sony_mode(SONY_MODES, parse_bracket("1 7")) is None


# --- Timing, frame count, scheduling ------------------------------------------

def test_bracket_duration_counts_all_exposures():
    # 1/2 + 1 + 2 s of exposure plus one picture overhead
    assert bracket_duration_s("1", bracket="1 3") == pytest.approx(3.5 + picture_duration_s("0"))


def test_bracket_duration_without_readable_bracket_counts_one_frame():
    assert bracket_duration_s("1", bracket="nonsense") == picture_duration_s("1")
    assert bracket_duration_s("1") == picture_duration_s("1")


def test_estimate_frames_uses_the_bracket():
    def bracket(text):
        return ScriptCommand("take_bracket", "C2", "+", "0:00:05.0", "Canon EOS R", ["Canon EOS R", "1/60", "5.6", "400", text], "")

    assert estimate_frames([bracket("1 3"), bracket("1 7")], "Canon") == 10
    assert estimate_frames([bracket("+/- 1"), bracket("nonsense")], "Canon") == 10


def test_invalid_bracket_is_reported_when_the_script_is_loaded(monkeypatch):
    reported = []
    monkeypatch.setattr(utils.hardware_problems, "report", lambda *a, **kw: reported.append(a))
    line = 'take_bracket, C2, +, 0:00:05.0, Canon EOS R, 1/60, 5.6, 400, "1 4", "Corona"'
    assert utils.schedule_command(None, {}, line, {}, None, None, None) is None
    assert len(reported) == 1
    assert "3, 5, 7 or 9" in reported[0][1]


def test_virtual_camera_takes_one_capture_per_frame(monkeypatch):
    virtual = cam.VirtualCamera()
    captures = []
    monkeypatch.setattr(virtual, "capture", lambda *a, **kw: captures.append(1))
    cam.take_bracket.__wrapped__(virtual, cam.CameraSettings("VirtualCamera", "1/60", "5.6", 400), "1 7")
    assert len(captures) == 7
