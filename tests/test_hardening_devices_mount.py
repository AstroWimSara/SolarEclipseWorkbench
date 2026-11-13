"""Regression tests for the hardening of the mount, INDI, bench console and timelapse modules."""
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from solareclipseworkbench import hardware_problems, indi_server, mount, timelapse
from solareclipseworkbench.hardware_console import Console
from solareclipseworkbench.indi_client import IndiClient
from solareclipseworkbench.indi_simulator import SimulatedIndiServer
from solareclipseworkbench.mount_ui import format_position


def test_format_position_nan_is_blank():
    """The INDI client keeps NaN for an unreadable number; round(NaN) raised on every refresh of the panel."""
    assert format_position((float("nan"), 10.0)) == ""
    assert format_position((12.5, 10.0)).startswith("RA 12h30m00s")


def test_mount_command_reports_unexpected_error(monkeypatch):
    reported = []
    monkeypatch.setattr(hardware_problems, "report", lambda *a, **k: reported.append(a))

    class _Odd:
        def track_solar(self):
            raise RuntimeError("driver bug")

    mount.mount_track(_Odd())       # must not raise
    assert reported and "driver bug" in reported[0][1]


def test_nudger_survives_unexpected_error(monkeypatch):
    monkeypatch.setattr(hardware_problems, "report", lambda *a, **k: None)
    calls = []

    class _FakeMount:
        device = "fake"
        reverse_ns = reverse_we = False

        def nudge_start(self, direction):
            calls.append(direction)
            raise RuntimeError("bug")

        def nudge_stop(self, direction):
            pass

    nudger = mount.Nudger(_FakeMount())
    try:
        nudger.hold("N")
        deadline = time.monotonic() + 2
        while not calls and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        assert nudger._thread.is_alive()
        assert "bug" in nudger.last_error
        nudger.hold("E")
        deadline = time.monotonic() + 2
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert calls == ["N", "E"]
    finally:
        nudger.stop()


def test_indi_reader_bug_marks_client_lost(monkeypatch):
    """A dead reader thread left a client that looked connected, so every change waited for its timeout."""
    server = SimulatedIndiServer()
    monkeypatch.setattr(IndiClient, "_handle", lambda self, element: (_ for _ in ()).throw(RuntimeError("bad")))
    client = IndiClient("127.0.0.1", server.port)
    try:
        deadline = time.monotonic() + 3
        while client.connected and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not client.connected
    finally:
        client.close()
        server.close()


def test_indi_server_unwritable_log_dir_raises_indi_server_error(tmp_path):
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    server = indi_server.IndiServer("/bin/true", port=1, server="/bin/true", log_dir=not_a_dir / "logs")
    with pytest.raises(indi_server.IndiServerError):
        server.start()


def test_console_keeps_running_on_unexpected_error(monkeypatch):
    console = Console(simulate=True)
    monkeypatch.setattr(console, "cmd_scan", lambda args: (_ for _ in ()).throw(OSError("port gone")), raising=False)
    monkeypatch.setattr(console, "out", lambda message="": None)
    assert console.dispatch("scan") is True


# ---------------------------------------------------------------- timelapse

def test_write_frames_skips_unreadable_interpolated_frame(tmp_path):
    """A frame that could not be read got a centre from _fill_gaps, then write_frames raised on it."""
    image = np.full((20, 20, 3), 100, dtype=np.uint8)
    frames = [timelapse.Frame(Path(f"f{i}.png"), None, x=10.0, y=10.0, radius=3.0, found=i != 1) for i in range(3)]

    def loader(path):
        if path.name == "f1.png":
            raise OSError("truncated file")
        return image

    written = timelapse.write_frames(frames, tmp_path, half=4, loader=loader)
    assert [p.name for p in written] == ["frame_00001.png", "frame_00002.png"]
    csv_text = (tmp_path / "alignment.csv").read_text()
    assert "not readable" in csv_text


def test_align_folder_keeps_frames_when_ffmpeg_fails(tmp_path, monkeypatch):
    frame = timelapse.Frame(tmp_path / "a.png", None, x=1.0, y=1.0, radius=2.0, found=True)
    monkeypatch.setattr(timelapse, "find_images", lambda folder, recursive=True: [frame.path])
    monkeypatch.setattr(timelapse, "order_frames", lambda paths: [frame])
    monkeypatch.setattr(timelapse, "locate", lambda frames, progress=None: None)
    monkeypatch.setattr(timelapse, "write_frames", lambda *a, **k: [tmp_path / "out" / "frame_00001.png"])

    def failing(*a, **k):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(timelapse, "make_video", failing)
    lines = []
    written = timelapse.align_folder(tmp_path, tmp_path / "out", video=tmp_path / "v.mp4", report=lines.append)
    assert len(written) == 1
    assert any("ffmpeg could not make the video" in line for line in lines)
