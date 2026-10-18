"""Tests for camera-busy estimates, load-time conflict detection and the C2/C3 burst spacing."""

import math
from datetime import datetime, timedelta

import pytest
import pytz

from solareclipseworkbench.command_timing import (
    BURST_LEAD_S,
    planning_profile,
    burst_lead_s,
    burst_duration_s,
    burst_shooting_s,
    contact_burst_plan,
    drive_mode,
    mode_switch_s,
    picture_duration_s,
)
from solareclipseworkbench.utils import (
    CameraBusyWindow,
    estimate_busy_s,
    find_camera_conflicts,
)

C2 = datetime(2026, 8, 12, 18, 29, 37, tzinfo=pytz.utc)
C3 = C2 + timedelta(seconds=98)


def _window(camera, offset_s, duration_s, description, ref=C2, mode=None, switch_s=0.0):
    return CameraBusyWindow(camera, ref + timedelta(seconds=offset_s), duration_s, description, mode, switch_s)


def _canon_burst(camera, offset_s, description, ref=C2):
    return _window(camera, offset_s, burst_duration_s("Canon", 2), description, ref)


def test_2026_script_drops_the_c2_diamond_ring():
    """The wizard script used on 2026-08-12: beads at C2-8s, diamond ring at C2-2s."""
    windows = [
        _canon_burst("Canon EOS R", -8, "Pre-C2 beads"),
        _canon_burst("Canon EOS R", -2, "C2 diamond ring"),
    ]
    conflicts = find_camera_conflicts(windows)
    assert [c.window.description for c in conflicts if c.dropped] == ["C2 diamond ring"]
    assert conflicts[0].blocked_by.description == "Pre-C2 beads"


def test_2026_script_keeps_the_c3_diamond_ring():
    """At C3 the diamond ring came first, so nothing was in front of it."""
    windows = [
        _canon_burst("Canon EOS R", 1, "C3 diamond ring", C3),
        _canon_burst("Canon EOS R", 8, "Post-C3 beads", C3),
        _window("Canon EOS R", 10, picture_duration_s("1/6400"), "Partial C3-C4 #1", C3),
    ]
    conflicts = {c.window.description: c for c in find_camera_conflicts(windows)}
    assert "C3 diamond ring" not in conflicts
    assert not conflicts["Post-C3 beads"].dropped          # about 1 s late
    assert conflicts["Partial C3-C4 #1"].dropped


def test_different_cameras_do_not_block_each_other():
    windows = [
        _canon_burst("Canon EOS R", -8, "Pre-C2 beads"),
        _canon_burst("Canon EOS 80D", -2, "C2 diamond ring"),
    ]
    assert find_camera_conflicts(windows) == []


def test_short_wait_is_late_not_dropped_and_pushes_the_next_command_back():
    windows = [
        _window("cam", 0, 3.0, "first"),
        _window("cam", 2, 2.0, "second"),   # waits 1 s, runs 3..5
        _window("cam", 4, 2.0, "third"),    # waits 1 s, runs 5..7
    ]
    conflicts = find_camera_conflicts(windows)
    assert [(c.window.description, c.dropped) for c in conflicts] == [("second", False), ("third", False)]
    assert conflicts[1].wait_s == pytest.approx(1.0)


def test_dropped_command_does_not_occupy_the_camera():
    windows = [
        _window("cam", 0, 10.0, "long"),
        _window("cam", 2, 2.0, "dropped"),
        _window("cam", 10, 2.0, "after"),
    ]
    conflicts = find_camera_conflicts(windows)
    assert [(c.window.description, c.dropped) for c in conflicts] == [("dropped", True)]


def test_estimate_uses_camera_vendor_over_name():
    class FakeCamera:
        vendor = "Nikon"

    # An alias hides the vendor; the camera object knows it is a Nikon (frames, not seconds).
    nikon = estimate_busy_s("take_burst", ["Left body", "1/1000", "8", "100", "30"], FakeCamera())
    assert nikon == pytest.approx(burst_duration_s("Nikon", 30))
    canon = estimate_busy_s("take_burst", ["Canon EOS R", "1/1000", "8", "100", "2"])
    assert canon == pytest.approx(burst_duration_s("Canon", 2))
    assert estimate_busy_s("voice_prompt", ["C2"]) is None


