"""The command line opens a mount only when --mount or --mount-host asks for one."""
from types import SimpleNamespace

import pytest

from solareclipseworkbench import sew
from solareclipseworkbench.hardware_registry import HARDWARE, register_hardware
from solareclipseworkbench.mounts import Capabilities, MountError
from solareclipseworkbench.mounts.simulator import SimulatorMount


@pytest.fixture(autouse=True)
def clean_registry():
    register_hardware("mount", None)
    yield
    mount = HARDWARE.get("mount")
    if mount is not None:
        mount.close()
    register_hardware("mount", None)


def _args(mount=None, host=None, driver=None, tcp_port=9999, latitude=45.0, longitude=-10.0):
    return SimpleNamespace(mount=mount, mount_host=host, mount_tcp_port=tcp_port, mount_driver=driver,
                           latitude=latitude, longitude=longitude)


def test_no_mount_is_opened_without_the_option(monkeypatch):
    opened = []
    monkeypatch.setattr(sew, "connect_mount", lambda *args, **kwargs: opened.append(args))

    sew.open_mount(_args())

    assert opened == []
    assert "mount" not in HARDWARE


def test_the_simulator_is_opened_and_registered():
    sew.open_mount(_args(mount="auto", driver="simulator"))

    assert isinstance(HARDWARE["mount"], SimulatorMount)


def test_a_port_is_opened_with_the_onstepx_driver(monkeypatch):
    calls = []
    monkeypatch.setattr(sew, "connect_mount", lambda driver, **config: calls.append((driver, config))
                        or SimulatorMount())

    sew.open_mount(_args(mount="/dev/ttyUSB3"))

    assert calls == [("onstepx", {"port": "/dev/ttyUSB3"})]


def test_a_network_mount_is_opened_at_its_host(monkeypatch):
    calls = []
    monkeypatch.setattr(sew, "connect_mount", lambda driver, **config: calls.append((driver, config))
                        or SimulatorMount())

    sew.open_mount(_args(host="192.168.0.1", tcp_port=9998))

    assert calls == [("onstepx", {"host": "192.168.0.1", "tcp_port": 9998})]


def test_auto_asks_every_driver(monkeypatch):
    calls = []
    monkeypatch.setattr(sew, "connect_mount", lambda driver, **config: calls.append((driver, config))
                        or SimulatorMount())

    sew.open_mount(_args(mount="auto"))

    assert calls == [(None, {})]


def test_the_mount_gets_the_site_of_the_command_line(monkeypatch):
    told = []

    class SitedMount(SimulatorMount):
        capabilities = Capabilities(site_time=True)

        def set_datetime(self, when=None):
            told.append("time")

        def set_site(self, latitude_deg, longitude_deg, elevation_m=None):
            told.append((latitude_deg, longitude_deg))

    monkeypatch.setattr(sew, "connect_mount", lambda driver, **config: SitedMount())

    sew.open_mount(_args(mount="/dev/ttyUSB3", latitude=45.0, longitude=-10.0))

    assert told == ["time", (45.0, -10.0)]


def test_a_mount_that_cannot_be_opened_is_reported_not_raised(monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise MountError("nothing answered LX200 on /dev/ttyUSB9")

    monkeypatch.setattr(sew, "connect_mount", refuse)

    sew.open_mount(_args(mount="/dev/ttyUSB9"))

    assert "mount" not in HARDWARE
    assert "nothing answered LX200 on /dev/ttyUSB9" in capsys.readouterr().out
