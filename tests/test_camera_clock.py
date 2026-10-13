"""Tests for setting the camera clock without ever leaving it at a wrong date."""

import threading
import time

import gphoto2
import gphoto2 as gp
import pytest

from solareclipseworkbench import camera as camera_module
from solareclipseworkbench import hardware_problems
from solareclipseworkbench.camera import read_camera_clock, set_time

THREE_DAYS = 3 * 24 * 3600
PTP_FORMAT = "%Y%m%dT%H%M%S"


class FakeWidget:
    def __init__(self, name, widget_type, value):
        self.name, self.widget_type, self.value = name, widget_type, value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value

    def get_type(self):
        return self.widget_type


class FakeConfig:
    def __init__(self, widgets):
        self.widgets = {w.name: w for w in widgets}

    def get_child_by_name(self, name):
        if name not in self.widgets:
            raise gphoto2.GPhoto2Error(-2)
        return self.widgets[name]


class FakeCamera:
    """A camera whose clock is stored as one widget value.

    accepts(value) decides whether a written value is understood; a value that
    is not understood resets the clock to `fallback`, like old bodies that end
    up in 1980 or in the year the model came out.
    """

    def __init__(self, widget, widget_type, value, accepts=lambda v: True, fallback=None, sync_toggle=None):
        self.name = "Canon EOS 400D"
        self._usb_lock = threading.RLock()
        self.widget, self.widget_type, self.value = widget, widget_type, value
        self.accepts, self.fallback, self.sync_toggle = accepts, fallback, sync_toggle
        self.writes = 0

    def get_config(self):
        widgets = [FakeWidget(self.widget, self.widget_type, self.value)]
        if self.sync_toggle:
            widgets.append(FakeWidget(self.sync_toggle, gp.GP_WIDGET_TOGGLE, 0))
        return FakeConfig(widgets)

    def set_config(self, config):
        if self.sync_toggle and config.get_child_by_name(self.sync_toggle).value == 1:
            self.writes += 1
            self.value = int(time.time()) if self.widget_type == gp.GP_WIDGET_DATE else time.strftime(PTP_FORMAT)
            return
        new = config.get_child_by_name(self.widget).value
        if new != self.value:
            self.writes += 1
            self.value = new if self.accepts(new) else self.fallback


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    # UTC, so a test offset can never be mistaken for a time-zone difference.
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    monkeypatch.setattr(camera_module.time, "sleep", lambda s: None)
    camera_module._clock_sync_disabled.clear()
    hardware_problems.clear()
    yield
    camera_module._clock_sync_disabled.clear()
    hardware_problems.clear()
    monkeypatch.undo()
    time.tzset()


def _is_ptp(value):
    try:
        time.strptime(str(value)[:15], PTP_FORMAT)
        return len(str(value)) >= 15
    except ValueError:
        return False


def test_date_widget_is_set_and_verified():
    cam = FakeCamera("datetime", gp.GP_WIDGET_DATE, int(time.time()) - THREE_DAYS)
    assert set_time(cam) is True
    assert abs(cam.value - time.time()) < 2
    assert hardware_problems.count() == 0


def test_ptp_text_clock_is_written_in_ptp_format():
    """The plain PTP DateTime property only understands YYYYMMDDThhmmss.

    The previous code wrote "YYYY-MM-DD hh:mm:ss" here, which such a camera
    cannot parse.
    """
    old = time.strftime(PTP_FORMAT, time.localtime(time.time() - THREE_DAYS))
    cam = FakeCamera("d034", gp.GP_WIDGET_TEXT, old, accepts=_is_ptp, fallback="19800101T000000")
    assert set_time(cam) is True
    assert _is_ptp(cam.value) and cam.value != "19800101T000000"
    reading = read_camera_clock(cam)
    assert abs(reading.error_s) < 2


def test_camera_that_resets_its_clock_gets_the_old_time_back_and_is_left_alone():
    old = int(time.time()) - THREE_DAYS
    year_2008 = 1199145600  # 2008-01-01
    cam = FakeCamera("datetime", gp.GP_WIDGET_DATE, old,
                     accepts=lambda v: v == old, fallback=year_2008)

    assert set_time(cam) is False
    assert cam.value == old                       # previous time restored
    problems = hardware_problems.peek()
    assert len(problems) == 1 and "2008-01-01" in problems[0].message

    writes = cam.writes
    assert set_time(cam) is False                 # e.g. a sync_cameras command later on
    assert cam.writes == writes                   # clock not touched again


def test_unreadable_clock_is_not_written():
    cam = FakeCamera("d034", gp.GP_WIDGET_TEXT, "garbage")
    assert set_time(cam) is False
    assert cam.writes == 0
    assert hardware_problems.count() == 1


def test_libgphoto2_sync_toggle_is_preferred():
    cam = FakeCamera("datetime", gp.GP_WIDGET_DATE, int(time.time()) - THREE_DAYS,
                     accepts=lambda v: False, fallback=0, sync_toggle="syncdatetime")
    assert set_time(cam) is True                  # direct writes would have been rejected
    assert abs(cam.value - time.time()) < 2


def test_clock_in_sync_is_not_rewritten():
    cam = FakeCamera("datetime", gp.GP_WIDGET_DATE, int(time.time()))
    assert set_time(cam) is True
    assert cam.writes == 0


def test_busy_camera_is_not_blocked_on(monkeypatch):
    """A clock sync must not wait long for a camera that is taking a picture."""
    monkeypatch.setattr(camera_module, "_CLOCK_LOCK_WAIT_S", 0.05)
    cam = FakeCamera("datetime", gp.GP_WIDGET_DATE, int(time.time()) - THREE_DAYS)
    locked, done = threading.Event(), threading.Event()

    def take_picture():
        with cam._usb_lock:
            locked.set()
            done.wait(5)

    holder = threading.Thread(target=take_picture)
    holder.start()
    locked.wait(5)
    try:
        assert set_time(cam) is False
        assert cam.writes == 0
    finally:
        done.set()
        holder.join()
