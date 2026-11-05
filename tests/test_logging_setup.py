"""Tests for the per-run log files."""

import logging
import re
import threading

import pytest

from solareclipseworkbench import camera, logging_setup, run_report


@pytest.fixture
def fresh_logging(monkeypatch):
    """Run setup_logging as if in a new process, and restore the root logger afterwards."""
    root = logging.getLogger()
    old_handlers, old_level = list(root.handlers), root.level
    monkeypatch.setattr(logging_setup, "_log_path", None)
    yield
    for handler in root.handlers:
        if handler not in old_handlers:
            handler.close()
    root.handlers = old_handlers
    root.setLevel(old_level)


def test_log_goes_to_a_new_file_in_the_log_directory(tmp_path, fresh_logging):
    path = logging_setup.setup_logging("sew", log_dir=tmp_path)
    logging.getLogger("solareclipseworkbench.camera").debug("trigger_capture fired")

    assert path.parent == tmp_path
    assert path.name.startswith("sew-") and path.suffix == ".log"
    text = path.read_text(encoding="utf-8")
    assert "trigger_capture fired" in text        # DEBUG reaches the file
    assert "Z DEBUG" in text                       # UTC timestamps


def test_timestamps_are_iso_8601_utc_and_read_back_by_the_run_report(tmp_path, fresh_logging, capsys):
    path = logging_setup.setup_logging("sew", log_dir=tmp_path)
    logging.getLogger("solareclipseworkbench.camera").info("trigger_capture fired")

    file_line = next(line for line in path.read_text(encoding="utf-8").splitlines()
                     if line.endswith("trigger_capture fired"))
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z INFO ", file_line)
    assert run_report._LINE.match(file_line)

    console_line = next(line for line in capsys.readouterr().out.splitlines()
                        if line.endswith("trigger_capture fired"))
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z INFO ", console_line)


def test_existing_log_is_never_overwritten(tmp_path, fresh_logging, monkeypatch):
    """Two runs started within the same second must not share (and truncate) a file."""
    monkeypatch.setattr(logging_setup.time, "strftime", lambda fmt, t=None: "20260812-182900")
    earlier = tmp_path / "sew-20260812-182900Z.log"
    earlier.write_text("C2 diamond ring fired\n", encoding="utf-8")

    path = logging_setup.setup_logging("sew", log_dir=tmp_path)

    assert path != earlier
    assert earlier.read_text(encoding="utf-8") == "C2 diamond ring fired\n"


def test_second_call_reuses_the_first_file(tmp_path, fresh_logging):
    first = logging_setup.setup_logging("sew", log_dir=tmp_path)
    assert logging_setup.setup_logging("sew", log_dir=tmp_path) == first
    assert len(list(tmp_path.iterdir())) == 1


def test_silencing_the_console_keeps_the_log_file(tmp_path):
    file_handler = logging.FileHandler(tmp_path / "x.log")
    console_handler = logging.StreamHandler()
    try:
        assert logging_setup.file_handlers_only([console_handler, file_handler]) == [file_handler]
    finally:
        file_handler.close()


class _NamedCamera:
    def __init__(self, name):
        self.name = name


def test_camera_log_starts_every_message_with_the_camera_name(caplog):
    caplog.set_level(logging.DEBUG)
    logging_setup.camera_log(_NamedCamera("Sun Wide")).debug("set aperture to %s", "f/8")
    logging_setup.camera_log("Sun Tele").warning("no continuous drive mode available")

    assert caplog.messages == ["Sun Wide: set aperture to f/8", "Sun Tele: no continuous drive mode available"]


def test_camera_log_takes_a_percent_sign_in_the_name_literally(caplog):
    caplog.set_level(logging.DEBUG)
    log = logging_setup.camera_log("Canon 100%")
    log.info("battery level is %s", "75%")
    log.info("connected to AC")

    assert caplog.messages == ["Canon 100%: battery level is 75%", "Canon 100%: connected to AC"]


def test_camera_log_exception_keeps_the_traceback(caplog):
    try:
        raise RuntimeError("-110 I/O in progress")
    except RuntimeError:
        logging_setup.camera_log("Sun Wide").exception("low-level capture failed")

    record, = caplog.records
    assert record.getMessage() == "Sun Wide: low-level capture failed"
    assert record.levelno == logging.ERROR and record.exc_info is not None


def test_shot_dropped_on_a_busy_camera_names_the_camera(caplog, monkeypatch):
    """With two bodies connected, a dropped shot must say which one it was."""
    monkeypatch.setattr(camera, "_MAX_LOCK_WAIT_S", 0.01)
    busy = _NamedCamera("Sun Tele")
    busy._usb_lock = threading.RLock()
    held, release = threading.Event(), threading.Event()

    def hold_the_camera():
        with busy._usb_lock:
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold_the_camera)
    holder.start()
    held.wait(5)
    try:
        camera.take_picture(busy, camera.CameraSettings("Sun Tele", "1/1000", "8", 100))
    finally:
        release.set()
        holder.join()

    assert caplog.messages[-1].startswith("Sun Tele: take_picture dropped")
