"""Tests for load-time validation of the voice prompts used in a script."""

import csv
import glob
import os

from solareclipseworkbench.notifications import Notifications, SOUND_PATH, check_notification


def test_every_notification_has_a_sound_file():
    """The enum and the sound directory must not drift apart."""
    missing = [item.name for item in Notifications if not (SOUND_PATH / item.value).is_file()]
    assert missing == [], f"notifications without a sound file: {missing}"


def test_known_notification_is_accepted():
    assert check_notification("C1_IN_60_SECONDS") is None


def test_surrounding_whitespace_is_tolerated():
    """Scripts are comma-separated, so a prompt often arrives padded."""
    assert check_notification("  C1  ") is None


def test_typo_is_rejected_with_a_suggestion():
    problem = check_notification("C1_IN_60_SECOND")
    assert problem is not None
    assert "C1_IN_60_SECONDS" in problem


def test_unknown_notification_is_rejected():
    problem = check_notification("TOTALITY_NOW")
    assert problem is not None
    assert "TOTALITY_NOW" in problem


def test_lowercase_is_rejected():
    """Lookup is case-sensitive, so lowercase would raise when the job fires."""
    assert check_notification("c1_in_60_seconds") is not None


def test_empty_notification_is_rejected():
    assert check_notification("") is not None


def test_production_scripts_have_no_unknown_prompts():
    """The scripts flown on eclipse day must resolve every prompt they use."""
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
    problems = []
    for path in sorted(glob.glob(os.path.join(scripts_dir, "20260812_*.txt"))):
        for line in open(path):
            line = line.strip()
            if not line.startswith("voice_prompt"):
                continue
            parts = next(csv.reader([line], skipinitialspace=True))
            name = parts[4] if len(parts) > 4 else ""
            problem = check_notification(name)
            if problem is not None:
                problems.append(f"{os.path.basename(path)}: {problem}")
    assert problems == [], "\n".join(problems)
