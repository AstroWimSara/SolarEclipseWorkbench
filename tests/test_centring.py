"""Keeping the sun centred: the centring loop, and the gaps between the scheduled shots it waits for."""
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from solareclipseworkbench import utils
from solareclipseworkbench.centring import (CENTRED, CORRECTING, NO_SUN, PAUSED, STOPPED, WAITING, Calibration,
                                            Centrer)
from solareclipseworkbench.sun_simulator import SimulatedSunCamera
from test_calibration import FakeMount, calibrate


@pytest.fixture
def setup():
    """A fake mount, a camera turned 35°, its calibration, and the sun put 20 px off the middle."""
    mount = FakeMount()
    camera = SimulatedSunCamera(mount, rotation_deg=35)
    calibration = calibrate(mount, camera)
    drift(mount, 240, -190)                    # about 19 px at 16″/px
    return mount, camera, calibration


def drift(mount, east_arcsec, north_arcsec):
    """Let the mount drift off the sun (polar alignment, periodic error)."""
    mount.ra_h += east_arcsec / 3600 / 15 / math.cos(math.radians(mount.dec_deg))
    mount.dec_deg += north_arcsec / 3600


def off_centre(camera, calibration) -> float:
    x, y = camera.sun_in_frame()
    width, height = calibration.frame_size
    return math.hypot(x - (width - 1) / 2, y - (height - 1) / 2)


def centrer(mount, camera, calibration, **kwargs):
    return Centrer(mount, camera, calibration, wait_for_pulses=False, settle_s=0.0, **kwargs)


# ------------------------------------------------------------------ centring


def test_the_sun_is_brought_back_to_the_middle(setup):
    mount, camera, calibration = setup
    assert off_centre(camera, calibration) > 15
    loop = centrer(mount, camera, calibration)
    for _ in range(6):
        loop.step()
    assert off_centre(camera, calibration) <= 2.0
    assert loop.status.state == CENTRED
    assert loop.status.corrections >= 2


def test_a_small_offset_is_left_alone(setup):
    mount, camera, calibration = setup
    loop = centrer(mount, camera, calibration, deadband_px=4.0)
    for _ in range(8):
        loop.step()
    assert off_centre(camera, calibration) <= 3.0
    pulses = len(mount.pulses)
    drift(mount, 10, 0)                         # 0.6 px more (16″/px): still in the dead band
    loop.step()
    assert len(mount.pulses) == pulses
    assert loop.status.state == CENTRED


def test_corrections_are_capped(setup):
    mount, camera, calibration = setup
    drift(mount, 2000, 0)                       # far off: more than one correction's worth
    loop = centrer(mount, camera, calibration, max_correction_ms=1000)
    before = len(mount.pulses)
    loop.step()
    assert all(ms <= 1000 for _, ms in mount.pulses[before:])


def test_a_crescent_is_centred_on_the_centre_of_the_sun():
    mount = FakeMount()
    camera = SimulatedSunCamera(mount, rotation_deg=-20, moon=(0.55, -0.3))
    calibration = calibrate(mount, camera)
    drift(mount, -250, 300)
    loop = centrer(mount, camera, calibration)
    for _ in range(6):
        loop.step()
    assert off_centre(camera, calibration) <= 2.0


def test_another_target_than_the_middle(setup):
    mount, camera, calibration = setup
    loop = centrer(mount, camera, calibration, target=(560.0, 300.0))
    for _ in range(8):
        loop.step()
    x, y = camera.sun_in_frame()
    assert math.hypot(x - 560, y - 300) <= 2.0


# --------------------------------------------------------- when not to guide


def test_nothing_is_done_around_totality(setup):
    mount, camera, calibration = setup
    loop = centrer(mount, camera, calibration, paused=lambda: True)
    before = len(mount.pulses)
    loop.step()
    assert loop.status.state == PAUSED
    assert len(mount.pulses) == before


def test_the_pulses_wait_for_a_gap_between_shots(setup):
    mount, camera, calibration = setup
    gap = {"open": False}
    asked = []

    def quiet(seconds):
        asked.append(seconds)
        return gap["open"]

    loop = centrer(mount, camera, calibration, quiet=quiet)
    before = len(mount.pulses)
    assert loop.step() == pytest.approx(2.0)     # looks again soon
    assert loop.status.state == WAITING
    assert len(mount.pulses) == before
    assert asked and asked[0] > 0
    gap["open"] = True
    loop.step()
    assert loop.status.state == CORRECTING
    assert len(mount.pulses) > before


def test_no_sun_no_pulses(setup):
    mount, camera, calibration = setup
    camera.offset = (3000, 0)
    loop = centrer(mount, camera, calibration)
    before = len(mount.pulses)
    loop.step()
    assert loop.status.state == NO_SUN
    assert len(mount.pulses) == before


# ---------------------------------------------------------- when to give up


def test_a_wrong_calibration_is_given_up_on(setup):
    mount, camera, calibration = setup
    # The north and east columns swapped: the corrections go the wrong way
    wrong = Calibration(north=calibration.east, east=calibration.north, frame_size=calibration.frame_size,
                        radius=calibration.radius)
    loop = centrer(mount, camera, wrong)
    for _ in range(8):
        loop.step()
        if loop.status.state == STOPPED:
            break
    assert loop.status.state == STOPPED
    assert "calibrate again" in loop.status.message


