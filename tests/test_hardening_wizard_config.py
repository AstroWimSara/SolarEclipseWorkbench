"""Hardening of the saved configuration (~/.sew_wizard_config.json) and of typed coordinates.

An old, hand-edited or half-written configuration used to fail later on a missing
key (or, for a damaged file, be replaced by an empty one on the next save), and a
coordinate typed with a decimal comma, which the locale-aware validators accept,
did not read as a number.
"""
import json
import logging
from pathlib import Path

import pytest

from solareclipseworkbench.location_ui import ConfigManager, parse_number


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ConfigManager, "_save_failure_reported", True)   # no message box
    return tmp_path


@pytest.mark.parametrize("text, value", [("50.85", 50.85), ("50,85", 50.85), (" -4,35 ", -4.35), ("12", 12.0)])
def test_parse_number_accepts_a_decimal_comma(text, value):
    assert parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "  ", "abc", "nan", "inf", "1,2,3"])
def test_parse_number_refuses_what_is_not_a_finite_number(text):
    with pytest.raises(ValueError):
        parse_number(text)


def test_an_incomplete_configuration_is_repaired(home):
    (home / ".sew_wizard_config.json").write_text(json.dumps({
        "cameras": [{"focal_length": 400}, {"name": "Canon EOS R5", "focal_length": 600}, "junk"],
        "locations": "oops",
        "last_used": None,
        "camera_aliases": [],
    }))
    manager = ConfigManager()
    assert [c["name"] for c in manager.get_cameras()] == ["Canon EOS R5"]
    assert manager.get_locations() == []
    assert manager.get_last_used_camera() is None
    assert manager.get_camera_aliases() == {}
    manager.set_last_used_location("Somewhere")      # used to raise TypeError on last_used None
    assert manager.get_last_used_location() == "Somewhere"


def test_a_configuration_that_is_not_an_object_gives_the_default(home):
    (home / ".sew_wizard_config.json").write_text("[1, 2, 3]")
    assert ConfigManager().get_cameras() == []


def test_a_damaged_configuration_is_kept_aside(home):
    damaged = '{"cameras": [{"name": "Nikon Z8"'
    (home / ".sew_wizard_config.json").write_text(damaged)
    manager = ConfigManager()
    assert manager.get_cameras() == []
    manager.add_location("Here", 1.0, 2.0, 3.0)
    # The next save no longer destroys what could still be recovered by hand
    assert (home / ".sew_wizard_config.json.corrupt").read_text() == damaged
    assert json.loads((home / ".sew_wizard_config.json").read_text())["locations"][0]["name"] == "Here"


def test_a_failed_save_leaves_the_file_intact(home, caplog):
    manager = ConfigManager()
    manager.add_location("Here", 1.0, 2.0, 3.0)
    before = (home / ".sew_wizard_config.json").read_text()
    manager.config["not_json"] = object()
    with caplog.at_level(logging.WARNING):
        manager.save_config()                        # used to raise TypeError after truncating the file
    assert (home / ".sew_wizard_config.json").read_text() == before
    assert not (home / ".sew_wizard_config.json.tmp").exists()
    assert any("Could not save the configuration" in r.getMessage() for r in caplog.records)
