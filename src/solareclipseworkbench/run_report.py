"""What happened to each command of a run, read back from its log file.

Rehearsing a script only pays off when the log of the rehearsal is read: which
commands were taken late, which were dropped because the camera was still
busy, and how long each command really kept the camera busy compared to the
estimate the script was planned with.  The log has all of this, spread over
thousands of lines; this module lines it up per command.

A run starts where a script is loaded ("Starting observation with script ...").
For every command the scheduler logs a "Planned:" line (see log_planned), and
the camera and scheduler threads log what became of it:

    - "<camera>: take_burst released the shutter at 18:29:27.012 UTC: 1.012 s after its scheduled time ..."
    - "<camera>: take_burst (scheduled 18:29:26.000 UTC) finished: the camera was busy 7.204 s"
    - "<camera>: take_burst (scheduled 18:29:26.000 UTC) dropped — camera was still busy ..."
    - apscheduler's "Running job ...", "... executed successfully", "... raised an exception",
      "Run time of job ... was missed by ..."

The planned time of a command is on the computer clock, like every other time
in the log: in a simulation, or with a GPS clock offset, it differs from the
contact time it was written against, which is kept as the reference
(e.g. C2-00:00:04.0).
"""

import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from solareclipseworkbench.logging_setup import LOG_DIR

PLANNED = "Planned: "

# Two times in the log name the same command when they are this close (the log
# has milliseconds, a release is logged as its time and its delay).
_MATCH_TOLERANCE_S = 0.05

# A command within this many seconds of second or third contact is listed under the contacts
CONTACT_WINDOW_S = 60.0

# A shot this much later than planned is reported as late
LATE_S = 1.0

# Log lines start with an ISO 8601 UTC timestamp; logs up to 2.0.0 have a space instead of the "T"
_LINE = re.compile(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d\.\d{3})Z (\w+)\s+\[([^\]]*)\] (\S+): (.*)$")
_RELEASED = re.compile(r"^(?P<camera>.*): (?P<cmd>\w+) released the shutter at (?P<tod>\d\d:\d\d:\d\d\.\d+) UTC: "
                       r"(?P<late>-?\d+(?:\.\d+)?) s after its scheduled time "
                       r"\((?P<after_start>-?\d+(?:\.\d+)?) s after the command started\)")
_FINISHED = re.compile(r"^(?P<camera>.*): (?P<cmd>\w+) \(scheduled (?P<tod>\d\d:\d\d:\d\d\.\d+) UTC\) finished: "
                       r"the camera was busy (?P<busy>\d+(?:\.\d+)?) s")
_DROPPED = re.compile(r"^(?P<camera>.*): (?P<cmd>\w+) \(scheduled (?P<tod>\d\d:\d\d:\d\d\.\d+) UTC\) dropped")
_RUNNING = re.compile(r'^Running job "(?P<name>.*) \(trigger: .*\)" \(scheduled at (?P<when>[^)]*)\)$')
_MISSED = re.compile(r'^Run time of job "(?P<name>.*) \(trigger: date\[(?P<when>[\d\- :]+) \w*\].*\)" '
                     r'was missed by (?P<by>.*)$')
_EXECUTED = re.compile(r'^Job ".*" executed successfully$')
_RAISED = re.compile(r'^Job ".*" raised an exception$')
_REFERENCE = re.compile(r"^Reference moment (\S+): (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?) UTC$")
_RELATIVE = re.compile(r"^(?P<ref>[A-Za-z0-9_]+)(?P<sign>[+-])(?P<h>\d+):(?P<m>\d+):(?P<s>\d+(?:\.\d+)?)$")

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def log_planned(func_name: str, camera: Optional[str], when: datetime, reference: str,
                busy_s: Optional[float], description: str) -> None:
    """Log a scheduled command, for the run report.

    Args:
        - func_name: Script command (take_picture, voice_prompt, ...)
        - camera: Camera name in the script, None for a command that does not use a camera
        - when: Time the command is scheduled for, on the computer clock
        - reference: Time as written in the script, e.g. C2-00:00:04.0
        - busy_s: Estimated time the command keeps the camera busy, None when not estimated
        - description: Description of the command (last field of the script line)
    """
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    busy = f"busy {busy_s:.1f} s" if busy_s is not None else "-"
    logging.info("%s%s | %s | %s UTC | %s | %s | %s", PLANNED, func_name, camera or "-",
                 when.strftime(_TIME_FORMAT)[:-3], reference, busy, description)


