"""Tests for camera-busy estimates, load-time conflict detection and the C2/C3 burst spacing."""

import math
from datetime import datetime, timedelta

import pytest
import pytz

from solareclipseworkbench.command_timing import (
    BURST_LEAD_S,
    burst_duration_s,
    burst_shooting_s,
    contact_burst_plan,
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
    # As in the wizard: the chromosphere shot has released the camera when the C3 beads burst starts
    chromosphere_before_c3 = max(2.0, math.ceil((chromosphere - plan.c3_beads_start) * 10) / 10)

    def window(offset_s, duration_s, description, mode, ref=C2):
        return _window(cam, offset_s, duration_s, description, ref, mode, switch_s)

    windows = [
        # Latest possible partial before C2 (offsets are written in whole seconds,
        # rounded towards C2, so the partial is at least c2_buffer before C2).
        window(-plan.c2_buffer, last_partial, "last partial", "single"),
        window(-plan.c2_diamond_start, burst, "C2 diamond ring", "burst"),
        window(-plan.c2_beads_start, burst, "Pre-C2 beads", "burst"),
        window(plan.totality_first_shot, prominences, "Prominences", "single"),
        # Chromosphere before C3, then the C3 bursts and the first partial after C3.
        window(-chromosphere_before_c3, chromosphere, "Chromosphere", "single", C3),
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
    assert plan.c3_beads_start < plan.c3_diamond_start
    # Beads are photographed in the last seconds before C2 / first seconds after C3.
    # The C3 beads burst starts earlier by the time the camera needs to change drive
    # mode, so its shooting still starts after C3.
    assert plan.c2_beads_start <= 5
    assert 0 < plan.c3_beads_start + plan.switch_s <= 2


def test_sony_burst_is_given_in_seconds():
    """Sony's take_burst holds the shutter for N seconds: 30 would shoot through early totality."""
    assert contact_burst_plan("Sony").burst_param == 2
    assert contact_burst_plan("Nikon").burst_param == 30


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
    # The C3 beads burst is the first burst after the totality shots: it also changes drive mode
    for start, switch_s, window in ((-plan.c2_beads_start, 0.0, beads_c2),
                                    (plan.c3_beads_start, plan.switch_s, beads_c3)):
        shooting_centre = start + BURST_LEAD_S + switch_s + shooting / 2
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
