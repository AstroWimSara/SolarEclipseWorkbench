"""The mount panel connects a mount through INDI, registers it for the script commands, and lets it go again."""
from pathlib import Path

import pytest

from types import SimpleNamespace

from PyQt6.QtCore import QSettings

from solareclipseworkbench import gui
from solareclipseworkbench.indi_server import MountDriver
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
        self.model = SimpleNamespace(latitude=40.4, longitude=-3.7)

    def stop_centring(self):
        self.centrer = None

    def stop_indi_server(self):
        pass

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


def test_reversed_axes_are_kept_for_the_mount(popup, server):
    assert not popup.reverse_ns_checkbox.isEnabled()
    popup.address.setText(f"127.0.0.1:{server.port}")
    popup.connect_or_disconnect()
    mount = popup.controller.mount
    assert popup.reverse_ns_checkbox.isEnabled() and not popup.reverse_ns_checkbox.isChecked()
    assert not mount.reverse_ns and not mount.reverse_we

    popup.reverse_ns_checkbox.setChecked(True)
    assert mount.reverse_ns and not mount.reverse_we

    popup.connect_or_disconnect()
    popup.reverse_ns_checkbox.setChecked(False)     # disconnected: changes nothing that is kept
    popup.connect_or_disconnect()
    assert popup.controller.mount.reverse_ns and not popup.controller.mount.reverse_we
    assert popup.reverse_ns_checkbox.isChecked()


def test_a_mount_that_does_not_keep_tracking_says_so(popup):
    server = SimulatedIndiServer(track_drops=10)
    try:
        popup.address.setText(f"127.0.0.1:{server.port}")
        popup.connect_or_disconnect()
        popup.track()
        assert "does not keep tracking" in popup.messages[-1]
        assert "not tracking" in popup.status_label.text()
    finally:
        popup.controller.mount.close()
        popup.controller.mount = None
        server.close()


def test_a_mount_that_had_another_location_gets_a_warning(popup):
    server = SimulatedIndiServer(location=(50.83, 4.86))
    try:
        popup.address.setText(f"127.0.0.1:{server.port}")
        popup.connect_or_disconnect()
        assert "50.83° N, 4.86° E" in popup.messages[-1] and "40.40° N, 3.70° W" in popup.messages[-1]
        assert "alt-azimuth" in popup.messages[-1]
        assert server.values("GEOGRAPHIC_COORD")["LAT"] == pytest.approx(40.4)     # sent all the same
        popup.connect_or_disconnect()
        popup.connect_or_disconnect()                   # it has the location now: no warning
        assert len(popup.messages) == 1
    finally:
        popup.controller.mount.close()
        popup.controller.mount = None
        server.close()


def test_a_mount_near_its_location_or_without_one_gets_no_warning(popup):
    server = SimulatedIndiServer(location=(40.5, -3.6))
    try:
        popup.address.setText(f"127.0.0.1:{server.port}")
        popup.connect_or_disconnect()
        assert popup.messages == []
    finally:
        popup.controller.mount.close()
        popup.controller.mount = None
        server.close()


def test_each_mount_model_keeps_its_port(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    haz = MountDriver("iOptron", "HAZ31", "indi_ioptronv3_telescope")
    azgti = MountDriver("SkyWatcher", "AZ-GTi Alt-Az WiFi", "indi_skywatcherAltAzMount")
    monkeypatch.setattr(gui, "mount_drivers", lambda: [haz, azgti])
    settings = QSettings(str(tmp_path / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)
    settings.setValue("mount/start_server", True)
    settings.setValue("mount/driver", haz.executable)
    settings.setValue("mount/model", haz.label)
    settings.setValue("mount/device_port", "10.10.100.254:8899")         # saved before ports were per model
    settings.setValue(f"mount/device_port/{azgti.label}", "192.168.4.1:11880")
    settings.sync()

    widget = gui.MountPopup(FakeController())
    try:
        assert widget.selected_driver() == haz
        assert widget.device_port.text() == "10.10.100.254:8899"
        widget.model_combobox.setCurrentIndex(1)
        assert widget.device_port.text() == "192.168.4.1:11880"
        assert widget._device_port_key() == f"mount/device_port/{azgti.label}"
        widget.model_combobox.setCurrentIndex(0)
        assert widget.device_port.text() == ""          # the HAZ31 never connected with a port of its own
        widget.start_server_checkbox.setChecked(False)
        assert widget.device_port.text() == "10.10.100.254:8899"     # the server started elsewhere
    finally:
        widget.close()