def _parse_planned(message: str) -> Optional["CommandOutcome"]:
    fields = message[len(PLANNED):].split(" | ", 5)
    if len(fields) != 6:
        return None
    func_name, camera, when, reference, busy, description = fields
    try:
        moment = datetime.strptime(when.removesuffix(" UTC"), _TIME_FORMAT).replace(tzinfo=timezone.utc)
        busy_s = float(busy.removeprefix("busy ").removesuffix(" s")) if busy != "-" else None
    except ValueError:
        return None
    return CommandOutcome(func_name=func_name, camera=None if camera == "-" else camera, planned=moment,
                          reference=reference, estimated_busy_s=busy_s, description=description)


@dataclass
class CommandOutcome:
    """A command of a run: what was planned and what the log says happened to it."""

    func_name: str
    camera: Optional[str]
    planned: Optional[datetime]          # None for an event that matches no planned command
    reference: str = ""
    estimated_busy_s: Optional[float] = None
    description: str = ""
    started: bool = False                # the scheduler ran the job
    succeeded: bool = False              # the job returned without an exception
    failed: bool = False                 # the job raised an exception
    missed_by: Optional[str] = None      # the scheduler skipped the job, this late
    released_at: Optional[datetime] = None
    delay_s: Optional[float] = None      # shutter release after the planned time
    dropped: bool = False                # dropped because the camera was still busy
    busy_s: Optional[float] = None       # how long the command really kept the camera busy

    @property
    def is_camera_command(self) -> bool:
        return self.camera is not None

    @property
    def offset_s(self) -> Optional[float]:
        """Seconds from the reference moment the command was written against, None when not known."""
        match = _RELATIVE.match(self.reference.replace(" ", ""))
        if match is None:
            return None
        seconds = int(match["h"]) * 3600 + int(match["m"]) * 60 + float(match["s"])
        return seconds if match["sign"] == "+" else -seconds

    @property
    def reference_moment(self) -> str:
        match = _RELATIVE.match(self.reference.replace(" ", ""))
        return match["ref"].upper() if match else ""

    def status(self, run_end: Optional[datetime] = None) -> str:
        """What happened, in a few words."""
        if self.dropped:
            return "dropped: camera busy"
        if self.missed_by is not None:
            return "missed by the scheduler"
        if self.failed:
            return "failed"
        if self.released_at is not None:
            return "late" if self.delay_s is not None and self.delay_s > LATE_S else "shot"
        if self.is_camera_command and self.func_name != "prepare_camera" and (self.busy_s is not None
                                                                             or self.succeeded):
            return "no shutter release"
        if self.succeeded or self.busy_s is not None:
            return "done"
        if self.started:
            return "running"
        if self.planned is not None and run_end is not None and self.planned > run_end:
            return "not reached"
        return "no record"


@dataclass
class Run:
    """One script load and everything logged until the next one (or the end of the log)."""

    script: str
    started: datetime
    reference_moments: Dict[str, datetime] = field(default_factory=dict)
    simulation: Optional[str] = None
    gps_offset_s: Optional[float] = None
    cameras: str = ""
    commands: List[CommandOutcome] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)   # warnings and errors, with their time
    ended: Optional[datetime] = None                     # time of the last line of the run

    def status_of(self, command: CommandOutcome) -> str:
        return command.status(self.ended)


