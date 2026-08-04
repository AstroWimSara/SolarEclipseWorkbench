"""Limb-corrected second and third contact times.

Standard eclipse geometry gives the Moon a single mean radius, so C2 and C3 are
computed as if the limb were smooth.  It is not: a valley lets sunlight through
for another second or two, a mountain cuts totality short.  Corrections of a few
seconds are normal and 30 s is possible near the edge of the path.

This module reads the true limb radius out of the marginal-zone blob (see
lunar_limb.py) at the position angle where each contact actually happens, and
feeds a corrected umbral radius back into the Besselian contact solver.

Frames matter here.  The Besselian elements are referred to the true equator and
equinox of date, so position angles are computed in that frame rather than in
ICRF -- the difference is a few tenths of a degree, which is kilometres along
the limb.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from skyfield import framelib
from skyfield.api import load, wgs84
from skyfield.planetarylib import PlanetaryConstants

from solareclipseworkbench.constants import EARTH_RADIUS
from solareclipseworkbench.lunar_limb import LimbBand

EARTH_RADIUS_KM = EARTH_RADIUS / 1000.0

# None of these are in the checkout.  The two lunar orientation kernels come
# down from NAIF on first use, the way the ephemeris already does; the limb blob
# is a 72 MB release asset, so everything here degrades to None when it is
# absent and the caller falls back to mean-limb contacts.
BAND_FILE_NAME = "lunar_limb_band_v1.bin"
FRAME_KERNEL_NAME = "moon_080317.tf"
ORIENTATION_KERNEL_NAME = "moon_pa_de421_1900-2050.bpc"
EPHEMERIS_NAME = "de440s.bsp"

BAND_FILE = Path(load.path_to(BAND_FILE_NAME))

# The reduced mean limb radius the l2 coefficients are built on.  Jubier charts
# the same value as k2, and it is already the constant used when we generate
# Besselian elements ourselves.
K2 = 0.272281

# The mean radius the LRO and Kaguya profiles are quoted against (IAU, k =
# 0.2725076).  Used only for reporting heights the way Jubier does.
IAU_MEAN_RADIUS_KM = 1738.091

# Radius used to place the tangent point.  An error of a few km here moves the
# sampled point by under a metre, so the mean is plenty.
NOMINAL_RADIUS_KM = 1737.4

DEFAULT_BEAD_ARC_DEG = 20.0


@dataclass(frozen=True)
class BeadWindow:
    """A photographic bead interval and whether both edges were solved.

    ``max_arc_deg`` is an explicit capture criterion, not an astronomical
    contact definition: outside this interval more than that total extent of
    the lunar limb is still illuminated and the beads have merged into a
    crescent for the purposes of this model.
    """

    start: float
    end: float
    solved: bool
    max_arc_deg: float
    search_limit_seconds: float

    @property
    def duration_seconds(self):
        return (self.end - self.start) * 3600.0


class LunarLimb:
    """The Moon's true limb, as seen from one place at one time."""

    def __init__(self, band_path=BAND_FILE, frame_kernel_name=FRAME_KERNEL_NAME,
                 orientation_kernel_name=ORIENTATION_KERNEL_NAME,
                 ephemeris_name=EPHEMERIS_NAME):
        self.band = LimbBand(band_path)
        self.ephemeris = load(ephemeris_name)

        constants = PlanetaryConstants()
        constants.read_text(load(frame_kernel_name))
        # The binary kernel is read lazily on every rotation_at() call, so the
        # handle has to outlive this constructor.
        self._orientation_kernel = load(orientation_kernel_name)
        constants.read_binary(self._orientation_kernel)
        self.frame = constants.build_frame_named("MOON_ME_DE421")

    def profile(self, t, latitude, longitude, elevation_m, position_angles):
        """Limb radius in metres at each sky position angle, in degrees.

        Position angles are measured from north through east, in the true
        equator and equinox of date.
        """
        site = self.ephemeris["earth"] + wgs84.latlon(latitude, longitude,
                                                      elevation_m=elevation_m)
        apparent = site.at(t).observe(self.ephemeris["moon"]).apparent()

        of_date = apparent.frame_xyz(framelib.true_equator_and_equinox_of_date).au
        distance_km = apparent.distance().km
        direction = of_date / np.linalg.norm(of_date)

        east = np.cross([0.0, 0.0, 1.0], direction)
        east /= np.linalg.norm(east)
        north = np.cross(direction, east)

        # The limb is where the line of sight grazes the sphere, so the outward
        # normal there is tilted off the plane of the sky by asin(R/D) -- about
        # 0.26 deg, which is 8 km of lunar surface.  Not optional.
        sin_parallax = NOMINAL_RADIUS_KM / distance_km
        cos_parallax = np.sqrt(1.0 - sin_parallax * sin_parallax)

        angles = np.radians(np.asarray(position_angles, dtype=np.float64))
        offsets = (np.cos(angles)[:, None] * north + np.sin(angles)[:, None] * east)
        normals = cos_parallax * offsets - sin_parallax * direction

        to_icrf = framelib.true_equator_and_equinox_of_date.rotation_at(t).T
        to_moon = self.frame.rotation_at(t)
        selenographic = normals @ to_icrf.T @ to_moon.T

        psi = np.degrees(np.arcsin(np.clip(selenographic[:, 0], -1.0, 1.0)))
        phi = np.degrees(np.arctan2(selenographic[:, 2], selenographic[:, 1])) % 360.0

        if np.abs(psi).max() > self.band.psi_limit_deg:
            raise ValueError("limb falls outside the marginal-zone band; blob is too narrow")

        return self.band.radius_m(phi, psi)

    def height_above_k2(self, t, latitude, longitude, elevation_m, position_angles):
        """Limb height in kilometres above the reduced mean radius k2.

        This is the quantity the umbral radius has to be corrected by: positive
        where a mountain makes the umbra larger, negative in a valley.
        """
        radius_km = self.profile(t, latitude, longitude, elevation_m, position_angles) / 1000.0
        return radius_km - K2 * EARTH_RADIUS_KM


