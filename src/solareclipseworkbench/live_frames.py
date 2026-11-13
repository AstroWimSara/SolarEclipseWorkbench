"""Live-view frames for the calibration and the centring.

``LiveFrames`` keeps the newest live-view frame, decoded, with the time it
arrived.  The calibration and the centring ask it for ``latest()``.  Frames are
pushed into it as JPEG bytes: by the `Live View` window (which already gets
them, so no extra USB traffic) or, without the GUI, by a ``LiveViewThread`` of
its own (``camera_frames``, for the bench console).
"""

import io
import logging
import threading
import time
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class LiveFrames:
    """The newest live-view frame: ``latest()`` → (time.monotonic(), RGB array) or None."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latest: Optional[tuple] = None
        self._jpeg: Optional[bytes] = None
        self._jpeg_time = 0.0
        # Counts clear(), so a frame being decoded while the live view closes is not kept after it
        self._generation = 0
        #: Name of the camera the frames come from
        self.camera = ""

    def push(self, jpeg: bytes, camera: Optional[str] = None) -> None:
        """A new frame arrived (any thread).  It is decoded when asked for, not now."""
        with self._lock:
            self._jpeg, self._jpeg_time = bytes(jpeg), time.monotonic()
            if camera is not None:
                self.camera = camera

    def clear(self) -> None:
        """Forget the frames (the live view closed): old frames must not count as the sun now."""
        with self._lock:
            self._jpeg, self._latest = None, None
            self._generation += 1

    def push_array(self, frame: np.ndarray) -> None:
        """A new frame that is already decoded."""
        with self._lock:
            self._jpeg = None
            self._latest = (time.monotonic(), frame)

    def latest(self) -> Optional[tuple]:
        with self._lock:
            jpeg, when, generation = self._jpeg, self._jpeg_time, self._generation
            if jpeg is None:
                return self._latest
            self._jpeg = None
        try:
            frame = np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"))
        except Exception:
            logger.debug("A live-view frame could not be decoded", exc_info=True)
            return self._latest
        with self._lock:
            if self._generation != generation:
                # Cleared while decoding (the live view closed): an old frame must not count as the sun now
                return self._latest
            if self._latest is None or when >= self._latest[0]:
                # Not when another thread decoded a newer frame meanwhile
                self._latest = (when, frame)
            return self._latest


def camera_frames(camera, interval_s: float = 1.0) -> tuple:
    """Start a live view on a camera (from camera.get_camera_dict()) that feeds a LiveFrames.

    Returns (frames, thread); call ``thread.stop()`` when done.
    """
    from solareclipseworkbench.camera import LiveViewThread

    frames = LiveFrames()
    thread = LiveViewThread(camera=camera, frame_callback=frames.push, interval_s=interval_s)
    thread.start()
    return frames, thread
