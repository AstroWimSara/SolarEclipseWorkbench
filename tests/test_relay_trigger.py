import inspect
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import serial as serial_mod

from solareclipseworkbench import relay_trigger
from solareclipseworkbench.relay_trigger import (
    Backend,
    DsdSerialBackend,
    RelayError,
    RelayTrigger,
    SimulatedBackend,
    Wiring,
    discover_backends,
    discover_relays,
    get_backend,
    list_backends,
    make_backend,
    register_backend,
    relay_arm,
    relay_bulb,
    relay_burst,
    relay_release,
    relay_shoot,
)


class _FailingBackend(SimulatedBackend):
    """Closes fine, but refuses to open — the worst case for a shutter."""

    def __init__(self):
        super().__init__(latency_s=0.0)
        self.open_attempts = 0

    def set_channel(self, channel, closed):
        if not closed:
            self.open_attempts += 1
            raise RelayError("contact stuck")
        super().set_channel(channel, closed)


def _trigger(single=True):
    wiring = Wiring(s2_channel=1) if single else Wiring(s2_channel=2, s1_channel=1)
    wiring.settle_s = 0.0
    wiring.pulse_s = 0.0
    return RelayTrigger(SimulatedBackend(latency_s=0.0), wiring)


def test_single_channel_wiring_reports_one_channel():
    trigger = _trigger(single=True)

    assert trigger.wiring.is_single_channel
    assert trigger.wiring.channels == [1]


def test_dual_channel_wiring_reports_both_channels():
    trigger = _trigger(single=False)

    assert not trigger.wiring.is_single_channel
    assert trigger.wiring.channels == [1, 2]


def test_shoot_leaves_every_contact_open():
    trigger = _trigger()

    trigger.shoot()

    assert trigger.closed_channels == set()


def test_single_channel_burst_holds_one_contact():
    trigger = _trigger(single=True)

    pulses = trigger.burst(0.05)

    # The camera free-runs while the contact is held, so one closure covers the
    # whole burst and the pulse count says nothing about the frame count.
    assert pulses == 1
    assert trigger.closed_channels == set()


def test_dual_channel_burst_pulses_repeatedly():
    trigger = _trigger(single=False)

    pulses = trigger.burst(0.25, interval_s=0.05)

    assert pulses >= 3
    assert trigger.closed_channels == set()


def test_dual_channel_burst_ignores_interval_on_single_channel():
    trigger = _trigger(single=True)

    assert trigger.burst(0.05, interval_s=0.01) == 1


def test_contacts_open_when_the_block_raises():
    trigger = _trigger()

    with pytest.raises(ZeroDivisionError):
        with trigger.pressed():
            raise ZeroDivisionError("something failed mid-exposure")

    assert trigger.closed_channels == set()


def test_release_all_survives_a_backend_that_refuses():
    # Building the trigger already opens the channels once, and that must not
    # raise either - the constructor meets whatever the last run left behind.
    trigger = RelayTrigger(_FailingBackend(), Wiring(s2_channel=1))
    already = trigger.backend.open_attempts

    # Must not raise: this runs from atexit and signal handlers, where an
    # exception would stop the remaining contacts from being released.
    trigger.release_all()

    assert trigger.backend.open_attempts == already + 1


def test_bulb_releases_after_the_exposure():
    trigger = _trigger()

    trigger.bulb(0.02)

    assert trigger.closed_channels == set()


def test_events_record_each_transition():
    trigger = _trigger()

    trigger.shoot()

    assert len(trigger.events) == 2
    assert trigger.events[0].closed is True
    assert trigger.events[-1].closed is False


def test_scheduler_commands_accept_string_arguments():
    trigger = _trigger()

    # Commands come out of the script as strings, never as floats.
    relay_burst(trigger, "0.05")
    relay_burst(trigger, "0.05", "")
    relay_bulb(trigger, "0.02")

    assert trigger.closed_channels == set()


def test_timing_sample_reports_a_spread():
    trigger = _trigger()

    stats = trigger.timing_sample(samples=5)

    assert stats["samples"] == 5
    assert stats["max_ms"] >= stats["min_ms"]
    assert stats["spread_ms"] == pytest.approx(stats["max_ms"] - stats["min_ms"])


# ------------------------------------------------------------ backend registry


def test_builtin_backends_are_registered():
    backends = discover_backends()

    assert {"lcus", "numato", "dsd", "hid", "simulated"} <= set(backends)


