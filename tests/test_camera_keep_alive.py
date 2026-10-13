import threading
import time
from unittest.mock import patch

import gphoto2 as gp
import pytest

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.camera import CameraKeepAliveThread, VirtualCamera, get_auto_power_off, \
    parse_power_off_delay


class _FakeCamera:
    """Camera-like object with the attributes the keep-alive thread relies on."""

    def __init__(self, name="Canon EOS R", vendor="Canon"):
        self.name = name
        self.vendor = vendor
        self._camera = object()
        self._usb_lock = threading.RLock()
        self.connected = True

    def is_connected(self):
        return self.connected


@pytest.fixture(autouse=True)
def _clear_problems():
    hardware_problems.clear()
    yield
    hardware_problems.clear()


@pytest.mark.parametrize("value, expected", [
    ("60", 60),
    (1800, 1800),
    ("0", None),
    (str(0xFFFFFFFF), None),
    ("Disable", None),
    ("No limit", None),
    ("4 seconds", 4),
    ("16s", 16),
    ("1 minute", 60),
    ("30 minutes", 1800),
    ("1m", 60),
    ("1.5 min", 90),
])
def test_parse_power_off_delay(value, expected):
    assert parse_power_off_delay(value) == expected


@pytest.mark.parametrize("value", ["", "soon", "5 fortnights"])
def test_parse_power_off_delay_rejects_unknown_values(value):
    with pytest.raises(ValueError):
        parse_power_off_delay(value)


def test_keep_alive_pings_idle_camera_only():
    idle = _FakeCamera("Idle")
    busy = _FakeCamera("Recently used")
    busy._last_usb_activity = time.monotonic()

    with patch("solareclipseworkbench.camera._keep_alive_request") as request:
        CameraKeepAliveThread(lambda: [idle, busy], interval_s=20).ping_all()

    request.assert_called_once_with(idle)
    assert idle._last_usb_activity > 0


def test_keep_alive_skips_aliases_virtual_and_disconnected_cameras():
    camera = _FakeCamera()
    disconnected = _FakeCamera("Unplugged")
    disconnected.connected = False

    with patch("solareclipseworkbench.camera._keep_alive_request") as request:
        CameraKeepAliveThread(lambda: [camera, camera, VirtualCamera(), disconnected, None]).ping_all()

    request.assert_called_once_with(camera)


def test_keep_alive_skips_ping_when_usb_lock_is_held():
    camera = _FakeCamera()
    holder_ready = threading.Event()
    release = threading.Event()

    def hold_lock():
        with camera._usb_lock:
            holder_ready.set()
            release.wait(1.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    holder_ready.wait(1.0)
    try:
        with patch("solareclipseworkbench.camera._keep_alive_request") as request:
            CameraKeepAliveThread(lambda: [camera], lock_timeout=0.01).ping_all()
        request.assert_not_called()
    finally:
        release.set()
        holder.join()


def test_keep_alive_reports_unresponsive_camera_once():
    camera = _FakeCamera()
    error = gp.GPhoto2Error(gp.GP_ERROR_IO)
    thread = CameraKeepAliveThread(lambda: [camera])

    with patch("solareclipseworkbench.camera._keep_alive_request", side_effect=error):
        thread.ping_all()
        thread.ping_all()

    problems = hardware_problems.peek()
    assert len(problems) == 1
    assert problems[0].source == camera.name
    assert problems[0].count == 1
    # The lock must be released even though the ping failed
    assert camera._usb_lock.acquire(timeout=0)
    camera._usb_lock.release()


def test_keep_alive_ignores_busy_camera():
    camera = _FakeCamera()
    with patch("solareclipseworkbench.camera._keep_alive_request",
               side_effect=gp.GPhoto2Error(gp.GP_ERROR_CAMERA_BUSY)):
        CameraKeepAliveThread(lambda: [camera]).ping_all()

    assert hardware_problems.count() == 0


def test_keep_alive_thread_honours_should_ping():
    camera = _FakeCamera()
    allowed = threading.Event()
    pinged = threading.Event()

    with patch("solareclipseworkbench.camera._keep_alive_request", side_effect=lambda cam: pinged.set()):
        thread = CameraKeepAliveThread(lambda: [camera], interval_s=0.01, should_ping=allowed.is_set)
        thread.start()
        try:
            assert not pinged.wait(0.1), "Pinged while suspended"
            allowed.set()
            assert pinged.wait(1.0), "Did not ping once allowed"
        finally:
            thread.stop()
            thread.join(timeout=1.0)


class _FakeWidget:
    def __init__(self, label, value):
        self._label = label
        self._value = value

    def get_label(self):
        return self._label

    def get_value(self):
        return self._value


def _single_config(widgets):
    def get_single_config(target, name, context):
        if name not in widgets:
            raise gp.GPhoto2Error(gp.GP_ERROR_BAD_PARAMETERS)
        return widgets[name]
    return get_single_config


def test_get_auto_power_off_canon():
    widgets = {"autopoweroff": _FakeWidget("Auto Power Off", "60")}
    with patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config", side_effect=_single_config(widgets)), \
         patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x):
        assert get_auto_power_off(_FakeCamera()) == ("Auto Power Off", "60", 60)


def test_get_auto_power_off_nikon_falls_back_to_standby_timer():
    widgets = {"meterofftime": _FakeWidget("Meter Off Time", "No limit")}
    with patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config", side_effect=_single_config(widgets)), \
         patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x):
        assert get_auto_power_off(_FakeCamera("Nikon Z 6", "Nikon")) == ("Meter Off Time", "No limit", None)


def test_get_auto_power_off_not_exposed():
    assert get_auto_power_off(_FakeCamera("Sony Alpha-A7 IV", "Sony")) is None
    assert get_auto_power_off(VirtualCamera()) is None
