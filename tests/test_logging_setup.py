"""Tests for the per-run log files."""

import logging

import pytest

from solareclipseworkbench import logging_setup


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
