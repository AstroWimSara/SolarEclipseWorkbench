"""The wizard reads the camera's brackets and writes take_bracket for the corona series (Issue #171)."""

import csv
from unittest.mock import MagicMock

import pytest

from solareclipseworkbench.bracketing import is_native, native_brackets, parse_bracket
from solareclipseworkbench.camera_check import (
    CameraProfile,
    ScriptCommand,
    TestReport as Report,
    adapt_script_lines,
    check_brackets,
    ExposureLimits,
    read_brackets,
)
from solareclipseworkbench.command_timing import DEFAULT_PROFILE, bracket_duration_s, bracket_planning_s
from solareclipseworkbench.wizard import PhenomenaPage, SummaryPage

CANON = {"aeb": ["off", "+/- 1/3", "+/- 2/3", "+/- 1", "+/- 2", "+/- 3"]}
NIKON = {"aebracketingstep": ["1/3 EV", "2/3 EV", "1 EV", "2 EV", "3 EV"],
         "aebracketingpattern": ["2 images (normal and under)", "3 images (normal, under and over)",
                                 "5 images (normal, under and over)"]}
SONY = {"capturemode": ["Single Shooting", "Bracketing S 0.3 Steps 3 Pictures",
                        "Bracketing C 0.3 Steps 3 Pictures", "Bracketing C 1.0 Steps 3 Pictures",
                        "Bracketing C 1.0 Steps 5 Pictures", "Bracketing C 3.0 Steps 5 Pictures"]}


# --- What the camera takes itself ---------------------------------------------

def test_canon_brackets_every_step_with_menu_frame_counts():
    brackets = native_brackets("Canon", CANON)
    assert "1/3 3" in brackets and "1 5" in brackets and "3 7" in brackets
    assert len(brackets) == 5 * 3


def test_nikon_brackets_combine_steps_and_odd_patterns():
    brackets = native_brackets("Nikon", NIKON)
    assert "2/3 3" in brackets and "3 5" in brackets
    assert not any(b.endswith(" 2") for b in brackets)
    assert len(brackets) == 5 * 2


def test_sony_brackets_are_its_continuous_modes():
    assert native_brackets("Sony", SONY) == ["1/3 3", "1 3", "1 5", "3 5"]


def test_no_bracketing_widgets():
    assert native_brackets("Canon", {}) == []
    assert native_brackets(None, CANON) == []


def test_native_bracket_matches_other_spellings():
    native = native_brackets("Sony", SONY)
    assert is_native("1.0 5", native)
    assert is_native("0.3 3", native)
    assert not is_native("2 5", native)


def test_planning_is_never_shorter_than_the_load_time_estimate():
    for bracket in ("1 3", "2/3 5", "3 9"):
        assert bracket_planning_s("1/15", bracket) >= bracket_duration_s("1/15", DEFAULT_PROFILE, bracket)


def test_profile_keeps_the_brackets():
    profile = CameraProfile(camera="Sony ILCE-7RM3A", vendor="Sony", brackets=["1 3", "1 5"])
    assert CameraProfile.from_dict(profile.to_dict()).brackets == ["1 3", "1 5"]
    assert CameraProfile.from_dict({"camera": "old profile"}).brackets == []


# --- Verify with Camera --------------------------------------------------------

class _Widget:
    def __init__(self, choices):
        self.choices = choices

    def count_choices(self):
        return len(self.choices)

    def get_choice(self, i):
        return self.choices[i]


class _Config:
    def __init__(self, widgets):
        self.widgets = widgets

    def get_child_by_name(self, name):
        if name not in self.widgets:
            raise Exception(name)
        return _Widget(self.widgets[name])


def _bracket(text):
    return ScriptCommand("take_bracket", "C2", "+", "0:00:20.0", "cam", ["cam", "1/60", "5.6", "400", text], "")


def _titles(report):
    return [item.title for item in report.items]


def test_read_brackets_from_the_camera_config():
    assert read_brackets(_Config(SONY), "Sony") == ["1/3 3", "1 3", "1 5", "3 5"]


def test_check_native_brackets():
    report = Report()
    check_brackets(_Config(SONY), "Sony", [_bracket("1 3"), _bracket("1.0 5")], report)
    assert _titles(report) == ["The camera takes every bracket itself"]


def test_check_software_and_invalid_brackets():
    report = Report()
    check_brackets(_Config(SONY), "Sony", [_bracket("2 5"), _bracket("1 4")], report)
    titles = _titles(report)
    assert any(t.startswith("Bracket not understood") for t in titles)
    assert "The camera does not take every bracket itself" in titles


def test_check_reminds_canon_of_the_menu_setting():
    report = Report()
    check_brackets(_Config(CANON), "Canon", [_bracket("1 5"), _bracket("2 5")], report)
    item = next(i for i in report.items if i.title == "Check the number of bracketed shots on the camera")
    assert "set the camera to 5" in item.detail


def test_check_warns_canon_of_different_frame_counts():
    # The menu setting applies to every bracket: a 3-frame bracket with 5 set is not centred
    report = Report()
    check_brackets(_Config(CANON), "Canon", [_bracket("1 3"), _bracket("1 5")], report)
    assert "The brackets use different numbers of frames" in _titles(report)
    assert "Check the number of bracketed shots on the camera" not in _titles(report)


