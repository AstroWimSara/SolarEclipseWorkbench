"""How long Fuji detection waits, with and without a Fujifilm device on the USB bus.

The SDK, the USB scan and the clock are fakes, so the file runs without a body
and without the SDK libraries.
"""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from solareclipseworkbench import fuji_camera

FUJI = fuji_camera.FUJIFILM_USB_VENDOR_ID
ROOT_HUB = 0x1D6B


class _Clock:
    """A clock that moves only when the code under test sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(fuji_camera, "time", SimpleNamespace(monotonic=fake.monotonic, sleep=fake.sleep))
    return fake


@pytest.fixture
def sdk(monkeypatch):
    """The SDK camera class.  Its detect finds no camera unless a test says so."""
    fake = MagicMock()
    fake.detect.return_value = []
    fake.return_value.device_info.product = "X-T4"
    monkeypatch.setattr(fuji_camera, "SDKCamera", fake)
    monkeypatch.setattr(fuji_camera, "FUJIXSDK_AVAILABLE", True)
    monkeypatch.setattr(fuji_camera, "_report_validation_issues", lambda camera: None)
    return fake


@pytest.fixture
def resets(monkeypatch):
    calls = []
    monkeypatch.setattr(fuji_camera, "_reset_mac_camera_stack", lambda: calls.append(True))
    return calls


def _bus(monkeypatch, *scans):
    """Each call of the USB scan gives the next of scans, and then the last one again."""
    queue = list(scans)

    def scan():
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(fuji_camera, "_usb_vendor_ids", scan)


def test_without_a_fujifilm_device_the_sdk_looks_once(monkeypatch, clock, sdk, resets):
    _bus(monkeypatch, {ROOT_HUB})

    detection = fuji_camera.detect_fuji("/sdk")

    assert detection == fuji_camera.FujiDetection({}, 0)
    assert sdk.detect.call_count == 1
    assert resets == []
    assert sum(clock.sleeps) <= 2.0


def test_a_body_that_appears_on_the_bus_during_the_wait_gets_the_retries(monkeypatch, clock, sdk, resets):
    _bus(monkeypatch, {ROOT_HUB}, {ROOT_HUB}, {ROOT_HUB, FUJI})

    fuji_camera.detect_fuji("/sdk")

    assert sdk.detect.call_count == 3


def test_a_fujifilm_device_the_sdk_does_not_see_gets_every_retry(monkeypatch, clock, sdk, resets):
    _bus(monkeypatch, {ROOT_HUB, FUJI})

    detection = fuji_camera.detect_fuji("/sdk")

    assert detection.bodies_seen == 0
    assert sdk.detect.call_count == 3
    assert resets == [True]
    # 6 s before the second try, 5 s before the third, and no wait after it.
    assert sum(clock.sleeps) == pytest.approx(11.0)


def test_a_body_the_sdk_sees_late_is_still_opened(monkeypatch, clock, sdk, resets):
    _bus(monkeypatch, {ROOT_HUB, FUJI})
    sdk.detect.side_effect = [[], [SimpleNamespace(device_name="ENUM:0")]]

    detection = fuji_camera.detect_fuji("/sdk")

    assert list(detection.cameras) == ["Fuji Fujifilm X-T4"]
    assert detection.bodies_seen == 1
    assert sdk.detect.call_count == 2
    assert resets == []


def test_when_the_bus_cannot_be_read_every_retry_runs(monkeypatch, clock, sdk, resets):
    _bus(monkeypatch, None)

    fuji_camera.detect_fuji("/sdk")

    assert sdk.detect.call_count == 3


# ------------------------------------------------------------------ USB scan


def test_linux_reads_the_vendor_ids_from_sysfs(tmp_path, monkeypatch):
    for device, vendor in (("usb1", "1d6b"), ("1-2", "04cb")):
        (tmp_path / device).mkdir()
        (tmp_path / device / "idVendor").write_text(vendor + "\n")
    # An interface entry has no idVendor file.
    (tmp_path / "1-2:1.0").mkdir()
    monkeypatch.setattr(fuji_camera, "SYSFS_USB_DEVICES", tmp_path)

    with patch.object(fuji_camera.platform, "system", return_value="Linux"):
        assert fuji_camera._usb_vendor_ids() == {ROOT_HUB, FUJI}


def test_linux_without_readable_sysfs_does_not_know(tmp_path, monkeypatch):
    monkeypatch.setattr(fuji_camera, "SYSFS_USB_DEVICES", tmp_path / "missing")

    with patch.object(fuji_camera.platform, "system", return_value="Linux"):
        assert fuji_camera._usb_vendor_ids() is None


def test_macos_reads_the_vendor_ids_from_ioreg():
    output = ('+-o X-T4@01100000  <class IOUSBHostDevice>\n'
              '    "idProduct" = 742\n'
              '    "idVendor" = 1227\n'
              '+-o USB3.0 Hub@02100000  <class IOUSBHostDevice>\n'
              '    "idVendor" = 0x05e3\n')
    done = subprocess.CompletedProcess([], 0, stdout=output, stderr="")

    with patch.object(fuji_camera.platform, "system", return_value="Darwin"), \
            patch.object(fuji_camera.subprocess, "run", return_value=done):
        assert fuji_camera._usb_vendor_ids() == {FUJI, 0x05E3}


def test_macos_without_ioreg_does_not_know():
    with patch.object(fuji_camera.platform, "system", return_value="Darwin"), \
            patch.object(fuji_camera.subprocess, "run", side_effect=FileNotFoundError("ioreg")):
        assert fuji_camera._usb_vendor_ids() is None


def test_macos_output_without_vendor_ids_does_not_know():
    done = subprocess.CompletedProcess([], 0, stdout="+-o Root  <class IORegistryEntry>\n", stderr="")

    with patch.object(fuji_camera.platform, "system", return_value="Darwin"), \
            patch.object(fuji_camera.subprocess, "run", return_value=done):
        assert fuji_camera._usb_vendor_ids() is None


def test_windows_does_not_know():
    with patch.object(fuji_camera.platform, "system", return_value="Windows"):
        assert fuji_camera._usb_vendor_ids() is None
