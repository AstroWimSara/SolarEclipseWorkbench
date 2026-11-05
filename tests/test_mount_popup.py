"""The mount panel connects a mount, registers it for the script commands, and lets it go again."""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui
from solareclipseworkbench.hardware_registry import HARDWARE, register_hardware
from solareclipseworkbench.mounts import MountError
from solareclipseworkbench.mounts.simulator import SimulatorMount
from solareclipseworkbench.observer import Observer


class FakeController(Observer):
    def __init__(self):
        self.mount = None
        self.model = SimpleNamespace(latitude=None, longitude=None)
        self.updates = []

    def update(self, changed_object):
        self.updates.append(changed_object)

    def do(self, actions):
        pass


@pytest.fixture
def popup(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(gui, "discover_mounts", lambda: [])
    warnings = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    register_hardware("mount", None)
    controller = FakeController()
    widget = gui.MountPopup(controller)
    widget.warnings = warnings
    yield widget
    if controller.mount is not None:
        controller.mount.close()
    register_hardware("mount", None)
    widget.close()


def _select_simulator(popup):
    popup.driver_combobox.setCurrentIndex(popup.driver_combobox.findData("simulator"))


def _wait_until(condition, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition()


def test_connecting_registers_the_mount_for_the_script(popup):
    _select_simulator(popup)

    popup.connect_or_disconnect()
    _wait_until(lambda: popup.controller.mount is not None)

    assert isinstance(popup.controller.mount, SimulatorMount)
    assert HARDWARE["mount"] is popup.controller.mount
    assert popup.connect_button.text() == "Disconnect"
    assert popup.goto_sun_button.isEnabled()
    assert popup in popup.controller.updates


def test_the_buttons_reach_the_mount(popup):
    _select_simulator(popup)
    popup.connect_or_disconnect()
    _wait_until(lambda: popup.controller.mount is not None)
    mount = popup.controller.mount

    popup.track_sun()
    assert mount.status().tracking_rate == "solar"
    assert mount.status().tracking is True
    popup.park()
    assert mount.status().parked is True
    popup.goto_sun()
    assert popup.warnings, "a goto while parked must say why it failed"
    popup.unpark()
    assert mount.status().parked is False


def test_disconnecting_unregisters_the_mount(popup):
    _select_simulator(popup)
    popup.connect_or_disconnect()
    _wait_until(lambda: popup.controller.mount is not None)

    popup.connect_or_disconnect()

    assert popup.controller.mount is None
    assert "mount" not in HARDWARE
    assert popup.connect_button.text() == "Connect"
    assert not popup.goto_sun_button.isEnabled()


def test_a_mount_that_does_not_answer_is_reported(popup, monkeypatch):
    def refuse(driver, **config):
        raise MountError(f"nothing answered LX200 on {config.get('port')}")

    monkeypatch.setattr(gui, "connect_mount", refuse)
    popup.port_combobox.setCurrentText("/dev/ttyUSB7 — ? no LX200 answer")

    popup.connect_or_disconnect()
    _wait_until(lambda: popup.warnings)

    assert "nothing answered LX200 on /dev/ttyUSB7" in popup.warnings[0]
    assert popup.controller.mount is None
    assert "mount" not in HARDWARE
    assert popup.connect_button.isEnabled()


def test_a_host_is_used_instead_of_the_port(popup, monkeypatch):
    calls = []
    monkeypatch.setattr(gui, "connect_mount", lambda driver, **config: calls.append((driver, config))
                        or SimulatorMount())
    popup.driver_combobox.setCurrentIndex(popup.driver_combobox.findData("onstepx"))
    popup.port_combobox.setCurrentText("/dev/ttyUSB7")
    popup.host_edit.setText("192.168.0.1")

    popup.connect_or_disconnect()
    _wait_until(lambda: popup.controller.mount is not None)

    assert calls == [("onstepx", {"host": "192.168.0.1"})]
