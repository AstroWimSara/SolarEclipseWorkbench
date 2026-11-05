"""A script laid out per camera: when each command starts and how long it keeps the camera busy.

The check that runs when a script is loaded warns about a command that will be
dropped, but a warning does not show why: which command is still running, how
much room there is, and how close the contacts are.  The timeline shows every
command as a bar from its start to the end of its estimated busy time, on one
row per camera, with the contacts and the Baily's beads windows drawn across.

It uses the same estimates and the same replay of the camera USB lock as that
check (utils.camera_busy_window, utils.replay_camera_windows), so a command
that is drawn as dropped is one the check warns about.  Nothing is scheduled:
the timeline can be drawn for any script, before the cameras are connected,
from the GUI or with ``sew --check``.

Times are the true UTC times of the reference moments, without a simulation
offset or GPS clock correction.
"""

import contextlib
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from solareclipseworkbench import scripts
from solareclipseworkbench.command_timing import DEFAULT_PROFILE, parse_timing_directives
from solareclipseworkbench.utils import (CameraBusyWindow, ReplayedWindow, camera_busy_window,
                                         replay_camera_windows)

# Commands that do not use a camera
NON_CAMERA_COMMANDS = ("voice_prompt", "command", "sync_cameras")

# Reference moments drawn across the timeline, with their label
CONTACTS = (("sunrise", "Sunrise"), ("C1", "C1"), ("C2", "C2"), ("MAX", "MAX"), ("C3", "C3"), ("C4", "C4"),
            ("sunset", "Sunset"))

# The totality view shows this much before C2 and after C3
TOTALITY_MARGIN_S = 90.0

ROW_PROMPTS = "Prompts & commands"


@dataclass
class TimelineCommand:
    """A command of the script, at the time it is written for."""

    func_name: str
    camera: Optional[str]
    start: datetime
    reference: str                              # as written, e.g. C2-00:00:04.0
    description: str
    replay: Optional[ReplayedWindow] = None     # camera commands whose busy time is estimated

    @property
    def status(self) -> str:
        if self.replay is None:
            return ""
        if self.replay.dropped:
            return "dropped"
        if self.replay.wait_s > 0.05:
            return "late"
        return "ok"


@dataclass
class Timeline:
    commands: List[TimelineCommand]
    reference_moments: Dict[str, datetime]
    unknown_moments: Dict[str, int] = field(default_factory=dict)   # moments the script needs that do not exist

    @property
    def cameras(self) -> List[str]:
        names = []
        for command in self.commands:
            if command.camera is not None and command.camera not in names:
                names.append(command.camera)
        return names

    def camera_commands(self, camera: Optional[str] = None) -> List[TimelineCommand]:
        return [c for c in self.commands if c.camera is not None and (camera is None or c.camera == camera)]

    @property
    def dropped(self) -> List[TimelineCommand]:
        return [c for c in self.commands if c.status == "dropped"]

    @property
    def late(self) -> List[TimelineCommand]:
        return [c for c in self.commands if c.status == "late"]

    @property
    def totality(self) -> Optional[tuple]:
        """(C2, C3) when the eclipse is total (or annular) here."""
        c2, c3 = self.reference_moments.get("C2"), self.reference_moments.get("C3")
        return (c2, c3) if c2 is not None and c3 is not None else None

    def relative(self, moment: datetime) -> str:
        """The moment relative to the nearest contact, e.g. C2-4.0 s."""
        nearest = None
        for name in ("C1", "C2", "MAX", "C3", "C4"):
            reference = self.reference_moments.get(name)
            if reference is None:
                continue
            offset = (moment - reference).total_seconds()
            if nearest is None or abs(offset) < abs(nearest[1]):
                nearest = (name, offset)
        if nearest is None:
            return ""
        name, offset = nearest
        if abs(offset) >= 600:
            return f"{name}{offset / 60:+.1f} min"
        return f"{name}{offset:+.1f} s"


