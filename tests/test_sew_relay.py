"""The command line opens a relay only when --relay asks for one."""
from types import SimpleNamespace

import pytest

from solareclipseworkbench import sew
from solareclipseworkbench.hardware_registry import HARDWARE, register_hardware
from solareclipseworkbench.relay_trigger import RelayError, SimulatedBackend


@pytest.fixture(autouse=True)
def clean_registry():
    register_hardware("relay", None)
    yield
    trigger = HARDWARE.get("relay")
    if trigger is not None:
        trigger.close()
    register_hardware("relay", None)


def _args(relay, backend="auto", s2=1, s1=None):
    return SimpleNamespace(relay=relay, relay_backend=backend, relay_s2=s2, relay_s1=s1)


def test_no_relay_is_opened_without_the_option(monkeypatch):
    opened = []
    monkeypatch.setattr(sew, "open_trigger", lambda *args, **kwargs: opened.append(args))

    sew.open_relay(_args(None))

    assert opened == []
    assert "relay" not in HARDWARE


def test_the_relay_asked_for_is_opened_and_registered():
    sew.open_relay(_args("auto", backend="simulated", s2=2, s1=1))

    trigger = HARDWARE["relay"]
    assert isinstance(trigger.backend, SimulatedBackend)
    assert (trigger.wiring.s1_channel, trigger.wiring.s2_channel) == (1, 2)


def test_a_relay_that_cannot_be_opened_is_reported_not_raised(monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise RelayError("nothing on /dev/ttyUSB9")

    monkeypatch.setattr(sew, "open_trigger", refuse)

    sew.open_relay(_args("/dev/ttyUSB9"))

    assert "relay" not in HARDWARE
    assert "nothing on /dev/ttyUSB9" in capsys.readouterr().out