# Refraction is deliberately outside this timing contract: these are geometric,
# top-of-atmosphere contacts.  A locally affine refraction map preserves
# tangency, but a complete low-altitude treatment also has to model its
# variation across both apparent discs.  At a roughly 7.5 degree solar altitude
# the omitted correction has been estimated at about 0.30 s for C2 and 0.22 s
# for C3, so callers needing that accuracy must apply a documented atmospheric
# model rather than squashing only the centre separation.


def contact_position_angle(elements):
    """Sky position angle of an internal contact, from north through east.

    At an internal contact the limbs touch on the line joining the two centres,
    at the point where the Sun's limb is tangent from inside.  The solver's
    (u, v) runs from the observer to the shadow axis, so the observer sits at
    -(u, v) from the axis, the Moon appears displaced by +(u, v) against the
    Sun, and the tangent point lies in the direction -(u, v).  The Besselian x
    axis points celestial east and y north, which is also how the profile is
    sampled.

    The result puts C2 near the Sun's east limb and C3 near its west limb, which
    is the way round the relative motion requires: the Moon slides east, so the
    last sliver before totality is the eastern one.
    """
    return np.degrees(np.arctan2(-elements["u"], -elements["v"])) % 360.0


def solar_limb_reach(elements, position_angles):
    """How far the Sun's limb reaches from the Moon's centre, per position angle.

    Everything is in fundamental-plane units, where the Moon's mean radius is
    k2 and lengths are Earth radii.  For a total eclipse L2' is negative and
    |L2'| is the umbral radius, which is the Moon's radius less the Sun's, so
    the Sun's radius is k2 + L2'.

    Along the ray leaving the Moon's centre at position angle P, the far
    intersection with the Sun's disk is at

        rho * cos(P - Q) + sqrt(R_sun^2 - rho^2 * sin^2(P - Q))

    with rho the centre separation and Q the position angle of the Sun's centre.
    """
    rho = math.hypot(elements["u"], elements["v"])
    q = contact_position_angle(elements)
    r_sun = K2 + elements["L2p"]

    offset = np.radians(np.asarray(position_angles, dtype=np.float64) - q)
    under_root = r_sun * r_sun - (rho * np.sin(offset)) ** 2
    return rho * np.cos(offset) + np.sqrt(np.clip(under_root, 0.0, None))


