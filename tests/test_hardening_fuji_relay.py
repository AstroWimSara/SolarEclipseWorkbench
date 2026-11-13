"""Regression tests for the hardening of the Fuji SDK bindings and the relay trigger.

No hardware: the SDK is a MagicMock, the relay a simulated or fake backend.
"""

import gc
from unittest.mock import MagicMock

import pytest
import serial as serial_mod

from fujixsdk import camera as sdk_camera_mod
from fujixsdk.camera import Camera
from solareclipseworkbench import fuji_camera, hardware_problems
from solareclipseworkbench.fuji_camera import FujiCamera
from solareclipseworkbench.hardware_registry import TETHERED_CAMERA, register_hardware
from solareclipseworkbench.relay_trigger import (DsdSerialBackend, LcusSerialBackend, RelayError,
                                                 RelayTrigger, SimulatedBackend, Wiring, relay_arm,
                                                 relay_shoot)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(fuji_camera, "BUSY_BACKOFF_S", 0.001)
    monkeypatch.setattr(fuji_camera, "TAP_GAP_S", 0.0)
    monkeypatch.setattr(fuji_camera, "TAP_EXPOSURE_MARGIN_S", 0.0)
    monkeypatch.setattr(fuji_camera, "SETTLE_BEFORE_DRAIN_S", 0.0)
    monkeypatch.setattr(fuji_camera, "SETTLE_BETWEEN_DRAINS_S", 0.0)
    hardware_problems.clear()
    register_hardware("relay", None)
    register_hardware(TETHERED_CAMERA, None)
    yield
    register_hardware("relay", None)
    register_hardware(TETHERED_CAMERA, None)
    hardware_problems.clear()


# ------------------------------------------------------------ fujixsdk.Camera

def test_del_of_a_camera_without_closed_does_not_raise():
    cam = Camera.__new__(Camera)
    cam.__del__()          # used to raise AttributeError: no attribute '_closed'


def test_a_library_that_fails_to_load_leaves_nothing_to_close(monkeypatch):
    def _boom(cls, sdk_path):
        raise OSError("XAPI.so: cannot open shared object file")

    monkeypatch.setattr(Camera, "_ensure_lib", classmethod(_boom))
    close_calls = []
    monkeypatch.setattr(Camera, "close", lambda self: close_calls.append(self))

    with pytest.raises(OSError):
        Camera("/nowhere", "ENUM:0")
    gc.collect()

    assert not close_calls, "__del__ tore down a session that was never opened"


def test_a_failed_open_leaves_nothing_to_close(monkeypatch):
    lib = MagicMock()
    lib.XSDK_OpenEx.return_value = -1
    monkeypatch.setattr(Camera, "_ensure_lib", classmethod(lambda cls, p: lib))
    monkeypatch.setattr(sdk_camera_mod.recovery, "unblock", MagicMock())

    with pytest.raises(Exception):
        Camera("/sdk", "ENUM:0")
    gc.collect()

    lib.XSDK_Close.assert_not_called()
    lib.XSDK_Release.assert_not_called()


def test_a_successful_open_is_closed_once(monkeypatch):
    lib = MagicMock()
    lib.XSDK_OpenEx.return_value = 0
    lib.XSDK_GetBufferCapacity.return_value = 0
    monkeypatch.setattr(Camera, "_ensure_lib", classmethod(lambda cls, p: lib))
    monkeypatch.setattr(Camera, "_release_lib", classmethod(lambda cls: None))
    monkeypatch.setattr(sdk_camera_mod.recovery, "unblock", MagicMock())

    cam = Camera("/sdk", "ENUM:0")
    assert not cam._closed
    cam.close()
    cam.__del__()

    assert lib.XSDK_Close.call_count == 1


# ------------------------------------------------------------ FujiCamera

def _fuji():
    sdk = MagicMock()
    sdk.get_buffer_capacity.return_value = (0, 32)
    sdk.drain_buffer.return_value = 0
    sdk.get_shutter_speed.return_value = (0, 0)
    return FujiCamera(sdk, "Fuji Fujifilm X-T4", "/sdk", "ENUM:0", model="X-T4"), sdk


