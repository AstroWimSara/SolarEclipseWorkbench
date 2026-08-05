"""A script line naming a moment that does not exist must not vanish quietly.

`BEADS_C2` and the other limb-corrected moments only exist when the correction
is on and the lunar limb profile is installed, so the same script can schedule
perfectly one day and lose its contact bursts the next.  Loading is the last
moment that can be noticed and fixed.
"""

from datetime import datetime, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from skyfield.units import Angle

from solareclipseworkbench.reference_moments import ReferenceMomentInfo
from solareclipseworkbench.utils import schedule_commands

C2 = datetime(2026, 8, 12, 18, 29, 13, tzinfo=timezone.utc)


@pytest.fixture
def scheduler():
    scheduler = BackgroundScheduler()
    yield scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


@pytest.fixture
def moments():
    return {"C2": ReferenceMomentInfo(C2, Angle(degrees=250.0), 8.7, timezone.utc)}


def _script(tmp_path, *lines):
    path = tmp_path / "script.txt"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_an_unknown_moment_is_reported_with_the_lines_it_cost(tmp_path, scheduler, moments):
    filename = _script(
        tmp_path,
        'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"',
        'voice_prompt, BEADS_C2_START, -, 0:00:01.0, C2_IN_5_SECONDS, "5 to totality"',
        'voice_prompt, BEADS_C2_START, +, 0:00:01.0, C2_IN_5_SECONDS, "5 to totality"',
    )

    unknown = schedule_commands(filename, scheduler, moments, {}, None, None, None)

    assert unknown == {"BEADS_C2_START": 2}
    # The line that could be scheduled still was.
    assert len(scheduler.get_jobs()) == 1


def test_a_script_that_names_only_known_moments_reports_nothing(tmp_path, scheduler, moments):
    filename = _script(tmp_path, 'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"')

    unknown = schedule_commands(filename, scheduler, moments, {}, None, None, None)

    assert unknown == {}
    assert len(scheduler.get_jobs()) == 1