def sunlight_margin(elements, position_angles, heights_km):
    """Positive where the Sun still shows past the true limb, per position angle.

    Totality is exactly the state where this is negative everywhere; the arcs
    where it is positive are the Baily's beads.
    """
    true_radius = K2 + np.asarray(heights_km, dtype=np.float64) / EARTH_RADIUS_KM
    return solar_limb_reach(elements, position_angles) - true_radius


def solve_limb_contact(elements, evaluate, start_hours, entering,
                       position_angles, heights_km,
                       search_hours=40.0 / 3600.0, step_hours=0.25 / 3600.0):
    """Find C2 or C3 as the moment the last, or first, bead is on the limb.

    `evaluate` is solar_eclipse.get_elements already bound to a place, and
    `start_hours` the uncorrected contact it should refine.  With `entering`
    true this returns C2, the instant sunlight last vanishes from every position
    angle; with it false, C3, when it first returns.

    Unlike a correction applied at a single position angle, this is set by the
    lowest limb point anywhere along the relevant arc.  That arc is wide: for
    disks of ratio 1.04 the radial gap grows as only about 21 arcsec per radian
    squared, so a 1 km valley 9 degrees away still governs the contact.
    """
    def worst(when):
        return sunlight_margin(evaluate(when), position_angles, heights_km).max()

    # Totality is margin < 0.  Step outwards from the uncorrected contact until
    # the sign flips, then bisect.  Stepping away from totality means going
    # backwards for C2 and forwards for C3.
    direction = -1.0 if entering else 1.0

    inside = start_hours
    for _ in range(int(search_hours / step_hours) + 1):
        if worst(inside) < 0.0:
            break
        inside += direction * -step_hours
    else:
        raise ValueError(
            f"no totality within {search_hours * 3600.0:.0f} s of the uncorrected "
            f"contact: the limb correction here is larger than the search window, "
            f"which happens close to the edge of the path")

    outside = inside
    for _ in range(int(search_hours / step_hours) + 1):
        outside += direction * step_hours
        if worst(outside) >= 0.0:
            break
    else:
        raise ValueError("totality does not end within the search window")

    for _ in range(60):
        middle = 0.5 * (inside + outside)
        if worst(middle) < 0.0:
            inside = middle
        else:
            outside = middle
    return 0.5 * (inside + outside)


def solve_point_contact(elements, evaluate, start_hours, entering, limb_height_at):
    """Find C2 or C3 corrected at the contact point alone.

    This is the correction the published Maestro sheets print: the limb is read
    only where the two discs touch, so the answer says when the Sun goes behind
    that one mountain or valley.  It is distinct from when the last bead goes --
    that is solve_limb_contact, and the two differ by up to the width of the bead
    window.

    `limb_height_at` returns the limb height in km at a position angle.  The
    angle is the one at the uncorrected contact, and it is deliberately not
    re-read from the corrected one: a correction of a few seconds swings the
    contact angle by about a degree, which on a mountainous limb is different
    terrain entirely, and iterating on that oscillates rather than converging.
    The published convention perturbs the nominal contact, so that is what this
    does.
    """
    angle = contact_position_angle(evaluate(start_hours))
    return solve_limb_contact(elements, evaluate, start_hours, entering,
                              np.array([angle]), np.array([limb_height_at(angle)]))