def test_dsd_backend_terminates_at_commands_with_crlf(monkeypatch):
    # The SH-UR parser is line-buffered: without CR/LF it executes nothing,
    # and leftover bytes from an interrupted sender corrupt the next command —
    # hence the bare CR/LF flush on open.

    written = []

    class _FakeSerial:
        def __init__(self, *args, **kwargs): pass
        def write(self, data): written.append(data)
        def flush(self): pass
        def close(self): pass
        def read(self, size): return b"OK+CH1=0\n"
        def reset_input_buffer(self): pass

    monkeypatch.setattr(serial_mod, "Serial", _FakeSerial)
    backend = DsdSerialBackend(port="/dev/fake")
    backend.set_channel(1, True)
    backend.set_channel(4, False)

    assert written == [b"\r\n", b"AT+CH1=0\r\n", b"AT+CH1=1\r\n", b"AT+CH4=0\r\n"]


def test_dsd_backend_refuses_a_port_that_does_not_answer(monkeypatch):
    """A replug can change the serial names, so a saved relay port can point
    at another device.  The SH-UR firmware echoes OK for every command, so a
    silent port is provably not a DSD board and connecting to it must fail."""

    closed = []

    class _MuteSerial:
        def __init__(self, *args, **kwargs): pass
        def write(self, data): pass
        def flush(self): pass
        def close(self): closed.append(True)
        def read(self, size): return b""
        def reset_input_buffer(self): pass

    monkeypatch.setattr(serial_mod, "Serial", _MuteSerial)
    with pytest.raises(RelayError, match="not a DSD board"):
        DsdSerialBackend(port="/dev/fake")
    assert closed, "the silent port was left open"


def test_get_backend_reports_what_is_available_when_the_name_is_wrong():
    with pytest.raises(RelayError, match="lcus"):
        get_backend("no-such-board")


def test_every_backend_declares_a_name():
    for backend in list_backends():
        assert backend.name
        assert backend.name != "backend"


def test_a_third_party_backend_can_register_itself():
    @register_backend
    class Fake(Backend):
        name = "test-only-fake-relay"

        def set_channel(self, channel, closed): pass
        def describe(self): return "fake"

    assert get_backend("test-only-fake-relay") is Fake


def test_registering_a_non_backend_is_refused():
    class NotABackend:
        name = "nope"

    with pytest.raises(TypeError):
        register_backend(NotABackend)


def test_a_backend_without_its_own_name_is_refused():
    class Unnamed(Backend):
        def set_channel(self, channel, closed): pass
        def describe(self): return "unnamed"

    with pytest.raises(ValueError):
        register_backend(Unnamed)


def test_lcus_discovery_leaves_cp2102_ports_to_the_dsd_backend(monkeypatch):
    # LCUS boards are CH340-based; DSD TECH builds on the CP2102.  An SH-UR
    # board offered as LCUS gets the wrong protocol and never fires.

    cp2102 = MagicMock(device="/dev/cu.SLAB_USBtoUART", vid=0x10C4, pid=0xEA60,
                       description="CP2102 USB to UART Bridge Controller",
                       manufacturer="Silicon Labs")
    ch340 = MagicMock(device="/dev/cu.wchusbserial1", vid=0x1A86, pid=0x7523,
                      description="USB Serial", manufacturer=None)
    monkeypatch.setattr(relay_trigger, "usb_serial_ports", lambda: [cp2102, ch340])

    lcus_targets = [c.target for c in relay_trigger.LcusSerialBackend.discover()]
    assert lcus_targets == ["/dev/cu.wchusbserial1"]

    dsd_targets = [c.target for c in relay_trigger.DsdSerialBackend.discover()]
    assert dsd_targets == ["/dev/cu.SLAB_USBtoUART"]


def test_simulated_backend_is_never_offered_by_discovery():
    # A real board must never be silently replaced by a simulated one, or a
    # script would appear to run while firing nothing.
    assert SimulatedBackend.discover() == []


def test_make_backend_honours_an_explicit_name():
    assert isinstance(make_backend("simulated"), SimulatedBackend)


def test_discovered_candidates_are_tagged_as_relays():
    for candidate in discover_relays():
        assert candidate.kind == "relay"
        assert candidate.driver


def test_a_latched_contact_is_opened_when_the_trigger_is_built():
    # A crash runs no shutdown guard, and the board keeps a latched contact
    # into the next run.  A new trigger must start from open contacts.
    backend = make_backend("simulated")
    wiring = Wiring()
    for channel in wiring.channels:
        backend.set_channel(channel, True)

    trigger = RelayTrigger(backend, wiring)

    assert not any(backend.state[c] for c in wiring.channels), \
        "the trigger adopted a latched board"
    assert trigger.closed_channels == set()
    assert trigger.events == [], "inherited state was logged as if commanded"


