"""The Sony background downloader must never cost a scheduled shot.

It yields the USB lock to waiting shots, releases it between files, and its camera
calls are cancelled when a shot starts waiting or a call runs too long.
"""
import threading
import time
from unittest import mock

import gphoto2 as gp
import pytest

from solareclipseworkbench import camera as cam_mod


class _FakeContext:
    def __init__(self):
        self.cancel_func = None

    def set_cancel_func(self, func, data):
        self.cancel_func = func
        return object()


class _FakeSony:
    def __init__(self):
        self.name = 'ILCE-7M4'
        self._usb_lock = threading.RLock()
        self._camera_claims = 0
        self._camera = object()
        self._bg_downloader = None


@pytest.fixture
def downloader(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    adapter = _FakeSony()
    ctx = _FakeContext()
    dl = cam_mod._SonyBackgroundDownloader(adapter, ctx)
    adapter._bg_downloader = dl
    yield dl
    dl.stop()
    if dl.is_alive():
        dl.join(timeout=2.0)


def _no_events(target, timeout, ctx):
    return [gp.GP_OK, gp.GP_EVENT_TIMEOUT, None]


def test_cancel_callback_is_installed(downloader):
    assert downloader.context.cancel_func == downloader._cancel_requested


def test_cancel_only_while_a_call_runs_and_a_shot_waits(downloader):
    ok, cancel = gp.GP_CONTEXT_FEEDBACK_OK, gp.GP_CONTEXT_FEEDBACK_CANCEL
    adapter = downloader.adapter
    # No call in progress: nothing to cancel.
    with cam_mod._claiming_camera(adapter):
        assert downloader._cancel_requested(None, None) == ok

    seen = []
    def call():
        seen.append(downloader._cancel_requested(None, None))
        with cam_mod._claiming_camera(adapter):
            seen.append(downloader._cancel_requested(None, None))
        seen.append(downloader._cancel_requested(None, None))
    downloader._camera_call(call)
    assert seen == [ok, cancel, ok]
    assert downloader.busy_for() == 0.0


def test_call_is_cancelled_after_timeout(downloader, monkeypatch):
    monkeypatch.setattr(cam_mod, '_DOWNLOADER_CALL_TIMEOUT_S', 0.01)
    seen = []
    def call():
        time.sleep(0.03)
        seen.append(downloader._cancel_requested(None, None))
    downloader._camera_call(call)
    assert seen == [gp.GP_CONTEXT_FEEDBACK_CANCEL]


def test_no_camera_calls_while_a_shot_waits(downloader, monkeypatch):
    calls = []
    monkeypatch.setattr(cam_mod.gp, 'gp_camera_wait_for_event',
                        lambda *a: calls.append('event') or _no_events(*a))
    with cam_mod._claiming_camera(downloader.adapter):
        downloader.start()
        time.sleep(0.3)
        assert calls == []
    deadline = time.monotonic() + 2.0
    while not calls and time.monotonic() < deadline:
        time.sleep(0.02)
    assert calls, 'downloader should resume once the shot has the camera'


def test_shot_gets_camera_during_long_download(downloader, monkeypatch):
    """A download that would take far longer than the lock wait is cancelled for the shot."""
    download_started = threading.Event()
    downloads = []

    def slow_file_get(target, folder, name, kind, cam_file, ctx):
        # Mimics libgphoto2 polling the context's cancel callback during a transfer.
        downloads.append(name)
        download_started.set()
        end = time.monotonic() + 30.0
        while time.monotonic() < end:
            if downloader.context.cancel_func(ctx, None) == gp.GP_CONTEXT_FEEDBACK_CANCEL:
                return gp.GP_ERROR_CANCEL
            time.sleep(0.01)
        return gp.GP_OK

    monkeypatch.setattr(cam_mod.gp, 'gp_camera_wait_for_event', _no_events)
    monkeypatch.setattr(cam_mod.gp, 'gp_camera_folder_list_files',
                        lambda *a: [gp.GP_OK, mock.Mock(count=lambda: 0)])
    monkeypatch.setattr(cam_mod.gp, 'gp_camera_file_get', slow_file_get)
    monkeypatch.setattr(cam_mod.gp, 'CameraFile', mock.Mock)
    downloader._queue_path('/', 'DSC00001.ARW', time.monotonic())
    downloader.start()
    assert download_started.wait(2.0)

    shot = cam_mod._serialised_on_camera(lambda camera: 'shot taken')
    started = time.monotonic()
    assert shot(downloader.adapter) == 'shot taken'
    assert time.monotonic() - started < cam_mod._MAX_LOCK_WAIT_S
    # The cancelled file stays queued for a later attempt.
    assert ('/', 'DSC00001.ARW') in downloader._pending


def test_lock_released_between_files(downloader, monkeypatch):
    """With several files queued, each download is a separate lock hold."""
    holds = []

    def file_get(target, folder, name, kind, cam_file, ctx):
        holds.append(downloader.adapter._usb_lock._is_owned())
        return gp.GP_OK

    real_acquire_count = {'n': 0}
    real_lock = downloader.adapter._usb_lock

    class CountingLock:
        def acquire(self, timeout=-1):
            ok = real_lock.acquire(timeout=timeout)
            if ok:
                real_acquire_count['n'] += 1
            return ok

        def release(self):
            real_lock.release()

        def _is_owned(self):
            return real_lock._is_owned()

    downloader.adapter._usb_lock = CountingLock()
    monkeypatch.setattr(cam_mod.gp, 'gp_camera_wait_for_event', _no_events)
    monkeypatch.setattr(cam_mod.gp, 'gp_camera_folder_list_files',
                        lambda *a: [gp.GP_OK, mock.Mock(count=lambda: 0)])
    monkeypatch.setattr(cam_mod.gp, 'gp_camera_file_get', file_get)
    monkeypatch.setattr(cam_mod.gp, 'CameraFile', mock.Mock)
    monkeypatch.setattr(cam_mod.gp, 'gp_file_save', lambda cam_file, path: open(path, 'wb').close() or gp.GP_OK)
    now = time.monotonic()
    for i in range(3):
        downloader._queue_path('/', f'DSC0000{i}.ARW', now)
    downloader.start()
    deadline = time.monotonic() + 3.0
    while downloader._pending and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not downloader._pending
    assert len(holds) == 3
    assert real_acquire_count['n'] >= 3


def test_dropped_shot_reports_stuck_downloader(downloader, monkeypatch):
    reports = []
    monkeypatch.setattr(cam_mod.hardware_problems, 'report', lambda *a, **k: reports.append(a))
    monkeypatch.setattr(downloader, 'busy_for', lambda: cam_mod._DOWNLOADER_STUCK_S + 1)
    cam_mod._report_stuck_downloader(downloader.adapter)
    assert len(reports) == 1

    monkeypatch.setattr(downloader, 'busy_for', lambda: 1.0)
    cam_mod._report_stuck_downloader(downloader.adapter)
    assert len(reports) == 1


def test_claims_are_released_after_shot(downloader):
    shot = cam_mod._serialised_on_camera(lambda camera: None)
    shot(downloader.adapter)
    assert not cam_mod._camera_claimed(downloader.adapter)
