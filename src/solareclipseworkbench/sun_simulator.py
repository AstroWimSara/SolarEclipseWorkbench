"""A simulated camera behind a mount: frames with the sun where the mount points.

For developing and testing the calibration and the centring without a mount,
a camera or the sun (the simulated mount of ``indi_simulator`` points at the sun
when it starts).  The sun stays at the sky position it has when the camera is
made; the frame follows the pointing of the mount, so a nudge or a guide pulse
moves the sun in the frame, and a mount that does not track lets it drift.

The camera can be turned and mirrored, as the optics of a real setup do, so
the calibration has to find out how the axes of the mount lie in the frame.

The sun is drawn (a limb-darkened disk, optionally with a moon), or, with
``EclipseImages``, cut from real frames of the 2026 eclipse in the phase of the
simulated time: the crescent of five minutes before C2 at C2 - 5 min, the
corona during totality (img/eclipse, made by scripts/make_eclipse_images.py).
"""

import io
import json
import math
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image

#: Apparent radius of the sun, in arcseconds
SUN_RADIUS_ARCSEC = 960.0

#: The eclipse images of the simulated camera
IMAGES = Path(__file__).parent / "img" / "eclipse"

#: Shown when the simulated time is not known (no total eclipse here): a crescent 20 min before C2
DEFAULT_FROM_C2 = -1250.0

#: Set by the GUI: () → (seconds from C2, seconds from C3) of the simulated time, or None.
#: Picks the phase the simulated camera shows.
ECLIPSE_CLOCK: Optional[Callable[[], Optional[tuple]]] = None


class EclipseImages:
    """Frames of a real eclipse around the sun, to paste where the simulated mount points."""

    def __init__(self, folder: Path = IMAGES):
        self.folder = Path(folder)
        manifest = json.loads((self.folder / "eclipse.json").read_text())
        self.radius = float(manifest["radius"])
        self.frames = manifest["frames"]
        self._cache: dict = {}
        self._lock = threading.Lock()

    @classmethod
    def available(cls, folder: Path = IMAGES) -> bool:
        return (Path(folder) / "eclipse.json").exists()

    def pick(self, from_c2: Optional[float] = None, from_c3: Optional[float] = None) -> dict:
        """The frame closest to this moment: by C2 before the middle of totality, by C3 after it."""
        if from_c2 is None or from_c3 is None:
            from_c2, from_c3 = DEFAULT_FROM_C2, None
        if from_c3 is None or from_c2 + from_c3 < 0:
            return min(self.frames, key=lambda e: abs(e["from_c2"] - from_c2))
        return min(self.frames, key=lambda e: abs(e["from_c3"] - from_c3))

    def image(self, entry: dict) -> Image.Image:
        with self._lock:
            image = self._cache.get(entry["file"])
            if image is None:
                image = Image.open(self.folder / entry["file"]).convert("RGB")
                image.load()
                self._cache[entry["file"]] = image
            return image

    def render(self, width: int, height: int, x: float, y: float, radius: float, entry: dict,
               noise: float = 2.0, rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """An RGB frame with the frame's sun centred on (x, y) and scaled to ``radius``."""
        image = self.image(entry)
        scale = radius / self.radius
        border = np.concatenate([np.asarray(image)[0], np.asarray(image)[-1]])
        sky = tuple(int(v) for v in np.median(border, axis=0))
        # Output pixel (u, v) shows image pixel ((u - x) / scale + ex, (v - y) / scale + ey)
        data = (1 / scale, 0, entry["x"] - x / scale, 0, 1 / scale, entry["y"] - y / scale)
        frame = np.asarray(image.transform((width, height), Image.Transform.AFFINE, data,
                                           resample=Image.Resampling.BILINEAR, fillcolor=sky), dtype=np.float32)
        if noise:
            rng = rng if rng is not None else np.random.default_rng()
            frame = frame + rng.normal(0, noise, frame.shape[:2])[..., None].astype(np.float32)
        return np.clip(frame, 0, 255).astype(np.uint8)


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
        - images: EclipseImages to show the real sun instead of drawing one
        - clock: () → (seconds from C2, seconds from C3) or None: the phase the images show
    """

    def __init__(self, mount, width: int = 1000, height: int = 667, arcsec_per_pixel: float = 16.0,
                 rotation_deg: float = 0.0, mirrored: bool = False, moon: Optional[tuple] = None,
                 offset: tuple = (0.0, 0.0), noise: float = 3.0, seed: int = 0,
                 images: Optional[EclipseImages] = None, clock: Optional[Callable[[], Optional[tuple]]] = None):
        self.images = images
        self.clock = clock
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
        if self.images is not None:
            moment = None
            if self.clock is not None:
                try:
                    moment = self.clock()
                except Exception:
                    moment = None
            entry = self.images.pick(*(moment or (None, None)))
            with self._lock:
                frame = self.images.render(self.width, self.height, x, y, self.radius_px, entry, noise=self.noise,
                                           rng=self._rng)
            return time.monotonic(), frame
        moon = None
        if self.moon is not None:
            moon = (x + self.moon[0] * self.radius_px, y + self.moon[1] * self.radius_px, 1.03 * self.radius_px)
        with self._lock:
            frame = render_sun(self.width, self.height, x, y, self.radius_px, moon=moon, noise=self.noise,
                               rng=self._rng)
        return time.monotonic(), frame


#: The simulated camera of each simulated mount, for the virtual camera's live view
_LIVE_VIEW_CAMERAS: dict = {}


def simulated_live_view_jpeg() -> Optional[bytes]:
    """A live-view frame (JPEG) of the sun where the connected simulated mount points, or None.

    For the virtual camera in simulation mode: with a simulated mount connected,
    its live view shows the sun, a little off-centre and turned, so the
    calibration and the centring can be tried without a mount, a camera or the sun.
    The sun is the real one of the 2026 eclipse, in the phase of the simulated
    time (ECLIPSE_CLOCK).
    """
    from solareclipseworkbench.hardware_registry import get_hardware

    mount = get_hardware('mount')
    if mount is None or getattr(mount, "_simulator", None) is None or not mount.connected:
        return None
    camera = _LIVE_VIEW_CAMERAS.get(id(mount))
    if camera is None or camera.mount is not mount:
        _LIVE_VIEW_CAMERAS.clear()
        images = EclipseImages() if EclipseImages.available() else None
        camera = SimulatedSunCamera(mount, width=960, height=640, rotation_deg=20, offset=(12, -8), noise=2.0,
                                    images=images, clock=lambda: ECLIPSE_CLOCK() if ECLIPSE_CLOCK else None)
        _LIVE_VIEW_CAMERAS[id(mount)] = camera
    latest = camera.latest()
    if latest is None:
        return None
    frame = latest[1]
    if frame.ndim == 2:
        # A drawn sun: yellowish-white, as through a filter
        frame = np.stack((frame, (frame * 0.92).astype(np.uint8), (frame * 0.75).astype(np.uint8)), axis=2)
    rgb = frame
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()
