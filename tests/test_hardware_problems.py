"""The rule these tests exist to defend: a hardware failure is never silent.

Anything that changes what lands on the memory card has to reach the person at
the telescope, and repeats must not turn into a flood.
"""

import pytest

from solareclipseworkbench import hardware_problems


@pytest.fixture(autouse=True)
def _clean():
    hardware_problems.clear()
    yield
    hardware_problems.clear()


def test_a_problem_is_queued_for_the_gui():
    hardware_problems.report("X-T4", "Exposure settings were not applied")

    assert hardware_problems.count() == 1
    assert hardware_problems.peek()[0].source == "X-T4"


def test_repeats_fold_into_a_count_rather_than_flooding():
    # A failure inside a burst can fire dozens of times per second.  It must not
    # become dozens of queued problems, or dozens of dialogs.
    for _ in range(50):
        hardware_problems.report("X-T4", "Exposure settings were not applied")

    assert hardware_problems.count() == 1
    assert hardware_problems.peek()[0].count == 50


def test_distinct_problems_stay_distinct():
    hardware_problems.report("X-T4", "Exposure settings were not applied")
    hardware_problems.report("Fuji SDK", "Detection failed")

    assert hardware_problems.count() == 2


def test_the_queue_is_bounded():
    for i in range(hardware_problems._MAX_PROBLEMS + 25):
        hardware_problems.report("X-T4", f"problem {i}")

    assert hardware_problems.count() == hardware_problems._MAX_PROBLEMS


def test_draining_empties_the_queue():
    hardware_problems.report("X-T4", "something")

    assert len(hardware_problems.drain()) == 1
    assert hardware_problems.count() == 0


def test_peeking_does_not_empty_the_queue():
    hardware_problems.report("X-T4", "something")

    hardware_problems.peek()

    assert hardware_problems.count() == 1


def test_reporting_never_raises():
    # This runs on worker threads and inside except blocks; if it could throw it
    # would mask the failure it is trying to describe.
    hardware_problems.report(None, None, detail=object(), severity="error")


def test_summary_shows_repeat_counts():
    for _ in range(3):
        hardware_problems.report("X-T4", "Exposure settings were not applied")

    summary = hardware_problems.summarise()

    assert "Exposure settings were not applied" in summary
    assert "x3" in summary
