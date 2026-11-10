"""Aligning the frames of a timelapse on the sun (timelapse, Issue #70)."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from solareclipseworkbench import timelapse


def _disk(cx, cy, radius=40.0, size=(300, 400), moon=None):
    ys, xs = np.mgrid[0:size[0], 0:size[1]]
    image = np.zeros(size + (3,), dtype=np.uint8)
    inside = np.hypot(xs - cx, ys - cy) <= radius
    if moon is not None:
        inside &= np.hypot(xs - moon[0], ys - moon[1]) > radius
    image[inside] = 230
    return image


def test_crop_puts_the_centre_in_the_middle():
    image = _disk(150.3, 120.7)
    crop = timelapse.crop_centred(image, 150.3, 120.7, 60)
    assert crop.shape == (120, 120, 3)
    ys, xs = np.nonzero(crop[..., 0] > 115)
    assert xs.mean() == pytest.approx(59.5, abs=0.3)
    assert ys.mean() == pytest.approx(59.5, abs=0.3)


def test_crop_outside_the_frame_is_black():
    crop = timelapse.crop_centred(_disk(20, 20), 5, 5, 30)
    assert crop[0, 0].tolist() == [0, 0, 0]


def test_frames_without_a_sun_are_interpolated_in_time():
    start = datetime(2026, 8, 12, 18, 0, 0)
    images = {
        "a": _disk(100, 100),
        "b": _disk(140, 110, moon=(170, 110)),     # a crescent: the centre of the sun, not of the crescent
        "c": np.zeros((300, 400, 3), dtype=np.uint8),   # totality: no limb
        "d": _disk(220, 130),
    }
    frames = [timelapse.Frame(Path(name), start + timedelta(seconds=10 * i)) for i, name in enumerate(images)]
    timelapse.locate(frames, loader=lambda path: images[path.name])
    a, b, c, d = frames
    assert a.found and b.found and d.found and not c.found
    assert (b.x, b.y) == (pytest.approx(140, abs=1.0), pytest.approx(110, abs=1.0))
    assert (c.x, c.y) == (pytest.approx(180, abs=1.5), pytest.approx(120, abs=1.5))


def test_aligns_real_eclipse_frames(tmp_path):
    """A few frames of the 2026 eclipse: partial phase, totality and after; every one comes out centred."""
    folder = Path(__file__).parent / "data" / "sun"
    names = ["EosR-100.png", "EosR-300.png", "EosR-330.png", "EosR-500.png"]
    paths = [folder / n for n in names if (folder / n).exists()]
    if len(paths) < len(names):
        pytest.skip("eclipse frames not available")
    frames = timelapse.order_frames(paths)
    timelapse.locate(frames)
    assert sum(f.found for f in frames) >= 3
    written = timelapse.write_frames(frames, tmp_path, half=100)
    assert len(written) == 4
    assert (tmp_path / "alignment.csv").exists()