def lit_arc_degrees(elements, position_angles, heights_km):
    """Total extent of limb, in degrees, that still has sunlight past it."""
    lit = sunlight_margin(elements, position_angles, heights_km) > 0.0
    return float(lit.sum()) * (360.0 / len(position_angles))


def bead_window(evaluate, contact_hours, entering, position_angles, heights_km,
                max_arc_deg=DEFAULT_BEAD_ARC_DEG, step_hours=0.05 / 3600.0,
                limit_hours=60.0 / 3600.0):
    """Return the photographic bead interval around an internal contact.

    This is what a burst wants to be centred on.  Rather than guessing a fixed
    number of seconds either side of C2, walk out from the contact until the
    sunlight still showing past the limb spans more than `max_arc_deg` of
    position angle -- the moment the beads merge back into a crescent.

    `entering` selects C2, where the window ends at the contact, from C3, where
    it starts there.
    """
    if not 0.0 <= max_arc_deg < 360.0:
        raise ValueError("max_arc_deg must be at least 0 and less than 360")
    if step_hours <= 0.0 or limit_hours <= 0.0:
        raise ValueError("step_hours and limit_hours must be positive")

    direction = -1.0 if entering else 1.0

    edge = contact_hours
    solved = False
    for _ in range(int(limit_hours / step_hours)):
        stepped = edge + direction * step_hours
        if lit_arc_degrees(evaluate(stepped), position_angles, heights_km) > max_arc_deg:
            solved = True
            break
        edge = stepped
    else:
        # The beads never merged back into a crescent inside the search window.
        logging.warning("Bead window did not close within %.0f s of the contact; "
                        "no schedulable bead-window edge will be published.",
                        limit_hours * 3600.0)

    start, end = ((edge, contact_hours) if entering
                  else (contact_hours, edge))
    return BeadWindow(start, end, solved, max_arc_deg, limit_hours * 3600.0)


def beads(elements, position_angles, heights_km):
    """Position angle ranges where sunlight still shows, as (start, end) pairs.

    The ranges wrap around 360 degrees, so a bead straddling north is reported
    once, with a start angle larger than its end.
    """
    lit = sunlight_margin(elements, position_angles, heights_km) > 0.0
    angles = np.asarray(position_angles, dtype=np.float64)

    if lit.all():
        return [(float(angles[0]), float(angles[-1]))]
    if not lit.any():
        return []

    # Rotate so the array starts on an unlit sample; runs are then contiguous.
    first_dark = int(np.flatnonzero(~lit)[0])
    order = np.roll(np.arange(angles.size), -first_dark)
    rolled = lit[order]

    starts = np.flatnonzero(rolled & ~np.roll(rolled, 1))
    ends = np.flatnonzero(rolled & ~np.roll(rolled, -1))
    return [(float(angles[order[start]]), float(angles[order[end]]))
            for start, end in zip(starts, ends)]


def load_default_limb():
    """The limb model, or None when the limb blob has not been installed.

    Only the blob is checked for: it is a 72 MB release asset the user has to
    fetch or build deliberately, whereas the kernels are small enough that
    skyfield can download them on the spot.
    """
    if not BAND_FILE.exists():
        logging.info("Lunar limb profile unavailable, contacts will use the mean limb. "
                     "Install %s (see tools/build_limb_blob.py) for limb-corrected "
                     "contacts and bead windows.", BAND_FILE)
        return None
    try:
        return LunarLimb(BAND_FILE)
    except Exception as exc:
        logging.warning("Could not load the lunar limb model, contacts will use the "
                        "mean limb: %s", exc)
        return None


def _refine_internal_contact(elements, evaluate, start_hours, entering):
    """Newton-iterate an uncorrected internal contact from a starting guess."""
    sign = 1.0 if entering else -1.0
    contact = start_hours
    for _ in range(20):
        o = evaluate(contact)
        s = (o["a"] * o["v"] - o["u"] * o["b"]) / (o["n"] * o["L2p"])
        step = (-(o["u"] * o["a"] + o["v"] * o["b"]) / (o["n"] * o["n"])
                + sign * o["L2p"] / o["n"] * math.sqrt(max(0.0, 1 - s * s)))
        contact += step
        if abs(step) < 1e-12:
            break
    return contact


