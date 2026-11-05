"""The run report lines a run's log up per command: planned, shot, late, dropped, missed."""
import logging
from datetime import datetime, timedelta, timezone

from solareclipseworkbench import run_report
from solareclipseworkbench.camera import _serialised_on_camera, _shutter_release
from solareclipseworkbench.run_report import log_planned, parse_log

C2 = datetime(2026, 8, 12, 18, 28, 25, 600000, tzinfo=timezone.utc)


def _line(moment, message, level="INFO", thread="MainThread", logger="root", separator="T"):
    return f"{moment.strftime(f'%Y-%m-%d{separator}%H:%M:%S.%f')[:-3]}Z {level:<8} [{thread}] {logger}: {message}\n"


def _planned(func_name, camera, when, reference, busy_s, description, caplog):
    """The "Planned:" line exactly as log_planned writes it."""
    caplog.clear()
    with caplog.at_level(logging.INFO):
        log_planned(func_name, camera, when, reference, busy_s, description)
    return caplog.records[-1].getMessage()


def _hms(moment):
    return moment.strftime("%H:%M:%S.%f")[:-3]


def _log(caplog):
    load = C2 - timedelta(minutes=5)
    beads = C2 - timedelta(seconds=3)
    close = C2 - timedelta(seconds=1)
    corona = C2 + timedelta(seconds=4)
    late = C2 + timedelta(seconds=10)
    prompt = C2 - timedelta(seconds=20)
    lines = [
        _line(load - timedelta(seconds=1), "Logging to x.log"),
        _line(load, "Starting observation with script /scripts/spain.txt"),
        _line(load, "Reference moment C2: 2026-08-12 18:28:25.6 UTC"),
        _line(load, "Simulation: C2 in 5 minutes"),
        _line(load, "GPS - computer clock offset: 0.250 s"),
        _line(load, "Cameras: Canon EOS R, Sony A7"),
        _line(load, _planned("voice_prompt", None, prompt, "C2-00:00:20.0", None, "C2 in 20 s", caplog)),
        _line(load, _planned("take_burst", "Canon EOS R", beads, "C2-00:00:03.0", 8.0, "C2 beads", caplog)),
        _line(load, _planned("take_burst", "Sony A7", beads, "C2-00:00:03.0", 6.3, "C2 beads", caplog)),
        _line(load, _planned("take_picture", "Canon EOS R", close, "C2-00:00:01.0", 2.0, "Too close", caplog)),
        _line(load, _planned("take_picture", "Canon EOS R", corona, "C2+00:00:04.0", 2.5, "Corona", caplog)),
        _line(load, _planned("take_picture", "Canon EOS R", late, "C2+00:00:10.0", 2.5, "Corona 2", caplog)),
        _line(load, "Script: something", level="WARNING"),
        _line(prompt, f'Running job "C2 in 20 s (trigger: date[2026-08-12 18:28:05 UTC], next run at: '
                      f'2026-08-12 18:28:05 UTC)" (scheduled at {prompt.isoformat()})',
              thread="ThreadPoolExecutor-0_0", logger="apscheduler.executors.default"),
        _line(prompt, 'Job "C2 in 20 s (trigger: date[2026-08-12 18:28:05 UTC], next run at: '
                      '2026-08-12 18:28:05 UTC)" executed successfully',
              thread="ThreadPoolExecutor-0_0", logger="apscheduler.executors.default"),
        # Both cameras shoot their beads burst at the same time; the Sony first
        _line(beads, f"Sony A7: take_burst released the shutter at {_hms(beads + timedelta(seconds=0.3))} UTC: "
                     f"0.300 s after its scheduled time (0.300 s after the command started)"),
        _line(beads, f"Canon EOS R: take_burst released the shutter at {_hms(beads + timedelta(seconds=1.2))} UTC: "
                     f"1.200 s after its scheduled time (1.200 s after the command started)"),
        _line(close, f"Canon EOS R: take_picture (scheduled {_hms(close)} UTC) dropped — camera was still busy "
                     f"after 1.5s (shot is too late; timing accuracy preserved)", level="WARNING"),
        _line(C2 + timedelta(seconds=6), f"Canon EOS R: take_burst (scheduled {_hms(beads)} UTC) finished: "
                                         f"the camera was busy 9.100 s", level="DEBUG"),
        _line(corona, 'Run time of job "Corona (trigger: date[2026-08-12 18:28:29 UTC], next run at: '
                      '2026-08-12 18:28:29 UTC)" was missed by 0:00:02.1', level="WARNING",
              logger="apscheduler.executors.default"),
        _line(C2 + timedelta(seconds=5), "Scheduler stopped by user"),
    ]
    return lines


