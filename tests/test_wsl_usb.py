"""Tests for attaching shared USB devices to WSL with usbipd-win."""

import json
import subprocess

import pytest

from solareclipseworkbench import camera, hardware_problems, wsl_usb

# Shaped like the output of ``usbipd state`` (usbipd-win 4.x).
STATE = {
    "Devices": [
        {   # a camera, shared and plugged in, not attached yet
            "BusId": "1-4", "ClientIPAddress": None, "Description": "Canon EOS R",
            "InstanceId": "USB\\VID_04A9&PID_32F4\\1", "IsForced": False,
            "PersistedGuid": "1b9a7e2c-0000-0000-0000-000000000001", "StubInstanceId": None,
        },
        {   # a GPS receiver, shared and already attached
            "BusId": "1-5", "ClientIPAddress": "172.20.0.2", "Description": "u-blox 7 - GPS/GNSS Receiver",
            "InstanceId": "USB\\VID_1546&PID_01A7\\2", "IsForced": False,
            "PersistedGuid": "1b9a7e2c-0000-0000-0000-000000000002", "StubInstanceId": None,
        },
        {   # the keyboard: not shared
            "BusId": "1-1", "ClientIPAddress": None, "Description": "USB Input Device",
            "InstanceId": "USB\\VID_046D&PID_C31C\\3", "IsForced": False,
            "PersistedGuid": None, "StubInstanceId": None,
        },
        {   # shared once, but not plugged in now
            "BusId": None, "ClientIPAddress": None, "Description": "Sony ILCE-7RM2",
            "InstanceId": "USB\\VID_054C&PID_0A6B\\4", "IsForced": False,
            "PersistedGuid": "1b9a7e2c-0000-0000-0000-000000000004", "StubInstanceId": None,
        },
    ]
}


class FakeUsbipd:
    """Stands in for ``subprocess.run`` and records the usbipd commands."""

    def __init__(self, state=STATE, attach_returncode=0, attach_stderr=""):
        self.state = state
        self.attach_returncode = attach_returncode
        self.attach_stderr = attach_stderr
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args[1:])
        if args[1] == "state":
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.state), stderr="")
        if args[1] == "attach":
            return subprocess.CompletedProcess(args, self.attach_returncode, stdout="",
                                               stderr=self.attach_stderr)
        raise AssertionError(f"unexpected usbipd command {args}")

    @property
    def attached_busids(self):
        return [call[call.index("--busid") + 1] for call in self.calls if call[0] == "attach"]


@pytest.fixture
def on_wsl(monkeypatch):
    """Pretend to run in WSL with usbipd-win installed, without waiting for devices to settle."""
    monkeypatch.setattr(wsl_usb, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl_usb, "find_usbipd", lambda: "/mnt/c/Program Files/usbipd-win/usbipd.exe")
    monkeypatch.setattr(wsl_usb, "_SETTLE_TIME_S", 0)
    hardware_problems.clear()
    yield
    hardware_problems.clear()


def test_parse_state_reads_shared_and_attached_devices_that_are_plugged_in():
    devices = wsl_usb.parse_state(json.dumps(STATE))

    assert [(d.busid, d.shared, d.attached) for d in devices] == [
        ("1-4", True, False),
        ("1-5", True, True),
        ("1-1", False, False),
    ]
    assert devices[0].description == "Canon EOS R"


def test_only_shared_devices_that_are_not_attached_are_attached(on_wsl, monkeypatch):
    fake = FakeUsbipd()
    monkeypatch.setattr(subprocess, "run", fake)

    attached = wsl_usb.attach_shared_devices()

    assert [d.busid for d in attached] == ["1-4"]
    assert fake.attached_busids == ["1-4"]
    assert ["attach", "--wsl", "--busid", "1-4"] in fake.calls


def test_nothing_happens_outside_wsl(monkeypatch):
    monkeypatch.setattr(wsl_usb, "is_wsl", lambda: False)
    fake = FakeUsbipd()
    monkeypatch.setattr(subprocess, "run", fake)

    assert wsl_usb.attach_shared_devices() == []
    assert fake.calls == []


def test_nothing_happens_without_usbipd(on_wsl, monkeypatch):
    monkeypatch.setattr(wsl_usb, "find_usbipd", lambda: None)
    fake = FakeUsbipd()
    monkeypatch.setattr(subprocess, "run", fake)

    assert wsl_usb.attach_shared_devices() == []
    assert fake.calls == []


def test_a_failed_attach_is_reported_and_does_not_raise(on_wsl, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        FakeUsbipd(attach_returncode=1, attach_stderr="usbipd: error: Device busy"))

    assert wsl_usb.attach_shared_devices() == []

    problems = hardware_problems.peek()
    assert len(problems) == 1
    assert "Canon EOS R" in problems[0].message
    assert "Device busy" in problems[0].detail
    assert problems[0].severity == "warning"


def test_unreadable_usbipd_output_gives_no_devices(on_wsl, monkeypatch):
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="not json", stderr="")
    monkeypatch.setattr(subprocess, "run", run)

    assert wsl_usb.list_devices() == []
    assert wsl_usb.attach_shared_devices() == []


def test_a_hung_usbipd_gives_no_devices(on_wsl, monkeypatch):
    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
    monkeypatch.setattr(subprocess, "run", run)

    assert wsl_usb.list_devices() == []


def test_hint_when_no_device_is_shared(on_wsl, monkeypatch):
    unshared = {"Devices": [STATE["Devices"][2]]}
    monkeypatch.setattr(subprocess, "run", FakeUsbipd(state=unshared))

    assert "Share cameras" in wsl_usb.missing_device_hint()


def test_hint_when_usbipd_is_missing(on_wsl, monkeypatch):
    monkeypatch.setattr(wsl_usb, "find_usbipd", lambda: None)

    assert "usbipd-win" in wsl_usb.missing_device_hint()


def test_no_hint_when_a_device_is_shared_or_outside_wsl(on_wsl, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeUsbipd())
    assert wsl_usb.missing_device_hint() is None

    monkeypatch.setattr(wsl_usb, "is_wsl", lambda: False)
    assert wsl_usb.missing_device_hint() is None


def test_detect_cameras_attaches_before_looking(on_wsl, monkeypatch):
    order = []
    monkeypatch.setattr(wsl_usb, "attach_shared_devices", lambda: order.append("attach") or [])
    monkeypatch.setattr(camera, "get_cameras", lambda: order.append("detect") or [("Canon EOS R", "usb:001,004")])

    assert camera.detect_cameras() == [("Canon EOS R", "usb:001,004")]
    assert order == ["attach", "detect"]
    assert hardware_problems.peek() == []


def test_detect_cameras_reports_the_wsl_hint_when_nothing_is_found(on_wsl, monkeypatch):
    monkeypatch.setattr(wsl_usb, "attach_shared_devices", lambda: [])
    monkeypatch.setattr(wsl_usb, "missing_device_hint", lambda: "share it first")
    monkeypatch.setattr(camera, "get_cameras", lambda: [])

    assert camera.detect_cameras() == []
    problems = hardware_problems.peek()
    assert [(p.source, p.detail) for p in problems] == [("WSL USB", "share it first")]


def test_detect_cameras_survives_a_failing_attach(on_wsl, monkeypatch):
    def boom():
        raise RuntimeError("usbipd exploded")
    monkeypatch.setattr(wsl_usb, "attach_shared_devices", boom)
    monkeypatch.setattr(camera, "get_cameras", lambda: [("Canon EOS R", "usb:001,004")])

    assert camera.detect_cameras() == [("Canon EOS R", "usb:001,004")]
