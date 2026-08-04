"""The limb correction has to reduce correctly and scale correctly.

K2 turns out not to matter: it enters both the Sun's radius (K2 + L2') and the
true limb radius (K2 + height/R_earth), and cancels between them to first order.
Setting it to the IAU mean radius instead of Watts' datum changes no contact
time, which is why "use a more modern k2" is not a fix for anything.

What can break is arithmetic that K2 does not protect: a sign error would move
the contacts the wrong way, and a metres-for-kilometres slip would move them by
a factor of a thousand.  Both are silent -- the answer stays plausible.  So one
test pins the reduction (no relief, no correction) and one pins the scale (a
kilometre of relief is about a second).
"""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from solareclipseworkbench.limb_correction import (
    contact_position_angle, solve_limb_contact, solve_point_contact,
)
from solareclipseworkbench.solar_eclipse import get_element_coeffs, get_elements

# Longyearbyen, TSE 2015 Mar 20 -- any total eclipse would do.
DATE = "2015-03-20"
LATITUDE = 78 + 13.328 / 60
LONGITUDE = -(15 + 39.028 / 60)      # the solver takes west longitude as positive
ELEVATION = 6.1
GOLDEN_PROFILE = Path(__file__).parent / "fixtures" / "longyearbyen_lola_profile.json"


@pytest.fixture(scope="module")
def contacts():
    elements = get_element_coeffs(DATE)

    def evaluate(when):
        return get_elements(elements, when, LATITUDE, LONGITUDE, ELEVATION)

    maximum = 0.0
    for _ in range(30):
        o = evaluate(maximum)
        maximum += -(o["u"] * o["a"] + o["v"] * o["b"]) / (o["n"] * o["n"])

    o = evaluate(maximum)
    s = (o["a"] * o["v"] - o["u"] * o["b"]) / (o["n"] * o["L2p"])
    half = o["L2p"] / o["n"] * math.sqrt(max(0.0, 1 - s * s))

    def refine(start, sign):
        contact = start
        for _ in range(20):
            o = evaluate(contact)
            s = (o["a"] * o["v"] - o["u"] * o["b"]) / (o["n"] * o["L2p"])
            step = (-(o["u"] * o["a"] + o["v"] * o["b"]) / (o["n"] * o["n"])
                    + sign * o["L2p"] / o["n"] * math.sqrt(max(0.0, 1 - s * s)))
            contact += step
            if abs(step) < 1e-12:
                break
        return contact

    return elements, evaluate, refine(maximum + half, +1), refine(maximum - half, -1)


def _shift_seconds(contacts, entering, relief_km):
    elements, evaluate, c2, c3 = contacts
    start = c2 if entering else c3
    angles = np.arange(0.0, 360.0, 0.05)
    heights = np.full_like(angles, relief_km)
    solved = solve_limb_contact(elements, evaluate, start, entering, angles, heights)
    return (solved - start) * 3600.0


@pytest.mark.parametrize("name,entering", [("C2", True), ("C3", False)])
def test_a_smooth_limb_moves_no_contact(contacts, name, entering):
    """No relief, no correction: the machinery has to reduce to the mean limb."""
    shift = _shift_seconds(contacts, entering, 0.0)
    assert abs(shift) < 0.001, f"{name} moved by {shift:+.3f} s on a limb with no relief"


@pytest.mark.parametrize("name,entering,sign", [("C2", True, +1.0), ("C3", False, -1.0)])
def test_a_kilometre_of_relief_is_about_a_second(contacts, name, entering, sign):
    """A uniformly higher limb is a bigger Moon: C2 earlier, C3 later.

    A bigger Moon covers the Sun sooner and uncovers it later, so totality both
    starts earlier and ends later, and a kilometre of relief is worth roughly a
    second at the rate the two limbs close.
    """
    shift = _shift_seconds(contacts, entering, 1.0)

    assert shift * sign < 0.0, (
        f"{name} moved {shift:+.2f} s for a limb raised 1 km; a higher limb has "
        f"to lengthen totality, so the sign is wrong")
    assert 0.5 < abs(shift) < 2.0, (
        f"{name} moved {shift:+.2f} s for 1 km of relief, expected about 1 s. "
        f"A factor of a thousand here means metres have been used as kilometres.")


@pytest.fixture(scope="module")
def golden_profile():
    """A compact real LOLA profile slice; no 72 MB blob is needed in CI."""
    with GOLDEN_PROFILE.open(encoding="utf-8") as fixture:
        return json.load(fixture)


@pytest.mark.parametrize("name", ["C2", "C3"])
def test_real_lola_profile_pins_point_and_arc_conventions(golden_profile, name):
    elements = golden_profile["elements"]
    site = golden_profile["site"]
    contact = golden_profile["contacts"][name]

    def evaluate(when):
        return get_elements(
            elements, when, site["latitude_deg"], -site["longitude_deg"],
            site["elevation_m"],
        )

    mean_contact = contact["mean_contact_tt_offset_hours"]
    position_angle = contact_position_angle(evaluate(mean_contact))
    assert position_angle == pytest.approx(contact["position_angle_deg"], abs=1e-9)

    relative = (golden_profile["fixture_relative_start_deg"]
                + np.arange(golden_profile["fixture_sample_count"])
                * golden_profile["fixture_relative_step_deg"])
    angles = (position_angle + relative) % 360.0
    heights = np.asarray(contact["heights_km"], dtype=np.float64)

    def height_at(angle):
        return float(np.interp(angle % 360.0, angles, heights, period=360.0))

    point = solve_point_contact(
        elements, evaluate, mean_contact, contact["entering"], height_at)
    arc = solve_limb_contact(
        elements, evaluate, mean_contact, contact["entering"], angles, heights)

    assert (point - mean_contact) * 3600.0 == pytest.approx(
        contact["expected_point_shift_seconds"], abs=0.001)
    assert (arc - mean_contact) * 3600.0 == pytest.approx(
        contact["expected_fixture_arc_shift_seconds"], abs=0.001)
