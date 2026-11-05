"""The mount panel connects a mount through INDI, registers it for the script commands, and lets it go again."""
from pathlib import Path

import pytest

from solareclipseworkbench import gui
from solareclipseworkbench.hardware_registry import HARDWARE, register_hardware
from solareclipseworkbench.indi_simulator import DEVICE, SimulatedIndiServer
from solareclipseworkbench.observer import Observer


class FakeController(Observer):
    def __init__(self):
        self.mount = None
        self.updates = []
        # Keeping the sun centred
        self.mount_calibration = None
        self.centrer = None
        self._live_view_window = None

    def stop_centring(self):
        self.centrer = None

    def update(self, changed_object):
        self.updates.append(changed_object)

    def do(self, actions):
        pass

    def send_site_to_mount(self):
        return self.mount.send_site(40.4, -3.7, 650)


@pytest.fixture
def server():
    server = SimulatedIndiServer()
    yield server
    server.close()


@pytest.fixture
def popup(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    messages = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *args: messages.append(args[2]))
    register_hardware("mount", None)
    controller = FakeController()
    widget = gui.MountPopup(controller)
    widget.messages = messages
    yield widget
    if controller.mount is not None:
        controller.mount.close()
    register_hardware("mount", None)
    widget.close()


def test_finding_mounts_lists_them(popup, server):
    popup.address.setText(f"127.0.0.1:{server.port}")
    popup.find_mounts()
    assert popup.device_combobox.currentText() == DEVICE


def test_connecting_registers_the_mount_and_sends_the_site(popup, server):
    popup.address.setText(f"127.0.0.1:{server.port}")
    popup.connect_or_disconnect()

    mount = popup.controller.mount
    assert HARDWARE["mount"] is mount
    assert popup.connect_button.text() == "Disconnect"
    assert popup.track_button.isEnabled()
    assert server.values("GEOGRAPHIC_COORD")["LAT"] == pytest.approx(40.4)
    assert "Sent to the mount" in popup.site_label.text()

    popup.track()
    assert mount.tracking
    assert "tracking (solar)" in popup.status_label.text()


def test_disconnecting_unregisters_the_mount_and_leaves_it_tracking(popup, server):
    popup.address.setText(f"127.0.0.1:{server.port}")
    popup.connect_or_disconnect()
    popup.track()
    popup.connect_or_disconnect()

    assert popup.controller.mount is None
    assert "mount" not in HARDWARE
    assert popup.connect_button.text() == "Connect"
    assert not popup.track_button.isEnabled()
    assert server.values("TELESCOPE_TRACK_STATE")["TRACK_ON"]


def test_no_server_is_shown_not_raised(popup):
    popup.address.setText("127.0.0.1:1")
    popup.connect_or_disconnect()
    assert popup.controller.mount is None
    assert "no INDI server" in popup.messages[0]


def test_a_mount_without_solar_rate_says_so(popup):
    server = SimulatedIndiServer(solar=False)
    try:
        popup.address.setText(f"127.0.0.1:{server.port}")
        popup.connect_or_disconnect()
        popup.track()
        assert "sidereal" in popup.messages[-1]
    finally:
        popup.controller.mount.close()
        popup.controller.mount = None
        server.close()
