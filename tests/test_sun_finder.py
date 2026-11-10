"""Finding the sun's centre in live-view frames, on synthetic frames of every phase of the eclipse."""
import math

import numpy as np
import pytest

from solareclipseworkbench.sun_finder import find_sun, fit_circle, otsu_threshold


def render(width=960, height=640, sun=(480.0, 320.0), radius=80.0, moon_offset=None, moon_angle_deg=30.0,
           moon_ratio=1.03, noise=3.0, sky=12.0, spots=(), cloud=0.0, corona=False, seed=1):
    """A synthetic live-view frame: a limb-darkened sun through a filter, a moon, noise.

    Args:
        - moon_offset: Distance of the moon's centre from the sun's, in sun radii (None: no moon)
        - moon_angle_deg: Direction of the moon from the sun's centre (0 = right, 90 = down)
        - spots: (dx, dy, r) of sunspots, in pixels from the centre
        - cloud: Strength of a brightness gradient across the frame (thin cloud)
        - corona: Draw the corona instead of the disk (totality: the moon covers all of it)
    """
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float64)
    sx, sy = sun
    r = np.hypot(x - sx, y - sy) / radius
    image = np.full((height, width), sky)
    if corona:
        outside = r > moon_ratio
        image[outside] += 120.0 * (np.clip(r[outside], 1.0, None) - 0.9) ** -2.5
    else:
        mu = np.sqrt(np.clip(1 - r ** 2, 0, 1))
        disk = r <= 1
        image[disk] = 40 + 190 * (1 - 0.6 * (1 - mu[disk]))
        for dx, dy, sr in spots:
            image[np.hypot(x - sx - dx, y - sy - dy) <= sr] = 60
        if moon_offset is not None:
            a = math.radians(moon_angle_deg)
            mx, my = sx + moon_offset * radius * math.cos(a), sy + moon_offset * radius * math.sin(a)
            image[np.hypot(x - mx, y - my) <= moon_ratio * radius] = sky
    if cloud:
        image *= 1 + cloud * (x / width - 0.5)
    image += rng.normal(0, noise, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


def assert_centre(fix, sun, tolerance=1.0):
    assert fix is not None, "the sun was not found"
    assert math.hypot(fix.x - sun[0], fix.y - sun[1]) <= tolerance, (fix.x, fix.y, sun)


# ------------------------------------------------------------------ the full disk


@pytest.mark.parametrize("sun, radius", [((480, 320), 80), ((300, 250), 40), ((620, 330), 200), ((100.5, 90.25), 60)])
def test_the_full_disk(sun, radius):
    fix = find_sun(render(sun=sun, radius=radius), seed=2)
    assert_centre(fix, sun)
    assert fix.radius == pytest.approx(radius, rel=0.04)
    assert fix.arc_deg >= 350
    assert fix.bright_fraction > 0.9


def test_sunspots_and_a_thin_cloud_do_not_move_the_centre():
    sun = (500, 300)
    fix = find_sun(render(sun=sun, spots=((20, -10, 6), (-35, 25, 4)), cloud=0.5))
    assert_centre(fix, sun)


def test_a_small_frame():
    sun = (160, 120)
    fix = find_sun(render(width=320, height=240, sun=sun, radius=50))
    assert_centre(fix, sun, tolerance=0.8)


# --------------------------------------------------------------- partial phases


@pytest.mark.parametrize("offset", [1.9, 1.5, 1.0, 0.6, 0.3, 0.15])
@pytest.mark.parametrize("angle", [0, 75, 160, 250, 330])
def test_the_centre_of_a_crescent_is_the_centre_of_the_sun(offset, angle):
    sun = (470, 330)
    frame = render(sun=sun, radius=90, moon_offset=offset, moon_angle_deg=angle, seed=angle)
    fix = find_sun(frame)
    # The centroid of the bright pixels would be tens of pixels off for the thin crescents
    assert_centre(fix, sun, tolerance=1.5)
    assert fix.radius == pytest.approx(90, rel=0.05)


@pytest.mark.parametrize("angle", range(0, 360, 30))
def test_the_thinnest_crescents_are_found_right_or_not_at_all(angle):
    """A few seconds before C2 the crescent is a sliver: no fix is fine (the centring pauses), a wrong one is not."""
    sun = (480, 320)
    for hint in (None, 90):
        fix = find_sun(render(sun=sun, radius=90, moon_offset=0.08, moon_angle_deg=angle, seed=angle),
                       radius_hint=hint)
        if fix is not None:
            assert_centre(fix, sun, tolerance=2.0)


def test_the_diamond_ring_has_no_disk():
    frame = render(corona=True).astype(np.int32)
    y, x = np.mgrid[0:640, 0:960]
    frame[np.hypot(x - 480 - 60, y - 320 - 75) <= 9] = 255        # the bead on the limb
    assert find_sun(frame.clip(0, 255).astype(np.uint8)) is None


def test_the_centroid_of_a_crescent_is_far_off():
    """Why a circle is fitted: the centre of the bright pixels moves with the moon."""
    sun = (480, 320)
    frame = render(sun=sun, radius=90, moon_offset=0.6, moon_angle_deg=0, noise=0)
    ys, xs = np.nonzero(frame > 100)
    assert abs(xs.mean() - sun[0]) > 30
    assert_centre(find_sun(frame), sun)


# ------------------------------------------------------------- no sun to find


def test_totality_has_no_disk():
    assert find_sun(render(corona=True)) is None


@pytest.mark.parametrize("frame", [
    np.full((480, 640), 20, dtype=np.uint8),                                  # clouded out / lens cap
    np.random.default_rng(0).normal(40, 3, (480, 640)).clip(0, 255).astype(np.uint8),
    np.full((480, 640), 255, dtype=np.uint8),                                 # filter off, overexposed
    np.zeros((10, 10), dtype=np.uint8),
])
def test_no_sun(frame):
    assert find_sun(frame) is None


def test_a_reflection_smaller_than_the_sun_is_ignored():
    sun = (500, 320)
    frame = render(sun=sun, radius=80).astype(np.int32)
    frame[50:70, 50:90] = 230          # a bright reflection in a corner
    assert_centre(find_sun(frame.astype(np.uint8)), sun)


def test_the_same_frame_gives_the_same_answer():
    frame = render(moon_offset=0.5)
    assert find_sun(frame) == find_sun(frame)


# ----------------------------------------------------------------- the pieces


def test_otsu_splits_two_levels():
    image = np.concatenate((np.full(1000, 20.0), np.full(500, 200.0)))
    assert 20 < otsu_threshold(image) < 200
    assert otsu_threshold(np.full(100, 7.0)) is None


def test_least_squares_circle():
    angles = np.linspace(0, math.pi, 50)
    points = np.column_stack((10 + 5 * np.cos(angles), -3 + 5 * np.sin(angles)))
    assert fit_circle(points) == pytest.approx((10, -3, 5))