def _at_time_of_day(time_of_day: str, near: datetime) -> Optional[datetime]:
    """The moment with this time of day (HH:MM:SS.fff, UTC) closest to near."""
    try:
        clock = datetime.strptime(time_of_day, "%H:%M:%S.%f").time()
    except ValueError:
        return None
    candidates = [datetime.combine(near.date() + timedelta(days=d), clock, tzinfo=timezone.utc) for d in (-1, 0, 1)]
    return min(candidates, key=lambda c: abs((c - near).total_seconds()))


def _find(commands: List[CommandOutcome], func_name: Optional[str], camera: Optional[str],
          planned: datetime, description: Optional[str] = None, free=None,
          tolerance_s: float = _MATCH_TOLERANCE_S) -> Optional[CommandOutcome]:
    """The planned command at this time.

    Of several (two cameras shooting together), the one on this camera, with this
    description and for which free(command) holds (the event is not known yet) comes first.
    """
    found = [c for c in commands
             if c.planned is not None and abs((c.planned - planned).total_seconds()) <= tolerance_s
             and (func_name is None or c.func_name == func_name)]
    if not found:
        return None

    def score(c):
        return ((camera is not None and c.camera == camera) + (description is not None and c.description == description)
                + (free is None or free(c)))
    return max(found, key=score)


def _event(run: Run, func_name: str, camera: str, planned: datetime, free) -> CommandOutcome:
    """The planned command an event is about, or a new entry for an event that matches none."""
    command = _find(run.commands, func_name, camera, planned, free=free)
    if command is None:
        command = CommandOutcome(func_name=func_name, camera=camera, planned=None)
        command.reference = f"scheduled {planned.strftime('%H:%M:%S.%f')[:-3]} UTC"
        run.commands.append(command)
    return command