def test_the_signal_handler_does_no_work_of_its_own():
    """A Python signal handler runs on the main thread between bytecodes, so it
    can interrupt any critical section.  A handler that does USB I/O can leave
    a lock held and the window frozen.  The contacts are opened at exit instead,
    on a normal stack."""

    source = inspect.getsource(relay_trigger._install_shutdown_guards)
    handler = source[source.index("def handler"):]

    assert "_release_all_contacts" not in handler, \
        "the handler does USB work"
    assert "atexit.register(_release_all_contacts)" in source, \
        "nothing would open the contacts at all"


def test_importing_the_module_leaves_the_signal_handlers_alone():
    """The shutdown guards are installed by the first trigger, not by the import."""

    source = inspect.getsource(relay_trigger)
    assert "\n_install_shutdown_guards()\n" not in source
    assert "_install_shutdown_guards()" in inspect.getsource(RelayTrigger.__init__)


def test_relay_arm_holds_s1_until_relay_release():
    trigger = _trigger(single=False)

    relay_arm(trigger)
    assert trigger.closed_channels == {trigger.wiring.s1_channel}

    # A pre-armed shot leaves S1 closed on the way out.
    relay_shoot(trigger)
    assert trigger.closed_channels == {trigger.wiring.s1_channel}

    relay_release(trigger)
    assert trigger.closed_channels == set()


def test_a_relay_command_that_cannot_have_the_trigger_is_dropped(monkeypatch):
    """Two overlapping jobs must not press the same contacts.  A command that
    waits longer than the camera commands may wait is dropped, not fired late."""

    monkeypatch.setattr(relay_trigger, "_MAX_LOCK_WAIT_S", 0.05)
    reported = []
    monkeypatch.setattr(relay_trigger.hardware_problems, "report",
                        lambda *args, **kwargs: reported.append(args))
    trigger = _trigger()
    busy = threading.Event()
    done = threading.Event()

    def hold():
        with trigger._lock:
            busy.set()
            done.wait(2.0)

    holder = threading.Thread(target=hold)
    holder.start()
    busy.wait(1.0)
    try:
        relay_shoot(trigger)
    finally:
        done.set()
        holder.join()

    assert trigger.events == [], "the dropped shot still pressed the contacts"
    assert reported and "dropped" in reported[0][1]


def test_relay_release_does_not_wait_for_a_running_command():
    trigger = _trigger(single=False)
    trigger.half_press()
    started = threading.Event()
    finished = threading.Event()

    def burst():
        started.set()
        relay_burst(trigger, "0.5")
        finished.set()

    worker = threading.Thread(target=burst)
    worker.start()
    started.wait(1.0)
    time.sleep(0.05)
    t0 = time.monotonic()
    relay_release(trigger)
    assert time.monotonic() - t0 < 0.2, "the release waited for the burst"
    worker.join()
    assert trigger.closed_channels == set()


def test_the_relay_port_is_reopened_after_a_transient_lock():
    """macOS holds the exclusive lock on a /dev/cu device for a moment after it
    is closed, and the scan that identifies the relay closes the port right
    before the connect opens it.  The open is retried through that lock."""

    attempts = []

    class _FakeSerial:
        def __init__(self, *args, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:            # locked, then free
                raise serial_mod.SerialException(
                    "[Errno 35] Could not exclusively lock port")
        def write(self, data): pass
        def flush(self): pass
        def close(self): pass
        def read(self, size): return b"OK+CH1=0\n"
        def reset_input_buffer(self): pass

    with patch.object(serial_mod, "Serial", _FakeSerial):
        backend = DsdSerialBackend(port="/dev/fake")

    assert len(attempts) == 3, "the open was not retried through the lock"
    assert backend.port == "/dev/fake"


def test_a_relay_port_that_never_opens_still_gives_up():
    """The retry must not hang a connect on a port that is simply not there."""

    class _NeverOpens:
        def __init__(self, *args, **kwargs):
            raise serial_mod.SerialException("[Errno 2] No such file or directory")

    with patch.object(relay_trigger, "OPEN_RETRY_S", 0.3), \
         patch.object(serial_mod, "Serial", _NeverOpens):
        started = time.monotonic()
        with pytest.raises(RelayError, match="cannot open relay"):
            DsdSerialBackend(port="/dev/nope")
        assert time.monotonic() - started < 2.0
