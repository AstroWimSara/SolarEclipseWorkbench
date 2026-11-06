"""Starting the INDI server for the mount, and choosing the mount from INDI's driver lists."""
import os
import socket
import stat
import sys
import textwrap
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from solareclipseworkbench.indi_server import (IndiServer, IndiServerError, MountDriver, find_server, mount_drivers,
                                               parse_drivers, server_running)
from solareclipseworkbench.indi_simulator import SimulatedIndiServer
from solareclipseworkbench.mount import Mount, network_address

DRIVERS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<driversList>
  <devGroup group="Telescopes">
    <device label="LX200 Classic" manufacturer="Meade">
      <driver name="LX200 Classic">indi_lx200classic</driver>
      <version>2.0</version>
    </device>
    <device label="EQMod Mount" manufacturer="Sky-Watcher">
      <driver name="EQMod Mount">indi_eqmod_telescope</driver>
    </device>
  </devGroup>
  <devGroup group="CCDs">
    <device label="CCD Simulator"><driver name="CCD Simulator">indi_simulator_ccd</driver></device>
  </devGroup>
</driversList>
"""

IOPTRON_XML = """<driversList>
  <devGroup group="Telescopes">
    <device label="iOptron HAZ31" manufacturer="iOptron">
      <driver name="iOptronV3">indi_ioptronv3_telescope</driver>
    </device>
    <device label="EQMod Mount" manufacturer="Sky-Watcher">
      <driver name="EQMod Mount">indi_eqmod_telescope</driver>
    </device>
  </devGroup>
</driversList>
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def drivers(tmp_path):
    folder = tmp_path / "indi"
    folder.mkdir()
    (folder / "drivers.xml").write_text(DRIVERS_XML)
    (folder / "indi-ioptron.xml").write_text(IOPTRON_XML)
    (folder / "broken.xml").write_text("<driversList><devGroup")
    return folder