def test_slow_capped_corrections_from_far_off_are_not_taken_for_failures(setup):
    """Far off, each capped correction gains only a little: that is not a wrong calibration."""
    mount, camera, calibration = setup
    drift(mount, 1500, 0)                       # about 90 px more off
    start = off_centre(camera, calibration)
    loop = centrer(mount, camera, calibration, max_correction_ms=300)    # about 3 px per correction
    for _ in range(12):
        loop.step()
    assert loop.status.state == CORRECTING
    assert off_centre(camera, calibration) < start - 25


def test_another_frame_size_needs_a_new_calibration(setup):
    mount, camera, calibration = setup
    camera.width, camera.height = 667, 1000     # the camera turned to portrait
    loop = centrer(mount, camera, calibration)
    loop.step()
    assert loop.status.state == STOPPED
    assert "calibrate again" in loop.status.message


def test_a_refused_pulse_stops_the_centring(setup):
    mount, camera, calibration = setup

    def refuse(direction, ms):
        raise RuntimeError("no")

    mount.guide = refuse
    loop = centrer(mount, camera, calibration)
    loop.step()
    assert loop.status.state == STOPPED


# ------------------------------------------------------------------ the thread


def test_the_thread_keeps_the_sun_centred_and_reports(setup):
    mount, camera, calibration = setup
    states = []
    loop = Centrer(mount, camera, calibration, wait_for_pulses=False, settle_s=0.0, interval_s=0.05,
                   on_status=lambda status: states.append(status.state))
    loop.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and off_centre(camera, calibration) > 2.0:
            time.sleep(0.05)
        assert off_centre(camera, calibration) <= 2.0
        drift(mount, 150, 150)                  # drifts off again, about 13 px
        deadline = time.monotonic() + 10
        time.sleep(0.2)
        while time.monotonic() < deadline and off_centre(camera, calibration) > 2.0:
            time.sleep(0.05)
        assert off_centre(camera, calibration) <= 2.0
    finally:
        loop.stop()
    assert not loop.running
    assert CORRECTING in states and CENTRED in states
    assert loop.status.state == "off"


# ------------------------------------------------------- gaps between shots


@pytest.fixture
def busy():
    saved = dict(utils.JOB_BUSY)
    utils.JOB_BUSY.clear()
    yield utils.JOB_BUSY
    utils.JOB_BUSY.clear()
    utils.JOB_BUSY.update(saved)


def _scheduler(*job_ids):
    return SimpleNamespace(get_jobs=lambda: [SimpleNamespace(id=job_id) for job_id in job_ids])


def test_quiet_without_a_script():
    assert utils.quiet_for(None, 60)


def test_a_shot_coming_up_is_not_quiet(busy):
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    busy["a"] = (now + timedelta(seconds=5), 1.0)
    scheduler = _scheduler("a")
    assert not utils.quiet_for(scheduler, 4, now=now)           # 4 s + 2 s margin reaches the shot
    assert utils.quiet_for(scheduler, 2, now=now)


def test_a_shot_still_running_is_not_quiet(busy):
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    busy["burst"] = (now - timedelta(seconds=3), 5.0)          # started, gone from the scheduler
    assert not utils.quiet_for(_scheduler(), 1, now=now)
    busy["burst"] = (now - timedelta(seconds=10), 5.0)         # finished
    assert utils.quiet_for(_scheduler(), 1, now=now)


def test_the_shots_of_a_stopped_run_do_not_count(busy):
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    busy["cancelled"] = (now + timedelta(seconds=3), 1.0)      # not on the scheduler any more
    assert utils.quiet_for(_scheduler(), 5, now=now)


def test_scheduling_records_the_busy_time_of_camera_commands(tmp_path, busy):
    from apscheduler.schedulers.background import BackgroundScheduler
    from skyfield.units import Angle

    from solareclipseworkbench.reference_moments import ReferenceMomentInfo

    script = tmp_path / "script.txt"
    script.write_text('relay_burst, C2, -, 0:00:05.0, 4.5, "burst"\n'
                      'voice_prompt, C2, -, 0:00:20.0, C2_IN_20_SECONDS, "prompt"\n'
                      'mount_track, C2, -, 0:10:00.0, "track"\n')
    c2 = datetime.now(timezone.utc) + timedelta(minutes=30)
    moments = {"C2": ReferenceMomentInfo(c2, Angle(degrees=250.0), 30.0, timezone.utc)}
    scheduler = BackgroundScheduler()
    utils.schedule_commands(str(script), scheduler, moments, {}, None, None, None)
    names = {job.id: job.name for job in scheduler.get_jobs()}
    recorded = {names[job_id]: value for job_id, value in busy.items() if job_id in names}
    assert set(recorded) == {"burst"}                          # prompts and mount commands leave the camera alone
    start, busy_s = recorded["burst"]
    assert busy_s >= 4.5
    assert not utils.quiet_for(scheduler, 10, now=start - timedelta(seconds=3))
    assert utils.quiet_for(scheduler, 10, now=start - timedelta(seconds=60))
