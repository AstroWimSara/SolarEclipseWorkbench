"""Path of totality (or annularity) on the ground, and where an observer sits in it.

The path is computed from the Besselian elements in ``solar_eclipse``:

- The centre line is traced by sampling the shadow axis over the time it meets the Earth.
- The two limits are found at the same times. At a limit the observer only grazes the umbra: at their moment of
  closest approach the shadow axis passes them at a distance of exactly the umbral radius ``|L2'|``, and in the
  direction perpendicular to their motion relative to the shadow. That motion depends on where the observer is
  (Earth's rotation), so the point is found by a short fixed-point iteration.

Everything here is pure computation (no Qt, no matplotlib), so it can be tested and reused by both the GUI and
the wizard.
"""

import functools
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from solareclipseworkbench import solar_eclipse as se

EARTH_RADIUS_KM = 6371.0088

# Sampling step along the path, in hours.  Twenty seconds keeps neighbouring centre-line points at most ~20 km
# apart even where the shadow moves fastest (near the ends of the path), which is plenty for a map and is refined
# further for the observer's distance by projecting onto segments.
DEFAULT_STEP_H = 20 / 3600

# How long after (before) the shadow axis leaves (meets) the Earth to keep looking for limit points, in hours.
_LIMIT_OVERRUN_H = 15 / 60


@dataclass
class PathPoint:
    """One sample of the centre line."""

    t: float  # Hours from T0 (TDT)
    lat: float  # Degrees
    lon: float  # Degrees, east positive, in [-180, 180]
    duration: float  # Seconds of totality/annularity on the centre line
    width: float  # Path width in km


@dataclass
class EclipsePath:
    """The ground track of the umbra (or antumbra) for one eclipse."""

    eclipse_type: str  # "T", "A", "H" (from eclipse_besselian.csv)
    central: List[PathPoint] = field(default_factory=list)
    # Limit points as (lat, lon); ``north`` is the limit with the higher mean latitude.
    north: List[Tuple[float, float]] = field(default_factory=list)
    south: List[Tuple[float, float]] = field(default_factory=list)
    # The (north, south) limit points found at the same instant, one entry per time sample; either is None when
    # that limit falls off the Earth at that instant.  Used to shade the path between the limits.
    limit_pairs: List[Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]] = field(
        default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.central) < 2


@dataclass
class ObserverInPath:
    """Where the observer is relative to the path."""

    distance_km: float  # Distance to the centre line (always >= 0)
    side: str  # "north", "south" or "" when on the line
    inside: bool  # True when the observer sees totality/annularity
    half_width_km: float  # Half the path width at the nearest centre-line point
    centre_duration_s: float  # Duration on the centre line at the nearest point

    @property
    def distance_from_limit_km(self) -> float:
        """Distance to the nearest limit: positive inside the path, negative outside."""
        return self.half_width_km - self.distance_km