def test_every_command_gets_its_outcome(caplog):
    (run,) = parse_log(_log(caplog))
    assert run.script == "/scripts/spain.txt"
    assert run.simulation == "C2 in 5 minutes" and run.gps_offset_s == 0.25
    assert run.reference_moments["C2"] == datetime(2026, 8, 12, 18, 28, 25, 600000, tzinfo=timezone.utc)

    status = {(c.camera, c.description): run.status_of(c) for c in run.commands}
    assert status == {
        (None, "C2 in 20 s"): "done",
        ("Canon EOS R", "C2 beads"): "late",
        ("Sony A7", "C2 beads"): "shot",
        ("Canon EOS R", "Too close"): "dropped: camera busy",
        ("Canon EOS R", "Corona"): "missed by the scheduler",
        ("Canon EOS R", "Corona 2"): "not reached",
    }


def test_releases_at_the_same_time_go_to_their_own_camera(caplog):
    (run,) = parse_log(_log(caplog))
    by_camera = {c.camera: c for c in run.commands if c.description == "C2 beads"}
    assert by_camera["Sony A7"].delay_s == 0.3
    assert by_camera["Canon EOS R"].delay_s == 1.2
    assert by_camera["Canon EOS R"].busy_s == 9.1 and by_camera["Canon EOS R"].estimated_busy_s == 8.0
    assert by_camera["Sony A7"].busy_s is None


def test_summary_statistics_and_contacts(caplog):
    (run,) = parse_log(_log(caplog))
    assert run_report.summary(run)["Canon EOS R"]["late"] == 1
    assert run_report.delay_statistics(run)[("Canon EOS R", "take_burst")] == (1, 1.2, 1.2)
    assert [c.description for c in run_report.underestimated(run)] == ["C2 beads"]
    assert {c.description for c in run_report.near_contacts(run)} == {"C2 beads", "Too close", "Corona",
                                                                       "Corona 2"}
    assert run.problems[0].endswith("WARNING: Script: something")


def test_text_report(caplog):
    (run,) = parse_log(_log(caplog))
    text = run_report.format_report(run, "x.log")
    assert "Run report: spain.txt" in text and "Script:     /scripts/spain.txt" in text
    summary_line = next(line for line in text.splitlines() if line.startswith("Canon EOS R: "))
    assert "1 late" in summary_line and "1 dropped: camera busy" in summary_line
    assert "took 9.1 s, estimated 8.0 s" in text


def test_each_script_load_is_its_own_run(caplog):
    lines = _log(caplog)
    later = C2 + timedelta(minutes=1)
    lines += [_line(later, "Starting observation with script /scripts/other.txt"),
              _line(later, _planned("take_picture", "Sony A7", later + timedelta(seconds=30), "C3+00:00:05.0",
                                    2.0, "After C3", caplog))]
    runs = parse_log(lines)
    assert [r.script for r in runs] == ["/scripts/spain.txt", "/scripts/other.txt"]
    assert [c.description for c in runs[1].commands] == ["After C3"]


def test_a_log_without_planned_commands_still_lists_the_releases():
    moment = C2
    lines = [_line(moment, "Starting observation with script old.txt"),
             _line(moment, f"Canon EOS R: take_picture released the shutter at {_hms(moment)} UTC: "
                           f"0.512 s after its scheduled time (0.600 s after the command started)")]
    (run,) = parse_log(lines)
    (command,) = run.commands
    assert command.planned is None and command.delay_s == 0.512 and command.reference.startswith("scheduled ")
    assert "no planned commands" in run_report.format_report(run)


