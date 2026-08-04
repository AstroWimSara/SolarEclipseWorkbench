"""Validate the limb correction against Jubier's published figures.

Reference case, from the Solar Eclipse Maestro limb profile for the total solar
eclipse of 2015 Mar 20 at Longyearbyen (Svalbard):

    libration    l = +0.88 deg, b = -0.26 deg, c = 335.08 deg
    ratio        Moon/Sun diameter 1.0431
    uncorrected  C2 10:10:43.9  C3 10:13:11.5   duration 2m27.5s
    corrected    C2' +0.4 s     C3' -2.8 s      duration 2m24.4s

Usage:
    python tools/validate_limb_correction.py
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from skyfield.api import load

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solareclipseworkbench import besselian_element_generator  # noqa: E402
from solareclipseworkbench.limb_correction import (  # noqa: E402
    K2, EARTH_RADIUS_KM, LunarLimb, bead_window, beads, contact_position_angle,
    solve_limb_contact, solve_point_contact)
from solareclipseworkbench.solar_eclipse import get_element_coeffs, get_elements  # noqa: E402


CASES = {
    # Solar Eclipse Maestro limb profile, LRO/Kaguya.
    "svalbard2015": {
        "date": "2015-03-20",
        "latitude": 78 + 13.328 / 60,
        "longitude": 15 + 39.028 / 60,
        "elevation": 6.1,
        "c2": 10 + 10 / 60 + 43.9 / 3600,
        "c3": 10 + 13 / 60 + 11.5 / 3600,
        "c2_correction": +0.4,
        "c3_correction": -2.8,
        # Maestro prints the corrected contacts and the bead spread separately
        # ("Baily's Beads: +/-3.0s"), so its correction is the contact-point one.
        "convention": "point",
        "tolerance": 0.5,
        "source": "Jubier, Solar Eclipse Maestro (LRO/Kaguya)",
    },
    # NASA/TP-1999-209484, worked example for Lusaka.  Watts-based, but the
    # publication states the result is within 0.2 s of a rigorous calculation
    # from the actual limb profile.  Coordinates are NASA's city database entry.
    "lusaka2001": {
        "date": "2001-06-21",
        "latitude": -(15 + 25 / 60),
        "longitude": 28 + 17 / 60,
        "elevation": 1277.0,
        "c2": 13 + 9 / 60 + 19.3 / 3600,
        "c3": 13 + 12 / 60 + 32.8 / 3600,
        "c2_correction": +4.0,
        "c3_correction": -1.2,
        "position_angles": (118.0, 247.0),
        # RP-1301: the contact is set by "a high mountain (annular) or a low
        # valley (total) in the vicinity", which is the whole-arc convention.
        "convention": "arc",
        # Looser, because this is Watts data rather than LRO/Kaguya: a different
        # profile with its own half-kilometre errors, and half a kilometre is
        # half a second here.
        "tolerance": 2.0,
        "source": "NASA/TP-1999-209484 table 15 and figure 8 (Watts)",
    },
}


def hms(hours):
    hours %= 24
    h = int(hours)
    m = int((hours - h) * 60)
    s = (hours - h - m / 60) * 3600
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def solve_internal_contact(elements, start, latitude, longitude, height, sign, umbral_radius=None):
    """Newton-iterate an internal contact, optionally with a corrected L2'.

    sign is -1 for third contact and +1 for second contact, matching the
    existing solver in solar_eclipse.get_local_circumstances.
    """
    contact = start
    for _ in range(20):
        o = get_elements(elements, contact, latitude, longitude, height)
        l2 = o["L2p"] if umbral_radius is None else umbral_radius(o, contact)
        s = (o["a"] * o["v"] - o["u"] * o["b"]) / (o["n"] * l2)
        step = (-(o["u"] * o["a"] + o["v"] * o["b"]) / (o["n"] * o["n"])
                + sign * l2 / o["n"] * math.sqrt(max(0.0, 1 - s * s)))
        contact += step
        if abs(step) < 1e-12:
            break
    return contact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(CASES), default="svalbard2015",
                        help="which published reference case to check against")
    parser.add_argument("--solar-radius-arcsec", type=float, default=None,
                        help="override the solar radius at 1 au; Solar Eclipse Maestro "
                             "defaults to the standard 959.63, ours is 959.94")
    options = parser.parse_args()

    if options.solar_radius_arcsec is not None:
        astronomical_unit_m = 149597870700.0
        besselian_element_generator.solar_radius = (
            astronomical_unit_m * math.tan(math.radians(options.solar_radius_arcsec / 3600.0)))
        print(f"solar radius overridden to {options.solar_radius_arcsec:.2f} arcsec\n")

    case = CASES[options.case]
    site_lat, site_lon = case["latitude"], case["longitude"]
    reference = case
    eclipse_date = case["date"]
    print(f"case {options.case}: {case['source']}")

    # The solver takes west longitude as positive.
    latitude, longitude, height = site_lat, -site_lon, case["elevation"]
    elements = get_element_coeffs(eclipse_date)

    # Maximum eclipse, then the uncorrected internal contacts, using the same
    # geometry the application already uses.
    t = 0.0
    for _ in range(30):
        o = get_elements(elements, t, latitude, longitude, height)
        step = -(o["u"] * o["a"] + o["v"] * o["b"]) / (o["n"] * o["n"])
        t += step

    o = get_elements(elements, t, latitude, longitude, height)
    s = (o["a"] * o["v"] - o["u"] * o["b"]) / (o["n"] * o["L2p"])
    tau = o["L2p"] / o["n"] * math.sqrt(max(0.0, 1 - s * s))

    c3 = solve_internal_contact(elements, t - tau, latitude, longitude, height, -1)
    c2 = solve_internal_contact(elements, t + tau, latitude, longitude, height, +1)

    delta_t_hours = elements["Δt"] / 3600.0
    ut_c2 = elements["T0"] + c2 - delta_t_hours
    ut_c3 = elements["T0"] + c3 - delta_t_hours
    ut_max = elements["T0"] + t - delta_t_hours

    print(f"uncorrected  C2 {hms(ut_c2)}  C3 {hms(ut_c3)}  "
          f"duration {(ut_c3 - ut_c2) * 3600:6.1f}s")
    print(f"  reference C2 {hms(reference['c2'])}  C3 {hms(reference['c3'])}  "
          f"duration {(reference['c3'] - reference['c2']) * 3600:6.1f}s")
    print(f"     offset  C2 {(ut_c2 - reference['c2']) * 3600:+.2f}s  "
          f"C3 {(ut_c3 - reference['c3']) * 3600:+.2f}s")

    limb = LunarLimb()

    # The profile is evaluated once, at maximum eclipse, the way Jubier does.
    ts = load.timescale()
    year, month, day = (int(part) for part in eclipse_date.split("-"))
    moment = ts.ut1(year, month, day, 0, 0, ut_max * 3600.0)

    angles = np.arange(0.0, 360.0, 0.01)
    heights_km = limb.height_above_k2(moment, site_lat, site_lon, case["elevation"], angles)
    print(f"\nlimb heights vs k2 ({K2 * EARTH_RADIUS_KM:.3f} km): "
          f"{heights_km.min():+.3f} .. {heights_km.max():+.3f} km, "
          f"mean {heights_km.mean():+.3f} km")

    o2 = get_elements(elements, c2, latitude, longitude, height)
    o3 = get_elements(elements, c3, latitude, longitude, height)
    print(f"contact position angles: C2 {contact_position_angle(o2):.2f} deg, "
          f"C3 {contact_position_angle(o3):.2f} deg")

    def evaluate(when):
        return get_elements(elements, when, latitude, longitude, height)

    # At the contact point, as the shipped code does it.
    def limb_height_at(angle):
        return float(np.interp(angle % 360.0, angles, heights_km))

    point_c2 = solve_point_contact(elements, evaluate, c2, True, limb_height_at)
    point_c3 = solve_point_contact(elements, evaluate, c3, False, limb_height_at)

    c2_corrected = solve_limb_contact(elements, evaluate, c2, True, angles, heights_km)
    c3_corrected = solve_limb_contact(elements, evaluate, c3, False, angles, heights_km)

    c2_shift = (c2_corrected - c2) * 3600.0
    c3_shift = (c3_corrected - c3) * 3600.0

    for label, when in (("C2", c2_corrected), ("C3", c3_corrected)):
        for offset in (-1.0, 1.0):
            lit = beads(evaluate(when + offset / 3600.0), angles, heights_km)
            spans = ", ".join(f"{a:.1f}-{b:.1f}" for a, b in lit[:4])
            print(f"beads {offset:+.0f}s around {label}: {len(lit)} at {spans or 'none'} deg")

    for label, when, entering in (("C2", c2_corrected, True), ("C3", c3_corrected, False)):
        start, end = bead_window(evaluate, when, entering, angles, heights_km)
        centre = 0.5 * (start + end)
        print(f"bead window {label}: {(end - start) * 3600:5.1f}s long, "
              f"centre {(centre - when) * 3600:+.1f}s from the contact")

    # The reference sheets correct at the contact point and quote the bead
    # spread separately, so that is the number to compare.  The whole-arc shift
    # is the far edge of that spread and is expected to differ.
    point_c2_shift = (point_c2 - c2) * 3600.0
    point_c3_shift = (point_c3 - c3) * 3600.0

    print(f"\nat the contact point  C2 {point_c2_shift:+.2f}s  C3 {point_c3_shift:+.2f}s  "
          f"duration {(point_c3_shift - point_c2_shift):+.2f}s")
    print(f"    last bead anywhere  C2 {c2_shift:+.2f}s  C3 {c3_shift:+.2f}s  "
          f"duration {(c3_shift - c2_shift):+.2f}s")
    print(f"             reference  C2 {reference['c2_correction']:+.2f}s  "
          f"C3 {reference['c3_correction']:+.2f}s  duration "
          f"{reference['c3_correction'] - reference['c2_correction']:+.2f}s")

    # Compare against whichever convention this source uses.  They are not the
    # same quantity: the contact-point correction sits inside the bead window,
    # the whole-arc one is its far edge.
    convention = case.get("convention", "point")
    ours = ((point_c2_shift, point_c3_shift) if convention == "point"
            else (c2_shift, c3_shift))
    tolerance = case.get("tolerance", 0.5)
    errors = (abs(ours[0] - reference["c2_correction"]),
              abs(ours[1] - reference["c3_correction"]))
    print(f"\ncompared on the {convention} convention, tolerance {tolerance:.1f}s")
    print(f"     residual C2 {errors[0]:.2f}s  C3 {errors[1]:.2f}s")
    ok = max(errors) < tolerance
    print("PASS" if ok else f"FAIL: differs from the reference by more than {tolerance:.1f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
