"""Hardening of the imaging slice: sorting images, map tiles, live frames, the sun finder."""

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from solareclipseworkbench import image_sorter as sorter
from solareclipseworkbench import run_report
from solareclipseworkbench.live_frames import LiveFrames
from solareclipseworkbench.sun_finder import find_sun

CAMERA = "Canon EOS R"
C2 = datetime(2026, 8, 12, 18, 29, 22, tzinfo=timezone.utc)


def _plan(tmp_path, names):
    """A run with one take_picture at C2+10 s and images all taken then; returns (plan, card folder)."""
    planned = C2 + timedelta(seconds=10)
    start = C2 - timedelta(hours=1)

    def line(moment, message):
        return f"{moment.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z INFO     [MainThread] root: {message}"

    when = planned.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    lines = [line(start, "Starting observation with script /tmp/eclipse.txt"),
             line(start, f"Reference moment C2: {C2.strftime('%Y-%m-%d %H:%M:%S.%f')[:-5]} UTC"),
             line(start, f"Cameras: {CAMERA}"),
             line(start, f"Planned: take_picture | {CAMERA} | {when} UTC | C2+00:00:10.0 | busy 5.0 s | corona")]
    run = run_report.parse_log(lines)[-1]
    card = tmp_path / "card"
    card.mkdir()
    images = []
    for name in names:
        (card / name).write_bytes(b"image " + name.encode())
        images.append(sorter.ImageInfo(card / name, planned.replace(tzinfo=None), True, "Canon", CAMERA))
    return sorter.plan_sorting(run, images, clock_offset_s=0.0), card


def test_one_failing_image_does_not_stop_the_sort(tmp_path, monkeypatch):
    plan, card = _plan(tmp_path, ["IMG_1.JPG", "IMG_2.JPG", "IMG_3.JPG"])
    real_copy = shutil.copy2

    def copy2(source, target):
        if Path(source).name == "IMG_2.JPG":
            # Half written, then the card fails
            Path(target).write_bytes(b"ima")
            raise OSError(5, "Input/output error")
        return real_copy(source, target)

    monkeypatch.setattr(sorter.shutil, "copy2", copy2)
    out = tmp_path / "sorted"
    manifest = sorter.apply_plan(plan, out)

    copied = sorted(p.name for p in out.rglob("*.JPG"))
    assert len(copied) == 2 and not any("IMG_2" in name for name in copied)   # no half copy left
    assert (card / "IMG_2.JPG").read_bytes() == b"image IMG_2.JPG"            # the original untouched
    assert "IMG_2.JPG" in manifest.read_text() and "Input/output error" in manifest.read_text()
    assert any("could not be copied" in warning for warning in plan.warnings)


def test_a_move_from_a_write_protected_card_keeps_the_copy(tmp_path, monkeypatch):
    plan, card = _plan(tmp_path, ["IMG_1.JPG"])

    def move(source, target):
        shutil.copy2(source, target)
        raise PermissionError(13, "Read-only file system")

    monkeypatch.setattr(sorter.shutil, "move", move)
    out = tmp_path / "sorted"
    manifest = sorter.apply_plan(plan, out, mode="move")
    assert (card / "IMG_1.JPG").exists()
    assert [p.read_bytes() for p in out.rglob("*.JPG")] == [b"image IMG_1.JPG"]
    assert "the original could not be removed" in manifest.read_text()


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_a_dangling_link_of_an_earlier_sort_is_not_written_through(tmp_path):
    plan, card = _plan(tmp_path, ["IMG_1.JPG"])
    out = tmp_path / "sorted"
    destination = out / plan.placements[0].destination
    destination.parent.mkdir(parents=True)
    elsewhere = tmp_path / "moved_away.JPG"
    destination.symlink_to(elsewhere)          # an earlier --link sort whose original has gone

    sorter.apply_plan(plan, out)
    assert not elsewhere.exists()              # not created through the link
    assert destination.is_symlink()
    assert any(p.read_bytes() == b"image IMG_1.JPG" for p in out.rglob("*.JPG") if not p.is_symlink())


def test_live_frames_cleared_while_decoding_stay_cleared(monkeypatch):
    from PIL import Image
    import io

    frames = LiveFrames()
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, "JPEG")
    frames.push(buffer.getvalue())

    real_open = Image.open

    def open_and_close_the_live_view(*args, **kwargs):
        frames.clear()                         # the live view closes while the frame is decoded
        return real_open(*args, **kwargs)

    monkeypatch.setattr("solareclipseworkbench.live_frames.Image.open", open_and_close_the_live_view)
    assert frames.latest() is None
    assert frames.latest() is None


def test_find_sun_on_a_float_frame_with_nan_pixels():
    y, x = np.mgrid[:480, :640]
    frame = ((x - 320) ** 2 + (y - 240) ** 2 < 60 ** 2).astype(float) * 200
    frame[0, 0] = np.nan
    frame[1, 1] = np.inf
    fix = find_sun(frame)
    assert fix is not None and abs(fix.x - 320) < 1 and abs(fix.y - 240) < 1
    assert find_sun(np.full((100, 100), np.nan)) is None