# Turned off from the interface when a correction looks untrustworthy at an
# untested location.  When off, only the mean-limb C2 and C3 are published.
_enabled = True


def set_enabled(enabled: bool) -> None:
    """Enable or disable the limb correction everywhere."""
    global _enabled
    _enabled = bool(enabled)


def is_enabled() -> bool:
    return _enabled


class LimbSolution:
    """Everything a limb-corrected eclipse needs, for scheduling or for drawing."""

    def __init__(self, elements, evaluate, to_utc, from_utc, angles, heights_km,
                 c2, c3, c2_limb, c3_limb, windows, c2_point=None, c3_point=None):
        self.elements = elements
        self.evaluate = evaluate
        self.to_utc = to_utc
        self.from_utc = from_utc
        self.angles = angles
        self.heights_km = heights_km
        self.c2 = c2
        self.c3 = c3
        self.c2_limb = c2_limb          # last bead gone anywhere on the limb
        self.c3_limb = c3_limb
        self.c2_point = c2_point        # corrected at the contact point alone
        self.c3_point = c3_point
        self.windows = windows          # {"C2": BeadWindow, "C3": BeadWindow}

    def correction_seconds(self, name, at_point=False):
        """Seconds the limb moves this contact.

        With at_point, return the correction read at the contact point alone.
        Otherwise return the last/first-bead envelope correction.
        """
        if at_point:
            contact, corrected = ((self.c2, self.c2_point) if name == "C2"
                                  else (self.c3, self.c3_point))
        else:
            contact, corrected = ((self.c2, self.c2_limb) if name == "C2"
                                  else (self.c3, self.c3_limb))
        return (corrected - contact) * 3600.0

    def window_seconds(self, name):
        window = self.windows[name]
        return window.duration_seconds if window.solved else None

    def margin_at(self, hours):
        """Sunlight margin per position angle at a moment, for drawing."""
        return sunlight_margin(self.evaluate(hours), self.angles, self.heights_km)