@pytest.mark.parametrize("vendor", ["Canon", "Nikon", "Sony", None])
def test_wizard_contact_plan_has_no_conflicts(vendor):
    """Everything the wizard writes around C2 and C3 fits without dropping or delaying a command,
    including the time a Sony needs to change drive mode."""
    plan = contact_burst_plan(vendor)
    burst = plan.burst_s
    cam = "camera"
    switch_s = mode_switch_s(vendor)
    last_partial = picture_duration_s("1/30")
    prominences = picture_duration_s("1/800")
    chromosphere = picture_duration_s("1/1600")
    # As in the wizard: the chromosphere shot has released the camera when the C3 sequence starts
    chromosphere_before_c3 = max(2.0, math.ceil((chromosphere - plan.c3_first_start) * 10) / 10)

    def window(offset_s, duration_s, description, mode, ref=C2):
        return _window(cam, offset_s, duration_s, description, ref, mode, switch_s)

    windows = [
        # Latest possible partial before C2 (offsets are written in whole seconds,
        # rounded towards C2, so the partial is at least c2_buffer before C2).
        window(-plan.c2_buffer, last_partial, "last partial", "single"),
        *([window(-plan.c2_prepare_start, picture_duration_s("0"), "Prepare for C2", "burst")]
          if plan.c2_prepare_start is not None else []),
        window(-plan.c2_diamond_start, burst, "C2 diamond ring", "burst"),
        window(-plan.c2_beads_start, burst, "Pre-C2 beads", "burst"),
        window(plan.totality_first_shot, prominences, "Prominences", "single"),
        # Chromosphere before C3, then the C3 bursts and the first partial after C3.
        window(-chromosphere_before_c3, chromosphere, "Chromosphere", "single", C3),
        *([window(plan.c3_prepare_start, picture_duration_s("0"), "Prepare for C3", "burst", C3)]
          if plan.c3_prepare_start is not None else []),
        window(plan.c3_beads_start, burst, "Post-C3 beads", "burst", C3),
        window(plan.c3_diamond_start, burst, "C3 diamond ring", "burst", C3),
        window(plan.c3_buffer, last_partial, "first partial", "single", C3),
    ]
    late = [(c.window.description, round(c.wait_s, 3)) for c in find_camera_conflicts(windows)
            if c.wait_s > 0.01]
    assert late == []


@pytest.mark.parametrize("vendor", ["Canon", "Nikon", "Sony", None])
def test_wizard_contact_plan_follows_the_phenomena(vendor):
    """Before C2: diamond ring, then beads.  After C3: beads, then diamond ring."""
    plan = contact_burst_plan(vendor)
    assert plan.c2_diamond_start > plan.c2_beads_start > 0
    assert 0 < plan.c3_beads_start < plan.c3_diamond_start
    # Beads are photographed in the last seconds before C2 / first seconds after C3.
    assert plan.c2_beads_start <= 5
    assert plan.c3_beads_start <= 2


def test_sony_burst_is_given_in_seconds():
    """Sony's take_burst holds the shutter for N seconds: 30 would shoot through early totality."""
    assert contact_burst_plan("Sony").burst_param == 2
    # Nikon: 2 s worth of frames, at the assumed or the measured frame rate
    assert contact_burst_plan("Nikon").burst_param == 20
    assert contact_burst_plan("Nikon", profile=planning_profile("Nikon", burst_overhead_s=0.5,
                                                               burst_fps=20.0)).burst_param == 40


def test_without_bursts_neighbouring_shots_keep_their_usual_distance():
    plan = contact_burst_plan("Canon", bursts_enabled=False)
    assert (plan.c2_buffer, plan.c3_buffer, plan.totality_first_shot) == (10, 10, 3)


# --- Bursts aimed at the Baily's beads windows ---------------------------------

@pytest.mark.parametrize("vendor", ["Canon", "Nikon", "Sony"])
def test_the_beads_bursts_are_centred_on_the_bead_windows(vendor):
    beads_c2, beads_c3 = (-0.1, 3.1), (-0.0, 4.0)
    plan = contact_burst_plan(vendor, beads_c2=beads_c2, beads_c3=beads_c3)
    shooting = burst_shooting_s(vendor, plan.burst_param)

    assert plan.beads_timed
    for start, window in ((-plan.c2_beads_start, beads_c2), (plan.c3_beads_start, beads_c3)):
        shooting_centre = start + burst_lead_s(vendor) + shooting / 2
        assert shooting_centre == pytest.approx(sum(window) / 2, abs=0.05)


