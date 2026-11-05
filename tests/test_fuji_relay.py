"""A Fuji body fired through the USB relay.

The relay fires the frames, and the SDK sets the shutter speed and empties the
transfer queue.  A fault here gives frames at the wrong speed, or a full queue
that stops the body.  The SDK is a MagicMock and the relay is the simulated
backend, so no hardware is needed.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from fujixsdk import EclipseShooter

from solareclipseworkbench import fuji_camera, hardware_problems
from solareclipseworkbench.fuji_camera import FujiCamera
from solareclipseworkbench.hardware_registry import register_hardware
from solareclipseworkbench.relay_trigger import RelayTrigger, SimulatedBackend, Wiring


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # The real waits are for a body that writes to its card.  The tests only
    # check what happens, and in which order.
    monkeypatch.setattr(fuji_camera, "BUSY_BACKOFF_S", 0.001)
    monkeypatch.setattr(fuji_camera, "TAP_GAP_S", 0.0)
    monkeypatch.setattr(fuji_camera, "TAP_EXPOSURE_MARGIN_S", 0.0)
    monkeypatch.setattr(fuji_camera, "SETTLE_BEFORE_DRAIN_S", 0.0)
    monkeypatch.setattr(fuji_camera, "SETTLE_BETWEEN_DRAINS_S", 0.0)
    hardware_problems.clear()
    register_hardware("relay", None)
    yield
    register_hardware("relay", None)
    hardware_problems.clear()


def _camera(capacity=(0, 32)):
    sdk = MagicMock()
    sdk.get_buffer_capacity.return_value = capacity
    sdk.drain_buffer.return_value = 0
    sdk.get_shutter_speed.return_value = (0, 0)
    cam = FujiCamera(sdk, "Fuji Fujifilm X-T4", "/sdk", "ENUM:0", model="X-T4")
    return cam, sdk


def _relay(dual=True):
    wiring = Wiring(s2_channel=2, s1_channel=1) if dual else Wiring(s2_channel=1)
    wiring.settle_s = 0.0
    wiring.pulse_s = 0.0
    trigger = RelayTrigger(SimulatedBackend(latency_s=0.0), wiring)
    register_hardware("relay", trigger)
    return trigger


def _mock_relay():
    relay = MagicMock()
    register_hardware("relay", relay)
    return relay


# ------------------------------------------------------------- the choice


def test_without_a_relay_the_sdk_fires_the_body():
    cam, _ = _camera()

    assert isinstance(cam.shooter, EclipseShooter)
    assert cam.relay is None


def test_with_a_relay_the_relay_fires_the_body():
    cam, _ = _camera()
    relay = _mock_relay()

    assert isinstance(cam.shooter, fuji_camera._RelayShooter)
    assert cam.relay is relay


# ------------------------------------------------------------ single frames


def test_a_single_frame_is_one_tap_and_no_sdk_release():
    cam, sdk = _camera()
    relay = _mock_relay()

    cam.capture()

    relay.shoot.assert_called_once_with(pulse=fuji_camera.TAP_S)
    assert not sdk.shoot_no_af.called


def test_a_single_frame_does_not_drain_a_queue_with_room():
    # A drain costs a settle and the deletes, more than a second, to free one
    # slot of 32.  That time is the gap to the next scripted frame.
    cam, sdk = _camera(capacity=(3, 32))
    _mock_relay()

    cam.capture()

    assert not sdk.drain_buffer.called


def test_a_single_frame_drains_a_queue_that_fills():
    cam, sdk = _camera(capacity=(30, 32))
    _mock_relay()

    cam.capture()

    assert sdk.drain_buffer.called


# ------------------------------------------------------------------ ladders


def test_a_ladder_is_one_tap_per_speed_in_the_order_given():
    cam, sdk = _camera()
    relay = _mock_relay()

    taken = cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    written = [call.args[0] for call in sdk.set_shutter_speed.call_args_list]
    assert written == sorted(written) and len(written) == 3
    assert taken == 3
    assert relay.shoot.call_count == 3
    assert all(call.kwargs == {"pulse": fuji_camera.TAP_S} for call in relay.shoot.call_args_list)
    assert not sdk.shoot_no_af.called


def test_a_ladder_never_holds_s1():
    # With S1 held the drive keeps running, and the body refuses every speed
    # change.  The ladder opens the contacts first, also after relay_arm.
    cam, _ = _camera()
    relay = _relay()
    relay.half_press()
    held_at_write = []
    cam._sdk_cam.set_shutter_speed.side_effect = \
        lambda _speed: held_at_write.append(relay.closed_channels.copy())

    cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    assert held_at_write == [set(), set(), set()]
    assert relay.closed_channels == set()


def test_a_speed_the_body_refuses_still_gets_its_frame_and_is_reported():
    # A frame at the previous speed is better than no frame at a contact.  The
    # image looks normal, so the fault must reach the problems list.
    cam, sdk = _camera()
    sdk.set_shutter_speed.side_effect = RuntimeError("refused")
    relay = _mock_relay()

    taken = cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    assert taken == 3
    assert relay.shoot.call_count == 3
    assert any("wrong shutter speed" in p.message for p in hardware_problems.peek())


def test_a_ladder_drains_the_queue_when_it_fills():
    # A fast exposure can give two frames for one tap, so a long ladder can
    # fill the 32 slots, and a full queue stops the body.
    cam, sdk = _camera(capacity=(30, 32))
    _mock_relay()

    cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    # One drain between each tap, and the one round at the end.
    assert sdk.drain_buffer.call_count == 4


def test_a_ladder_with_room_drains_only_at_the_end():
    cam, sdk = _camera(capacity=(2, 32))
    _mock_relay()

    cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125])

    assert sdk.drain_buffer.call_count == 1


def test_a_queue_that_cannot_be_read_does_not_stop_the_ladder():
    cam, sdk = _camera()
    sdk.get_buffer_capacity.side_effect = RuntimeError("unreadable")
    _mock_relay()

    assert cam.shoot_ladder([1 / 2000, 1 / 500, 1 / 125]) == 3


# ------------------------------------------------------------------- bursts


def test_a_burst_holds_the_release_and_drains_while_it_is_held():
    # The transfer queue does not empty when the frames reach the card.  The
    # hold drains it, or the body stops at 32 frames.
    cam, sdk = _camera()
    relay = _relay()
    seen = []
    sdk.drain_buffer.side_effect = lambda budget_s=None: seen.append(
        (relay.closed_channels.copy(), threading.current_thread())) or 0

    cam.shoot_burst(0.2)

    assert len(seen) >= 2, "the burst did not drain while the release was held"
    held, thread = seen[0]
    assert held == {1, 2}
    # On the thread of the burst: on a separate thread the drain did not keep up.
    assert thread is threading.current_thread()
    assert seen[-1][0] == set(), "the last drain runs after the contacts open"
    assert relay.closed_channels == set()
    assert not sdk.shoot_no_af.called


def test_a_burst_drain_round_never_runs_past_the_end_of_the_hold():
    cam, sdk = _camera()
    _relay()
    budgets = []
    sdk.drain_buffer.side_effect = lambda budget_s=None: budgets.append(budget_s) or 0

    cam.shoot_burst(0.1)

    held = [b for b in budgets if b is not None]
    assert held and all(b <= 0.1 for b in held)


def test_a_burst_is_capped_at_the_longest_hold(monkeypatch):
    monkeypatch.setattr(fuji_camera, "MAX_BURST_S", 0.05)
    cam, _ = _camera()
    _relay()

    started = time.monotonic()
    cam.shoot_burst(30)

    assert time.monotonic() - started < 1.0


def test_a_burst_of_no_length_still_takes_a_frame():
    cam, _ = _camera()
    relay = _mock_relay()

    assert cam.shoot_burst(0) >= 1
    assert relay.pressed.called


def test_a_failed_drain_does_not_end_the_burst_early():
    cam, sdk = _camera()
    relay = _relay()
    sdk.drain_buffer.side_effect = RuntimeError("gone")

    started = time.monotonic()
    cam.shoot_burst(0.1)

    assert time.monotonic() - started >= 0.1
    assert relay.closed_channels == set()


def test_the_longest_hold_follows_the_drive_rate():
    # The limit is a number of frames.  The seconds come from the rate, so the
    # two cannot disagree.
    assert fuji_camera.MAX_BURST_S == fuji_camera.MAX_BURST_FRAMES / fuji_camera.RELAY_FPS
    cam, _ = _camera()
    assert cam.max_relay_hold_s == fuji_camera.MAX_BURST_S
