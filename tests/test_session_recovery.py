"""A session that died with live view running must not block the next one.

An X-T4 can refuse SetPriorityMode in both directions while it answers every
read normally.  The body is not broken and needs no power cycle: it is still in
live view from a process that crashed.  One StopLiveView frees it.
"""

import ctypes
import gc
import inspect
import logging
import threading

import pytest

import fujixsdk.camera as sdk_camera_module
from fujixsdk import _constants as C
from fujixsdk import recovery
from fujixsdk._errors import CommunicationError, XSDKError
from fujixsdk.camera import Camera
from fujixsdk.eclipse import LiveViewStream

from solareclipseworkbench.camera import BaseCamera
from solareclipseworkbench.fuji_camera import FujiCamera


class _FakeBody:
    """A body that reports what blocks it and is freed by the right remedy.

    Stands in for the SDK's C entry points, which take the handle first and
    write their answers through pointers.
    """

    def __init__(self, blockers=0, freed_by=None, err=0x1006):
        self.calls = []
        self.blockers = blockers
        self.freed_by = freed_by          # the one call that clears it
        self.err = err
        self._lib_inst = self
        self._handle = ctypes.c_void_p()

    # --- the SDK entry points recovery.unblock calls -------------------------
    def XSDK_GetErrorDetails(self, handle, out):
        out._obj.value = self.blockers
        return C.COMPLETE

    def XSDK_GetErrorNumber(self, handle, api, err):
        api._obj.value = 0x1033
        err._obj.value = self.err
        return C.COMPLETE

    def XSDK_SetPriorityMode(self, handle, mode):
        self.calls.append("set_priority")
        return 0x1006 if self.blockers else C.COMPLETE

    def XSDK_Release(self, handle, mode, shot_opt, af_status):
        # The wrapper passes ctypes values, not ints.
        name = {C.RELEASE_CANCEL: "release_cancel",
                C.RELEASE_S1ON: "FLUSH SHOT"}.get(mode.value, "release")
        self.calls.append(name)
        self._clear_if(name)
        return C.COMPLETE

    def XSDK_SetForceMode(self, handle, mode):
        self.calls.append("force_standby")
        self._clear_if("force_standby")
        return C.COMPLETE

    # --- the wrapper methods it calls ----------------------------------------
    def stop_live_view(self):
        self.calls.append("stop_live_view")
        self._clear_if("stop_live_view")

    def drain_buffer(self):
        self.calls.append("drain")
        self._clear_if("drain")
        return 0

    def _clear_if(self, call):
        if self.freed_by == call:
            self.blockers = 0


def test_live_view_is_stopped_first():
    body = _FakeBody(blockers=recovery.BLOCKER_LIVEVIEW,
                     freed_by="stop_live_view")

    assert recovery.unblock(body, C.PRIORITY_CAMERA) is True

    remedies = [c for c in body.calls if c != "set_priority"]
    assert remedies[0] == "stop_live_view"


def test_no_shutter_is_fired_when_stopping_live_view_is_enough():
    # The flush shot cannot clear a live view and costs an actuation to find
    # out.  During totality that actuation is also a lost frame.
    body = _FakeBody(blockers=recovery.BLOCKER_LIVEVIEW,
                     freed_by="stop_live_view")

    recovery.unblock(body, C.PRIORITY_CAMERA)

    assert "FLUSH SHOT" not in body.calls


def test_a_ready_body_costs_one_call():
    # This runs on every recovery path, so the healthy case must stay cheap.
    body = _FakeBody(blockers=0)

    assert recovery.unblock(body, C.PRIORITY_CAMERA) is True
    assert body.calls == ["set_priority"]


def test_a_remedy_is_skipped_when_its_cause_is_not_reported():
    body = _FakeBody(blockers=recovery.BLOCKER_UNTRANSFERRED, freed_by="drain")

    recovery.unblock(body, C.PRIORITY_CAMERA)

    assert "stop_live_view" not in body.calls, "stopped a stream that was not running"
    assert "drain" in body.calls


def test_the_shutter_can_be_forbidden():
    # What an eclipse run passes: better to fail than to fire a frame nobody
    # asked for, at the one moment it cannot be retaken.
    body = _FakeBody(blockers=recovery.BLOCKER_SHOOTING, freed_by=None)

    assert recovery.unblock(body, C.PRIORITY_CAMERA, allow_shot=False) is False
    assert "FLUSH SHOT" not in body.calls


def test_the_flush_shot_remains_available_as_a_last_resort():
    body = _FakeBody(blockers=recovery.BLOCKER_SHOOTING, freed_by="FLUSH SHOT")

    assert recovery.unblock(body, C.PRIORITY_CAMERA, allow_shot=True) is True
    assert "FLUSH SHOT" in body.calls


def test_an_unreadable_mask_tries_every_remedy():
    # Silence must not read as "nothing is wrong", or every remedy is skipped
    # and the body stays stuck with nothing in the log to say why.
    body = _FakeBody(blockers=recovery.BLOCKER_LIVEVIEW,
                     freed_by="stop_live_view")
    body.XSDK_GetErrorDetails = lambda handle, out: -1

    assert recovery.unblock(body, C.PRIORITY_CAMERA) is True
    assert "stop_live_view" in body.calls


def test_why_it_was_busy_and_the_exact_error_reach_the_log(caplog):
    body = _FakeBody(blockers=recovery.BLOCKER_LIVEVIEW,
                     freed_by="stop_live_view")

    with caplog.at_level(logging.INFO):
        recovery.unblock(body, C.PRIORITY_CAMERA, why="session open")

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "live view is running" in logged, "did not say why it was busy"
    assert "0x1006" in logged, "did not log the exact error for later"