def solve_limb(eclipse_date, latitude, longitude, elevation_m,
               limb=None, arc_degrees=DEFAULT_BEAD_ARC_DEG, profile_step_deg=0.01):
    """Solve the limb-corrected contacts and bead windows, or None.

    Returns None when there is no totality here or the limb data is not
    installed.  This does not consult the enable flag: the interface wants to
    show what the correction *would* be even while it is switched off.
    """
    from solareclipseworkbench.solar_eclipse import get_element_coeffs, get_elements

    limb = limb or load_default_limb()
    if limb is None:
        return None

    elements = get_element_coeffs(eclipse_date)

    # The solver takes west longitude as positive.
    def evaluate(when):
        return get_elements(elements, when, latitude, -longitude, elevation_m)

    maximum = 0.0
    for _ in range(30):
        o = evaluate(maximum)
        maximum += -(o["u"] * o["a"] + o["v"] * o["b"]) / (o["n"] * o["n"])

    o = evaluate(maximum)
    if o["L2p"] >= 0.0:
        return None      # annular or partial here: no totality to bracket

    s = (o["a"] * o["v"] - o["u"] * o["b"]) / (o["n"] * o["L2p"])
    half = o["L2p"] / o["n"] * math.sqrt(max(0.0, 1 - s * s))

    c2 = _refine_internal_contact(elements, evaluate, maximum + half, True)
    c3 = _refine_internal_contact(elements, evaluate, maximum - half, False)

    delta_t_hours = elements["\u0394t"] / 3600.0
    day = datetime.strptime(eclipse_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    def to_utc(hours):
        return day + timedelta(hours=hours + elements["T0"] - delta_t_hours)

    def from_utc(moment):
        return ((moment - day).total_seconds() / 3600.0
                - elements["T0"] + delta_t_hours)

    # One profile for the whole of totality, evaluated at maximum eclipse.
    # Comparing this with contact-epoch profiles on two eclipses/four contacts
    # moved the solved contacts by at most 0.014 s, below the profile-source
    # uncertainty, so the cheaper single-profile convention is retained.
    timescale = load.timescale()
    moment = timescale.ut1(day.year, day.month, day.day, 0, 0,
                           (maximum + elements["T0"] - delta_t_hours) * 3600.0)
    angles = np.arange(0.0, 360.0, profile_step_deg)
    heights_km = limb.height_above_k2(moment, latitude, longitude, elevation_m, angles)

    c2_limb = solve_limb_contact(elements, evaluate, c2, True, angles, heights_km)
    c3_limb = solve_limb_contact(elements, evaluate, c3, False, angles, heights_km)

    def limb_height_at(angle):
        # period, or the last hundredth of a degree before north interpolates
        # against nothing and returns the value at 359.99 instead of wrapping.
        return float(np.interp(angle % 360.0, angles, heights_km, period=360.0))

    c2_point = solve_point_contact(elements, evaluate, c2, True, limb_height_at)
    c3_point = solve_point_contact(elements, evaluate, c3, False, limb_height_at)

    windows = {
        "C2": bead_window(evaluate, c2_limb, True, angles, heights_km, max_arc_deg=arc_degrees),
        "C3": bead_window(evaluate, c3_limb, False, angles, heights_km, max_arc_deg=arc_degrees),
    }
    return LimbSolution(elements, evaluate, to_utc, from_utc, angles, heights_km,
                        c2, c3, c2_limb, c3_limb, windows, c2_point, c3_point)


def bead_reference_moments(eclipse_date, latitude, longitude, elevation_m,
                           limb=None, arc_degrees=DEFAULT_BEAD_ARC_DEG,
                           profile_step_deg=0.01):
    """Limb-corrected contacts and bead windows, as UTC datetimes.

    Returns a dict keyed by reference-moment name, empty if there is no totality
    at this place, the limb data is not installed, or the correction has been
    switched off.  The keys are the ones a script can schedule against:

        C2, C3                        contact-point corrected internal contacts
        BEADS_C2, BEADS_C3            the middle of each bead window
        BEADS_C2_START / _END         its edges, and likewise for C3

    ``calculate_reference_moments()`` preserves the uncorrected contacts as
    ``C2_MEAN`` and ``C3_MEAN`` when it installs this result.

    The observable last/first-bead envelope remains the inner edge of each
    solved bead window: BEADS_C2_END and BEADS_C3_START.  C2/C3 retain the
    published-sheet contact-point convention expected by existing scripts.

    A bead window is published only when its photographic arc criterion closes
    inside the search interval.  ``BEADS_C2_STATUS`` and ``BEADS_C3_STATUS``
    say ``solved`` or ``unresolved``; an unresolved window has no schedulable
    start, end, or midpoint keys.
    """
    if not _enabled:
        return {}

    solution = solve_limb(eclipse_date, latitude, longitude, elevation_m,
                          limb, arc_degrees, profile_step_deg)
    if solution is None:
        return {}

    moments = {"C2": solution.to_utc(solution.c2_point),
               "C3": solution.to_utc(solution.c3_point)}
    for name in ("C2", "C3"):
        window = solution.windows[name]
        moments[f"BEADS_{name}_STATUS"] = "solved" if window.solved else "unresolved"
        if window.solved:
            moments[f"BEADS_{name}_START"] = solution.to_utc(window.start)
            moments[f"BEADS_{name}_END"] = solution.to_utc(window.end)
            moments[f"BEADS_{name}"] = solution.to_utc(0.5 * (window.start + window.end))
    return moments