def parse_log(lines: Iterable[str]) -> List[Run]:
    """The runs in a log file, in the order they were started."""
    runs: List[Run] = []
    running: Dict[str, CommandOutcome] = {}   # job running on each scheduler thread
    run: Optional[Run] = None
    for line in lines:
        match = _LINE.match(line.rstrip("\n"))
        if match is None:
            continue
        stamp, level, thread, _logger, message = match.groups()
        try:
            moment = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if message.startswith("Starting observation with script "):
            run = Run(script=message[len("Starting observation with script "):], started=moment)
            runs.append(run)
            running.clear()
        if run is None:
            continue
        run.ended = moment

        if level in ("WARNING", "ERROR", "CRITICAL"):
            run.problems.append(f"{moment.strftime('%H:%M:%S.%f')[:-3]} {level}: {message}")

        if message.startswith(PLANNED):
            command = _parse_planned(message)
            if command is not None:
                run.commands.append(command)
        elif (m := _REFERENCE.match(message)) is not None:
            try:
                run.reference_moments[m[1]] = datetime.fromisoformat(m[2]).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        elif message.startswith("Simulation: "):
            run.simulation = message[len("Simulation: "):]
        elif message.startswith("GPS - computer clock offset: "):
            try:
                run.gps_offset_s = float(message.split(": ", 1)[1].split()[0])
            except (IndexError, ValueError):
                pass
        elif message.startswith("Cameras: "):
            run.cameras = message[len("Cameras: "):]
        elif (m := _RELEASED.match(message)) is not None:
            released = _at_time_of_day(m["tod"], moment)
            if released is not None:
                late = float(m["late"])
                command = _event(run, m["cmd"], m["camera"], released - timedelta(seconds=late),
                                 lambda c: c.released_at is None)
                command.released_at, command.delay_s = released, late
        elif (m := _FINISHED.match(message)) is not None:
            planned = _at_time_of_day(m["tod"], moment)
            if planned is not None:
                _event(run, m["cmd"], m["camera"], planned, lambda c: c.busy_s is None).busy_s = float(m["busy"])
        elif (m := _DROPPED.match(message)) is not None:
            planned = _at_time_of_day(m["tod"], moment)
            if planned is not None:
                _event(run, m["cmd"], m["camera"], planned, lambda c: not c.dropped).dropped = True
        elif (m := _RUNNING.match(message)) is not None:
            try:
                planned = datetime.fromisoformat(m["when"]).astimezone(timezone.utc)
            except ValueError:
                continue
            command = _find(run.commands, None, None, planned, m["name"], lambda c: not c.started)
            if command is not None:
                command.started = True
                running[thread] = command
        elif _EXECUTED.match(message) and thread in running:
            running.pop(thread).succeeded = True
        elif _RAISED.match(message) and thread in running:
            running.pop(thread).failed = True
        elif (m := _MISSED.match(message)) is not None:
            try:
                planned = datetime.strptime(m["when"].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            # The scheduler names the time to the second only
            candidates = [c for c in run.commands if c.planned is not None and c.description == m["name"]
                          and c.planned.replace(microsecond=0) == planned]
            if candidates:
                candidates[0].missed_by = m["by"]
    return runs


def read_log(path) -> List[Run]:
    """The runs in a log file (see parse_log)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_log(f)


def run_logs(directory: Optional[Path] = None) -> List[Path]:
    """Log files in which a script was loaded, newest first."""
    directory = LOG_DIR if directory is None else Path(directory)
    found = []
    for path in sorted(directory.glob("sew-*.log"), key=lambda p: p.name, reverse=True):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                if any("Starting observation with script " in line for line in f):
                    found.append(path)
        except OSError:
            continue
    return found


# Report

def _hms(moment: Optional[datetime]) -> str:
    return moment.strftime("%H:%M:%S.%f")[:-4] if moment is not None else "-"


def _seconds(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}" if signed else f"{value:.1f}"


def camera_commands(run: Run) -> List[CommandOutcome]:
    return [c for c in run.commands if c.is_camera_command]


def summary(run: Run) -> Dict[str, Dict[str, int]]:
    """Number of camera commands per status, per camera."""
    counts: Dict[str, Dict[str, int]] = {}
    for command in camera_commands(run):
        per_camera = counts.setdefault(command.camera, {})
        status = run.status_of(command)
        per_camera[status] = per_camera.get(status, 0) + 1
    return counts


def delay_statistics(run: Run) -> Dict[tuple, tuple]:
    """(number, median, maximum) of the shutter delays, per (camera, command)."""
    delays: Dict[tuple, list] = {}
    for command in camera_commands(run):
        if command.delay_s is not None:
            delays.setdefault((command.camera, command.func_name), []).append(command.delay_s)
    return {key: (len(values), statistics.median(values), max(values)) for key, values in sorted(delays.items())}


def underestimated(run: Run, margin_s: float = 0.5) -> List[CommandOutcome]:
    """Commands that kept the camera busy longer than estimated, the worst first."""
    found = [c for c in camera_commands(run) if c.busy_s is not None and c.estimated_busy_s is not None
             and c.busy_s > c.estimated_busy_s + margin_s]
    return sorted(found, key=lambda c: c.busy_s - c.estimated_busy_s, reverse=True)


def near_contacts(run: Run, window_s: float = CONTACT_WINDOW_S) -> List[CommandOutcome]:
    """Camera commands written within window_s of second or third contact (or the Baily's beads)."""
    found = []
    for command in camera_commands(run):
        reference, offset = command.reference_moment, command.offset_s
        if offset is None or not (reference.startswith(("C2", "C3")) or reference.startswith("BEADS_")):
            continue
        if abs(offset) <= window_s:
            found.append(command)
    return found


def format_report(run: Run, log_path=None) -> str:
    """The report of a run as plain text."""
    lines = []
    title = f"Run report: {Path(run.script).name}"
    lines += [title, "=" * len(title), f"Script:     {run.script}"]
    if log_path is not None:
        lines.append(f"Log file:   {log_path}")
    lines.append(f"Loaded at:  {run.started.strftime('%Y-%m-%d %H:%M:%S')} UTC, "
                 f"log ends at {_hms(run.ended)} UTC")
    if run.simulation:
        lines.append(f"Simulation: {run.simulation} (times below are on the computer clock)")
    if run.gps_offset_s:
        lines.append(f"GPS - computer clock offset: {run.gps_offset_s:.3f} s")
    if run.cameras:
        lines.append(f"Cameras:    {run.cameras}")
    for name in ("C1", "C2", "MAX", "C3", "C4"):
        if name in run.reference_moments:
            lines.append(f"  {name:<4} {run.reference_moments[name].strftime('%H:%M:%S.%f')[:-5]} UTC")
    lines.append("")

    planned = [c for c in run.commands if c.planned is not None]
    if not planned:
        lines += ["This log has no planned commands: it was written by a version of Solar Eclipse Workbench",
                  "before the run report, so only the shutter releases and dropped commands are listed.", ""]

    lines.append("Summary per camera")
    lines.append("------------------")
    counts = summary(run)
    if not counts:
        lines.append("No camera commands.")
    for camera, per_status in counts.items():
        parts = ", ".join(f"{n} {status}" for status, n in sorted(per_status.items(), key=lambda kv: -kv[1]))
        lines.append(f"{camera}: {parts}")
    lines.append("")

    stats = delay_statistics(run)
    if stats:
        lines.append("Shutter release after the planned time")
        lines.append("--------------------------------------")
        lines.append(f"{'Camera':<28} {'Command':<15} {'n':>4} {'median s':>9} {'max s':>7}")
        for (camera, func_name), (n, median, worst) in stats.items():
            lines.append(f"{camera[:28]:<28} {func_name:<15} {n:>4} {median:>9.2f} {worst:>7.2f}")
        lines.append("")

    contacts = near_contacts(run)
    if contacts:
        lines.append(f"Around second and third contact (within {CONTACT_WINDOW_S:.0f} s)")
        lines.append("-" * 44)
        lines += _command_table(run, contacts)
        lines.append("")

    slow = underestimated(run)
    if slow:
        lines.append("Longer than estimated (the next command on the camera may have waited)")
        lines.append("-----------------------------------------------------------------------")
        for command in slow[:15]:
            lines.append(f"{_hms(command.planned)}  {command.camera}: {command.func_name} \"{command.description}\" "
                         f"took {command.busy_s:.1f} s, estimated {command.estimated_busy_s:.1f} s")
        lines.append("")

    lines.append("All commands")
    lines.append("------------")
    lines += _command_table(run, run.commands)
    lines.append("")

    if run.problems:
        lines.append(f"Warnings and errors ({len(run.problems)})")
        lines.append("-------------------")
        lines += run.problems[:50]
        if len(run.problems) > 50:
            lines.append(f"... and {len(run.problems) - 50} more in the log file")
    return "\n".join(lines) + "\n"


def _command_table(run: Run, commands: List[CommandOutcome]) -> List[str]:
    header = (f"{'Planned UTC':<12} {'Reference':<17} {'Camera':<18} {'Command':<14} {'Status':<22} "
              f"{'Delay s':>8} {'Busy s':>7} {'Est. s':>7}  Description")
    rows = [header]
    ordered = sorted(commands, key=lambda c: (c.planned or c.released_at or run.started))
    for c in ordered:
        rows.append(f"{_hms(c.planned):<12} {c.reference[:17]:<17} {(c.camera or '-')[:18]:<18} {c.func_name[:14]:<14} "
                    f"{run.status_of(c):<22} {_seconds(c.delay_s, True):>8} {_seconds(c.busy_s):>7} "
                    f"{_seconds(c.estimated_busy_s):>7}  {c.description}")
    return rows
