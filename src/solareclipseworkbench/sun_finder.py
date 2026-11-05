"""Find the sun's disk in a live-view frame, also when the moon covers part of it.

Used to keep the sun centred (step 3 of docs/MOUNT_PLAN.md).  The centre of the
sun is what the mount must hold, so it must not move as the eclipse goes on.
The centre of the bright pixels would: a crescent's centroid lies well away
from the centre of the sun, and moves as the moon moves.  Instead, a circle is
fitted to the edge of the bright part, and only to the part of that edge that
is the sun's own limb:

    1. Make the frame small (at most ``WORK_SIZE`` pixels wide) and split it into
       bright and dark with Otsu's threshold.  When that leaves too little bright
       (the last minute before C2, the crescent is 1-2 pixels wide), the search
       is done in the full frame.
    2. Keep the largest bright region (a reflection or a bright cloud edge is
       smaller than the sun).
    3. Take the pixels on the edge of that region.  Part of the edge is the sun's
       limb, part (during the partial phases) is the moon's limb.
    4. Fit circles through random triples of edge pixels (RANSAC) and keep the one
       that most edge pixels lie on, among the circles that have the bright
       region *inside* them.  An edge pixel only counts as lying on a circle
       when the image gets darker going outward from the circle's centre there.
       That holds on the sun's limb, but not on the moon's: seen from the sun's
       centre, going outward across the moon's limb goes from the dark moon into
       the bright crescent.  Without this, a thin crescent (two arcs of nearly
       the same radius, a few pixels apart) gives circles that lie half on
       each.
    5. Refine the circle with a least-squares fit to the pixels on it, and scale
       it back to the frame.
    6. Refine it again in the full frame: along radial lines through the limb
       that was found, put the limb where the brightness is halfway between the
       sky and the limb itself (to a fraction of a pixel), and fit the circle to
       those points.  Otsu's threshold falls inside the darkened limb, so step 5
       alone makes the sun too small, and a crescent's centre a few pixels off.

During totality there is no disk, only the corona around a dark moon.  Its outer
edge can look like a disk, but its edge is soft: on frames of the 2026 eclipse
the corona fades out over 8-10 pixels where the sun's limb (filtered, unfiltered
just after C3, or reddened at sunset) drops in 1-3 pixels of a sun of 60 pixels.
An edge wider than ``MAX_EDGE_WIDTH`` of the radius is not the sun's limb.  And
when the ring of the corona is closed, the dark moon is a hole in it (a
crescent's dark side is open to the sky, sunspots are small).  Either way
``find_sun`` returns None.

Around C2 and C3, frames without a filter show a short, overexposed sliver (the
beads, the diamond ring) whose glare pulls the circle several pixels towards the
moon.  A short arc that is saturated is not trusted either.

Colour frames: the brightest channel is used, not the luminance.  A sun low in
the sky is red, and its limb is darker still: in luminance the limb falls below
the threshold and the sun comes out too small and off-centre.  The same for a
frame without the sun or one that is too dark or too bright to tell.

Only numpy is needed.
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Width or height (the larger) the frame is reduced to before the search
WORK_SIZE = 400

#: Smallest radius of the sun, in pixels of the reduced frame, that is trusted
MIN_RADIUS = 6

#: Edge pixels within this distance (reduced frame) of a circle lie on it
INLIER_TOLERANCE = 1.5

#: Share of the bright region that must lie inside the circle of the sun
MIN_INSIDE = 0.97

#: How much of the limb must be seen, in degrees.  The uncovered limb spans about
#: 180° in a thin crescent, but its cusps fade below the threshold: in the frames
#: of the 2026 eclipse, 68-120° was seen of crescents in the last minute and a half
#: before C2.  With the radius known, the centre is fitted with the radius held, so
#: a short arc is enough.
MIN_ARC_DEG = 60.0

#: Without the radius known, a short arc is not trusted: at least this much limb is needed then.
#: Unfiltered glare just after C2 and C3 gives arcs of 80-90° on circles 10-30 % too small.
MIN_ARC_WITHOUT_HINT_DEG = 120.0

#: How far the radius may be from the known one (radius_hint).  The sun keeps its size
#: during an eclipse; refraction flattens it by a few % at the horizon.
RADIUS_HINT_TOLERANCE = 0.08

#: Largest share of the disk that may be an enclosed dark hole (sunspots); more is the moon in the corona
MAX_HOLE = 0.03

#: An edge pixel lies on the sun's limb only when the brightness falls going outward:
#: the cosine between the outward direction and the direction of the fall must be at least this
MIN_OUTWARD_COS = 0.6

#: Widest edge of the sun's limb (from 75 % to 25 % of the step), as a share of the radius,
#: and at least MIN_EDGE_LIMIT pixels.  The corona's edge is much wider.
MAX_EDGE_WIDTH = 0.08
MIN_EDGE_LIMIT = 3.0

#: A bright region smaller than this (pixels of the reduced frame) is looked for again in the full frame
SMALL_REGION = 400

#: Random triples tried
RANSAC_ITERATIONS = 400


@dataclass
class SunFix:
    """Where the sun is in a frame, in pixels of the full frame."""
    x: float
    y: float
    radius: float
    #: How much of the limb was seen, in degrees (360 for a full disk)
    arc_deg: float
    #: RMS distance of the limb pixels from the circle, in pixels of the full frame
    residual: float
    #: Share of the sun's disk that is bright (1 for a full disk, small for a thin crescent)
    bright_fraction: float
    #: Width of the limb, from 75 % to 25 % of the step, in pixels of the full frame
    edge_width: float = 0.0

    @property
    def centre(self) -> tuple:
        return self.x, self.y


def _reduce(grey: np.ndarray) -> tuple:
    """Average blocks of pixels so the larger side is at most WORK_SIZE; return (image, factor)."""
    height, width = grey.shape
    factor = max(1, int(np.ceil(max(height, width) / WORK_SIZE)))
    if factor == 1:
        return grey.astype(np.float32), 1
    h, w = height // factor * factor, width // factor * factor
    blocks = grey[:h, :w].astype(np.float32).reshape(h // factor, factor, w // factor, factor)
    return blocks.mean(axis=(1, 3)), factor


def otsu_threshold(image: np.ndarray) -> Optional[float]:
    """Otsu's threshold of an image, or None when it has no contrast."""
    low, high = float(image.min()), float(image.max())
    if high - low < 8.0:
        return None
    hist, edges = np.histogram(image, bins=256, range=(low, high))
    centres = (edges[:-1] + edges[1:]) / 2
    weight_low = np.cumsum(hist)
    weight_high = weight_low[-1] - weight_low
    sum_low = np.cumsum(hist * centres)
    total = sum_low[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_low = sum_low / weight_low
        mean_high = (total - sum_low) / weight_high
        between = weight_low * weight_high * (mean_low - mean_high) ** 2
    between = np.nan_to_num(between)
    return float(centres[int(np.argmax(between))])


def largest_region(mask: np.ndarray) -> np.ndarray:
    """The largest 4-connected region of a boolean mask."""
    height, width = mask.shape
    labels = np.zeros(mask.shape, dtype=np.int32)
    best_label, best_size, label = 0, 0, 0
    flat = mask.ravel()
    lab = labels.ravel()
    for start in np.flatnonzero(flat):
        if lab[start]:
            continue
        label += 1
        lab[start] = label
        size = 0
        queue = deque([start])
        while queue:
            index = queue.popleft()
            size += 1
            y, x = divmod(index, width)
            for neighbour, ok in ((index - width, y > 0), (index + width, y < height - 1),
                                  (index - 1, x > 0), (index + 1, x < width - 1)):
                if ok and flat[neighbour] and not lab[neighbour]:
                    lab[neighbour] = label
                    queue.append(neighbour)
        if size > best_size:
            best_label, best_size = label, size
    return labels == best_label if best_label else np.zeros_like(mask)


def holes(region: np.ndarray) -> np.ndarray:
    """The dark pixels that a region encloses: not connected to the border of the frame.

    Only the bounding box of the region (with a margin of one pixel) is searched:
    a pixel outside it cannot be enclosed.
    """
    ys, xs = np.nonzero(region)
    result = np.zeros(region.shape, dtype=bool)
    if len(ys) == 0:
        return result
    y0, y1 = max(ys.min() - 1, 0), min(ys.max() + 2, region.shape[0])
    x0, x1 = max(xs.min() - 1, 0), min(xs.max() + 2, region.shape[1])
    result[y0:y1, x0:x1] = _holes_in_box(np.pad(region[y0:y1, x0:x1], 1, constant_values=False))[1:-1, 1:-1]
    return result


def _holes_in_box(region: np.ndarray) -> np.ndarray:
    height, width = region.shape
    outside = np.zeros(region.shape, dtype=bool)
    dark = ~region
    queue = deque()
    for y in range(height):
        for x in (0, width - 1):
            if dark[y, x] and not outside[y, x]:
                outside[y, x] = True
                queue.append((y, x))
    for x in range(width):
        for y in (0, height - 1):
            if dark[y, x] and not outside[y, x]:
                outside[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and dark[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                queue.append((ny, nx))
    return dark & ~outside


def edge_pixels(region: np.ndarray) -> np.ndarray:
    """(x, y) of the pixels of a region that touch a pixel outside it (or the frame edge is excluded)."""
    padded = np.pad(region, 1, constant_values=False)
    inner = (padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    edge = region & ~inner
    # The border of the frame is not the limb: a sun cut off by the frame edge
    edge[0, :] = edge[-1, :] = False
    edge[:, 0] = edge[:, -1] = False
    ys, xs = np.nonzero(edge)
    return np.column_stack((xs, ys)).astype(np.float64)


def _fall_directions(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Unit vectors at edge pixels, pointing the way the (smoothed) brightness falls."""
    padded = np.pad(image, 1, mode="edge")
    smooth = sum(padded[dy:dy + image.shape[0], dx:dx + image.shape[1]] for dy in range(3) for dx in range(3)) / 9
    gy, gx = np.gradient(smooth)
    xs, ys = points[:, 0].astype(int), points[:, 1].astype(int)
    fall = -np.column_stack((gx[ys, xs], gy[ys, xs]))
    norm = np.hypot(fall[:, 0], fall[:, 1])
    norm[norm == 0] = 1.0
    return fall / norm[:, None]


def _on_limb(points: np.ndarray, falls: np.ndarray, cx, cy, radius, tolerance: float) -> np.ndarray:
    """Which edge pixels lie on the limb of circles (cx, cy, radius): near it, and darker outward.

    cx, cy and radius may be arrays of shape (n, 1) for n circles at once.
    """
    dx, dy = points[..., 0] - cx, points[..., 1] - cy
    distance = np.hypot(dx, dy)
    with np.errstate(divide="ignore", invalid="ignore"):
        outward_cos = (dx * falls[..., 0] + dy * falls[..., 1]) / distance
    return (np.abs(distance - radius) < tolerance) & (outward_cos >= MIN_OUTWARD_COS)


def _circles_through(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> tuple:
    """Centres and radii of the circles through triples of points (arrays of shape (n, 2))."""
    ax, ay = p1[:, 0], p1[:, 1]
    bx, by = p2[:, 0], p2[:, 1]
    cx, cy = p3[:, 0], p3[:, 1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    with np.errstate(divide="ignore", invalid="ignore"):
        ux = ((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay) + (cx ** 2 + cy ** 2) * (ay - by)) / d
        uy = ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx) + (cx ** 2 + cy ** 2) * (bx - ax)) / d
    radius = np.hypot(ax - ux, ay - uy)
    return ux, uy, radius


def fit_centre(points: np.ndarray, radius: float, x0: float, y0: float) -> tuple:
    """Least-squares centre of a circle of known radius through points (Gauss-Newton from x0, y0)."""
    cx, cy = float(x0), float(y0)
    for _ in range(20):
        dx, dy = points[:, 0] - cx, points[:, 1] - cy
        distance = np.hypot(dx, dy)
        distance[distance == 0] = 1e-9
        residual = distance - radius
        jacobian = -np.column_stack((dx / distance, dy / distance))
        step, *_ = np.linalg.lstsq(jacobian, -residual, rcond=None)
        cx, cy = cx + step[0], cy + step[1]
        if np.hypot(*step) < 1e-4:
            break
    return cx, cy, float(radius)


#: A short arc with more than this share of its limb saturated is glare (beads, diamond ring)
MAX_SATURATED_SHORT_ARC = 0.3

#: Below this much limb, the circle is fitted with the radius held at the known one
SHORT_ARC_DEG = 150.0


def fit_circle(points: np.ndarray) -> tuple:
    """Least-squares circle (Kåsa) through points: (x, y, radius)."""
    x, y = points[:, 0], points[:, 1]
    a = np.column_stack((x, y, np.ones_like(x)))
    b = x ** 2 + y ** 2
    (c0, c1, c2), *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy = c0 / 2, c1 / 2
    return float(cx), float(cy), float(np.sqrt(max(c2 + cx ** 2 + cy ** 2, 0.0)))


def _bin_deg(radius: float) -> float:
    """Width of the angle bins for limb pixels on a circle of this radius: about 3 pixels of limb, at least 5°."""
    return float(min(30.0, max(5.0, np.degrees(3.0 / max(radius, 1e-6)))))


def _covered_bins(points: np.ndarray, cx: float, cy: float, bin_deg: float) -> np.ndarray:
    angles = np.degrees(np.arctan2(points[:, 1] - cy, points[:, 0] - cx)) % 360
    return np.unique((angles // bin_deg).astype(int))


def _arc_deg(points: np.ndarray, cx: float, cy: float, radius: float) -> float:
    """How much of a circle the points cover, in degrees."""
    bin_deg = _bin_deg(radius)
    return bin_deg * len(_covered_bins(points, cx, cy, bin_deg))


def _inside_fraction(region_points: np.ndarray, cx: float, cy: float, radius: float) -> float:
    distance = np.hypot(region_points[:, 0] - cx, region_points[:, 1] - cy)
    return float(np.mean(distance <= radius + INLIER_TOLERANCE))


def _sample(grey: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of a frame at (xs, ys); NaN outside it."""
    height, width = grey.shape
    inside = (xs >= 0) & (ys >= 0) & (xs <= width - 1) & (ys <= height - 1)
    x = np.clip(xs, 0, width - 1.001)
    y = np.clip(ys, 0, height - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    g = grey.astype(np.float64)
    value = (g[y0, x0] * (1 - fx) * (1 - fy) + g[y0, x0 + 1] * fx * (1 - fy)
             + g[y0 + 1, x0] * (1 - fx) * fy + g[y0 + 1, x0 + 1] * fx * fy)
    return np.where(inside, value, np.nan)


#: Radial profiles: from this share of the radius inside the limb to this share outside
PROFILE_INSIDE, PROFILE_OUTSIDE = 0.12, 0.12
#: Step along a profile, in pixels of the full frame
PROFILE_STEP = 0.25


def refine_limb(grey: np.ndarray, cx: float, cy: float, radius: float, angles_deg: np.ndarray,
                fixed_radius: Optional[float] = None) -> Optional[tuple]:
    """Fit the circle again to limb points found to a fraction of a pixel in the full frame.

    Along each angle, the limb is where the brightness drops through halfway
    between the limb (the brightest value just inside) and the sky (the median
    just outside).  Returns (x, y, radius, residual, edge width) or None; the
    edge width is the median distance from 75 % to 25 % of the step, followed by
    the share of the profiles whose peak is saturated.  With
    ``fixed_radius``, only the centre is fitted (for a short arc).
    """
    span = np.arange(-PROFILE_INSIDE * radius, PROFILE_OUTSIDE * radius, PROFILE_STEP)
    angles = np.radians(angles_deg)
    cos, sin = np.cos(angles)[:, None], np.sin(angles)[:, None]
    distance = radius + span[None, :]
    profiles = _sample(grey, cx + distance * cos, cy + distance * sin)
    limb_points = []
    widths = []
    saturated = 0
    saturation = 250.0 if grey.max() <= 255 else 0.98 * float(grey.max())
    outer = span > 0.4 * PROFILE_OUTSIDE * radius
    for angle_cos, angle_sin, profile in zip(cos[:, 0], sin[:, 0], profiles):
        if np.isnan(profile).any():
            continue
        sky = np.median(profile[outer])
        peak = profile[~outer].max()
        saturated += peak >= saturation
        if peak - sky < 8:
            continue
        level = (peak + sky) / 2
        above = profile >= level
        # The last crossing from bright to dark, going outward
        crossings = np.flatnonzero(above[:-1] & ~above[1:])
        if len(crossings) == 0:
            continue
        i = crossings[-1]
        fraction = (profile[i] - level) / (profile[i] - profile[i + 1])
        r = radius + span[i] + fraction * PROFILE_STEP
        limb_points.append((cx + r * angle_cos, cy + r * angle_sin))
        high = np.flatnonzero(profile >= sky + 0.75 * (peak - sky))
        low = np.flatnonzero(profile >= sky + 0.25 * (peak - sky))
        if len(high) and len(low):
            widths.append((low[-1] - high[-1]) * PROFILE_STEP)
    if len(limb_points) < 12:
        return None
    points = np.array(limb_points)
    keep = np.ones(len(points), dtype=bool)
    for _ in range(3):
        if fixed_radius:
            x, y, r = fit_centre(points[keep], fixed_radius, cx, cy)
        else:
            x, y, r = fit_circle(points[keep])
        error = np.abs(np.hypot(points[:, 0] - x, points[:, 1] - y) - r)
        limit = max(3 * np.sqrt(np.mean(error[keep] ** 2)), 0.5)
        new_keep = error <= limit
        if new_keep.sum() < 12 or (new_keep == keep).all():
            break
        keep = new_keep
    residual = float(np.sqrt(np.mean(error[keep] ** 2)))
    return (x, y, r, residual, float(np.median(widths)) if widths else float("inf"),
            saturated / len(profiles))


def _no_sun(reason: str) -> None:
    """No sun in this frame: say why in the debug log."""
    logger.debug("No sun found: %s", reason)
    return None


def sun_channel(frame: np.ndarray) -> np.ndarray:
    """The image to look for the sun in: the brightest channel of a colour frame, or the grey frame itself."""
    frame = np.asarray(frame)
    if frame.ndim == 3:
        return frame[..., :3].max(axis=2)
    return frame


def find_sun(grey: np.ndarray, radius_hint: Optional[float] = None, seed: int = 0) -> Optional[SunFix]:
    """Find the sun's disk in a frame: grey (2-D) or colour (height × width × 3 or 4), any numeric type.

    Args:
        - grey: The frame
        - radius_hint: The radius of the sun in pixels of the full frame, when it
                       is known (from earlier fixes): only circles within
                       RADIUS_HINT_TOLERANCE of it are accepted, and shorter arcs
                       are trusted.  Makes thin crescents reliable.
        - seed: Seed of the random triples, so a frame always gives the same answer

    Returns: The sun, or None when no disk is found (totality, no sun, no contrast).
    """
    grey = sun_channel(grey)
    if grey.ndim != 2 or min(grey.shape) < 16:
        return _no_sun("not an image")
    image, factor = _reduce(grey)
    threshold = otsu_threshold(image)
    if threshold is None:
        return _no_sun("no contrast")
    region = largest_region(image > threshold)
    region_size = int(region.sum())
    if region_size < SMALL_REGION and factor > 1:
        # A crescent of a pixel or two wide disappears in the reduced frame: look in the full one.
        # Cheap, because the region search only visits the few bright pixels.
        image, factor = grey.astype(np.float32), 1
        threshold = otsu_threshold(image)
        if threshold is None:
            return _no_sun("no contrast")
        region = largest_region(image > threshold)
        region_size = int(region.sum())
    if region_size < np.pi * MIN_RADIUS ** 2 / 4:
        return _no_sun("bright region too small")
    points = edge_pixels(region)
    if len(points) < 12:
        return _no_sun("too few edge pixels")
    ys, xs = np.nonzero(region)
    region_points = np.column_stack((xs, ys)).astype(np.float64)
    if len(region_points) > 4000:
        region_points = region_points[np.random.default_rng(seed).choice(len(region_points), 4000, replace=False)]

    if radius_hint:
        r_min = (1 - RADIUS_HINT_TOLERANCE) * radius_hint / factor
        r_max = (1 + RADIUS_HINT_TOLERANCE) * radius_hint / factor
    else:
        r_min, r_max = MIN_RADIUS, max(image.shape)

    # RANSAC over random triples, all at once
    rng = np.random.default_rng(seed)
    triples = rng.integers(0, len(points), size=(RANSAC_ITERATIONS, 3))
    ux, uy, radius = _circles_through(points[triples[:, 0]], points[triples[:, 1]], points[triples[:, 2]])
    ok = np.isfinite(ux) & np.isfinite(uy) & (radius >= r_min) & (radius <= r_max)
    best = None
    best_score = 0
    candidates = np.flatnonzero(ok)
    if len(candidates) == 0:
        return _no_sun("no circle of a possible size")
    # Count the edge pixels on the limb of each candidate circle
    falls = _fall_directions(image, points)
    scores = _on_limb(points[None, :, :], falls[None, :, :], ux[candidates, None], uy[candidates, None],
                      radius[candidates, None], INLIER_TOLERANCE).sum(axis=1)
    for index in np.argsort(-scores):
        if scores[index] <= best_score or scores[index] < 12:
            break
        i = candidates[index]
        # The sun's circle has the bright region inside it; the moon's does not
        if _inside_fraction(region_points, ux[i], uy[i], radius[i]) < MIN_INSIDE:
            continue
        best, best_score = i, scores[index]
        break
    if best is None:
        return _no_sun("no circle with the bright region inside it")

    # Refine on the pixels on the circle, twice: the first fit can move the circle
    cx, cy, r = ux[best], uy[best], radius[best]
    for _ in range(2):
        on = _on_limb(points, falls, cx, cy, r, INLIER_TOLERANCE * 1.5)
        if on.sum() < 12:
            return _no_sun("too few limb pixels")
        cx, cy, r = fit_circle(points[on])
    if _inside_fraction(region_points, cx, cy, r) < MIN_INSIDE:
        return _no_sun("the refined circle leaves bright pixels outside")
    limb = points[on]
    # The moon inside the corona is a hole in the "disk"; sunspots are small ones
    if holes(region).sum() > MAX_HOLE * np.pi * r ** 2:
        return _no_sun("a dark hole inside: the moon in the corona")
    arc = min(360.0, _arc_deg(limb, cx, cy, r))
    min_arc = MIN_ARC_DEG if radius_hint else MIN_ARC_WITHOUT_HINT_DEG
    if arc < min_arc:
        return _no_sun(f"only {arc:.0f}° of limb" + ("" if radius_hint else " and the radius is not known"))
    residual = float(np.sqrt(np.mean((np.hypot(limb[:, 0] - cx, limb[:, 1] - cy) - r) ** 2))) * factor
    bright_fraction = min(1.0, region_size / (np.pi * r ** 2))

    # Back to full-frame pixels: the centre of reduced pixel i is at full pixel i*f + (f-1)/2
    offset = (factor - 1) / 2
    x, y, radius = cx * factor + offset, cy * factor + offset, r * factor

    # Only along the sun's own limb, not across the moon's edge: in the bins of
    # the limb found, without the bins at the ends of the arc (the cusps)
    bin_deg = _bin_deg(r)
    count = int(round(360 / bin_deg))
    bins = set(int(b) % count for b in _covered_bins(limb, cx, cy, bin_deg))
    inner = [b for b in bins if (b - 1) % count in bins and (b + 1) % count in bins]
    angles = np.concatenate([np.arange(b * bin_deg, (b + 1) * bin_deg, 1.0) for b in inner]) if inner else np.array([])
    short = radius_hint is not None and arc < SHORT_ARC_DEG
    if short:
        # A short arc pins the centre down badly when the radius is free as well
        x, y, radius = *fit_centre(limb * factor + offset, radius_hint, x, y)[:2], radius_hint
    refined = refine_limb(grey, x, y, radius, angles, fixed_radius=radius_hint if short else None)
    # Without the refinement the edge cannot be checked, and a soft edge is the corona: no answer rather
    # than a wrong one
    if refined is None:
        return _no_sun("the limb could not be measured in the full frame")
    if abs(refined[2] - radius) >= 0.15 * radius or np.hypot(refined[0] - x, refined[1] - y) >= 2 * factor:
        return _no_sun(f"the full-frame limb disagrees: r {refined[2]:.1f} for {radius:.1f}, "
                       f"centre moved {np.hypot(refined[0] - x, refined[1] - y):.1f} px")
    x, y, radius, residual, edge_width, saturated = refined
    if arc < SHORT_ARC_DEG and saturated > MAX_SATURATED_SHORT_ARC:
        return _no_sun(f"a short, overexposed arc ({saturated:.0%} saturated): glare of the beads or the diamond ring")
    if radius_hint and abs(radius - radius_hint) > RADIUS_HINT_TOLERANCE * radius_hint:
        return _no_sun(f"radius {radius:.1f} px, not the {radius_hint:.1f} px of the sun")
    if edge_width > max(MIN_EDGE_LIMIT, MAX_EDGE_WIDTH * radius):
        return _no_sun(f"soft edge ({edge_width:.1f} px): corona, not the limb")
    return SunFix(x=x, y=y, radius=radius, arc_deg=arc, residual=residual, bright_fraction=bright_fraction,
                  edge_width=edge_width)
