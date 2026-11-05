"""The script timeline lays a script out per camera with the same estimates as the load-time check."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytz
from matplotlib.figure import Figure

from solareclipseworkbench.script_timeline import build_timeline, command_at, describe, draw_timeline, format_timeline
from solareclipseworkbench.utils import RELAY_BUSY_NAME, CameraBusyWindow, find_camera_conflicts, replay_camera_windows

C2 = datetime(2026, 8, 12, 18, 28, 25, 600000, tzinfo=pytz.utc)
C3 = C2 + timedelta(seconds=104)


def _moments():
    moments = {"C1": C2 - timedelta(minutes=55), "C2": C2, "MAX": C2 + timedelta(seconds=52), "C3": C3,
               "C4": C3 + timedelta(minutes=51), "BEADS_C2_START": C2 - timedelta(seconds=0.4),
               "BEADS_C2_END": C2 + timedelta(seconds=1.6)}
    info = {name: SimpleNamespace(time_utc=moment) for name, moment in moments.items()}
    info["duration"] = timedelta(seconds=104)   # not a moment: ignored
    return info


SCRIPT = """\
# A comment
voice_prompt, C2, -, 0:00:20.0, C2_IN_20_SECONDS, "C2 in 20 s"
take_burst, C2, -, 0:00:06.0, Canon EOS R, 1/2000, 8, 200, 2, "Diamond ring"
take_picture, C2, -, 0:00:01.0, Canon EOS R, 1/1000, 8, 200, "Too close"
take_picture, C2, -, 0:00:01.0, Sony A7, 1/1000, 8, 200, "Other camera"
take_picture, C2, +, 0:00:04.0, Canon EOS R, 1/2, 8, 200, "Corona 1"
take_picture, C2, +, 0:00:05.0, Canon EOS R, 1/2, 8, 200, "Corona 2"
take_picture, LAST, +, 0:00:10.0, Canon EOS R, 1/2, 8, 200, "After the last"
take_picture, BEADS_C9, +, 0:00:04.0, Canon EOS R, 1/2, 8, 200, "Bad reference"
"""


def _timeline(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text(SCRIPT)
    return build_timeline(str(script), _moments())


def test_dropped_late_and_unknown(tmp_path):
    timeline = _timeline(tmp_path)
    assert [c.description for c in timeline.dropped] == ["Too close"]
    assert [c.description for c in timeline.late] == ["Corona 2"]
    assert timeline.unknown_moments == {"BEADS_C9": 1}
    assert timeline.cameras == ["Canon EOS R", "Sony A7"]
    other = next(c for c in timeline.commands if c.description == "Other camera")
    assert other.status == "ok"


def test_last_is_the_latest_command_so_far(tmp_path):
    timeline = _timeline(tmp_path)
    after = next(c for c in timeline.commands if c.description == "After the last")
    assert after.start == C2 + timedelta(seconds=15)


def test_prompts_have_no_camera(tmp_path):
    timeline = _timeline(tmp_path)
    prompt = timeline.commands[0]
    assert prompt.func_name == "voice_prompt" and prompt.camera is None and prompt.replay is None


def test_relative_to_the_nearest_contact(tmp_path):
    timeline = _timeline(tmp_path)
    assert timeline.relative(C2 - timedelta(seconds=6)) == "C2-6.0 s"
    assert timeline.relative(C3 + timedelta(minutes=20)) == "C3+20.0 min"


def test_relay_commands_share_one_row(tmp_path):
    script = tmp_path / "relay.txt"
    script.write_text('relay_burst, C2, -, 0:00:05.0, 4.5, "Diamond ring"\n'
                      'relay_shoot, C3, +, 0:00:10.0, "One frame"\n')
    timeline = build_timeline(str(script), _moments())
    assert timeline.cameras == [RELAY_BUSY_NAME]
    burst = next(c for c in timeline.commands if c.func_name == "relay_burst")
    assert burst.camera == RELAY_BUSY_NAME
    assert burst.replay is not None and burst.replay.window.duration_s >= 4.5


def test_mount_commands_have_no_camera(tmp_path):
    script = tmp_path / "mount.txt"
    script.write_text('mount_tracking, C1, -, 0:10:00.0, on, "Track"\n'
                      'mount_track_sun, C1, -, 0:05:00.0, "Solar rate"\n')
    timeline = build_timeline(str(script), _moments())
    assert timeline.cameras == []
    assert [c.camera for c in timeline.commands] == [None, None]


def test_replay_agrees_with_the_load_time_check():
    start = C2 - timedelta(seconds=10)
    windows = [CameraBusyWindow("Canon", start, 8.0, "burst", "burst"),
               CameraBusyWindow("Canon", start + timedelta(seconds=2), 2.0, "dropped", "single"),
               CameraBusyWindow("Canon", start + timedelta(seconds=7), 2.0, "late", "single"),
               CameraBusyWindow("Sony", start + timedelta(seconds=2), 2.0, "other", "single")]
    replayed = {r.window.description: r for r in replay_camera_windows(windows)}
    conflicts = {c.window.description: c for c in find_camera_conflicts(windows)}
    assert set(conflicts) == {"dropped", "late"}
    assert replayed["dropped"].dropped and conflicts["dropped"].dropped
    assert replayed["late"].wait_s == conflicts["late"].wait_s == 1.0
    assert replayed["late"].start == start + timedelta(seconds=8)
    assert replayed["other"].wait_s == 0 and replayed["other"].blocked_by is None


def test_text(tmp_path):
    text = format_timeline(_timeline(tmp_path))
    assert "Totality 104.0 s" in text
    assert 'DROPPED: Canon EOS R: "Too close"' in text and "Diamond ring" in text
    assert "LATE:    Canon EOS R: \"Corona 2\"" in text
    assert "BEADS_C9, which does not exist here" in text
    assert "1 voice prompt(s)" in text


def test_drawing_finds_the_command_under_the_mouse(tmp_path):
    timeline = _timeline(tmp_path)
    figure = Figure(figsize=(10, 3))
    artists = draw_timeline(figure, timeline)
    figure.canvas.draw()
    bar, command = next((a, c) for a, c in artists if c.description == "Diamond ring")
    x0, y0, width, height = bar.get_paths()[0].get_extents().bounds
    centre = bar.axes.transData.transform((x0 + width / 2, y0 + height / 2))
    event = SimpleNamespace(x=centre[0], y=centre[1], inaxes=bar.axes, canvas=figure.canvas)
    assert command_at(artists, event) is command
    assert "busy about" in describe(timeline, command)
