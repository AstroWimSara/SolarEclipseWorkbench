"""LiveViewThread with a camera that gives its own live-view frames.

The camera is a fake with the three preview source methods, as a camera that a
vendor SDK drives has them.  No camera and no SDK are needed.
"""

import threading
import time

from solareclipseworkbench import camera as camera_mod
from solareclipseworkbench.camera import LiveViewThread, get_live_view_sizes, has_preview_source, \
    set_live_view_size

JPEG = b"\xff\xd8sdk-frame\xff\xd9"


class _FakeSdkCamera:
    """A camera with a preview source and a lock, and a record of the calls."""

    def __init__(self, frames=(JPEG,), fail_start=None, fail_read=None):
        self.name = "Fake SDK camera"
        self._usb_lock = threading.RLock()
        self._frames = list(frames)
        self._fail_start = fail_start
        self._fail_read = fail_read
        self.calls = []
        self.threads = set()
        self.started = threading.Event()
        self.stopped = threading.Event()

    def _note(self, name):
        self.calls.append(name)
        self.threads.add(threading.current_thread().name)

    def start_preview(self):
        self._note("start")
        if self._fail_start:
            raise self._fail_start
        self.started.set()

    def read_preview_frame(self):
        self._note("read")
        if self._fail_read:
            raise self._fail_read
        return self._frames[0] if self._frames else None

    def stop_preview(self):
        self._note("stop")
        self.stopped.set()


def _wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def _thread(camera, received):
    return LiveViewThread(camera=camera, frame_callback=received.append, interval_s=0.005,
                          lock_timeout=0.01)


# ---------------------------------------------------------------- detection


def test_a_camera_with_the_three_methods_is_a_preview_source():
    assert has_preview_source(_FakeSdkCamera())


def test_a_camera_without_them_is_not():
    class _Gphoto:
        _camera = object()

    assert not has_preview_source(_Gphoto())
    assert not has_preview_source(camera_mod.VirtualCamera())


def test_live_view_size_never_touches_a_preview_source():
    camera = _FakeSdkCamera()
    # A gphoto2 handle beside the preview source must still not be used
    camera._camera = object()

    assert get_live_view_sizes(camera) is None
    assert set_live_view_size(camera, "Large") is False
    assert camera.calls == []


# ---------------------------------------------------------------- the thread


def test_frames_come_from_the_preview_source_on_the_worker_thread():
    camera = _FakeSdkCamera()
    received = []
    thread = _thread(camera, received)
    thread.start()
    try:
        assert _wait_for(lambda: received), "no frame was delivered"
    finally:
        thread.stop()
        thread.join(timeout=1.0)

    assert received[0] == JPEG
    assert camera.calls[0] == "start"
    assert camera.calls[-1] == "stop"
    assert threading.current_thread().name not in camera.threads


def test_pause_stops_the_preview_source_and_resume_starts_it_again():
    camera = _FakeSdkCamera()
    received = []
    thread = _thread(camera, received)
    thread.start()
    try:
        assert camera.started.wait(1.0)
        thread.pause()
        assert camera.stopped.wait(1.0)
        reads = camera.calls.count("read")
        time.sleep(0.05)
        assert camera.calls.count("read") == reads, "frames were read while paused"

        camera.started.clear()
        thread.resume()
        assert camera.started.wait(1.0)
    finally:
        thread.stop()
        thread.join(timeout=1.0)
    assert camera.calls.count("start") == 2
    assert camera.calls.count("stop") == 2


def test_exit_live_view_makes_no_call_on_the_calling_thread():
    camera = _FakeSdkCamera()
    thread = _thread(camera, [])
    thread.start()
    try:
        assert camera.started.wait(1.0)
        thread.exit_live_view()
        assert camera.stopped.wait(1.0)
    finally:
        thread.stop()
        thread.join(timeout=1.0)
    assert threading.current_thread().name not in camera.threads


def test_no_frame_is_read_while_a_shot_holds_the_lock():
    camera = _FakeSdkCamera()
    thread = _thread(camera, [])
    thread.start()
    try:
        assert camera.started.wait(1.0)
        with camera._usb_lock:
            reads = camera.calls.count("read")
            time.sleep(0.1)
            assert camera.calls.count("read") == reads
    finally:
        thread.stop()
        thread.join(timeout=1.0)


def test_a_failed_start_pauses_the_thread_and_gives_the_reason():
    camera = _FakeSdkCamera(fail_start=RuntimeError("no PC priority"))
    thread = _thread(camera, [])
    thread.start()
    try:
        assert _wait_for(lambda: thread.is_paused)
        error = thread.take_error()
    finally:
        thread.stop()
        thread.join(timeout=1.0)

    assert "no PC priority" in error
    assert thread.take_error() is None
    assert camera.calls.count("start") == 1, "a failed start was tried again without a resume"
    assert "stop" not in camera.calls


def test_a_failed_read_stops_the_preview_source():
    camera = _FakeSdkCamera(fail_read=RuntimeError("the camera has left the bus"))
    thread = _thread(camera, [])
    thread.start()
    try:
        assert camera.stopped.wait(1.0)
        assert "left the bus" in thread.take_error()
    finally:
        thread.stop()
        thread.join(timeout=1.0)
    assert camera.calls.count("read") == 1