def test_a_beads_burst_after_c2_moves_the_first_totality_shot():
    plan = contact_burst_plan("Canon", beads_c2=(2.0, 6.0), beads_c3=(-6.0, -2.0))

    assert plan.c2_beads_start < 0 and plan.c3_beads_start < 0
    # The first totality shot waits for the beads burst, which now starts after C2
    assert plan.totality_first_shot >= -plan.c2_beads_start + plan.burst_s
    # The diamond ring bursts stay a whole burst away from the beads bursts
    assert plan.c2_diamond_start - plan.c2_beads_start >= plan.burst_s
    assert plan.c3_diamond_start - plan.c3_beads_start >= plan.burst_s


def test_without_both_windows_the_fixed_offsets_are_used():
    assert contact_burst_plan("Canon", beads_c2=(-0.1, 3.1)) == contact_burst_plan("Canon")
    assert not contact_burst_plan("Canon").beads_timed


# --- prepare_camera before the C2 and C3 sequences -------------------------------

def test_a_sony_is_prepared_before_the_c2_and_c3_bursts():
    """The mode change happens before the burst, so the burst shoots at its planned time."""
    plan = contact_burst_plan("Sony")
    assert plan.c2_prepare_start > plan.c2_diamond_start
    assert plan.c2_prepare_start - plan.c2_diamond_start >= picture_duration_s("0") + mode_switch_s("Sony")
    assert plan.c3_prepare_start < plan.c3_beads_start
    assert plan.c3_beads_start - plan.c3_prepare_start >= picture_duration_s("0") + mode_switch_s("Sony")
    assert plan.c3_first_start == plan.c3_prepare_start
    # The bursts themselves are where they are for a camera that changes mode quickly
    canon = contact_burst_plan("Canon")
    assert (plan.c3_beads_start, plan.c2_beads_start) == (canon.c3_beads_start, canon.c2_beads_start)


@pytest.mark.parametrize("vendor", ["Canon", "Nikon", None])
def test_a_camera_that_changes_mode_quickly_is_not_prepared(vendor):
    plan = contact_burst_plan(vendor)
    assert plan.c2_prepare_start is None and plan.c3_prepare_start is None
    assert plan.c3_first_start == plan.c3_beads_start


def test_prepare_takes_the_mode_change_off_the_burst():
    """In the conflict check the mode change is paid by prepare_camera, not by the burst after it."""
    switch_s = mode_switch_s("Sony")
    windows = [
        _window("cam", -60, picture_duration_s("1/800"), "partial", mode="single", switch_s=switch_s),
        _window("cam", -20, picture_duration_s("0"), "prepare", mode="burst", switch_s=switch_s),
        # The prepare keeps the camera busy for 2 + 4 s, until C2-14 s
        _window("cam", -14, burst_duration_s("Sony", 2), "diamond ring", mode="burst", switch_s=switch_s),
        _window("cam", -6, burst_duration_s("Sony", 2), "beads", mode="burst", switch_s=switch_s),
    ]
    assert find_camera_conflicts(windows) == []
    # Without the prepare, the diamond ring pays the mode change and the beads burst is dropped
    conflicts = find_camera_conflicts([windows[0]] + windows[2:])
    assert [(c.window.description, c.dropped) for c in conflicts] == [("beads", True)]


def test_prepare_drive_modes():
    assert estimate_busy_s("prepare_camera", ["Sony A7", "1/100", "8", "400", "burst"]) == picture_duration_s("0")
    assert drive_mode("prepare_camera", "burst") == drive_mode("take_burst")
    assert drive_mode("prepare_camera", "single") == drive_mode("take_picture")
    assert drive_mode("prepare_camera", '"1 5"') == drive_mode("take_bracket", '"1 5"')


def test_a_sony_starts_shooting_sooner_after_a_burst_command():
    """Discussion #192: an A7R IIIA shoots within 0.2-0.3 s when its settings do not change."""
    assert burst_lead_s("Sony") == 0.3
    assert burst_lead_s("Canon") == burst_lead_s("Nikon") == burst_lead_s(None) == BURST_LEAD_S
    window = (-0.1, 3.1)
    sony = contact_burst_plan("Sony", beads_c2=window, beads_c3=window)
    canon = contact_burst_plan("Canon", beads_c2=window, beads_c3=window)
    # Same shooting time (Sony and Canon both hold the shutter 2 s), so the Sony command comes 0.7 s later
    assert sony.c3_beads_start - canon.c3_beads_start == pytest.approx(0.7)
    assert canon.c2_beads_start - sony.c2_beads_start == pytest.approx(0.7)


# --- Measured Nikon bursts and the timing recorded in a script -----------------

