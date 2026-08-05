"""A script written for a longer totality steals third contact.

The last corona ladder of a 110 s script run against a 100 s totality is still
holding the camera when the bead exposure for third contact should load, so the
bead burst fires at the corona exposure — fewer frames, none of them beads, and
nothing says anything until the photographs are reviewed.  Loading is the last
moment another file can still be chosen.
"""

from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from skyfield.units import Angle

from solareclipseworkbench import utils
from solareclipseworkbench.reference_moments import ReferenceMomentInfo
from solareclipseworkbench.utils import TOTALITY_OVERRUN_MARGIN_S, warn_if_script_outlasts_totality

C2 = datetime(2026, 8, 12, 18, 29, 13, tzinfo=timezone.utc)
TOTALITY_S = 100


@pytest.fixture
def scheduler():
    # Running, because a job only gets its next_run_time when the scheduler
    # takes it; the jobs below sit in 2026 and never fire during the test.
    scheduler = BackgroundScheduler()
    scheduler.start()
    yield scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
    utils.JOB_COMMANDS.clear()


@pytest.fixture
def moments():
    return {
        "C2": ReferenceMomentInfo(C2, Angle(degrees=250.0), 8.7, timezone.utc),
        "C3": ReferenceMomentInfo(C2 + timedelta(seconds=TOTALITY_S), Angle(degrees=251.0), 8.5,
                                  timezone.utc),
    }


def _job_at(scheduler, seconds_after_c2, command):
    job = scheduler.add_job(lambda: None, trigger=DateTrigger(run_date=C2 + timedelta(seconds=seconds_after_c2)))
    utils.JOB_COMMANDS[job.id] = command
    return job


def test_a_frame_inside_the_third_contact_reserve_is_reported(scheduler, moments):
    _job_at(scheduler, TOTALITY_S - 4.4, "take_bracket")

    overrun = warn_if_script_outlasts_totality(scheduler, moments)

    assert overrun == pytest.approx(TOTALITY_OVERRUN_MARGIN_S - 4.4, abs=0.01)


def test_a_script_that_ends_in_time_is_not_reported(scheduler, moments):
    _job_at(scheduler, TOTALITY_S - TOTALITY_OVERRUN_MARGIN_S - 1, "take_bracket")

    assert warn_if_script_outlasts_totality(scheduler, moments) == 0.0


def test_a_voice_prompt_in_the_reserve_is_not_an_overrun(scheduler, moments):
    """A countdown to third contact belongs there — it does not hold the shutter."""
    _job_at(scheduler, TOTALITY_S - 3, "voice_prompt")

    assert warn_if_script_outlasts_totality(scheduler, moments) == 0.0


def test_without_both_contacts_there_is_nothing_to_compare(scheduler, moments):
    _job_at(scheduler, TOTALITY_S - 3, "take_bracket")

    assert warn_if_script_outlasts_totality(scheduler, {"C2": moments["C2"]}) == 0.0