@pytest.fixture
def fake_indi(tmp_path):
    """A fake indiserver (the simulated INDI server on the -p port) and a fake driver executable."""
    src = Path(__file__).resolve().parents[1] / "src"
    server = tmp_path / "indiserver"
    server.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import sys, time
        sys.path.insert(0, {str(src)!r})
        args = sys.argv[1:]
        port = int(args[args.index("-p") + 1])
        driver = args[-1]
        print("fake indiserver: starting", driver, "on", port, flush=True)
        if driver.endswith("broken_driver"):
            print("driver broken_driver: exec failed", flush=True)
            sys.exit(1)
        from solareclipseworkbench.indi_simulator import SimulatedIndiServer
        SimulatedIndiServer(port=port)
        while True:
            time.sleep(1)
        """))
    driver = tmp_path / "indi_fake_telescope"
    driver.write_text("#!/bin/sh\n")
    broken = tmp_path / "broken_driver"
    broken.write_text("#!/bin/sh\n")
    for path in (server, driver, broken):
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return server, driver, broken


# ------------------------------------------------------------- the driver lists


def test_the_mounts_of_the_driver_lists(drivers):
    mounts = mount_drivers([drivers])
    labels = [m.label for m in mounts]
    assert labels == ["iOptron HAZ31", "Meade LX200 Classic", "Sky-Watcher EQMod Mount"]   # each once, sorted
    haz = mounts[0]
    assert (haz.manufacturer, haz.model, haz.executable, haz.name) == \
        ("iOptron", "iOptron HAZ31", "indi_ioptronv3_telescope", "iOptronV3")
    assert "indi_simulator_ccd" not in [m.executable for m in mounts]         # not a telescope


def test_a_broken_driver_list_is_skipped(drivers):
    assert parse_drivers(drivers / "broken.xml") == []


def test_no_indi_no_mounts(tmp_path):
    assert mount_drivers([tmp_path]) == []


def test_a_label_without_the_manufacturer_gets_it():
    assert MountDriver("iOptron", "CEM40", "x").label == "iOptron CEM40"
    assert MountDriver("iOptron", "iOptron CEM40", "x").label == "iOptron CEM40"
    assert MountDriver("", "Telescope Simulator", "x").label == "Telescope Simulator"
    assert MountDriver("Simulator", "Telescope Simulator", "x").label == "Telescope Simulator"


# ----------------------------------------------------------------- the server


def test_the_server_is_started_used_and_stopped(fake_indi):
    server_path, driver, _ = fake_indi
    port = _free_port()
    server = IndiServer(str(driver), port=port, server=str(server_path))
    server.start()
    try:
        assert server.owned and server.running and server_running(port)
        assert "fake indiserver: starting" in server.log_path.read_text()
        mount = Mount.open(f"localhost:{port}")
        assert mount.connected
        mount.close()
    finally:
        server.stop()
    assert not server.running
    deadline = time.monotonic() + 5
    while server_running(port) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not server_running(port)


def test_a_server_that_already_runs_is_used_and_left_alone(fake_indi):
    server_path, driver, _ = fake_indi
    running = SimulatedIndiServer()
    try:
        server = IndiServer(str(driver), port=running.port, server=str(server_path))
        server.start()
        assert server.borrowed and not server.owned
        assert "already runs" in server.describe()
        server.stop()
        assert server_running(running.port)                # still there
    finally:
        running.close()


def test_without_indi_the_message_says_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setattr("solareclipseworkbench.indi_server.find_server", lambda: None)
    with pytest.raises(IndiServerError, match="apt install indi-bin"):
        IndiServer("indi_eqmod_telescope", port=_free_port()).start()


def test_a_driver_that_is_not_installed(fake_indi):
    server_path, _, _ = fake_indi
    with pytest.raises(IndiServerError, match="not installed"):
        IndiServer("indi_no_such_telescope", port=_free_port(), server=str(server_path)).start()


def test_a_server_that_stops_at_once_says_why(fake_indi):
    server_path, _, broken = fake_indi
    server = IndiServer(str(broken), port=_free_port(), server=str(server_path))
    with pytest.raises(IndiServerError, match="exec failed"):
        server.start()
    assert not server.running


@pytest.mark.skipif(find_server() is None or not Path("/usr/bin/indi_simulator_telescope").exists(),
                    reason="INDI is not installed")
def test_the_real_indiserver_with_the_telescope_simulator():
    server = IndiServer("indi_simulator_telescope", port=_free_port())
    server.start()
    try:
        mount = Mount.open(f"localhost:{server.port}", timeout=20)
        assert mount.connected
        assert mount.track_solar() in ("solar", "sidereal")
        mount.close()
    finally:
        server.stop()


# ------------------------------------------------- how the driver reaches the mount


@pytest.mark.parametrize("text, expected", [
    ("192.168.4.1:8899", ("192.168.4.1", 8899)), ("tcp://mount.local:4030", ("mount.local", 4030)),
    ("/dev/ttyUSB0", None), ("COM3", None), ("", None), ("mount.local", None),
])
def test_network_addresses_and_serial_ports(text, expected):
    assert network_address(text) == expected


def test_a_network_address_switches_the_driver_to_tcp():
    server = SimulatedIndiServer()
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}", device_port="192.168.4.1:8899")
        assert server.values("CONNECTION_MODE")["CONNECTION_TCP"]
        assert server.values("DEVICE_ADDRESS") == {"ADDRESS": "192.168.4.1", "PORT": "8899"}
        mount.close()
    finally:
        server.close()


def test_without_a_port_the_driver_searches(monkeypatch):
    server = SimulatedIndiServer()
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        assert server.values("DEVICE_AUTO_SEARCH")["INDI_ENABLED"]
        mount.close()
    finally:
        server.close()


# ------------------------------------------------------------- the Mount window


def test_the_mount_window_starts_the_server_for_the_chosen_model(tmp_path, monkeypatch, drivers, fake_indi):
    from PyQt6.QtWidgets import QApplication

    from solareclipseworkbench import gui
    from solareclipseworkbench.observer import Observer

    _app = QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    server_path, driver, _ = fake_indi
    port = _free_port()
    haz = MountDriver("iOptron", "HAZ31", str(driver), "iOptronV3")
    monkeypatch.setattr(gui, "mount_drivers", lambda: [MountDriver("Meade", "LX200 Nowhere", "indi_not_installed_x"),
                                                       haz])
    monkeypatch.setattr(gui, "IndiServer", lambda executable: IndiServer(executable, port=port,
                                                                         server=str(server_path)))
    opened = []
    real_open = gui.Mount.open

    def open_mount(address, device=None, device_port=None, timeout=15.0):
        opened.append((address, device, device_port, timeout))
        return real_open(f"localhost:{port}", device, device_port, timeout)

    monkeypatch.setattr(gui.Mount, "open", staticmethod(open_mount))
    messages = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: messages.append(args[2]))

    class Controller(Observer):
        mount = None
        indi_server = None
        mount_calibration = None
        centrer = None
        _live_view_window = None

        def update(self, changed_object):
            pass

        def do(self, actions):
            pass

        def stop_centring(self):
            pass

        def stop_indi_server(self):
            if self.indi_server is not None:
                self.indi_server.stop()
                self.indi_server = None

        def send_site_to_mount(self):
            return []

    controller = Controller()
    popup = gui.MountPopup(controller)
    try:
        popup.simulated_checkbox.setChecked(False)
        popup.start_server_checkbox.setChecked(True)
        assert not popup.address.isEnabled() and popup.model_combobox.isEnabled()
        assert popup.model_combobox.count() == 2
        assert "(driver not installed)" in popup.model_combobox.itemText(0)
        popup.model_combobox.setCurrentIndex(1)
        popup.connect_or_disconnect()
        assert messages == []
        assert controller.mount is not None and controller.indi_server.owned
        assert opened[-1][:3] == ("localhost", None, None) and opened[-1][3] > 15   # the driver searches the ports
        assert "INDI server started" in popup.site_label.text()

        popup.connect_or_disconnect()                    # disconnect: the server stops too
        assert controller.mount is None and controller.indi_server is None
        assert not server_running(port) or time.sleep(1) or not server_running(port)

        # Remembered for the next time
        again = gui.MountPopup(controller)
        assert again.start_server_checkbox.isChecked()
        assert again.selected_driver() == haz
        again.close()
    finally:
        if controller.mount is not None:
            controller.mount.close()
        controller.stop_indi_server()
        popup.close()
