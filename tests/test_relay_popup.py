"""The relay panel connects a relay, registers it for the script commands, and lets it go again."""
from pathlib import Path

import pytest

from solareclipseworkbench import gui
from solareclipseworkbench.hardware_registry import HARDWARE, register_hardware
from solareclipseworkbench.observer import Observer
from solareclipseworkbench.relay_trigger import SimulatedBackend


class FakeController(Observer):
    def __init__(self):
        self.relay_trigger = None
        self.updates = []

    def update(self, changed_object):
        self.updates.append(changed_object)

    def do(self, actions):
        pass


@pytest.fixture
def popup(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(gui, "discover_relays", lambda: [])
    warnings = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    register_hardware("relay", None)
    controller = FakeController()
    widget = gui.RelayPopup(controller)
    widget.warnings = warnings
    yield widget
    if controller.relay_trigger is not None:
        controller.relay_trigger.close()
    register_hardware("relay", None)
    widget.close()


def test_connecting_registers_the_relay_for_the_script(popup):
    popup.backend_combobox.setCurrentText("simulated")
    popup.s2_channel.setText("2")
    popup.s1_checkbox.setChecked(True)
    popup.s1_channel.setText("1")

    popup.connect_or_disconnect()

    trigger = popup.controller.relay_trigger
    assert isinstance(trigger.backend, SimulatedBackend)
    assert HARDWARE["relay"] is trigger
    assert (trigger.wiring.s1_channel, trigger.wiring.s2_channel) == (1, 2)
    assert popup.connect_button.text() == "Disconnect"
    assert popup.test_button.isEnabled()


def test_disconnecting_unregisters_the_relay(popup):
    popup.backend_combobox.setCurrentText("simulated")
    popup.connect_or_disconnect()

    popup.connect_or_disconnect()

    assert popup.controller.relay_trigger is None
    assert "relay" not in HARDWARE
    assert popup.connect_button.text() == "Connect"
    assert not popup.test_button.isEnabled()


def test_s1_and_s2_on_one_channel_is_refused(popup):
    popup.backend_combobox.setCurrentText("simulated")
    popup.s2_channel.setText("1")
    popup.s1_checkbox.setChecked(True)
    popup.s1_channel.setText("1")

    popup.connect_or_disconnect()

    assert popup.controller.relay_trigger is None
    assert popup.warnings


def test_the_wiring_is_remembered(popup, tmp_path):
    popup.backend_combobox.setCurrentText("simulated")
    popup.s2_channel.setText("3")
    popup.connect_or_disconnect()
    popup.connect_or_disconnect()

    again = gui.RelayPopup(popup.controller)
    try:
        assert again.backend_combobox.currentText() == "simulated"
        assert again.s2_channel.text() == "3"
    finally:
        again.close()


def test_the_default_wiring_is_one_channel(popup):
    assert popup.s2_channel.text() == "1"
    assert not popup.s1_checkbox.isChecked()
