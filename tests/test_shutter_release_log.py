"""Every camera command logs when it really released the shutter (discussion #192).

The setup before a shot can take seconds, so the log shows how long after its
scheduled time each command shot, not only when the job started.
"""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from apscheduler.schedulers.background import BackgroundScheduler

import solareclipseworkbench.camera as cam
from solareclipseworkbench.camera import _serialised_on_camera, _shutter_release
from solareclipseworkbench.utils import schedule_command


class _DummyLock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


class _Camera:
    vendor = "Sony"
    name = "Sony Test"

    def __init__(self):
        self._usb_lock = _DummyLock()


@_serialised_on_camera
def _two_frames(camera):
    """Releases the shutter twice, e.g. a software bracket."""
    with _shutter_release(camera):
        pass
    with _shutter_release(camera):
        pass


@_serialised_on_camera
def _failing_trigger(camera):
    with _shutter_release(camera):
        raise RuntimeError("trigger failed")


def _release_messages(caplog):
    return [r.getMessage() for r in caplog.records if "released the shutter" in r.getMessage()]


def test_first_release_is_logged_against_the_scheduled_time(caplog):
    caplog.set_level(logging.INFO)
    scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    _two_frames(_Camera(), scheduled_at=scheduled_at)

    messages = _release_messages(caplog)
    assert len(messages) == 1
    assert messages[0].startswith("Sony Test: _two_frames released the shutter at ")
    late = float(messages[0].split(": ")[2].split(" s after its scheduled time")[0])
    assert 2.0 <= late < 3.0


def test_without_a_scheduled_time_the_time_since_the_start_is_logged(caplog):
    caplog.set_level(logging.INFO)
    _two_frames(_Camera())
    messages = _release_messages(caplog)
    assert len(messages) == 1 and "after the command started" in messages[0]
    assert "scheduled" not in messages[0]


def test_a_failed_trigger_is_not_logged_as_a_release(caplog):
    caplog.set_level(logging.INFO)
    try:
        _failing_trigger(_Camera(), scheduled_at=datetime.now(timezone.utc))
    except RuntimeError:
        pass
    assert _release_messages(caplog) == []


def test_outside_a_camera_command_nothing_is_logged(caplog):
    caplog.set_level(logging.INFO)
    with _shutter_release(_Camera()):
        pass
    assert _release_messages(caplog) == []


def test_scheduler_passes_the_scheduled_time_to_camera_commands():
    c2 = datetime.now(timezone.utc) + timedelta(hours=1)
    moments = {"C2": SimpleNamespace(time_utc=c2)}
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    try:
        schedule_command(scheduler, moments, 'take_picture, C2, -, 0:00:10.0, cam, 1/100, 8, 400, "Partial"',
                         {"cam": object()}, None, None, None)
        schedule_command(scheduler, moments, 'voice_prompt, C2, -, 0:00:10.0, C2, "Prompt"',
                         {"cam": object()}, None, None, None)
        jobs = {job.name: job for job in scheduler.get_jobs()}
    finally:
        scheduler.shutdown(wait=False)
    assert jobs["Partial"].kwargs == {"scheduled_at": c2 - timedelta(seconds=10)}
    assert jobs["Prompt"].kwargs == {}


def test_a_sony_bracket_logs_the_bulb_press(caplog):
    from contextlib import ExitStack
    from solareclipseworkbench.camera import CameraSettings, take_bracket
    from test_unchanged_settings import _Camera as _GphotoCamera, _fake_gphoto, _sony_config

    caplog.set_level(logging.INFO)
    with ExitStack() as stack:
        _fake_gphoto(stack, _sony_config())
        stack.enter_context(patch.object(cam.time, 'sleep'))
        stack.enter_context(patch.object(cam, '_drain_camera_events'))
        take_bracket(_GphotoCamera("Sony"), CameraSettings("Sony Test", "1/30", "8", 400),
                     "Bracketing C 3.0 Steps 5 Pictures", scheduled_at=datetime.now(timezone.utc))
    messages = _release_messages(caplog)
    assert len(messages) == 1 and "take_bracket released the shutter" in messages[0]
