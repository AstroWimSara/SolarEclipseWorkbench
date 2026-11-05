"""Relay commands in a script: conversion, load-time checks, timing and the late relay."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from skyfield.units import Angle

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.command_timing import RELAY_SHOT_S, relay_duration_s
from solareclipseworkbench.hardware_registry import HARDWARE_COMMANDS, register_hardware
from solareclipseworkbench.reference_moments import ReferenceMomentInfo
from solareclipseworkbench.relay_trigger import relay_burst, relay_shoot
from solareclipseworkbench.utils import COMMANDS, RELAY_BUSY_NAME, DeviceAtRuntime, schedule_commands


@pytest.fixture(autouse=True)
def clean_state():
    hardware_problems.clear()
    register_hardware("relay", None)
    yield
    hardware_problems.clear()
    register_hardware("relay", None)


@pytest.fixture
def scheduler():
    scheduler = BackgroundScheduler()
    yield scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _moments(c2):
    return {"C2": ReferenceMomentInfo(c2, Angle(degrees=250.0), 8.7, timezone.utc)}


def _script(tmp_path, *lines):
    path = tmp_path / "script.txt"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _future_c2():
    return datetime.now(timezone.utc) + timedelta(minutes=5)


# ------------------------------------------------------------------ the commands


def test_every_relay_command_can_be_scheduled():
    for name in HARDWARE_COMMANDS:
        assert name in COMMANDS


def test_relay_commands_are_scheduled_with_their_arguments(tmp_path, scheduler):
    filename = _script(
        tmp_path,
        'relay_arm, C2, -, 0:00:10.0, "arm"',
        'relay_burst, C2, -, 0:00:05.0, 4.5, "diamond ring and beads"',
        'relay_burst, C2, +, 0:00:05.0, 2, 0.25, "paced"',
        'relay_shoot, C2, +, 0:00:20.0, "one frame"',
        'relay_bulb, C2, +, 0:00:30.0, 1.5, "bulb"',
        'relay_release, C2, +, 0:00:40.0, "release"',
    )

    schedule_commands(filename, scheduler, _moments(_future_c2()), {}, None, None, None)

    jobs = {job.name: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"arm", "diamond ring and beads", "paced", "one frame", "bulb", "release"}
    assert jobs["diamond ring and beads"].args[1:] == ("4.5",)
    assert jobs["paced"].args[1:] == ("2", "0.25")
    assert jobs["bulb"].args[1:] == ("1.5",)
    assert all(isinstance(job.args[0], DeviceAtRuntime) for job in jobs.values())
    assert hardware_problems.peek() == []


@pytest.mark.parametrize("line", [
    'relay_burst, C2, -, 0:00:05.0, "no duration"',
    'relay_burst, C2, -, 0:00:05.0, four, "not a number"',
    'relay_burst, C2, -, 0:00:05.0, 2, -1, "negative interval"',
    'relay_bulb, C2, -, 0:00:05.0, 0, "zero"',
])
def test_a_bad_relay_line_is_reported_at_load_time(tmp_path, scheduler, line):
    filename = _script(tmp_path, line)

    schedule_commands(filename, scheduler, _moments(_future_c2()), {}, None, None, None)

    assert scheduler.get_jobs() == []
    problems = hardware_problems.peek()
    assert len(problems) == 1
    assert "relay command will not run" in problems[0].message


def test_overlapping_relay_commands_are_reported_at_load_time(tmp_path, scheduler):
    filename = _script(
        tmp_path,
        'relay_burst, C2, -, 0:00:06.0, 5, "long burst"',
        'relay_shoot, C2, -, 0:00:03.0, "too soon"',
    )

    schedule_commands(filename, scheduler, _moments(_future_c2()), {}, None, None, None)

    problems = hardware_problems.peek()
    assert len(problems) == 1
    assert '"too soon"' in problems[0].message
    assert f"{RELAY_BUSY_NAME} is still busy" in problems[0].message


def test_relay_commands_that_fit_report_nothing(tmp_path, scheduler):
    filename = _script(
        tmp_path,
        'relay_burst, C2, -, 0:00:06.0, 4, "burst"',
        'relay_shoot, C2, -, 0:00:01.0, "after it"',
    )

    schedule_commands(filename, scheduler, _moments(_future_c2()), {}, None, None, None)

    assert hardware_problems.peek() == []


def test_relay_durations():
    assert relay_duration_s("relay_shoot", []) == RELAY_SHOT_S
    assert relay_duration_s("relay_burst", ["4"]) == pytest.approx(4 + RELAY_SHOT_S)
    assert relay_duration_s("relay_bulb", ["1.5"]) == pytest.approx(1.5 + RELAY_SHOT_S)
    assert relay_duration_s("relay_arm", []) is None
    assert relay_duration_s("relay_release", []) is None
    assert relay_duration_s("relay_burst", []) is None


# ------------------------------------------------------- a relay connected late


def test_a_device_connected_after_scheduling_is_the_one_used():
    proxy = DeviceAtRuntime("relay", "relay_burst")

    relay = MagicMock()
    register_hardware("relay", relay)

    proxy.release_all()
    relay.release_all.assert_called_once()


def test_a_device_swapped_after_scheduling_is_picked_up():
    """A reconnect replaces the registered device; jobs must follow it."""
    proxy = DeviceAtRuntime("relay", "relay_burst")
    first, second = MagicMock(), MagicMock()

    register_hardware("relay", first)
    proxy.shoot()
    register_hardware("relay", second)
    proxy.shoot()

    first.shoot.assert_called_once()
    second.shoot.assert_called_once()


def test_a_device_still_missing_when_the_job_fires_raises_with_the_command_name():
    proxy = DeviceAtRuntime("relay", "relay_burst")

    with pytest.raises(RuntimeError, match="relay_burst"):
        proxy.release_all()


def test_a_scheduled_command_fires_through_the_registered_relay():
    relay = MagicMock()
    register_hardware("relay", relay)

    relay_shoot(DeviceAtRuntime("relay", "relay_shoot"))
    relay_burst(DeviceAtRuntime("relay", "relay_burst"), "2", "0.5")

    relay.shoot.assert_called_once_with()
    relay.burst.assert_called_once_with(2.0, 0.5)