def build_timeline(filename: str, reference_moments: dict, cameras: Optional[dict] = None) -> Timeline:
    """Lay out a script against the reference moments, the way schedule_commands would schedule it.

    Args:
        - filename: Script file
        - reference_moments: Reference moments (ReferenceMomentInfo per name), as for observe_solar_eclipse
        - cameras: Camera objects per name, when connected: their vendor is used for the estimates
                   (otherwise the vendor is taken from the camera name in the script)
    """
    moments = {name: info.time_utc for name, info in reference_moments.items()
               if getattr(info, "time_utc", None) is not None}
    # convert_script prints every line it converts
    with contextlib.redirect_stdout(io.StringIO()):
        script = scripts.convert_script(filename, reference_moments)
    script.seek(0)
    try:
        with open(filename, encoding="utf-8", errors="replace") as f:
            timing_profiles = parse_timing_directives(f)
    except OSError:
        timing_profiles = {}

    commands: List[TimelineCommand] = []
    windows: List[CameraBusyWindow] = []
    window_of: Dict[int, TimelineCommand] = {}
    unknown: Dict[str, int] = {}
    latest: Optional[datetime] = None
    for line in script:
        try:
            fields = next(csv.reader([line], skipinitialspace=True))
            func_name, ref_moment, sign = fields[0].strip(), fields[1].strip(), fields[2].strip()
            hours, minutes, seconds = fields[3].strip().split(":")
        except (StopIteration, IndexError, ValueError):
            continue
        description = fields[-1].strip()
        script_args = fields[4:-1]
        if ref_moment.upper() in ("SUNRISE", "SUNSET"):
            ref_moment = ref_moment.lower()

        if ref_moment == "LAST":
            # The scheduler takes the latest job scheduled so far
            if latest is None:
                continue
            reference = latest
        elif ref_moment in moments:
            reference = moments[ref_moment]
        else:
            unknown[ref_moment] = unknown.get(ref_moment, 0) + 1
            continue
        try:
            delta = timedelta(hours=float(hours), minutes=float(minutes), seconds=float(seconds))
        except ValueError:
            continue
        start = reference + delta if sign == "+" else reference - delta
        latest = start if latest is None else max(latest, start)

        camera_name = script_args[0].strip() if script_args and func_name not in NON_CAMERA_COMMANDS else None
        command = TimelineCommand(func_name, camera_name, start, f"{ref_moment}{sign}{fields[3].strip()}",
                                  description)
        commands.append(command)
        if camera_name is None:
            continue
        profile = timing_profiles.get(camera_name, DEFAULT_PROFILE)
        window = camera_busy_window(start, func_name, script_args, description,
                                    (cameras or {}).get(camera_name), profile)
        if window is not None:
            windows.append(window)
            window_of[id(window)] = command

    for replayed in replay_camera_windows(windows):
        window_of[id(replayed.window)].replay = replayed

    commands.sort(key=lambda c: c.start)
    return Timeline(commands, moments, unknown)


def format_timeline(timeline: Timeline) -> str:
    """The timeline as plain text: the problems first, then every camera command per camera."""
    lines = []
    for name, label in CONTACTS:
        if name in timeline.reference_moments:
            lines.append(f"{label:<8}{timeline.reference_moments[name].strftime('%H:%M:%S.%f')[:-5]} UTC")
    if timeline.totality:
        c2, c3 = timeline.totality
        lines.append(f"Totality {(c3 - c2).total_seconds():.1f} s")
    lines.append("")

    for name, count in timeline.unknown_moments.items():
        lines.append(f"WARNING: {count} line(s) are written against {name}, which does not exist here; "
                     f"they will not run.")
    for command in timeline.dropped:
        blocker = command.replay.blocked_by
        lines.append(f"DROPPED: {command.camera}: \"{command.description}\" at {_hms(command.start)} "
                     f"({timeline.relative(command.start)}): the camera is still busy with "
                     f"\"{blocker.description if blocker else '?'}\" for {command.replay.wait_s:.1f} s.")
    for command in timeline.late:
        lines.append(f"LATE:    {command.camera}: \"{command.description}\" at {_hms(command.start)} "
                     f"({timeline.relative(command.start)}) starts {command.replay.wait_s:.1f} s late.")
    if not timeline.dropped and not timeline.late and not timeline.unknown_moments:
        lines.append("No command has to wait for its camera.")
    lines.append("")

    for camera in timeline.cameras:
        lines.append(camera)
        lines.append("-" * len(camera))
        lines.append(f"{'Start UTC':<11} {'Relative':<14} {'Command':<15} {'Busy s':>6} {'Ends':<11} {'Status':<8} "
                     f"Description")
        for command in timeline.camera_commands(camera):
            replay = command.replay
            busy = f"{replay.duration_s:.1f}" if replay is not None and not replay.dropped else "-"
            end = _hms(replay.start + timedelta(seconds=replay.duration_s)) \
                if replay is not None and not replay.dropped else "-"
            lines.append(f"{_hms(command.start):<11} {timeline.relative(command.start):<14} "
                         f"{command.func_name:<15} {busy:>6} {end:<11} {command.status:<8} {command.description}")
        lines.append("")
    others = [c for c in timeline.commands if c.camera is None]
    if others:
        lines.append(f"{len(others)} voice prompt(s) and other commands do not use a camera.")
    return "\n".join(lines) + "\n"


def _hms(moment: datetime) -> str:
    return moment.strftime("%H:%M:%S.%f")[:-5]


# Drawing

STATUS_COLOURS = {"ok": "#3b7dd8", "late": "#e69f00", "dropped": "#d62728"}
PROMPT_COLOUR = "#7f7f7f"
CONTACT_COLOUR = "#444444"
BEADS_COLOUR = "#f2c14e"


def default_range(timeline: Timeline, totality_only: bool = True) -> Optional[tuple]:
    """The time range to show: around totality, or the whole script."""
    if totality_only and timeline.totality:
        c2, c3 = timeline.totality
        margin = timedelta(seconds=TOTALITY_MARGIN_S)
        return c2 - margin, c3 + margin
    times = [c.start for c in timeline.commands]
    ends = [c.replay.start + timedelta(seconds=c.replay.duration_s) for c in timeline.commands if c.replay]
    if not times:
        return None
    first, last = min(times), max(times + ends)
    margin = max(timedelta(seconds=10), (last - first) * 0.03)
    return first - margin, last + margin


