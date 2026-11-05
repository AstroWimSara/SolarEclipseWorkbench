"""Mount commands in a script: conversion, scheduling and the late mount."""
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from skyfield.units import Angle

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.hardware_registry import HARDWARE_COMMANDS, register_hardware
from solareclipseworkbench.mounts import connect, mount_park, mount_stop, mount_track_sun, mount_tracking
from solareclipseworkbench.reference_moments import ReferenceMomentInfo
from solareclipseworkbench.utils import COMMANDS, DeviceAtRuntime, job_touches_camera, schedule_commands

MOUNT_COMMANDS = [name for name, kind in HARDWARE_COMMANDS.items() if kind == "mount"]


@pytest.fixture(autouse=True)
def clean_state():
    hardware_problems.clear()
    register_hardware("mount", None)
    yield
    hardware_problems.clear()
    register_hardware("mount", None)


@pytest.fixture
def scheduler():
    scheduler = BackgroundScheduler()
    yield scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


@pytest.fixture
def simulator():
    mount = connect(driver="simulator")
    yield mount
    mount.close()


def _moments(c2):
    return {"C2": ReferenceMomentInfo(c2, Angle(degrees=250.0), 8.7, timezone.utc)}


def _script(tmp_path, *lines):
    path = tmp_path / "script.txt"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_every_mount_command_can_be_scheduled():
    assert set(MOUNT_COMMANDS) == {"mount_track_sun", "mount_goto_sun", "mount_tracking", "mount_park",
                                   "mount_unpark", "mount_stop"}
    for name in MOUNT_COMMANDS:
        assert name in COMMANDS


def test_mount_commands_are_scheduled_with_their_arguments(tmp_path, scheduler):
    filename = _script(
        tmp_path,
        'mount_unpark, C2, -, 0:04:00.0, "unpark"',
        'mount_goto_sun, C2, -, 0:03:00.0, wait, "goto"',
        'mount_track_sun, C2, -, 0:02:00.0, "track"',
        'mount_tracking, C2, +, 0:02:00.0, off, "tracking off"',
        'mount_stop, C2, +, 0:03:00.0, "stop"',
        'mount_park, C2, +, 0:04:00.0, "park"',
    )

    schedule_commands(filename, scheduler, _moments(datetime.now(timezone.utc) + timedelta(minutes=10)),
                      {}, None, None, None)

    jobs = {job.name: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"unpark", "goto", "track", "tracking off", "stop", "park"}
    assert jobs["goto"].args[1:] == ("wait",)
    assert jobs["tracking off"].args[1:] == ("off",)
    assert all(isinstance(job.args[0], DeviceAtRuntime) for job in jobs.values())
    assert not any(job_touches_camera(job) for job in jobs.values())
    assert hardware_problems.peek() == []


def test_a_mount_connected_after_scheduling_is_the_one_used(simulator):
    proxy = DeviceAtRuntime("mount", "mount_track_sun")
    register_hardware("mount", simulator)

    mount_track_sun(proxy)

    status = simulator.status()
    assert status.tracking is True
    assert status.tracking_rate == "solar"


def test_scheduled_mount_commands_reach_the_registered_mount(simulator):
    register_hardware("mount", simulator)

    mount_tracking(DeviceAtRuntime("mount", "mount_tracking"), "on")
    assert simulator.status().tracking is True
    mount_tracking(DeviceAtRuntime("mount", "mount_tracking"), "off")
    assert simulator.status().tracking is False
    mount_park(DeviceAtRuntime("mount", "mount_park"))
    assert simulator.status().parked is True
    mount_stop(DeviceAtRuntime("mount", "mount_stop"))


def test_a_mount_still_missing_when_the_job_fires_raises_with_the_command_name():
    with pytest.raises(RuntimeError, match="mount_park"):
        mount_park(DeviceAtRuntime("mount", "mount_park"))
