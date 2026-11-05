"""The sun finder on real frames of the total solar eclipse of 2026-08-12 (tests/data/sun_frames).

Every phase is there: the filtered partial phases, the last crescents before C2
(1-2 pixels wide), the beads and the diamond ring without a filter, totality,
the crescents after C3, a red sun with a ghost edge near sunset, an overexposed
sun in a pink sky and a landscape.  The expected centres were found on the
lossless frames and checked by eye; where the manifest has no sun, none may be
found: no answer is fine, a wrong one is not.
"""
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from solareclipseworkbench.sun_finder import find_sun

DATA = Path(__file__).parent / "data" / "sun_frames"
MANIFEST = json.loads((DATA / "frames.json").read_text())
FRAMES = MANIFEST["frames"]
RADIUS = MANIFEST["radius"]


def load(entry) -> np.ndarray:
    return np.asarray(Image.open(DATA / entry["file"]).convert("RGB"))


def ids(entry) -> str:
    return f'{entry["file"][:-4]} ({entry["note"]})'


@pytest.mark.parametrize("entry", FRAMES, ids=ids)
def test_with_the_radius_known(entry):
    """How the centring uses it: the radius is known from the frames before."""
    fix = find_sun(load(entry), radius_hint=RADIUS)
    if entry["sun"] is None:
        assert fix is None, f"found a sun at {fix.x:.1f}, {fix.y:.1f} where there is none"
    else:
        x, y, radius = entry["sun"]
        assert fix is not None, "the sun was not found"
        assert math.hypot(fix.x - x, fix.y - y) < 0.75, (fix.x, fix.y)
        assert fix.radius == pytest.approx(radius, rel=0.02)


@pytest.mark.parametrize("entry", FRAMES, ids=ids)
def test_without_the_radius_never_wrong(entry):
    """The first frames of a run: no radius known yet.  Fewer frames are found, but none wrongly.

    A little less precise: on a short arc the radius and the centre trade off when
    the radius is free (0.8 px on the 140° arc two minutes before C2).
    """
    fix = find_sun(load(entry))
    if fix is None:
        return
    assert entry["sun"] is not None, f"found a sun at {fix.x:.1f}, {fix.y:.1f} where there is none"
    x, y, _ = entry["sun"]
    assert math.hypot(fix.x - x, fix.y - y) < 1.5, (fix.x, fix.y)


@pytest.mark.parametrize("name", ["eclipse2026_001.jpg", "eclipse2026_100.jpg", "eclipse2026_200.jpg",
                                  "eclipse2026_560.jpg"])
def test_broad_phases_need_no_radius(name):
    entry = next(e for e in FRAMES if e["file"] == name)
    fix = find_sun(load(entry))
    assert fix is not None
    assert fix.radius == pytest.approx(RADIUS, rel=0.03)


def test_the_last_crescent_before_c2_is_found_up_to_the_pause():
    """The centring pauses 15 s before C2: the crescent 17 s before C2 must still be found."""
    entry = next(e for e in FRAMES if e["file"] == "eclipse2026_327.jpg")
    assert find_sun(load(entry), radius_hint=RADIUS) is not None
