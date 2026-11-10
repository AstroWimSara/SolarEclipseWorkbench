"""The script timeline lays a script out per camera with the same estimates as the load-time check."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytz
from matplotlib.figure import Figure

from solareclipseworkbench.command_timing import BURST_LEAD_S, NIKON_BURST_FPS, burst_lead_s, hdr_shot_overhead_s
from solareclipseworkbench.script_timeline import (FrameCount, TimelineCommand, build_timeline, busy_fraction,
                                                   command_at, command_frames, count_frames, describe, draw_timeline,
                                                   format_timeline, merged_intervals)
from solareclipseworkbench.utils import (RELAY_BUSY_NAME, CameraBusyWindow, ReplayedWindow, find_camera_conflicts,
                                         replay_camera_windows)

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


def _args(extra=None, shutter="1/100"):
    return ["Camera", shutter, "8", "200"] + ([extra] if extra is not None else [])


def test_frames_of_a_picture_a_bracket_and_an_hdr():
    assert command_frames("take_picture", _args(), "Sony").offsets_s == (0.0,)
    # 5 frames 1 EV apart, darkest first, each one starting as the one before it ends
    bracket = command_frames("take_bracket", _args('"1 5"', "1/4"), "Sony").offsets_s
    assert bracket == (0.0, 1 / 16, 1 / 16 + 1 / 8, 1 / 16 + 1 / 8 + 1 / 4, 1 / 16 + 1 / 8 + 1 / 4 + 1 / 2)
    assert len(command_frames("take_bracket", _args('"not a bracket"'), "Sony").offsets_s) == 1
    # 2 stops up and back down: 1/100, 1/50, 1/25, 1/50, 1/100
    hdr = command_frames("take_hdr", _args("2"), "Sony").offsets_s
    assert len(hdr) == 5 and abs(hdr[1] - (0.01 + hdr_shot_overhead_s())) < 1e-9
    assert command_frames("relay_shoot", [], None).offsets_s == (0.0,)
    assert command_frames("prepare_camera", _args('"burst"'), "Sony").offsets_s == ()


def test_frames_of_a_burst():
    # A Nikon burst is a number of frames, taken at the frame rate of the estimates
    nikon = command_frames("take_burst", _args("20"), "Nikon").offsets_s
    assert len(nikon) == 20
    assert nikon[0] == BURST_LEAD_S and abs(nikon[-1] - (BURST_LEAD_S + 19 / NIKON_BURST_FPS)) < 1e-9
    # Other bursts are a time: the number of frames is not known, only when the shutter is held
    other = command_frames("take_burst", _args("2"), "Sony")
    lead_s = burst_lead_s("Sony")
    assert other.offsets_s is None and other.shooting_s == (lead_s, lead_s + 2)
    relay = command_frames("relay_burst", ["4.5"], None)
    assert relay.offsets_s is None and relay.shooting_s[1] >= 4.5
    assert command_frames("relay_burst", ["long"], None).offsets_s == ()


def test_frames_between_c2_and_c3(tmp_path):
    script = tmp_path / "nikon.txt"
    script.write_text('take_burst, C2, -, 0:00:02.0, Nikon Z 8, 1/2000, 8, 200, 30, "Beads"\n'
                      'take_picture, C2, +, 0:00:01.0, Nikon Z 8, 1/1000, 8, 200, "Dropped"\n'
                      'take_picture, C2, +, 0:00:10.0, Nikon Z 8, 1/2, 8, 200, "Corona"\n'
                      'take_picture, C3, +, 0:00:20.0, Nikon Z 8, 1/1000, 8, 200, "Partial"\n')
    timeline = build_timeline(str(script), _moments())
    commands = timeline.camera_commands()
    assert [c.description for c in timeline.dropped] == ["Dropped"]
    # 30 + corona + partial; the dropped picture takes no frame
    assert count_frames(commands) == FrameCount(32)
    # The burst shoots from C2-1 s at 10 fps: 20 of its frames are after C2, plus the corona
    assert count_frames(commands, C2, C3) == FrameCount(21)


def test_burst_of_unknown_frames_between_c2_and_c3(tmp_path):
    timeline = _timeline(tmp_path)
    commands = timeline.camera_commands("Canon EOS R")
    assert count_frames(commands) == FrameCount(3, unknown=1)
    # The diamond ring burst shoots from C2-5 s to C2-3 s: it is busy, but takes no frame, after C2
    assert count_frames(commands, C2, C3) == FrameCount(3)


def test_merged_intervals():
    assert merged_intervals([(5, 8), (0, 2), (1, 3), (8, 9)]) == [(0, 3), (5, 9)]


def _busy(camera, start_s, duration_s, dropped=False):
    window = CameraBusyWindow(camera, C2 + timedelta(seconds=start_s), duration_s, "")
    replay = ReplayedWindow(window, window.start, 0.0 if dropped else duration_s, dropped=dropped)
    return TimelineCommand("take_picture", camera, window.start, "", "", replay)


def test_busy_fraction_counts_overlapping_commands_once():
    commands = [_busy("A", -5, 10), _busy("B", 2, 10), _busy("A", 50, 4), _busy("A", 60, 4, dropped=True),
                _busy("B", 100, 10)]
    # C2-C2+12 (A and B overlap), 50-54 and C3-4 s to C3: 20 s of the 104 s
    assert abs(busy_fraction(commands, C2, C3) - 20 / 104) < 1e-9
    assert abs(busy_fraction(commands[:1], C2, C3) - 5 / 104) < 1e-9


def test_text_gives_the_frames_and_the_busy_time(tmp_path):
    text = format_timeline(_timeline(tmp_path))
    assert ("All cameras: 4 + unknown frame(s), 3 between C2 and C3; at least one camera busy 9 % of C2 to C3; "
            "the frames of 1 burst(s) are unknown") in text
    assert "Canon EOS R\n-----------\n3 + unknown frame(s), 3 between C2 and C3; busy 9 % of C2 to C3" in text
    assert "Sony A7\n-------\n1 frame(s), 0 between C2 and C3; busy 1 % of C2 to C3\n" in text
