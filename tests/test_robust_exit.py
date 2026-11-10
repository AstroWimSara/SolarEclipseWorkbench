"""The application survives an error in the interface, and Ctrl-C, STOP and a native crash end cleanly."""

import logging
import os
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from solareclipseworkbench import gui


@pytest.fixture
def restore_excepthook():
    original = sys.excepthook
    yield
    sys.excepthook = original


def _run_python(code: str, *args, timeout: float = 60) -> subprocess.CompletedProcess:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code), *args], env=env,
                          capture_output=True, text=True, timeout=timeout)


def test_hook_logs_an_error_and_returns(restore_excepthook, caplog):
    gui._keep_running_on_unhandled_errors()
    try:
        raise ValueError("a bug in a button")
    except ValueError:
        kind, value, traceback_object = sys.exc_info()

    with mock.patch.object(gui.os, "_exit") as exit_now, caplog.at_level(logging.ERROR):
        sys.excepthook(kind, value, traceback_object)

    exit_now.assert_not_called()
    record = next(r for r in caplog.records if "ValueError" in r.getMessage())
    assert record.exc_info[1] is value


def test_hook_stops_the_scheduler_and_opens_the_contacts_on_ctrl_c(restore_excepthook):
    scheduler = mock.Mock()
    controller = SimpleNamespace(scheduler=scheduler)
    gui._keep_running_on_unhandled_errors(controller)

    with mock.patch.object(gui, "_release_all_contacts") as release, \
            mock.patch.object(gui.logging, "shutdown"), \
            mock.patch.object(gui.os, "_exit") as exit_now:
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    scheduler.shutdown.assert_called_once_with(wait=False)
    release.assert_called_once_with()
    exit_now.assert_called_once_with(130)


def test_an_error_in_a_slot_does_not_abort_the_process():
    result = _run_python("""
        import sys
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from solareclipseworkbench import gui

        app = QApplication([])
        gui._keep_running_on_unhandled_errors()

        def broken_slot():
            raise ValueError("a bug in a button")

        QTimer.singleShot(0, broken_slot)
        QTimer.singleShot(200, app.quit)
        sys.exit(app.exec())
    """)

    assert result.returncode == 0, result.stderr
    assert "Unhandled ValueError" in result.stderr


def test_stop_does_not_wait_for_the_job_in_flight():
    started = threading.Event()
    release_job = threading.Event()

    def long_job():
        started.set()
        release_job.wait(5)

    scheduler = BackgroundScheduler()
    scheduler.start()
    scheduler.add_job(long_job)
    assert started.wait(10)

    controller = SimpleNamespace(scheduler=scheduler, jobs_model=mock.Mock(),
                                 view=mock.Mock(), model=mock.Mock(),
                                 _set_limb_correction_locked=mock.Mock())
    try:
        begin = time.monotonic()
        gui.SolarEclipseController._shutdown_scheduler(controller)
        elapsed = time.monotonic() - begin
    finally:
        release_job.set()

    assert elapsed < 0.5
    assert not scheduler.running


def test_a_native_crash_writes_the_stack_of_the_thread(tmp_path):
    crash_log = tmp_path / "logs" / "crash.log"
    result = _run_python("""
        import faulthandler
        import sys
        import threading
        from pathlib import Path
        from solareclipseworkbench import gui

        gui.CRASH_LOG = Path(sys.argv[1])
        gui._catch_native_crashes()

        def camera_worker():
            faulthandler._sigsegv()

        worker = threading.Thread(target=camera_worker, name="camera-worker")
        worker.start()
        worker.join()
    """, str(crash_log))

    assert result.returncode != 0
    text = crash_log.read_text()
    assert "Segmentation fault" in text
    assert "in camera_worker" in text


def test_one_ctrl_c_ends_the_process_behind_a_dialog_with_a_job_in_flight():
    result = _run_python("""
        import os
        import signal
        import threading
        from types import SimpleNamespace
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from apscheduler.schedulers.background import BackgroundScheduler
        from solareclipseworkbench import gui

        app = QApplication([])
        scheduler = BackgroundScheduler()
        scheduler.start()
        scheduler.add_job(threading.Event().wait)
        gui._keep_running_on_unhandled_errors(SimpleNamespace(scheduler=scheduler))

        # Python code must run now and then for the interrupt to be noticed, as the clock does in the window.
        tick = QTimer()
        tick.timeout.connect(lambda: None)
        tick.start(50)
        QTimer.singleShot(0, lambda: QMessageBox.question(None, "Dialog", "A modal dialog"))
        QTimer.singleShot(500, lambda: os.kill(os.getpid(), signal.SIGINT))
        app.exec()
        os._exit(1)
    """, timeout=30)

    assert result.returncode == 130, result.stderr


@pytest.mark.parametrize("value, code", [(SystemExit(), 0), (SystemExit(1), 1), (SystemExit("message"), 1)])
def test_system_exit_in_a_slot_keeps_its_exit_code(restore_excepthook, value, code):
    gui._keep_running_on_unhandled_errors()

    with mock.patch.object(gui, "_release_all_contacts"), \
            mock.patch.object(gui.logging, "shutdown"), \
            mock.patch.object(gui.os, "_exit") as exit_now:
        sys.excepthook(SystemExit, value, None)

    exit_now.assert_called_once_with(code)
