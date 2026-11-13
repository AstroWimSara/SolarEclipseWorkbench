"""Hardening of script parsing and scheduling: one bad line must not stop the others, nor the application."""

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from solareclipseworkbench import hardware_problems, logging_setup, notifications, scripts
from solareclipseworkbench.utils import schedule_commands

FUTURE = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)


@pytest.fixture(autouse=True)
def no_problems():
    hardware_problems.clear()
    yield
    hardware_problems.clear()


@pytest.fixture
def scheduler():
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    yield scheduler
    scheduler.shutdown(wait=False)


def _moments():
    return {
        "C1": SimpleNamespace(time_utc=FUTURE - timedelta(hours=1)),
        "C2": SimpleNamespace(time_utc=FUTURE),
        "C3": SimpleNamespace(time_utc=FUTURE + timedelta(minutes=3)),
        "sunrise": SimpleNamespace(time_utc=FUTURE - timedelta(hours=3)),
    }


def _script(tmp_path, *lines, encoding="utf-8"):
    path = tmp_path / "script.txt"
    path.write_text("\n".join(lines) + "\n", encoding=encoding)
    return str(path)


def _run_dates(scheduler):
    return sorted(job.trigger.run_date for job in scheduler.get_jobs())


# Simulation against sunrise / sunset

def test_simulation_against_sunrise_schedules_the_script(tmp_path, scheduler):
    # The simulator offers "sunrise" in lower case; .upper() made every line a missing moment and then raised
    filename = _script(tmp_path, 'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"')
    start = datetime.now(timezone.utc) + timedelta(minutes=10)

    unknown = schedule_commands(filename, scheduler, _moments(), {}, None, "sunrise", start)

    assert unknown == {}
    expected = start + (FUTURE - timedelta(seconds=5) - (FUTURE - timedelta(hours=3)))
    assert _run_dates(scheduler) == [expected]


# LAST

def test_last_in_a_simulation_is_not_shifted_twice(tmp_path, scheduler):
    filename = _script(tmp_path,
                       'voice_prompt, C2, -, 0:00:10.0, C2_IN_10_SECONDS, "10 to totality"',
                       'voice_prompt, LAST, +, 0:00:05.0, C2_IN_5_SECONDS, "5 after the last"')
    start = datetime.now(timezone.utc) + timedelta(minutes=10)

    schedule_commands(filename, scheduler, _moments(), {}, None, "C2", start, gps_time_offset=timedelta(seconds=2))

    first, last = _run_dates(scheduler)
    assert last - first == timedelta(seconds=5)
    assert first == start - timedelta(seconds=10) - timedelta(seconds=2)


def test_last_without_a_command_before_it_is_reported(tmp_path, scheduler):
    filename = _script(tmp_path,
                       'voice_prompt, LAST, +, 0:00:05.0, C2_IN_5_SECONDS, "nothing before"',
                       'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "5 to totality"')

    schedule_commands(filename, scheduler, _moments(), {}, None, None, None)

    assert len(scheduler.get_jobs()) == 1
    assert any("LAST" in p.message for p in hardware_problems.peek())


# One bad line does not cost the others

def test_a_bad_iso_does_not_stop_the_rest_of_the_script(tmp_path, scheduler):
    camera = SimpleNamespace(vendor="Canon", name="Cam")
    filename = _script(tmp_path,
                       'take_picture, C2, -, 0:00:20.0, Cam, 1/1000, 8, abc, "bad ISO"',
                       'take_picture, C2, -, 0:00:10.0, Cam, 1/1000, 8, 200, "good"')

    schedule_commands(filename, scheduler, _moments(), {"Cam": camera}, None, None, None)

    assert [job.name for job in scheduler.get_jobs()] == ["good"]
    assert any("bad ISO" in p.detail for p in hardware_problems.peek())


def test_a_sign_that_is_not_plus_or_minus_is_reported(tmp_path, scheduler):
    filename = _script(tmp_path, 'voice_prompt, C2, x, 0:00:05.0, C2_IN_5_SECONDS, "typo in the sign"')

    schedule_commands(filename, scheduler, _moments(), {}, None, None, None)

    assert scheduler.get_jobs() == []
    assert any("sign" in p.message for p in hardware_problems.peek())


