"""A simulated camera behind a mount: frames with the sun where the mount points.

For developing and testing the calibration and the centring without a mount,
a camera or the sun (the simulated mount of ``indi_simulator`` points at the sun
when it starts).  The sun stays at the sky position it has when the camera is
made; the frame follows the pointing of the mount, so a nudge or a guide pulse
moves the sun in the frame, and a mount that does not track lets it drift.

The camera can be turned and mirrored, as the optics of a real setup do, so
the calibration has to find out how the axes of the mount lie in the frame.
"""

import math
import threading
import time
from typing import Optional

import numpy as np

#: Apparent radius of the sun, in arcseconds
SUN_RADIUS_ARCSEC = 960.0


def render_sun(width: int, height: int, x: float, y: float, radius: float, moon: Optional[tuple] = None,
               sky: float = 12.0, noise: float = 3.0, rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """A grey frame (uint8) with a limb-darkened sun through a filter.

    Args:
        - x, y, radius: The sun, in pixels
        - moon: (x, y, radius) of the moon in pixels, or None
    """
    rng = rng if rng is not None else np.random.default_rng()
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    r = np.hypot(xx - x, yy - y) / radius
    image = np.full((height, width), sky, dtype=np.float32)
    disk = r <= 1
    mu = np.sqrt(np.clip(1 - r[disk] ** 2, 0, 1))
    image[disk] = 40 + 190 * (1 - 0.6 * (1 - mu))
    if moon is not None:
        mx, my, mr = moon
        image[np.hypot(xx - mx, yy - my) <= mr] = sky
    if noise:
        image += rng.normal(0, noise, image.shape).astype(np.float32)
    return np.clip(image, 0, 255).astype(np.uint8)


class SimulatedSunCamera:
    """Frames of the sun as a camera on the given mount would see it.

    Args:
        - mount: A mount.Mount (its position is read for every frame)
        - width, height: Size of the frames
        - arcsec_per_pixel: Scale; 16″/px makes a sun of 60 px radius, as a 600 mm
                            lens on a full-frame body in a 1000 px live view
        - rotation_deg: How far the camera turns the image, anticlockwise on the screen
                        (0: north up and east left, as the sky looks)
        - mirrored: Whether the optics mirror the image (a diagonal, for instance)
        - moon: Moon position relative to the sun, (dx, dy) in sun radii in the
                frame, or None
        - offset: Where the sun starts in the frame, in pixels from the centre
    """

    def __init__(self, mount, width: int = 1000, height: int = 667, arcsec_per_pixel: float = 16.0,
                 rotation_deg: float = 0.0, mirrored: bool = False, moon: Optional[tuple] = None,
                 offset: tuple = (0.0, 0.0), noise: float = 3.0, seed: int = 0):
        self.mount = mount
        self.width, self.height = width, height
        self.arcsec_per_pixel = arcsec_per_pixel
        self.rotation = math.radians(rotation_deg)
        self.mirrored = mirrored
        self.moon = moon
        self.offset = offset
        self.noise = noise
        self._rng = np.random.default_rng(seed)
        self._lock = threading.Lock()
        position = mount.position()
        if position is None:
            raise ValueError("the mount does not report its position")
        #: Where the sun is on the sky: where the mount points now
        self.sun_ra_h, self.sun_dec_deg = position

    @property
    def radius_px(self) -> float:
        return SUN_RADIUS_ARCSEC / self.arcsec_per_pixel

    def sun_in_frame(self) -> Optional[tuple]:
        """(x, y) of the sun's centre in the frame for the current pointing of the mount."""
        position = self.mount.position()
        if position is None:
            return None
        ra_h, dec_deg = position
        # The sun relative to the pointing, in arcseconds: east and north on the sky
        d_ra = ((self.sun_ra_h - ra_h + 12.0) % 24.0) - 12.0
        east = d_ra * 15.0 * 3600.0 * math.cos(math.radians(self.sun_dec_deg))
        north = (self.sun_dec_deg - dec_deg) * 3600.0
        # The sky as seen looking up, north up: east is to the left.  Then the
        # camera's rotation (anticlockwise on the screen), and a mirror flips it.
        left, up = -east, north
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        right, up = left * c - up * s, left * s + up * c
        if self.mirrored:
            right = -right
        return (self.width / 2 + self.offset[0] + right / self.arcsec_per_pixel,
                self.height / 2 + self.offset[1] - up / self.arcsec_per_pixel)

    def latest(self) -> Optional[tuple]:
        """(time, frame) of a frame taken now, like the live view provides them."""
        centre = self.sun_in_frame()
        if centre is None:
            return None
        x, y = centre
        moon = None
        if self.moon is not None:
            moon = (x + self.moon[0] * self.radius_px, y + self.moon[1] * self.radius_px, 1.03 * self.radius_px)
        with self._lock:
            frame = render_sun(self.width, self.height, x, y, self.radius_px, moon=moon, noise=self.noise,
                               rng=self._rng)
        return time.monotonic(), frame
