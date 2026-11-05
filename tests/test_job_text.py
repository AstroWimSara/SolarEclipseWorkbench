"""The commands of the jobs table in words (job_text)."""

from types import SimpleNamespace

import pytest

from solareclipseworkbench import job_text
from solareclipseworkbench.camera import (CameraSettings, prepare_camera, set_exposure_compensation, take_bracket,
                                          take_burst, take_hdr, take_picture)
from solareclipseworkbench.commands import execute_command
from solareclipseworkbench.gui import sync_cameras
from solareclipseworkbench.mounts import (mount_goto_sun, mount_park, mount_stop, mount_track_sun, mount_tracking,
                                          mount_unpark)
from solareclipseworkbench.notifications import voice_prompt
from solareclipseworkbench.relay_trigger import relay_arm, relay_bulb, relay_burst, relay_release, relay_shoot

CAMERA = "VirtualCamera"


def _settings(speed="1/1000", aperture="8", iso=200):
    return CameraSettings(CAMERA, speed, aperture, iso)


def _job(func, *args):
    return SimpleNamespace(func=func, args=list(args), name="description")


@pytest.fixture(autouse=True)
def _no_compensation():
    set_exposure_compensation(0)
    yield
    set_exposure_compensation(0)

@pytest.mark.parametrize("job, expected", [
    (_job(take_picture, object(), _settings()),
     "Picture at 1/1000 s, f/8, ISO 200 (VirtualCamera)"),
    (_job(take_picture, object(), _settings(aperture="-")),
     "Picture at 1/1000 s, ISO 200 (VirtualCamera)"),
    (_job(take_burst, object(), _settings(), 3.0),
     "Burst for 3 s at 1/1000 s, f/8, ISO 200 (VirtualCamera)"),
    (_job(take_bracket, object(), _settings(), "1 5"),
     "Bracket of 5 frames, 1 EV apart, around 1/1000 s, f/8, ISO 200 (VirtualCamera)"),
    (_job(take_bracket, object(), _settings(), "+/- 2/3"),
     "Bracket of 5 frames, 2/3 EV apart, around 1/1000 s, f/8, ISO 200 (VirtualCamera)"),
    (_job(take_hdr, object(), _settings("1/2000", "5.6", 100), 4, "round-trip"),
     "HDR of 9 frames from 1/2000 s, 4 stops longer and back, f/5.6, ISO 100 (VirtualCamera)"),
    (_job(take_hdr, object(), _settings("1/2000", "5.6", 100), 4, "one-way"),
     "HDR of 5 frames from 1/2000 s, 4 stops longer, f/5.6, ISO 100 (VirtualCamera)"),
    (_job(prepare_camera, object(), _settings(), "single"),
     "Set up 1/1000 s, f/8, ISO 200 for single pictures (VirtualCamera)"),
    (_job(prepare_camera, object(), _settings(), "burst"),
     "Set up 1/1000 s, f/8, ISO 200 for a burst (VirtualCamera)"),
    (_job(prepare_camera, object(), _settings(), "1 3"),
     "Set up 1/1000 s, f/8, ISO 200 for a bracket of 3 frames, 1 EV apart (VirtualCamera)"),
    (_job(sync_cameras, object()), "Check the cameras and set their clocks"),
    (_job(voice_prompt, "C2_IN_10_SECONDS"), "Voice prompt: C2 in 10 seconds"),
    (_job(voice_prompt, "C3_PLUS_1_MINUTE"), "Voice prompt: C3 plus 1 minute"),
    (_job(voice_prompt, "FILTERS_ON"), "Voice prompt: filters on"),
    (_job(execute_command, "ls -l"), "Run: ls -l"),
    (_job(relay_shoot, object()), "Relay: take one frame"),
    (_job(relay_burst, object(), "3"), "Relay: hold the shutter for 3 s"),
    (_job(relay_burst, object(), "3", "0.5"), "Relay: a frame every 0.5 s for 3 s"),
    (_job(relay_bulb, object(), "2.0"), "Relay: bulb exposure of 2 s"),
    (_job(relay_arm, object()), "Relay: hold the half press"),
    (_job(relay_release, object()), "Relay: release the shutter"),
    (_job(mount_goto_sun, object()), "Mount: go to the Sun"),
    (_job(mount_track_sun, object()), "Mount: track the Sun at the solar rate"),
    (_job(mount_tracking, object(), "off"), "Mount: stop tracking"),
    (_job(mount_tracking, object(), "on"), "Mount: start tracking"),
    (_job(mount_park, object()), "Mount: park"),
    (_job(mount_unpark, object()), "Mount: unpark"),
    (_job(mount_stop, object()), "Mount: stop all motion"),
])
def test_each_command_in_words(job, expected):
    assert job_text.describe_job(job) == expected


def test_the_words_show_the_compensated_speed():
    job = _job(take_picture, object(), _settings())

    assert job_text.describe_job(job, ev=1) == "Picture at 1/500 s (+1 EV), f/8, ISO 200 (VirtualCamera)"
    set_exposure_compensation(-2)
    assert job_text.describe_job(job) == "Picture at 1/4000 s (-2 EV), f/8, ISO 200 (VirtualCamera)"


def test_a_speed_that_is_not_a_number_is_shown_as_written():
    job = _job(take_picture, object(), _settings(speed="bulb"))

    assert job_text.describe_job(job, ev=1) == "Picture at bulb, f/8, ISO 200 (VirtualCamera)"


def test_unknown_commands_and_unreadable_jobs_have_no_words():
    def dome_open():
        pass

    for job in (_job(dome_open),                        # a command without words
                _job(take_picture),                     # no arguments
                _job(take_hdr, object(), _settings(), "many"),
                SimpleNamespace(func=None, args=()),
                object()):
        assert job_text.describe_job(job) is None