def test_a_byte_order_mark_does_not_lose_the_first_line(tmp_path, scheduler):
    filename = _script(tmp_path, 'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "first"', encoding="utf-8-sig")

    schedule_commands(filename, scheduler, _moments(), {}, None, None, None)

    assert [job.name for job in scheduler.get_jobs()] == ["first"]


# Loops

def test_a_for_loop_on_a_missing_moment_does_not_exit(tmp_path):
    # Used to print a message and call exit(), which closed the application
    filename = _script(tmp_path,
                       "for, C2, C4, 10",
                       'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "in the loop"',
                       "endfor",
                       'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "after the loop"')

    converted = scripts.convert_script(filename, _moments()).getvalue().splitlines()

    assert len(converted) == 1 and "after the loop" in converted[0]


def test_a_for_loop_with_no_interval_is_skipped(tmp_path):
    # An interval of 0 never reached the end of the loop
    filename = _script(tmp_path,
                       "for, C2, C3, 0",
                       'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "in the loop"',
                       "endfor")

    assert scripts.convert_script(filename, _moments()).getvalue() == ""


def test_a_for_loop_without_endfor_ends_with_the_file(tmp_path):
    filename = _script(tmp_path,
                       "for, C2, C3, 60",
                       'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "in the loop"',
                       "",
                       "# a comment")

    converted = scripts.convert_script(filename, _moments()).getvalue().splitlines()

    assert len(converted) == 3      # C2, C2+60, C2+120 before C3 at C2+180


def test_an_intervalometer_keeps_the_tenths_of_its_offset(tmp_path):
    filename = _script(tmp_path,
                       "FOR,(INTERVALOMETER),1,1.0,2",
                       "TAKEPIC,C2,-,00:00:02.5,Cam,1/1000,8,200,,,,,Shot",
                       "ENDFOR")

    converted = scripts.convert_script(filename, _moments()).getvalue().splitlines()

    assert [line.split(", ")[3] for line in converted] == ["00:00:02.5", "00:00:01.5"]


def test_float_noise_does_not_lose_a_tenth():
    assert scripts.display1_10th_second(0.7 * 3) == "00:00:02.1"
    assert scripts.display1_10th_second(1e-05) == "00:00:00.0"
    assert scripts.display1_10th_second(-5.3) == "00:00:05.3"
    assert scripts.display1_10th_second(5) == "00:00:05.0"


def test_a_line_with_too_few_fields_is_dropped_not_raised(tmp_path):
    filename = _script(tmp_path,
                       "FOR,(INTERVALOMETER),1,1.0,2",
                       "TAKEPIC,C2,-,00:00:02.5",
                       "ENDFOR",
                       'voice_prompt, C2, -, 0:00:05.0, C2_IN_5_SECONDS, "after"')

    converted = scripts.convert_script(filename, _moments()).getvalue().splitlines()

    assert len(converted) == 1 and "after" in converted[0]


# Voice prompts

def test_a_voice_prompt_that_cannot_play_is_reported():
    with patch.object(notifications.sys, "platform", "darwin"), \
            patch.object(notifications.subprocess, "run", side_effect=FileNotFoundError("afplay")):
        with pytest.raises(FileNotFoundError):
            notifications.voice_prompt("C2_IN_5_SECONDS ")

    assert [p.source for p in hardware_problems.peek()] == ["Voice prompt"]


# Logging

def test_no_writable_log_directory_does_not_stop_the_application(monkeypatch):
    def refuse(directory, prefix):
        raise PermissionError("read-only")

    monkeypatch.setattr(logging_setup, "_log_path", None)
    monkeypatch.setattr(logging_setup, "_configured_without_file", False)
    monkeypatch.setattr(logging_setup, "_open_new_log_file", refuse)
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    try:
        assert logging_setup.setup_logging("sew") is None
        added = [h for h in root.handlers if h not in handlers]
        assert len(added) == 1          # the console only
        # A second call adds nothing
        logging_setup.setup_logging("sew")
        assert len([h for h in root.handlers if h not in handlers]) == 1
    finally:
        for handler in [h for h in root.handlers if h not in handlers]:
            root.removeHandler(handler)
        root.setLevel(level)