def _normalise_lon(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def _axis_on_earth(e: dict, t: float) -> bool:
    """True when the shadow axis meets the Earth at time ``t`` (hours from T0)."""
    be = se.get_elements(e, t, 0, 0, 0)
    omega = 1 / math.sqrt(1 - 0.006694385 * math.cos(be['d'] * se.rad) ** 2)
    return be['X'] ** 2 + (omega * be['Y']) ** 2 < 1


def _central_time_range(e: dict) -> Optional[Tuple[float, float]]:
    """Return the first and last time (hours from T0) at which the shadow axis meets the Earth."""
    coarse = 1 / 60
    times = [k * coarse for k in range(int(-4 / coarse), int(4 / coarse) + 1)]
    on = [t for t in times if _axis_on_earth(e, t)]
    if not on:
        return None

    def bisect(inside: float, outside: float) -> float:
        for _ in range(30):
            mid = (inside + outside) / 2
            if _axis_on_earth(e, mid):
                inside = mid
            else:
                outside = mid
        return inside

    return bisect(on[0], on[0] - coarse), bisect(on[-1], on[-1] + coarse)


def _limit_point(e: dict, be: dict, t: float, a: float, b: float, side: int) -> Optional[Tuple[float, float]]:
    """Ground point of one path limit at time ``t``.

    Args:
        - e: Besselian element coefficients.
        - be: Elements at ``t`` for Greenwich (``get_elements(e, t, 0, 0, 0)``).
        - t: Hours from T0.
        - a, b: Starting guess for the observer's velocity relative to the shadow in the fundamental plane.
        - side: +1 or -1, selects the limit.

    Returns: (lat, lon) in degrees, or None when the point does not fall on the Earth.
    """
    point = None
    for _ in range(6):
        n = math.hypot(a, b)
        if n == 0:
            return None
        # Unit vector perpendicular to the relative motion.
        px, py = -b / n * side, a / n * side
        # compute_outline_point places the point at (X - L sinQ, Y - L cosQ).
        q = math.degrees(math.atan2(-px, -py))
        try:
            p = se.compute_outline_point(be, q, umbra=True)
        except ValueError:
            return None
        if math.isnan(p['lat']) or math.isnan(p['lon']):
            return None
        point = (p['lat'], _normalise_lon(p['lon']))
        o = se.get_elements(e, t, point[0], -point[1], 0)
        if o['zeta'] < 0:  # Behind the Earth's limb
            return None
        a, b = o['a'], o['b']
    return point


def compute_eclipse_path(date=None, step: float = DEFAULT_STEP_H) -> EclipsePath:
    """Compute the centre line and limits of the path of totality/annularity.

    Args:
        - date: Eclipse date ('YYYY-MM-DD' or datetime); the closest eclipse in the catalogue is used.
        - step: Sampling step in hours.

    Returns: An ``EclipsePath``.  It is empty (``is_empty``) for partial eclipses and for the rare non-central
             eclipses whose shadow axis misses the Earth.
    """
    e = se.get_element_coeffs(date)
    path = EclipsePath(eclipse_type=e['type'])
    if e['type'] not in ("T", "A", "H"):
        return path

    time_range = _central_time_range(e)
    if time_range is None:
        return path
    start, end = time_range
    n = max(2, int(math.ceil((end - start) / step)) + 1)
    times = [start + (end - start) * k / (n - 1) for k in range(n)]
    # Near sunrise and sunset the limits carry on for a few minutes after the shadow axis has left the Earth (the
    # edge of the umbra still touches it), so sample them a little beyond the centre line's time range.
    extra = int(_LIMIT_OVERRUN_H / step)
    before = [start - step * k for k in range(extra, 0, -1)]
    after = [end + step * k for k in range(1, extra + 1)]

    limit_a: List[Tuple[float, float]] = []
    limit_b: List[Tuple[float, float]] = []
    for t in before + times + after:
        be = se.get_elements(e, t, 0, 0, 0)
        # Starting guess for the relative motion: the shadow's own motion, refined below at the central point
        # when there is one.
        a, b = be['Xp'], be['Yp']
        if start <= t <= end:
            c = se.compute_central_lat_lon_for_time(e, e['T0'] + t)
            if math.isnan(c['lat']) or math.isnan(c['lon']):
                continue
            lon = _normalise_lon(c['lon'])
            path.central.append(PathPoint(t=t, lat=c['lat'], lon=lon, duration=abs(c['duration']),
                                          width=c['width']))
            o = se.get_elements(e, t, c['lat'], -lon, 0)
            a, b = o['a'], o['b']

        found = []
        for side, target in ((1, limit_a), (-1, limit_b)):
            p = _limit_point(e, be, t, a, b, side)
            if p is not None:
                target.append(p)
            found.append(p)
        if found != [None, None]:
            path.limit_pairs.append((found[0], found[1]))

    mean = lambda pts: sum(p[0] for p in pts) / len(pts) if pts else 0.0  # noqa: E731
    if mean(limit_a) >= mean(limit_b):
        path.north, path.south = limit_a, limit_b
    else:
        path.north, path.south = limit_b, limit_a
        path.limit_pairs = [(pair[1], pair[0]) for pair in path.limit_pairs]
    return path


def path_polygons(path: EclipsePath) -> List[List[Tuple[float, float]]]:
    """Polygons, as lists of (lon, lat), that together cover the path between its limits.

    Where both limits are known at consecutive instants the path is covered by quadrilaterals.  At the sunrise and
    sunset ends one limit usually carries on a little longer than the other; that tail is closed with a fan from
    the last point of the limit that stopped.  A polygon that would straddle the ±180° meridian is dropped rather
    than drawn across the whole map.
    """
    def add(polygons, corners):
        lons = [c[1] for c in corners]
        if max(lons) - min(lons) <= 180:
            polygons.append([(c[1], c[0]) for c in corners])

    polygons: List[List[Tuple[float, float]]] = []
    pairs = path.limit_pairs
    both = [k for k, (n, s) in enumerate(pairs) if n is not None and s is not None]
    if not both:
        return polygons

    for k in range(len(pairs) - 1):
        (n1, s1), (n2, s2) = pairs[k], pairs[k + 1]
        if None not in (n1, s1, n2, s2):
            add(polygons, [n1, n2, s2, s1])

    # End caps: fan from the stopped limit's last point over the other limit's tail.
    for anchor_index, tail_indices in ((both[0], range(both[0], -1, -1)), (both[-1], range(both[-1], len(pairs)))):
        anchor_n, anchor_s = pairs[anchor_index]
        for side in (0, 1):
            tail = [pairs[k][side] for k in tail_indices if pairs[k][side] is not None]
            anchor = anchor_s if side == 0 else anchor_n
            for p, q in zip(tail, tail[1:]):
                add(polygons, [anchor, p, q])

    # The sunrise/sunset end of the path bulges outwards and the centre line reaches furthest along it, so close
    # each end through the centre line's end point rather than with a straight edge between the limits.
    if path.central:
        for end_pair, centre in ((pairs[0], path.central[0]), (pairs[-1], path.central[-1])):
            ends = [p for p in end_pair if p is not None]
            if len(ends) == 2:
                add(polygons, [ends[0], (centre.lat, centre.lon), ends[1]])
            elif len(ends) == 1:
                other = pairs[both[0] if end_pair is pairs[0] else both[-1]]
                stopped = other[1] if end_pair[0] is not None else other[0]
                add(polygons, [ends[0], (centre.lat, centre.lon), stopped])
    return polygons


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _local_xy(lat0: float, lon0: float, lat: float, lon: float) -> Tuple[float, float]:
    """Equirectangular projection (km) around (lat0, lon0); accurate over the few tens of km we use it for."""
    dlon = _normalise_lon(lon - lon0)
    x = math.radians(dlon) * EARTH_RADIUS_KM * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * EARTH_RADIUS_KM
    return x, y


def locate_observer(path: EclipsePath, latitude: float, longitude: float) -> Optional[ObserverInPath]:
    """Distance and side of the observer relative to the centre line.

    The nearest sample is found by great-circle distance, then the distance is refined by projecting the observer
    onto the two neighbouring segments in a local flat projection.

    Returns: None when the path is empty.
    """
    pts = path.central
    if len(pts) < 2:
        return None

    i = min(range(len(pts)), key=lambda k: haversine_km(latitude, longitude, pts[k].lat, pts[k].lon))

    best = None  # (distance, cross, fraction, segment index)
    for j in (i - 1, i):
        if j < 0 or j + 1 >= len(pts):
            continue
        p, q = pts[j], pts[j + 1]
        qx, qy = _local_xy(p.lat, p.lon, q.lat, q.lon)
        ox, oy = _local_xy(p.lat, p.lon, latitude, longitude)
        seg2 = qx * qx + qy * qy
        f = 0.0 if seg2 == 0 else max(0.0, min(1.0, (ox * qx + oy * qy) / seg2))
        dx, dy = ox - f * qx, oy - f * qy
        dist = math.hypot(dx, dy)
        cross = qx * oy - qy * ox  # > 0: observer is left of the direction of travel
        if best is None or dist < best[0]:
            best = (dist, cross, f, j)

    dist, cross, f, j = best
    p, q = pts[j], pts[j + 1]
    width = p.width + f * (q.width - p.width)
    duration = p.duration + f * (q.duration - p.duration)

    # Which side is north: compare against the local direction of the northern limit, i.e. step a little off the
    # line to the left and see whether latitude increases.
    qx, qy = _local_xy(p.lat, p.lon, q.lat, q.lon)
    left_is_north = qx > 0  # Moving east, left is north; moving west, left is south.
    if abs(qx) < 1e-9:
        left_is_north = qy < 0
    if dist < 0.05:
        side = ""
    else:
        side = "north" if (cross > 0) == left_is_north else "south"

    return ObserverInPath(distance_km=dist, side=side, inside=dist <= width / 2, half_width_km=width / 2,
                          centre_duration_s=duration)


def split_at_dateline(points: Sequence[Tuple[float, float]]) -> List[List[Tuple[float, float]]]:
    """Split a (lat, lon) polyline into runs that do not jump across the ±180° meridian."""
    runs: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    for pt in points:
        if current and abs(pt[1] - current[-1][1]) > 180:
            runs.append(current)
            current = []
        current.append(pt)
    if current:
        runs.append(current)
    return runs


def path_bounds(path: EclipsePath, margin_deg: float = 5.0) -> Optional[Tuple[float, float, float, float]]:
    """(min_lon, min_lat, max_lon, max_lat) of the path, padded by ``margin_deg``; None for an empty path."""
    pts = [(p.lat, p.lon) for p in path.central] + path.north + path.south
    if not pts:
        return None
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return (max(-180.0, min(lons) - margin_deg), max(-90.0, min(lats) - margin_deg),
            min(180.0, max(lons) + margin_deg), min(90.0, max(lats) + margin_deg))


@functools.lru_cache(maxsize=8)
def eclipse_path_for_date(date: str) -> EclipsePath:
    """Cached ``compute_eclipse_path`` for a 'YYYY-MM-DD' date string (the path does not change between calls)."""
    return compute_eclipse_path(date)


def format_duration(seconds: float) -> str:
    """Format a duration such as 107.4 as '1m47s'."""
    total = int(round(seconds))
    return f"{total // 60}m{total % 60:02d}s"


def describe_observer(path: EclipsePath, where: Optional[ObserverInPath], local_type: str,
                      local_duration_s: float) -> str:
    """One or two lines of text summarising where the observer is relative to the path.

    Args:
        - path: The eclipse path.
        - where: Result of ``locate_observer`` (None when the path is empty).
        - local_type: Eclipse type at the observer ("Total", "Annular", "Partial", "No eclipse").
        - local_duration_s: Duration of totality/annularity at the observer (seconds).
    """
    if path.is_empty or where is None:
        if path.eclipse_type == "P":
            return "Partial eclipse: there is no path of totality or annularity."
        return "This eclipse has no central path on the Earth."

    phase = {"T": "totality", "A": "annularity"}.get(path.eclipse_type, "totality/annularity")
    if local_type == "Annular":
        phase = "annularity"
    elif local_type == "Total":
        phase = "totality"

    if where.side:
        position = f"{where.distance_km:.1f} km {where.side} of the centre line"
    else:
        position = "On the centre line"

    if local_type in ("Total", "Annular") and local_duration_s > 0:
        margin = where.distance_from_limit_km
        return (f"{position}, {max(margin, 0):.1f} km inside the {where.side or 'nearest'} limit.\n"
                f"{phase.capitalize()} here: {format_duration(local_duration_s)} "
                f"(centre line: {format_duration(where.centre_duration_s)}).")

    outside = -where.distance_from_limit_km
    if outside > 0:
        return (f"{position}: {outside:.1f} km outside the path, no {phase} here.\n"
                f"Move more than {outside:.1f} km towards the centre line to see {phase} "
                f"({format_duration(where.centre_duration_s)} on the centre line).")
    if where.distance_from_limit_km > 0.5:
        # Within the path's width but no central phase: beyond the sunrise/sunset end of the path.
        return f"{position}, but beyond the end of the path: the Sun is below the horizon during {phase}."
    return f"{position}, at the edge of the path: no {phase} here."