from solareclipseworkbench.command_timing import (  # noqa: E402
    CONTACT_BURST_S, DEFAULT_PROFILE, DIAMOND_RING_SHIFT_MAX_S, MAX_BEADS_BURST_S, BURST_MARGIN_S,
    TimingProfile, fit_test_bursts, nikon_burst_fit, parse_timing_directives, timing_directive,
)


def test_fast_nikon_burst_is_planned_shorter_than_the_default_but_longer_than_measured():
    """Z 8 with a CFexpress card: 30 frames at 20 fps, 0.6 s overhead -> 2.1 s busy."""
    profile = planning_profile("Nikon", burst_overhead_s=0.6, burst_fps=20.0)
    planned = burst_duration_s("Nikon", 30, profile)
    assert planned < burst_duration_s("Nikon", 30)
    assert planned >= 2.1 + BURST_MARGIN_S
    assert burst_shooting_s("Nikon", 30, profile) == pytest.approx(1.5)


@pytest.mark.parametrize("vendor", ["Canon", "Sony", None])
def test_fast_canon_and_sony_bursts_are_planned_shorter_than_the_default(vendor):
    """An EOS R5 with a CFexpress card: 1 s and 5 s bursts busy for 1.8 s and 5.8 s."""
    fit = fit_test_bursts(vendor, (1.0, 1.8), (5.0, 5.8))
    assert fit.busy_per_s == pytest.approx(1.0) and fit.overhead_s == pytest.approx(0.8)
    profile = planning_profile(vendor, burst_overhead_s=fit.overhead_s, burst_busy_per_s=fit.busy_per_s,
                               burst_max_s=fit.max_s)
    planned = burst_duration_s(vendor, 2, profile)
    assert planned < burst_duration_s(vendor, 2)
    assert planned >= 2.8 + BURST_MARGIN_S
    # A slow camera is planned longer than the default
    assert planning_profile(vendor, burst_overhead_s=9.0).burst_overhead_s == pytest.approx(14.5)


def test_untested_nikon_keeps_the_defaults():
    assert planning_profile("Nikon") == DEFAULT_PROFILE


def test_nikon_frame_rate_and_overhead_from_two_bursts():
    fps, overhead = nikon_burst_fit((10, 0.6 + 10 / 20), (30, 0.6 + 30 / 20))
    assert fps == pytest.approx(20.0)
    assert overhead == pytest.approx(0.6)


def test_implausible_nikon_frame_rate_falls_back_to_the_default():
    """Same time for 10 and 30 frames: no rate can be read, the overhead uses NIKON_BURST_FPS."""
    fps, overhead = nikon_burst_fit((10, 5.0), (30, 5.0))
    assert fps is None
    assert overhead == pytest.approx(5.0 - 30 / DEFAULT_PROFILE.nikon_burst_fps)


@pytest.mark.parametrize("short, long", [((10, 0.9), (30, 1.4)), ((10, 3.0), (30, 2.0)), ((10, 1.0), (30, 9.0))])
def test_planned_nikon_burst_always_outlasts_the_measured_one(short, long):
    fps, overhead = nikon_burst_fit(short, long)
    profile = planning_profile("Nikon", burst_overhead_s=overhead, burst_fps=fps)
    assert burst_duration_s("Nikon", long[0], profile) >= long[1] + BURST_MARGIN_S - 0.1


def test_timing_directive_round_trip():
    profile = TimingProfile(picture_overhead_s=2.4, burst_overhead_s=1.9, nikon_burst_fps=19.6,
                            burst_busy_per_s=1.2, burst_max_s=4.5)
    line = timing_directive("Nikon Z 8", profile)
    assert line.startswith("# timing: Nikon Z 8;")
    lines = ["# header", line, "# timing: broken; burst_overhead_s=abc", "# timing: neg; burst_overhead_s=-1",
             'take_picture, C2, -, 0:10:00.0, Nikon Z 8, 1/1000, 8, 100, "Partial"']
    assert parse_timing_directives(lines) == {"Nikon Z 8": profile}



# --- Beads bursts that cover the Baily's beads window ----------------------------

TESTED_CANON = planning_profile("Canon", burst_overhead_s=3.0, burst_busy_per_s=1.0, burst_max_s=5.0)
TESTED_Z8 = planning_profile("Nikon", burst_overhead_s=0.6, burst_fps=20.0, burst_max_s=5.0)


def test_canon_and_sony_test_bursts_give_the_time_per_second_of_shooting():
    fit = fit_test_bursts("Canon", (1.0, 4.5), (5.0, 10.5))
    assert fit.busy_per_s == pytest.approx(1.5)
    assert fit.overhead_s == pytest.approx(3.0)
    assert fit.max_s == 5.0