def test_session_open_uses_the_shared_recovery(monkeypatch):
    # Session open, live view and the busy retry go through one place.
    seen = {}

    def _fake_unblock(camera, priority=C.PRIORITY_CAMERA, allow_shot=True, why=""):
        seen.update(priority=priority, why=why)
        return True

    monkeypatch.setattr(recovery, "unblock", _fake_unblock)
    cam = object.__new__(Camera)

    cam._cleanup_stale_state()

    assert seen["priority"] == C.PRIORITY_CAMERA
    assert seen["why"] == "session open"


def test_the_camera_and_live_view_share_one_lock():
    """BaseCamera makes _usb_lock, and FujiCamera must use that same lock.

    With a second lock, a thread holding one could be inside the SDK while a
    thread holding the other is too, and the SDK is not thread-safe.  Two
    calls at the same time end the USB session with 0x2001.
    """

    camera = object.__new__(FujiCamera)
    BaseCamera.__init__(camera, name="X-T4")
    camera._lock = camera._usb_lock          # what __init__ does

    assert camera._lock is camera._usb_lock, \
        "two names for two locks lets two threads into the SDK"
    # Reentrant, because a public method may call another that also locks.
    assert camera._lock.acquire(blocking=False)
    assert camera._lock.acquire(blocking=False)
    camera._lock.release()
    camera._lock.release()


def test_the_adapter_does_not_make_a_lock_of_its_own():
    # A second lock would be one line: self._lock = threading.RLock().

    source = inspect.getsource(FujiCamera.__init__)
    assert "self._lock = self._usb_lock" in source
    assert "self._lock = threading.RLock()" not in source, \
        "a second lock is a second door into the SDK"


def test_a_failed_open_does_not_tear_down_a_session_that_never_opened():
    """A failed open must not close a handle the SDK never gave out.

    When XSDK_OpenEx fails, check_result raises and the half-built object is
    collected, so __del__ calls close().  A full teardown (Release, drain,
    SetPriorityMode, Close) on that handle corrupts the heap:

        malloc: Incorrect checksum for freed object ...
                probably modified after being freed

    and the process aborts, past the reach of any handler.
    """

    class _FailingLib:
        def __init__(self):
            self.teardown = []

        def XSDK_Detect(self, *a):
            return C.COMPLETE

        def XSDK_OpenEx(self, *a):
            return -1

        def XSDK_Release(self, *a):
            self.teardown.append("Release")
            return C.COMPLETE

        def XSDK_Close(self, *a):
            self.teardown.append("Close")
            return C.COMPLETE

        def XSDK_SetPriorityMode(self, *a):
            self.teardown.append("SetPriorityMode")
            return C.COMPLETE

        def XSDK_GetBufferCapacity(self, *a):
            return C.COMPLETE

    lib = _FailingLib()
    original = Camera._ensure_lib
    Camera._ensure_lib = classmethod(lambda cls, path: lib)
    try:
        try:
            Camera("/nowhere", "ENUM:0")
        except XSDKError:
            pass
        gc.collect()
    finally:
        Camera._ensure_lib = original

    assert lib.teardown == [], \
        "closed a session that was never opened: %s" % lib.teardown


def test_a_vanished_body_is_abandoned_not_closed():
    """A body that left the bus is not closed: its handle is abandoned.

    The SDK's device-removal path corrupts the heap when the teardown calls
    (Release, drain, SetPriorityMode, Close) are made into a handle whose
    device has left the bus, and the process crashes with no Python frame on
    the stack.  A leaked handle costs nothing next to that.
    """

    class _RecordingLib:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            if name.startswith("XSDK_"):
                def _record(*a):
                    self.calls.append(name)
                    return C.COMPLETE
                return _record
            raise AttributeError(name)

    lib = _RecordingLib()
    cam = object.__new__(Camera)
    cam._lib_inst = lib
    cam._handle = ctypes.c_void_p()
    cam._closed = False
    cam.vanished = True
    cam._release_lib = lambda: None

    cam.close()

    assert lib.calls == [], "dialed a body that left the bus: %s" % lib.calls
    assert cam._closed, "the session must still count as closed"


def test_the_stream_stops_polling_a_body_that_left_the_bus():
    # Each poll of a body that left the bus goes through the SDK's removal
    # path, which corrupts the heap.  The stream stops at the first one.

    class _GoneBody:
        vanished = False

        def read_image_info(self):
            raise CommunicationError(0x2001, "Communication error")

        def stop_live_view(self):
            raise AssertionError("said goodbye to a body that is off the bus")

    stream = LiveViewStream.__new__(LiveViewStream)
    stream.camera = _GoneBody()
    stream._running = True

    with pytest.raises(RuntimeError):
        stream.read_frame()
    assert stream.camera.vanished, "the departure was not recorded"

    stream.stop()                      # must not raise, must not dial out
    assert stream.read_frame() is None, "kept polling after the departure"


def test_closing_the_last_camera_does_not_exit_the_sdk():
    """This SDK does not survive Exit followed by Init in one process.

    Measured: a reopen after a close that called Exit answered a bare -1 every
    time.  Without the Exit, the reopen worked every time.
    """

    source = inspect.getsource(Camera._release_lib)
    # The docstring names XSDK_Exit while explaining why it must not be
    # called; the assertion is about the call.
    assert ".XSDK_Exit()" not in source, \
        "Exit on last close breaks every later open in the process"

    assert hasattr(sdk_camera_module, "_exit_sdk_at_process_end"), \
        "nothing exits the SDK at process end"