def draw_timeline(figure, timeline: Timeline, totality_only: bool = True) -> list:
    """Draw the timeline on a matplotlib figure.

    Returns: (artist, command) for every bar and marker, to find the command under the mouse.
    """
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D

    figure.clear()
    ax = figure.add_subplot(111)
    rows = timeline.cameras
    if any(c.camera is None for c in timeline.commands):
        rows = rows + [ROW_PROMPTS]
    y_of = {row: len(rows) - 1 - i for i, row in enumerate(rows)}
    artists = []

    def x(moment):
        return mdates.date2num(moment)

    one_second = 1.0 / 86400
    for command in timeline.commands:
        if command.camera is None:
            y = y_of[ROW_PROMPTS]
            (marker,) = ax.plot([x(command.start)], [y], marker="|", markersize=16, color=PROMPT_COLOUR,
                                linestyle="none")
            artists.append((marker, command))
            continue
        y = y_of[command.camera]
        replay = command.replay
        if replay is None:
            (marker,) = ax.plot([x(command.start)], [y], marker="|", markersize=16, color=CONTACT_COLOUR,
                                linestyle="none")
            artists.append((marker, command))
            continue
        colour = STATUS_COLOURS[command.status]
        if replay.dropped:
            (marker,) = ax.plot([x(command.start)], [y], marker="X", markersize=10, color=colour,
                                linestyle="none", zorder=4)
            artists.append((marker, command))
            continue
        bar = ax.broken_barh([(x(replay.start), replay.duration_s * one_second)], (y - 0.3, 0.6),
                             facecolors=colour, edgecolors="white", linewidth=0.5, alpha=0.9, zorder=3)
        artists.append((bar, command))
        if command.status == "late":
            # From the planned start to when the camera is free
            ax.plot([x(command.start), x(replay.start)], [y + 0.36, y + 0.36], color=colour, linewidth=2)

    # The Baily's beads windows, then the contacts
    for contact in ("C2", "C3"):
        start = timeline.reference_moments.get(f"BEADS_{contact}_START")
        end = timeline.reference_moments.get(f"BEADS_{contact}_END")
        if start is not None and end is not None:
            ax.axvspan(x(start), x(end), color=BEADS_COLOUR, alpha=0.35, zorder=1)
    for name, label in CONTACTS:
        moment = timeline.reference_moments.get(name)
        if moment is None:
            continue
        ax.axvline(x(moment), color=CONTACT_COLOUR, linestyle="--", linewidth=1, zorder=2)
        ax.annotate(label, (x(moment), 1.0), xycoords=("data", "axes fraction"), xytext=(2, -12),
                    textcoords="offset points", fontsize=8, color=CONTACT_COLOUR, clip_on=True)

    ax.set_yticks(list(y_of.values()), list(y_of.keys()))
    ax.set_ylim(-0.7, len(rows) - 0.3)
    span = default_range(timeline, totality_only)
    if span is not None:
        ax.set_xlim(x(span[0]), x(span[1]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.set_xlabel("UTC")
    ax.grid(axis="x", alpha=0.3)

    legend = [Patch(color=STATUS_COLOURS["ok"], label="busy"),
              Patch(color=STATUS_COLOURS["late"], label="starts late"),
              Line2D([], [], marker="X", color=STATUS_COLOURS["dropped"], linestyle="none", label="dropped")]
    if any(f"BEADS_{c}_START" in timeline.reference_moments for c in ("C2", "C3")):
        legend.append(Patch(color=BEADS_COLOUR, alpha=0.35, label="Baily's beads"))
    ax.legend(handles=legend, loc="upper right", fontsize=8, framealpha=0.8)
    figure.autofmt_xdate()
    figure.tight_layout()
    return artists


def command_at(artists: list, event) -> Optional[TimelineCommand]:
    """The command drawn under a matplotlib mouse event, if any."""
    for artist, command in artists:
        contains, _ = artist.contains(event)
        if contains:
            return command
    return None


def describe(timeline: Timeline, command: TimelineCommand) -> str:
    """One line about a command, for the hover text."""
    text = (f"{command.camera or ''}{': ' if command.camera else ''}{command.func_name} \"{command.description}\" "
            f"at {_hms(command.start)} UTC ({command.reference}; {timeline.relative(command.start)})")
    replay = command.replay
    if replay is not None:
        if replay.dropped:
            blocker = replay.blocked_by.description if replay.blocked_by else "?"
            text += f" — dropped: the camera is still busy with \"{blocker}\" for {replay.wait_s:.1f} s"
        else:
            text += f" — busy about {replay.duration_s:.1f} s"
            if replay.wait_s > 0.05:
                text += f", starts {replay.wait_s:.1f} s late"
    return text