def test_a_ladder_that_fails_part_way_forgets_the_applied_speed():
    camera, sdk = _fuji()
    camera._applied_speed = 1000            # what the last configure wrote
    shooter = MagicMock()
    shooter.bracket_no_download.side_effect = RuntimeError("USB gone mid-ladder")
    camera._shooter = shooter

    with pytest.raises(RuntimeError):
        camera.shoot_ladder([1 / 1000, 1 / 250, 1 / 60])

    # The body may be on any speed of the ladder: the next configure must write
    # the speed again rather than skip it as already set.
    assert camera._applied_speed is None
    sdk.set_shutter_speed.reset_mock()
    camera.configure(shutter_speed="1/1000")
    sdk.set_shutter_speed.assert_called_once()


def test_disconnect_drops_the_closed_session():
    camera, sdk = _fuji()

    camera.disconnect()

    sdk.close.assert_called_once()
    assert camera._sdk_cam is None
    # A status poll after disconnect does not reach the closed handle.
    assert camera.get_config().get_child_by_name("batterylevel").get_value() == "Unknown"
    assert camera.get_storageinfo() == []


# ------------------------------------------------------------ relay

class _UnpluggedSerial:
    """A serial port whose adapter was pulled: flush fails with a non-Serial error."""

    def __init__(self, *args, **kwargs):
        self.closed = False

    def write(self, data):
        pass

    def flush(self):
        raise OSError(5, "Input/output error")

    def close(self):
        self.closed = True

    def read(self, size):
        return b"OK"

    def reset_input_buffer(self):
        pass


def test_an_unplugged_serial_relay_raises_relay_error(monkeypatch):
    monkeypatch.setattr(serial_mod, "Serial", _UnpluggedSerial)
    backend = LcusSerialBackend(port="/dev/fake")

    with pytest.raises(RelayError):
        backend.set_channel(1, True)


def test_a_dsd_port_that_fails_the_probe_is_closed(monkeypatch):
    opened = []

    class _Tracked(_UnpluggedSerial):
        def __init__(self, *args, **kwargs):
            super().__init__()
            opened.append(self)

    monkeypatch.setattr(serial_mod, "Serial", _Tracked)
    with pytest.raises(RelayError):
        DsdSerialBackend(port="/dev/fake")

    assert opened and opened[-1].closed, "the port stayed open and exclusively locked"


class _CloseFailsBackend(SimulatedBackend):
    """Closes S1, then fails on the next close; opening always works."""

    def __init__(self):
        super().__init__(latency_s=0.0)
        self.fail_close = False

    def set_channel(self, channel, closed):
        if closed and self.fail_close:
            # The board latched the contact, but the write reported a failure.
            self.state[channel] = True
            raise RelayError("write failed")
        super().set_channel(channel, closed)


def test_a_failed_relay_command_leaves_every_contact_open():
    backend = _CloseFailsBackend()
    trigger = RelayTrigger(backend, Wiring(s2_channel=2, s1_channel=1, settle_s=0.0, pulse_s=0.0))
    backend.fail_close = True

    with pytest.raises(RelayError):
        relay_arm(trigger)

    assert not any(backend.state.values()), "a contact was left closed after the failure"
    assert any("relay_arm" in p.message for p in hardware_problems.peek())


def test_a_failed_relay_shoot_is_reported_and_releases():
    backend = _CloseFailsBackend()
    trigger = RelayTrigger(backend, Wiring(s2_channel=1, settle_s=0.0, pulse_s=0.0))
    backend.fail_close = True

    with pytest.raises(RelayError):
        relay_shoot(trigger)

    assert not any(backend.state.values())
    assert not trigger._lock._is_owned(), "the trigger lock was not released"


def test_timing_sample_opens_the_contact_when_a_write_fails():
    class _OpenFailsOnce(SimulatedBackend):
        failed = False

        def set_channel(self, channel, closed):
            if not closed and not self.failed and self.state.get(channel):
                self.failed = True
                raise RelayError("write failed")
            super().set_channel(channel, closed)

    backend = _OpenFailsOnce(latency_s=0.0)
    trigger = RelayTrigger(backend, Wiring(s2_channel=1))

    with pytest.raises(RelayError):
        trigger.timing_sample(samples=3)

    assert backend.state.get(1) is False
    assert trigger.closed_channels == set()