def test_script_without_brackets_is_not_checked():
    report = Report()
    check_brackets(_Config(CANON), "Canon", [], report)
    assert report.items == []


def test_fitting_keeps_the_bracket_quoted():
    profile = CameraProfile(camera="cam", vendor="Canon", shutter_speeds=["1/50", "1/100"], isos=[400])
    line = 'take_bracket, C2, +, 0:00:20.0, cam, 1/60, 5.6, 400, "1 2/3 5", "Corona"'
    lines, _ = adapt_script_lines([line], "cam", profile, ExposureLimits(100, 6400, 2.8, 22))
    parts = next(csv.reader([lines[0]], skipinitialspace=True))
    assert parts[8] == "1 2/3 5"
    assert '"1 2/3 5"' in lines[0]


# --- Phenomena page ------------------------------------------------------------

def _page(profile):
    page = PhenomenaPage()
    wizard = MagicMock()
    wizard.field.side_effect = lambda key: {"camera_name": "cam"}.get(key)
    wizard.camera_profiles = {"cam": profile} if profile else {}
    wizard.config_manager = None
    page.wizard = lambda: wizard
    page._fill_bracket_options()
    return page


def _items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_untested_camera_gets_standard_brackets():
    page = _page(None)
    assert _items(page.bracket_step_combo)[0] == "1/3"
    assert "1 2/3" in _items(page.bracket_step_combo)
    assert _items(page.bracket_frames_combo) == ["3", "5", "7", "9"]
    assert page.bracket_step_combo.currentText() == "1"
    assert "not tested" in page.bracket_note.text()


def test_tested_camera_offers_only_its_own_brackets():
    page = _page(CameraProfile(camera="cam", vendor="Sony", brackets=native_brackets("Sony", SONY)))
    assert _items(page.bracket_step_combo) == ["1/3", "1", "3"]
    page.bracket_step_combo.setCurrentText("1")
    assert _items(page.bracket_frames_combo) == ["3", "5"]
    page.bracket_step_combo.setCurrentText("1/3")
    assert _items(page.bracket_frames_combo) == ["3"]


def test_canon_note_names_the_menu_setting():
    page = _page(CameraProfile(camera="cam", vendor="Canon", brackets=native_brackets("Canon", CANON)))
    page.bracket_frames_combo.setCurrentText("5")
    assert "Number of bracketed shots" in page.bracket_note.text()
    assert "to 5" in page.bracket_note.text()


def test_bracket_options_follow_the_corona_checkbox():
    page = _page(None)
    page.bracket_check.setChecked(True)
    assert page.bracket_step_combo.isEnabled()
    page.corona_check.setChecked(False)
    assert not page.bracket_check.isEnabled()
    assert not page.bracket_step_combo.isEnabled()


# --- Generated script ------------------------------------------------------------

FIELDS = {
    'eclipse_name': '2026 Spain Total Solar Eclipse', 'eclipse_date': 'August 12, 2026', 'eclipse_type': 'Total',
    'location': 'Valencia, Spain', 'latitude': '39.47', 'longitude': '-0.38', 'altitude': '16',
    'camera_name': 'Canon EOS R5', 'focal_length': 600, 'aperture_min': 5.6, 'aperture_max': 32,
    'preferred_iso': 400, 'iso_min': 100, 'iso_max': 6400, 'filter_value': '5.0',
    'c1_c4': False, 'equispaced': False, 'diamond': False, 'bailys': False, 'corona': True,
    'chromosphere': False, 'prominences': False, 'sync_enabled': False, 'voice_enabled': False,
}


def _script(**fields):
    wizard = MagicMock()
    values = dict(FIELDS, **fields)
    wizard.field.side_effect = lambda key: values.get(key)
    page = SummaryPage()
    page.wizard = lambda: wizard
    rows = [next(csv.reader([line], skipinitialspace=True)) for line in page._generate_script().split('\n')
            if line and not line.startswith('#')]
    return [r for r in rows if r[0].startswith('take_')]


def _seconds(offset):
    h, m, s = offset.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


@pytest.fixture(scope="module")
def bracketed():
    return _script(corona_bracket=True, bracket_step="1", bracket_frames="3")


def test_corona_series_is_bracketed(bracketed):
    corona = [r for r in bracketed if r[-1].startswith("Corona")]
    assert corona, "no corona shots generated"
    assert all(r[0] == "take_bracket" and r[8] == "1 3" for r in corona)
    for r in corona:
        assert parse_bracket(r[8]).frames == 3


def test_brackets_are_spaced_by_their_duration(bracketed):
    corona = sorted((r for r in bracketed if r[0] == "take_bracket" and r[1] == "C2"),
                    key=lambda r: _seconds(r[3]))
    for first, second in zip(corona, corona[1:]):
        gap = _seconds(second[3]) - _seconds(first[3])
        assert gap >= bracket_planning_s(first[5], first[8]) - 1e-6, (first, second)


def test_without_bracketing_the_corona_series_is_single_pictures():
    rows = _script(corona_bracket=False)
    assert not any(r[0] == "take_bracket" for r in rows)
    assert any(r[0] == "take_picture" and r[-1].startswith("Corona") for r in rows)