def test_logs_with_a_space_in_the_timestamp_are_still_read():
    """Logs up to 2.0.0 wrote "2026-08-12 18:28:25.600Z" instead of the ISO 8601 "T"."""
    lines = [_line(C2, "Starting observation with script old.txt", separator=" "),
             _line(C2, f"Canon EOS R: take_picture released the shutter at {_hms(C2)} UTC: "
                       f"0.512 s after its scheduled time (0.600 s after the command started)", separator=" ")]
    (run,) = parse_log(lines)
    assert run.started == C2
    assert run.commands[0].released_at == C2


def test_release_just_after_midnight_belongs_to_the_previous_day():
    logged = datetime(2026, 8, 13, 0, 0, 0, 100000, tzinfo=timezone.utc)
    lines = [_line(logged - timedelta(minutes=1), "Starting observation with script x.txt"),
             _line(logged, "Canon EOS R: take_picture released the shutter at 23:59:59.900 UTC: "
                           "0.100 s after its scheduled time (0.100 s after the command started)")]
    (run,) = parse_log(lines)
    assert run.commands[0].released_at == datetime(2026, 8, 12, 23, 59, 59, 900000, tzinfo=timezone.utc)


def test_offset_from_the_reference(caplog):
    (run,) = parse_log(_log(caplog))
    beads = next(c for c in run.commands if c.description == "C2 beads")
    assert beads.reference_moment == "C2" and beads.offset_s == -3.0


def test_run_logs_lists_only_logs_with_a_loaded_script(tmp_path):
    (tmp_path / "sew-20260812-170000Z.log").write_text("x Starting observation with script a.txt\n")
    (tmp_path / "sew-20260812-180000Z.log").write_text("nothing\n")
    (tmp_path / "sew-20260812-190000Z.log").write_text("x Starting observation with script b.txt\n")
    (tmp_path / "sew_wizard-20260812-200000Z.log").write_text("x Starting observation with script c.txt\n")
    assert [p.name for p in run_report.run_logs(tmp_path)] == ["sew-20260812-190000Z.log",
                                                              "sew-20260812-170000Z.log"]


# The camera side of the log

class _Lock:
    def __init__(self, free=True):
        self.free = free

    def acquire(self, timeout=None):
        return self.free

    def release(self):
        return None


class _Camera:
    vendor = "Canon"
    name = "Canon EOS R"

    def __init__(self, free=True):
        self._usb_lock = _Lock(free)


@_serialised_on_camera
def take_picture(camera):
    with _shutter_release(camera):
        pass


def test_the_camera_log_lines_are_read_back(caplog):
    caplog.set_level(logging.DEBUG)
    scheduled = datetime.now(timezone.utc).replace(microsecond=0)
    lines = [_line(scheduled - timedelta(seconds=10), "Starting observation with script x.txt"),
             _line(scheduled - timedelta(seconds=10),
                   _planned("take_picture", "Canon EOS R", scheduled, "C2+00:00:04.0", 2.0, "Corona", caplog)),
             _line(scheduled - timedelta(seconds=10),
                   _planned("take_picture", "Canon EOS R", scheduled + timedelta(seconds=2), "C2+00:00:06.0",
                            2.0, "Corona 2", caplog))]
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    take_picture(_Camera(), scheduled_at=scheduled)
    take_picture(_Camera(free=False), scheduled_at=scheduled + timedelta(seconds=2))
    lines += [_line(datetime.fromtimestamp(r.created, timezone.utc), r.getMessage(), r.levelname)
              for r in caplog.records]

    (run,) = parse_log(lines)
    first, second = sorted(run.commands, key=lambda c: c.planned)
    assert run.status_of(first) == "shot" and first.busy_s is not None
    assert run.status_of(second) == "dropped: camera busy"