@pytest.mark.parametrize("short, long", [((1.0, 7.0), (5.0, 7.5)), ((1.0, 2.0), (5.0, 30.0)), ((1.0, 6.0), (5.0, 9.0))])
def test_planned_canon_burst_covers_both_test_bursts(short, long):
    fit = fit_test_bursts("Canon", short, long)
    profile = planning_profile("Canon", burst_overhead_s=fit.overhead_s, burst_busy_per_s=fit.busy_per_s,
                               burst_max_s=fit.max_s)
    for seconds, busy in (short, long):
        assert burst_duration_s("Canon", seconds, profile) >= busy - 0.01


@pytest.mark.parametrize("vendor, profile", [("Canon", TESTED_CANON), ("Sony", TESTED_CANON), ("Nikon", TESTED_Z8)])
def test_a_tested_camera_covers_the_beads_window(vendor, profile):
    beads_c2, beads_c3 = (-1.0, 2.0), (-0.5, 3.0)
    plan = contact_burst_plan(vendor, profile=profile, beads_c2=beads_c2, beads_c3=beads_c3)
    for start, shooting, window in ((-plan.c2_beads_start, plan.c2_beads_shooting_s, beads_c2),
                                    (plan.c3_beads_start, plan.c3_beads_shooting_s, beads_c3)):
        # The window plus 0.5 s either side, centred on it
        assert shooting == pytest.approx(window[1] - window[0] + 1.0, abs=0.06)
        assert start + burst_lead_s(vendor) + shooting / 2 == pytest.approx(sum(window) / 2, abs=0.06)
    # The diamond ring bursts wait for the beads bursts and the first totality shot for the C2 beads
    assert plan.c3_diamond_start - plan.c3_beads_start >= plan.c3_beads_s
    assert plan.c2_diamond_start - plan.c2_beads_start >= plan.burst_s
    assert plan.totality_first_shot >= plan.c2_beads_s - plan.c2_beads_start


def test_nikon_beads_burst_is_given_in_frames():
    plan = contact_burst_plan("Nikon", profile=TESTED_Z8, beads_c2=(-1.0, 2.0), beads_c3=(-0.5, 3.0))
    assert plan.c2_beads_param == 80              # 4 s at 20 fps
    assert plan.c3_beads_param == 90              # 4.5 s at 20 fps
    assert plan.burst_param == 40                 # diamond ring: 2 s


def test_an_untested_camera_keeps_two_second_beads_bursts():
    plan = contact_burst_plan("Canon", beads_c2=(-1.0, 2.0), beads_c3=(-0.5, 3.0))
    assert plan.c2_beads_shooting_s == plan.c3_beads_shooting_s == CONTACT_BURST_S


def test_beads_burst_is_never_longer_than_the_longest_test_burst():
    plan = contact_burst_plan("Canon", profile=TESTED_CANON, beads_c2=(-4.0, 4.0), beads_c3=(-4.0, 4.0))
    assert plan.c2_beads_shooting_s <= MAX_BEADS_BURST_S
    short_test = planning_profile("Canon", burst_overhead_s=3.0, burst_max_s=3.0)
    plan = contact_burst_plan("Canon", profile=short_test, beads_c2=(-4.0, 4.0), beads_c3=(-4.0, 4.0))
    assert plan.c2_beads_shooting_s == plan.c3_beads_shooting_s == 3.0


def test_beads_burst_is_shortened_so_the_diamond_ring_burst_stays_close():
    """A camera that needs 3 s per second of shooting: a full-window C3 beads burst pushes the diamond ring late."""
    slow = planning_profile("Canon", burst_overhead_s=3.0, burst_busy_per_s=3.0, burst_max_s=5.0)
    window = (-0.5, 3.0)
    standard = contact_burst_plan("Canon", profile=planning_profile("Canon", burst_overhead_s=3.0,
                                                                    burst_busy_per_s=3.0),
                                  beads_c2=window, beads_c3=window)
    plan = contact_burst_plan("Canon", profile=slow, beads_c2=window, beads_c3=window)
    assert CONTACT_BURST_S < plan.c3_beads_shooting_s < window[1] - window[0] + 1.0
    assert plan.c3_diamond_start - standard.c3_diamond_start <= DIAMOND_RING_SHIFT_MAX_S
    assert plan.c2_diamond_start - standard.c2_diamond_start <= DIAMOND_RING_SHIFT_MAX_S
