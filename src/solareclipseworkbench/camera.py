import functools
import locale
import logging
import threading
import time

import gphoto2
import gphoto2 as gp
from datetime import datetime
import os

from gphoto2 import Camera
from abc import ABC, abstractmethod
from typing import Any, Tuple, Optional
from solareclipseworkbench import configuration


class CameraError(Exception):
    pass


def _is_sony_model(name: str) -> bool:
    """Return True when a camera model string represents a Sony body.

    gphoto2 may report Sony cameras either with an explicit "Sony" prefix
    (for example "Sony Alpha-A7 IV") or as ILCE model codes
    (for example "ILCE-7M5"). Treat both as Sony so vendor-specific
    behavior is applied consistently.
    """
    upper_name = (name or "").upper()
    return "SONY" in upper_name or upper_name.startswith("ILCE-")


def _is_sony_camera_instance(camera: object) -> bool:
    """Return True when a camera object represents a Sony body."""
    vendor = str(getattr(camera, 'vendor', '') or '').upper()
    name = str(getattr(camera, 'name', '') or '')
    return vendor == 'SONY' or _is_sony_model(name)


def _set_gp_config(camera, config, context):
    """Set camera config using underlying gphoto object when wrapped by adapter."""
    target = camera._camera if hasattr(camera, '_camera') else camera
    return gp.gp_camera_set_config(target, config, context)


def _normalise_aperture(value: str) -> str:
    """Normalise an aperture string to the format gphoto2 camera drivers expect.

    Whole-number f-stops must be passed without a decimal point (e.g. "8" not
    "8.0") because gphoto2 matches the string exactly against the widget's
    choice list. Fractional values such as "5.6" or "1.8" are kept as-is.
    """
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
    except ValueError:
        pass
    return value


# Per-camera aperture verification cache.  Maps camera_name -> set of aperture strings
# that have already been checked via a read-back round-trip.  Once an aperture value
# has been verified (or a mismatch has been warned about) for a given camera, subsequent
# shots skip the extra USB get_config call to avoid adding latency to tight sequences.
_aperture_verified: dict[str, set] = {}


class CameraSettings:

    def __init__(self, camera_name: str, shutter_speed: str, aperture: str, iso: int):
        """ Initialise new camera settings.

        Args:
            - camera_name: Name of the camera
            - shutter_speed: Exposure time [s], e.g. "1/2000".
            - aperture: Aperture (f-number), e.g. 5.6.
            - iso: ISO-value.
        """
        self.camera_name = camera_name
        self.shutter_speed = shutter_speed
        self.aperture = _normalise_aperture(str(aperture))
        self.iso = iso


class BaseCamera(ABC):
    """Abstract base camera class. Implementations should provide the
    same public surface so higher-level code can use any camera
    interchangeably.
    """

    def __init__(self, name: str = ""):
        self.name = name
        self._connected = False
        # Serialises concurrent APScheduler threads that target the same camera.
        # gphoto2 / libgphoto2 is not thread-safe: simultaneous USB operations
        # raise -110 I/O in progress.  Acquiring this lock at the start of every
        # public capture function ensures jobs queue up rather than crash.
        self._usb_lock = threading.RLock()

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def configure(self, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def capture(self):
        pass

    def is_connected(self) -> bool:
        return self._connected


class VirtualCamera(BaseCamera):
    """Simple virtual camera for simulator mode. Returns a plain
    numpy image (H, W, 3) of the configured resolution. This is a
    minimal stub that will be extended with modes (static, scripted,
    generated) in subsequent steps.
    """

    def __init__(self):
        super().__init__(name="VirtualCamera")

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def configure(self, **kwargs: Any) -> None:
        # Accept resolution, mode, source, fps, timestamp_mode
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def capture(self):
        """Return a single RGB frame as a numpy.ndarray (H, W, 3).

        Raises CameraError if not connected.
        """
        if not self._connected:
            raise CameraError("VirtualCamera is not connected")

        return

    # GPhoto-style stubs so the VirtualCamera can be used in places where
    # code expects gphoto Camera-like methods.
    class _WidgetStub:
        def __init__(self, name: str, value: Any):
            self._name = name
            self._value = value

        def get_value(self):
            return self._value

        def set_value(self, v: Any):
            self._value = v

        def get_type(self):
            # Mimic GP_WIDGET_DATE for datetime if value is numeric
            try:
                float(self._value)
                return gp.GP_WIDGET_DATE
            except Exception:
                return gp.GP_WIDGET_TEXT


    class _ConfigStub:
        def __init__(self, parent):
            self.parent = parent

        def get_child_by_name(self, name: str):
            # Return a widget-like stub with plausible defaults
            name = name.lower()
            if name in ('focusmode',):
                return VirtualCamera._WidgetStub(name, 'Manual')
            if name in ('batterylevel',):
                return VirtualCamera._WidgetStub(name, '67%')
            if name in ('autoexposuremodedial',):
                return VirtualCamera._WidgetStub(name, 'Manual')
            if name in ('expprogram',):
                return VirtualCamera._WidgetStub(name, 'M')
            if name in ('datetime', 'datetimeutc', 'd034'):
                # return an ISO formatted string for convenience
                return VirtualCamera._WidgetStub(name, time.strftime('%Y-%m-%d %H:%M:%S'))
            # Generic fallback
            return VirtualCamera._WidgetStub(name, '')

    def get_config(self):
        """Return a minimal config-like object for compatibility with callers
        that expect `get_config().get_child_by_name(name).get_value()`.
        """
        return VirtualCamera._ConfigStub(self)

    def set_config(self, config) -> None:
        # no-op for virtual camera
        return None

    def get_storageinfo(self):
        """Return a list-like object with storage info entries that have
        `freekbytes` and `capacitykbytes` attributes. Values are large
        defaults since virtual camera has plentiful space.
        """
        class _StorageEntry:
            def __init__(self):
                self.freekbytes = 34.9 * 1024 * 1024
                self.capacitykbytes = 64.9 * 1024 * 1024

        return [_StorageEntry()]

    def exit(self):
        # mirror gphoto Camera.exit()
        self.disconnect()

    def capture_preview(self) -> bytes:
        """Return a synthetic 640×480 grey JPEG frame for simulator mode.

        Uses PyQt6 (a hard project dependency) so no extra packages are
        needed.  The frame contains the current timestamp so the preview
        window shows visible activity.
        """
        import datetime as _dt
        from PyQt6.QtCore import QBuffer, QIODevice
        from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

        width, height = 640, 480
        img = QImage(width, height, QImage.Format.Format_RGB888)
        img.fill(QColor(30, 30, 30))

        painter = QPainter(img)
        # Crosshair (same style as LiveViewWindow)
        pen = QPen(QColor(0, 80, 255))
        pen.setWidth(1)
        painter.setPen(pen)
        cx, cy = width // 2, height // 2
        painter.drawLine(cx, 0, cx, height)
        painter.drawLine(0, cy, width, cy)

        # Informational text
        painter.setPen(QPen(QColor(180, 180, 180)))
        painter.setFont(QFont("monospace", 11))
        ts = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        painter.drawText(10, 28, f"VirtualCamera  {ts}")
        painter.drawText(10, 52, "[ simulator mode — no physical camera ]")
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.ReadWrite)
        img.save(buf, "JPEG")
        return bytes(buf.data())


class GPhotoCameraAdapter(BaseCamera):
    """Adapter that wraps a gphoto2 Camera object and exposes a
    `vendor` attribute so higher-level code can branch on vendor-less
    checks via the adapter.
    """

    def __init__(self, gp_camera, name: str):
        super().__init__(name=name)
        self._camera = gp_camera
        if 'Canon' in name:
            self.vendor = 'Canon'
        elif 'Nikon' in name:
            self.vendor = 'Nikon'
        elif _is_sony_model(name):
            self.vendor = 'Sony'
        else:
            self.vendor = None
        logging.debug('GPhotoCameraAdapter created for %s, vendor=%s', name, self.vendor)
        # camera returned by get_camera() is already initialised
        self._connected = True
        # --- Canon EOS R live-view / trigger_capture mode conflict ---
        # gp_camera_capture_preview sets gphoto2's internal eos_remotemode to 1.
        # On EOS R mirrorless, gp_camera_trigger_capture needs eos_remotemode = 0 so
        # it can initialize it to 15 (the correct remote capture mode for EOS R).
        # If capture_preview runs before the first trigger_capture, eos_remotemode is
        # already 1 and trigger_capture skips EOS_SetRemoteMode, causing both
        # capture_preview and trigger_capture to fail.
        # The fix resets the PTP session (exit + init) once, before the first capture,
        # when capture_preview has already been called.  See _reset_canon_eos_ptp_session().
        self._capture_preview_was_called: bool = False  # set by LiveViewThread
        self._first_capture_done: bool = False          # set by take_picture / take_hdr

    def __getattr__(self, item):
        # Delegate attribute access to the underlying gphoto Camera
        return getattr(self._camera, item)

    def connect(self) -> None:
        # Already initialised in get_camera
        self._connected = True

    def disconnect(self) -> None:
        try:
            self._camera.exit()
        except Exception:
            pass
        self._connected = False

    def configure(self, **kwargs: Any) -> None:
        # noop -- configuration typically done via gp widgets in other functions
        return None

    def capture(self, *args, **kwargs):
        return self._camera.capture(*args, **kwargs)


class CanonCamera(GPhotoCameraAdapter):
    """Adapter specialized for Canon cameras. Future Canon-specific
    helpers can be added here."""

    def __init__(self, gp_camera, name: str):
        super().__init__(gp_camera, name)
        self.vendor = 'Canon'


class NikonCamera(GPhotoCameraAdapter):
    """Adapter specialized for Nikon cameras. Future Nikon-specific
    helpers can be added here."""

    def __init__(self, gp_camera, name: str):
        super().__init__(gp_camera, name)
        self.vendor = 'Nikon'


class SonyCamera(GPhotoCameraAdapter):
    """Camera adapter for Sony Alpha bodies in PC Remote mode.

    Sony Alpha bodies save images to the SD card when 'Save Destination' is
    set to 'PC+Camera' or 'Camera Only' in:

        MENU → Network → PC Remote Settings → Save Destination

    'PC+Camera' is recommended: every shot is written to the SD card
    (guaranteed backup) AND a FILE_ADDED event fires over USB so SEW
    can confirm the shot was taken. No image download is attempted.
    """

    def __init__(self, gp_camera, name: str):
        super().__init__(gp_camera, name)
        self.vendor = 'Sony'
        self._bg_downloader = None

    def disconnect(self) -> None:
        """Disconnect; drain any queued camera events first."""
        # 1. MUST stop background activity FIRST to release the USB interface
        self.stop_background_downloader()

        # 2. Now safely drain remaining events without thread contention
        try:
            context = gp.gp_context_new()
            target = self._camera
            _drain_camera_events(target, context, timeout_ms=100, max_events=60)
        except Exception:
            logging.debug('%s: SonyCamera.disconnect() event drain raised (non-fatal)')

        # 3. Close the camera connection
        try:
            self._camera.exit()
        except Exception:
            pass
        self._connected = False

    def start_background_downloader(self) -> None:
        # If a thread exists AND is actively running, don't start another one
        if self._bg_downloader is not None and self._bg_downloader.is_alive():
            return

        # If an old dead thread reference is laying around, clear it first
        self._bg_downloader = None

        try:
            ctx = gp.gp_context_new()
            self._bg_downloader = _SonyBackgroundDownloader(self, ctx)
            self._bg_downloader.daemon = True
            self._bg_downloader.start()
            logging.info('%s: Background Downloader started', self.name)
        except Exception:
            logging.exception('%s: failed to start Background Downloader', self.name)

    def stop_background_downloader(self) -> None:
        if self._bg_downloader is None:
            return

        downloader = self._bg_downloader
        try:
            downloader.stop()
            downloader.join(timeout=2.0)

            # Check if the thread actually exited
            if downloader.is_alive():
                logging.warning('%s: Background Downloader failed to terminate within timeout.', self.name)

                # Force-release the USB lock if the thread is stuck and holding it
                if hasattr(self, '_usb_lock') and self._usb_lock.locked():
                    try:
                        self._usb_lock.release()
                        logging.warning('%s: forced release of _usb_lock after downloader thread timeout.')
                    except RuntimeError:
                        # Raised if release() is called on an unacquired or cross-thread locked RLock/Lock
                        pass
        except Exception as e:
            logging.debug('%s: error stopping Background Downloader (%s)', self.name, e)
        finally:
            self._bg_downloader = None


def _raise_camera_init_error(camera_name: str, error: Exception) -> None:
    """Raise a CameraError with an actionable message for camera initialisation failures.

    Error -53 (GP_ERROR_IO_USB_CLAIM) means another process holds exclusive USB access to
    the device.  Common causes and fixes:

    * **Windows / WSL**: Windows keeps the Microsoft PTP/WIA driver active even after
      ``usbipd attach``.  You must replace that driver with WinUSB so that libusb (and
      therefore gphoto2 inside WSL) can claim the device:
        1. Download and run **Zadig** (https://zadig.akeo.ie) on the Windows host.
        2. Select the camera in the device list (it may show as "MTP USB Device" or the
           camera model name).
        3. Choose **WinUSB** as the target driver and click *Replace Driver*.
        4. Detach and re-attach the camera in usbipd:
               usbipd detach --busid <busid>
               usbipd attach --wsl --busid <busid>
      Sony cameras must also have **PC Remote** mode enabled on the camera itself:
      Menu → Network → PC Remote Settings → PC Remote → On.

    * **macOS**: ``ptpcamerad`` / ``PTPCamera`` grabs the device immediately.  Quit
      Image Capture and Sony Imaging Edge, then:
          sudo pkill -9 PTPCamera

    * **Linux**: A stale gphoto2 process or gvfs-gphoto2-volume-monitor may hold the
      device.  Check with ``gphoto2 --auto-detect`` and kill conflicting processes.
    """
    code = getattr(error, 'code', None)
    if code == -53:
        sony_note = (
            "\nNOTE: Sony cameras must have PC Remote mode enabled on the camera: "
            "Menu → Network → PC Remote Settings → PC Remote → On."
            if _is_sony_model(camera_name) else ''
        )
        raise CameraError(
            f"Cannot claim USB device for '{camera_name}' (gphoto2 error -53 — device busy).\n"
            "On Windows/WSL: run Zadig on the Windows host, select the camera, switch the\n"
            "driver to WinUSB, then re-run: usbipd detach && usbipd attach --wsl.\n"
            "On macOS: quit Image Capture / Sony Imaging Edge, then: sudo pkill -9 PTPCamera.\n"
            "On Linux: check for conflicting processes with: gphoto2 --auto-detect"
            + sony_note
        ) from error
    raise CameraError(
        f"Could not initialise camera '{camera_name}': {error}"
    ) from error


def _find_memory_card_choice(capture_target_widget) -> str:
    """Return the choice string that represents the camera's memory card.

    Scans all available choices for the ``capturetarget`` widget and returns the
    first one whose label contains "card" or starts with "memory" (case-insensitive).
    Falls back to choice index 1 when no card-like label is found, which is the
    conventional position for "Memory card" on Canon and most Nikon bodies.
    """
    try:
        n = gp.check_result(gp.gp_widget_count_choices(capture_target_widget))
        for i in range(n):
            choice = gp.check_result(gp.gp_widget_get_choice(capture_target_widget, i))
            label = choice.lower()
            if 'card' in label or label.startswith('memory'):
                return choice
        # Fallback: index 1 is the traditional "Memory card" position
        if n > 1:
            return gp.check_result(gp.gp_widget_get_choice(capture_target_widget, 1))
        return gp.check_result(gp.gp_widget_get_choice(capture_target_widget, 0))
    except gphoto2.GPhoto2Error:
        # Ultimate fallback: return the literal string used by most cameras
        return 'Memory card'


def _find_closest_shutter_choice(widget, target_speed: str) -> Optional[str]:
    """Return the widget choice string whose shutter speed is closest to *target_speed*.

    *target_speed* can be a fraction string (e.g. ``"1/1250"``) or a whole number
    (e.g. ``"2"`` for 2 s).  The function converts both *target_speed* and each
    widget choice to seconds (as a float) and returns the choice with the smallest
    absolute difference on a logarithmic scale (nearest stop).

    Returns ``None`` when the widget has no parseable choices.
    """
    def _to_seconds(s: str) -> Optional[float]:
        s = s.strip()
        try:
            if '/' in s:
                num, den = s.split('/', 1)
                return float(num) / float(den)
            return float(s)
        except (ValueError, ZeroDivisionError):
            return None

    target_secs = _to_seconds(target_speed)
    if target_secs is None or target_secs <= 0:
        return None

    import math
    best_choice = None
    best_diff = float('inf')
    try:
        n = gp.check_result(gp.gp_widget_count_choices(widget))
        for i in range(n):
            choice = gp.check_result(gp.gp_widget_get_choice(widget, i))
            secs = _to_seconds(choice)
            if secs is None or secs <= 0:
                continue
            diff = abs(math.log(secs) - math.log(target_secs))
            if diff < best_diff:
                best_diff = diff
                best_choice = choice
    except gphoto2.GPhoto2Error:
        pass
    return best_choice


def _find_capturemode_choice(
    widget,
    want_continuous: bool = False,
    custom_keyword: Optional[str] = None,
) -> Optional[str]:
    """Return the choice string for single or continuous capture mode.

    Scans all available choices of the ``capturemode`` widget and returns the
    first one whose label contains *custom_keyword* (if provided), falling back
    to 'single' (or 'continuous' when *want_continuous* is True) if no match is
    found. Returns None when no matching choice is found.
    """
    keyword = (
        custom_keyword
        if custom_keyword is not None
        else ("continuous" if want_continuous else "single")
    )

    try:
        n = gp.check_result(gp.gp_widget_count_choices(widget))
        for i in range(n):
            choice = gp.check_result(gp.gp_widget_get_choice(widget, i))
            if keyword.lower() in choice.lower():
                return choice
    except gphoto2.GPhoto2Error:
        pass

    # If a custom keyword was provided and yielded no match, re-run with default logic
    if custom_keyword is not None:
        return _find_capturemode_choice(
            widget, want_continuous=want_continuous, custom_keyword=None
        )

    return None


# Maximum time a scheduled job may wait for the camera USB lock before it is
# considered too late to be worth taking.  Once a job has waited this long, the
# camera is clearly busy with a previous shot and the queued shot would fire
# well past its scheduled time.  Dropping it preserves timing accuracy for all
# remaining scheduled shots (e.g. C1, C2, MAX) that have not yet been delayed.
# Increase this only if you intentionally schedule shots closer together than
# the camera's own cycle time and accept the resulting timing drift.
_MAX_LOCK_WAIT_S: float = 1.5


def _serialised_on_camera(func):
    """Decorator that serialises access to the physical camera.

    gphoto2 / libgphoto2 is not thread-safe.  APScheduler fires each scheduled
    job in its own thread, so two take_picture jobs scheduled 1 s apart can
    collide on the USB connection and raise -110 I/O in progress.  This
    decorator uses a timed acquire on the per-camera RLock.  If the lock
    cannot be acquired within _MAX_LOCK_WAIT_S the job is silently dropped:
    the camera was still busy from a previous shot and firing now would place
    this shot well past its scheduled time, undermining the timing accuracy
    that eclipse photography requires.
    functools.wraps preserves __name__ so GUI table formatting still works.
    """
    @functools.wraps(func)
    def wrapper(camera, *args, **kwargs):
        acquired = camera._usb_lock.acquire(timeout=_MAX_LOCK_WAIT_S)
        if not acquired:
            logging.warning(
                '%s: dropped — camera was still busy after %.1fs '
                '(shot is too late; timing accuracy preserved)',
                func.__name__, _MAX_LOCK_WAIT_S,
            )
            return
        try:
            return func(camera, *args, **kwargs)
        finally:
            camera._usb_lock.release()
    return wrapper


def _wait_for_capture_complete(target, context, timeout_ms: int = 3000, max_events: int = 30) -> None:
    """Wait until the camera signals GP_EVENT_CAPTURE_COMPLETE after a trigger_capture
    call, then flush any remaining queued events (GP_EVENT_OBJECT_ADDED, etc.).

    This is the correct inter-shot synchronisation point: CAPTURE_COMPLETE means the
    shutter has physically closed and the camera's USB interface is free for the next
    command. Waiting only on TIMEOUT (as _drain_camera_events does) is unreliable
    because CAPTURE_COMPLETE can arrive several hundred milliseconds after the trigger
    on slower bodies (e.g. Canon EOS 80D), causing subsequent gp_camera_set_config /
    gp_camera_trigger_capture calls to fail with -110 I/O in progress.

    Args:
        target:      gphoto2 Camera object.
        context:     gphoto2 context.
        timeout_ms:  Per-wait timeout in milliseconds. 3000 ms gives enough headroom
                     even for slow Canon bodies writing RAW files.
        max_events:  Safety cap on iterations to avoid an infinite loop.
    """
    for _ in range(max_events):
        try:
            event_type, _ = gp.check_result(
                gp.gp_camera_wait_for_event(target, timeout_ms, context)
            )
            if event_type in (gp.GP_EVENT_CAPTURE_COMPLETE, gp.GP_EVENT_TIMEOUT):
                break
        except gphoto2.GPhoto2Error:
            break
    # Flush any ObjectAdded / leftover events with a short timeout.
    _drain_camera_events(target, context, timeout_ms=200, max_events=10)


def _drain_camera_events(target, context, timeout_ms: int = 200, max_events: int = 50) -> None:
    """Drain pending camera events after a trigger_capture sequence.

    Canon cameras push CaptureComplete and ObjectAdded events onto the USB queue for
    every triggered shot. Leaving them unconsumed can stall subsequent gphoto2
    operations. This function consumes events until a GP_EVENT_TIMEOUT is received
    or max_events is exhausted.
    """
    for _ in range(max_events):
        try:
            event_type, _ = gp.check_result(gp.gp_camera_wait_for_event(target, timeout_ms, context))
            if event_type == gp.GP_EVENT_TIMEOUT:
                break
        except gphoto2.GPhoto2Error:
            break


class _SonyBackgroundDownloader(threading.Thread):
    """Background thread that consumes Sony file-added events and downloads them.

    This is event-driven first, with a light fallback scan to recover from missed
    events. It keeps a small retry queue so files that are visible before they
    are actually readable do not get hammered in a tight loop.
    """

    def __init__(self, adapter: GPhotoCameraAdapter, context):
        super().__init__(daemon=True)
        self.adapter = adapter
        self.context = context
        self._stop_event = threading.Event()
        self.save_dir = os.path.expanduser('~/Pictures/SolarEclipseWorkbench')
        os.makedirs(self.save_dir, exist_ok=True)

        # Files already present on disk should never be downloaded again.
        self._seen_on_disk = set(os.listdir(self.save_dir))

        # (folder, name) -> state dict
        self._pending = {}

        # For proper logging
        self.camera_name = getattr(adapter, 'name', 'Sony')

    def stop(self):
        self._stop_event.set()

    def join(self, timeout=None):
        self.stop()
        super().join(timeout)

    def _queue_path(self, folder, name, now: float) -> None:
        if not name:
            return
        folder = folder or "/"
        key = (folder, name)
        if name in self._seen_on_disk or key in self._pending:
            return
        self._pending[key] = {
            "first_seen": now,
            "next_try": now,
            "attempts": 0,
        }
        logging.info("%s: queued %s", self.camera_name, name)

    def _download_one(self, target, ctx, folder: str, name: str) -> None:
        cam_file = gp.CameraFile()
        gp.check_result(
            gp.gp_camera_file_get(
                target,
                folder,
                name,
                gp.GP_FILE_TYPE_NORMAL,
                cam_file,
                ctx,
            )
        )
        save_path = os.path.join(self.save_dir, name)
        gp.check_result(gp.gp_file_save(cam_file, save_path))
        size = os.path.getsize(save_path)
        logging.info("%s: saved %s (%d bytes)", self.camera_name, save_path, size)
        self._seen_on_disk.add(name)

    def run(self):
        target = self.adapter._camera if hasattr(self.adapter, "_camera") else self.adapter
        ctx = self.context

        event_timeout_ms = 100
        fallback_scan_every_s = 2.5
        retry_base_s = 0.25
        retry_max_s = 2.0
        cycle_sleep = 0.25

        last_fallback_scan = 0.0

        while not self._stop_event.is_set():
            acquired = False
            try:
                # Use a non-blocking or low-timeout attempt to acquire lock
                acquired = self.adapter._usb_lock.acquire(timeout=0.05)
                if not acquired:
                    # Interruptible sleep check
                    self._stop_event.wait(cycle_sleep)
                    continue

                # Check if stop requested right after obtaining lock
                if self._stop_event.is_set():
                    break

                now = time.monotonic()

                # 1) Primary path: consume one camera event per cycle.
                try:
                    event_type, event_data = gp.check_result(
                        gp.gp_camera_wait_for_event(target, event_timeout_ms, ctx)
                    )
                except gphoto2.GPhoto2Error as e:
                    logging.debug("%s Background Downloader: wait_for_event failed: %s", self.camera_name, e)
                    event_type, event_data = gp.GP_EVENT_TIMEOUT, None
                    error_str = str(e).lower()
                    if any(x in error_str for x in ['-52', 'could not find the requested device']):
                        logging.info(
                            "%s Background Downloader: camera got disconnected, shutting down", self.camera_name)
                        self.stop()
                    if any(x in error_str for x in ['-110', 'i/o in progress']):
                        logging.warning(
                            "%s Background Downloader: camera is busy, safe to ignore", self.camera_name)

                if event_type in (gp.GP_EVENT_FILE_ADDED, gp.GP_EVENT_FOLDER_ADDED) and event_data is not None:
                    folder = getattr(event_data, "folder", "/")
                    name = getattr(event_data, "name", None)
                    self._queue_path(folder, name, now)

                # 2) Safety net: occasionally scan the root folder in case an event was missed.
                if now - last_fallback_scan >= fallback_scan_every_s:
                    try:
                        files = gp.check_result(gp.gp_camera_folder_list_files(target, "/", ctx))
                        for i in range(files.count()):
                            name = files.get_name(i)
                            self._queue_path("/", name, now)
                    except Exception as exc:
                        logging.debug(
                            "%s Background Downloader: fallback list failed: %s", self.camera_name,  exc)
                    last_fallback_scan = now

                # 3) Try any queued downloads whose retry delay has expired.
                for key, state in list(self._pending.items()):
                    if now < state["next_try"]:
                        continue

                    folder, name = key
                    try:
                        self._download_one(target, ctx, folder, name)
                        del self._pending[key]
                    except gphoto2.GPhoto2Error as exc:
                        state["attempts"] += 1
                        delay = min(
                            retry_max_s,
                            retry_base_s * (2 ** min(state["attempts"], 3)),
                        )
                        state["next_try"] = now + delay
                        logging.debug(
                            "%s Background Downloader: download not ready for %s: %s (retry in %.1fs)",
                            self.camera_name,
                            name,
                            exc,
                            delay,
                        )
                    except Exception as exc:
                        state["attempts"] += 1
                        delay = min(
                            retry_max_s,
                            retry_base_s * (2 ** min(state["attempts"], 3)),
                        )
                        state["next_try"] = now + delay
                        logging.info(
                            "%s Background Downloader: download failed for %s: %s (retry in %.1fs)",
                            self.camera_name,
                            name,
                            exc,
                            delay,
                        )

            finally:
                if acquired:
                    try:
                        self.adapter._usb_lock.release()
                    except Exception:
                        pass

            # Responsive wait instead of un-interruptible time.sleep
            self._stop_event.wait(cycle_sleep)


class LiveViewThread(threading.Thread):
    """Background thread that periodically fetches a live-view preview frame.

    Tries to acquire the camera's USB lock with a short timeout.  When the
    lock is held by a scheduled shot, the frame is silently skipped.  The
    caller-supplied *frame_callback* is invoked on this worker thread with the
    raw JPEG bytes of each successfully obtained preview frame.

    Parameters
    ----------
    camera : GPhotoCameraAdapter or equivalent
        Must have ``_camera`` and ``_usb_lock`` attributes.
    frame_callback : callable[[bytes], None]
        Called with the JPEG preview bytes each time a frame is successfully
        captured.  Must be thread-safe (e.g. use a queue.Queue to forward
        frames to the GUI thread).
    interval_s : float
        Interval between preview captures in seconds.  Default 1.0.
    lock_timeout : float
        Maximum seconds to wait for the USB lock before skipping a frame.
        Default 0.05 (50 ms).
    """

    def __init__(self, camera, frame_callback, interval_s: float = 1.0, lock_timeout: float = 0.05):
        super().__init__(daemon=True)
        self._camera = camera
        self._frame_callback = frame_callback
        self._interval_s = interval_s
        self._lock_timeout = lock_timeout
        self._stop_event = threading.Event()
        self._paused = threading.Event()

    def stop(self):
        """Signal the thread to stop and wait briefly for it to exit."""
        self._stop_event.set()

    def pause(self):
        """Suspend preview capture without stopping the thread."""
        self._paused.set()

    def resume(self):
        """Resume suspended preview capture."""
        self._paused.clear()

    def exit_live_view(self):
        """Force the camera out of live-view mode (important for Nikon DSLRs)."""
        if not hasattr(self, '_camera') or not hasattr(self._camera, '_camera'):
            return
        try:
            target = self._camera._camera if hasattr(self._camera, '_camera') else self._camera
            context = gp.gp_context_new()

            # Nikon DSLRs (like D610) often need this to drop the mirror
            gp.check_result(gp.gp_camera_exit(target, context))
            logging.info(f"LiveViewThread: requested exit live view for {getattr(self._camera, 'name', 'camera')}")

            # Optional: small delay + re-init can help some bodies
            time.sleep(0.3)
            # gp.gp_camera_init(target, context)  # uncomment if needed
        except Exception as e:
            logging.debug("LiveViewThread: could not exit live view: %s", e)

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def run(self):
        # If the camera provides a capture_preview() method (e.g. VirtualCamera
        # in simulator mode), use that path — no gphoto2 calls or USB lock needed.
        # Do not use this path for wrapped gphoto2 cameras: delegated
        # capture_preview() may return a CameraFile object (not JPEG bytes).
        _has_virtual_preview = isinstance(self._camera, VirtualCamera)

        target = None
        context = None
        if not _has_virtual_preview:
            target = self._camera._camera if hasattr(self._camera, '_camera') else self._camera
            context = gp.gp_context_new()

        while not self._stop_event.wait(self._interval_s):
            if self._paused.is_set():
                continue

            if _has_virtual_preview:
                try:
                    jpeg_bytes = self._camera.capture_preview()
                    if isinstance(jpeg_bytes, memoryview):
                        jpeg_bytes = jpeg_bytes.tobytes()
                    elif isinstance(jpeg_bytes, bytearray):
                        jpeg_bytes = bytes(jpeg_bytes)
                    if jpeg_bytes:
                        self._frame_callback(jpeg_bytes)
                except Exception:
                    logging.exception('LiveViewThread: virtual preview failed')
                continue

            acquired = False
            try:
                acquired = self._camera._usb_lock.acquire(timeout=self._lock_timeout)
                if not acquired:
                    logging.debug('LiveViewThread: USB lock busy, skipping frame')
                    continue

                cam_file = gp.CameraFile()
                # Signal that capture_preview has been called on this camera.
                # Used by take_picture / take_hdr to detect the Canon EOS R
                # eos_remotemode conflict (see _reset_canon_eos_ptp_session).
                self._camera._capture_preview_was_called = True
                gp.check_result(gp.gp_camera_capture_preview(target, cam_file, context))
                file_data = gp.check_result(gp.gp_file_get_data_and_size(cam_file))
                self._frame_callback(bytes(file_data))
            except gphoto2.GPhoto2Error as exc:
                logging.debug('LiveViewThread: preview capture failed: %s', exc)
            except Exception:
                logging.exception('LiveViewThread: unexpected error')
            finally:
                if acquired:
                    try:
                        self._camera._usb_lock.release()
                    except Exception:
                        pass


def _reset_canon_eos_ptp_session(camera) -> None:
    """Reset the PTP session for a Canon EOS camera before the first capture.

    Background
    ----------
    gp_camera_capture_preview on Canon EOS cameras sends EOS_SetRemoteMode(0x01)
    and caches the result as ``params->eos_remotemode = 1`` inside gphoto2's PTP2
    driver state.

    gp_camera_trigger_capture on Canon EOS R mirrorless bodies needs to send
    EOS_SetRemoteMode(0x15) to enter the correct remote-capture mode.  It only
    does so when ``params->eos_remotemode == 0`` (uninitialised).  If
    capture_preview has already run, eos_remotemode is 1, trigger_capture skips
    the EOS_SetRemoteMode call entirely, tries to fire the shutter in mode 1,
    and fails.  Subsequent capture_preview calls also fail because the camera is
    now in an inconsistent state.

    On Canon DSLR bodies (EOS 80D, EOS 1000D, etc.) both paths use mode 1, so
    there is no conflict.  The reset is harmless on those bodies.

    Fix
    ---
    Calling gp_camera_exit + gp_camera_init closes and re-opens the PTP session.
    This resets ``params->eos_remotemode`` to 0, allowing the next
    gp_camera_trigger_capture to initialise correctly with mode 0x15.

    After the first successful trigger_capture ``camera._first_capture_done`` is
    set to True so this reset is never repeated for the same camera object.
    """
    target = camera._camera if hasattr(camera, '_camera') else camera
    context = gp.gp_context_new()
    try:
        gp.gp_camera_exit(target)
        gp.gp_camera_init(target, context)
        logging.info(
            'Canon EOS: PTP session reset before first capture '
            '(live view had initialised eos_remotemode=1; cleared for trigger_capture)'
        )
    except gphoto2.GPhoto2Error as e:
        logging.warning(
            'Canon EOS: PTP session reset failed: %s — '
            'trigger_capture may fail if live view set eos_remotemode=1', e
        )
    finally:
        # Clear the flag regardless of success so we do not attempt the reset
        # again even if it failed (to avoid an infinite retry loop).
        camera._capture_preview_was_called = False


@_serialised_on_camera
def take_picture(camera: Camera, camera_settings: CameraSettings) -> None:
    """ Take a picture with the selected camera 
    
    Args: 
        - camera_name: Camera object
        - camera_settings: Settings of the camera (exposure, f, iso)
    """

    # Canon EOS R live-view / trigger_capture mode conflict:
    # If capture_preview (live view) was called before the first trigger_capture
    # on a Canon EOS R mirrorless body, gphoto2's internal eos_remotemode is set
    # to 1, preventing trigger_capture from initialising it to 15.  Reset the PTP
    # session once to clear the stale remote mode.  Only applies before the first
    # successful capture; subsequent shots are unaffected.
    if (getattr(camera, 'vendor', None) == 'Canon'
            and hasattr(camera, '_camera')
            and not getattr(camera, '_first_capture_done', True)
            and getattr(camera, '_capture_preview_was_called', False)):
        _reset_canon_eos_ptp_session(camera)

    context, config = __adapt_camera_settings(camera, camera_settings)

    # If __adapt_camera_settings returned None context, it's a virtual/non-gphoto
    # camera: call its capture() method directly and return.
    if context is None:
        try:
            camera.capture()
            return
        except Exception as e:
            logging.exception('Virtual camera capture failed: %s', e)
            raise

    # For Nikon cameras, defensively ensure single-frame mode is active before
    # taking a single picture, in case a previous take_burst left the camera in
    # continuous/burst mode.
    if getattr(camera, 'vendor', None) == 'Nikon':
        target = camera._camera if hasattr(camera, '_camera') else camera
        try:
            cfg2 = gp.check_result(gp.gp_camera_get_config(target, context))
            capture_mode_widget = gp.check_result(gp.gp_widget_get_child_by_name(cfg2, 'capturemode'))
            single_choice = _find_capturemode_choice(capture_mode_widget, want_continuous=False)
            if single_choice is not None:
                gp.gp_widget_set_value(capture_mode_widget, single_choice)
                _set_gp_config(camera, cfg2, context)
                logging.debug('Ensured Nikon capturemode="%s" before take_picture', single_choice)
        except gphoto2.GPhoto2Error:
            try:
                capture_mode_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'stillcapturemode'))
                gp.gp_widget_set_value(capture_mode_widget, 0)  # 0 = Single Frame
                _set_gp_config(camera, config, context)
                logging.debug('Ensured Nikon stillcapturemode is Single Frame (0) before take_picture')
            except gphoto2.GPhoto2Error as e:
                logging.warning('Could not ensure Nikon single-frame mode before take_picture: %s', e)

    # For Sony cameras, ensure single-frame capture mode is active before taking
    # a single picture (separate set_config call so a bad capturemode value can
    # never poison the ISO/shutter batch).
    if getattr(camera, 'vendor', None) == 'Sony':
        target = camera._camera if hasattr(camera, '_camera') else camera
        try:
            cfg2 = gp.check_result(gp.gp_camera_get_config(target, context))
            capture_mode_widget = gp.check_result(gp.gp_widget_get_child_by_name(cfg2, 'capturemode'))
            single_choice = _find_capturemode_choice(capture_mode_widget, want_continuous=False)
            if single_choice is not None:
                gp.gp_widget_set_value(capture_mode_widget, single_choice)
                _set_gp_config(camera, cfg2, context)
                logging.debug('Ensured Sony capturemode="%s" before take_picture', single_choice)
            else:
                logging.debug('Sony capturemode: no "single" choice found, leaving as-is')
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not ensure Sony single-frame mode before take_picture: %s', e)

    target = camera._camera if hasattr(camera, '_camera') else camera

    # Fire the shutter via trigger_capture (PTP InitiateCapture).  This is the
    # only path that guarantees the camera uses the USB-programmed ISO, shutter
    # speed and aperture values from __adapt_camera_settings.  eosremoterelease
    # ('Immediate', 'Press Full', etc.) emulates the physical shutter button and
    # causes the camera to use its physical-dial settings, ignoring USB-set
    # values — so it must not be used for take_picture.
    # On EOS R-series mirrorless bodies trigger_capture incurs a live-view
    # exit+re-entry overhead (~1-2 s).  This is handled by increasing
    # misfire_grace_time in the APScheduler so queued shots are not dropped.
    try:
        gp.check_result(gp.gp_camera_trigger_capture(target, context))
        logging.debug('take_picture: trigger_capture fired')
        _wait_for_capture_complete(target, context)
        # First successful trigger_capture: eos_remotemode is now 15 (EOS R) or
        # unchanged (DSLR).  Mark as done so no further PTP session reset is needed.
        if getattr(camera, 'vendor', None) == 'Canon':
            camera._first_capture_done = True
    except gphoto2.GPhoto2Error as e:
        logging.warning('trigger_capture failed (%s), falling back to GP_CAPTURE_IMAGE', e)
        try:
            camera.capture(gp.GP_CAPTURE_IMAGE, context)
        except Exception:
            logging.exception('GP_CAPTURE_IMAGE fallback also failed')
            raise


def __adapt_camera_settings(camera, camera_settings):
    # For virtual or non-gphoto cameras, skip gphoto configuration and
    # return (None, None) so callers can handle capture directly.
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return None, None

    context = gp.gp_context_new()
    target = camera._camera if hasattr(camera, '_camera') else camera
    config = gp.check_result(gp.gp_camera_get_config(target, context))

    vendor = getattr(camera, 'vendor', None)

    # --- Step 1: mutate exposure mode in memory (no separate set_config) ---
    # The mode widget is included in the ISO+shutter batch below so that all
    # three reach the camera in a single USB round-trip instead of two.
    if vendor == 'Nikon':
        try:
            exp_program = gp.check_result(gp.gp_widget_get_child_by_name(config, 'expprogram'))
            gp.gp_widget_set_value(exp_program, "1")  # 1 = Manual
            logging.debug('Queued Nikon expprogram=Manual for next set_config')
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not queue Nikon expprogram: %s', e)
    elif vendor == 'Canon':
        try:
            ae_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'autoexposuremodedial'))
            gp.gp_widget_set_value(ae_mode, "Manual")
            logging.debug('Queued Canon autoexposuremodedial=Manual for next set_config')
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not queue Canon autoexposuremodedial: %s', e)
        # Force single-frame drive mode so that eosremoterelease='Immediate' fires
        # exactly one shot even if the camera was left in continuous/burst mode.
        try:
            drive_w = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
            gp.gp_widget_set_value(drive_w, 'Single')
            logging.debug('Queued Canon drivemode=Single for next set_config')
        except gphoto2.GPhoto2Error:
            pass  # Not available on all bodies — safe to skip
    elif vendor == 'Sony':
        # 'expprogram' on Sony Alpha cameras is READ-ONLY: it mirrors the physical
        # PASM dial and cannot be set via USB.  The user must set the dial to M
        # before shooting.  We deliberately do NOT mutate it here — an invalid
        # mutation in the batch could cause the entire gp_camera_set_config call
        # to fail, taking ISO and shutter speed down with it.
        #
        # capturemode is handled separately in take_picture / take_burst with a
        # dedicated set_config call using the correct choice string (e.g.
        # "Single Shooting"), NOT '0' / '1' which would also poison the batch.
        pass  # no vendor-specific batch mutations for Sony

    # --- Step 2: mutate ISO and shutter speed in memory, push all in one round-trip ---
    # This single set_config also delivers the exposure-mode change from step 1.
    # Auto-ISO must be off on Nikon before setting a manual value; mutate in memory
    # together with the ISO widget so it costs no extra round-trip.
    if vendor == 'Nikon':
        try:
            gp.gp_widget_set_value(
                gp.check_result(gp.gp_widget_get_child_by_name(config, 'autoiso')), "Off")
        except gphoto2.GPhoto2Error as e:
            logging.debug('Could not disable auto ISO: %s', e)

    try:
        gp.gp_widget_set_value(
            gp.check_result(gp.gp_widget_get_child_by_name(config, 'iso')), str(camera_settings.iso))
    except gphoto2.GPhoto2Error as e:
        logging.warning('Could not set ISO to %s: %s', camera_settings.iso, e)

    if vendor == 'Sony':
        sony_exception_ss = {"3.2", "3", "2.5", "1.6", "1.3", "0.8", "0.6", "0.5", "1/2", "0.4"}
        if camera_settings.shutter_speed in sony_exception_ss:
            ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
            closest = _find_closest_shutter_choice(ss_widget, camera_settings.shutter_speed)
            if closest is not None:
                camera_settings.shutter_speed = closest
                logging.warning('Using closest shutter speed choice: %s', closest)
            else:
                logging.warning('No suitable shutter speed choice found for %s',
                                camera_settings.shutter_speed)

    try:
        gp.gp_widget_set_value(gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed')),
                               str(camera_settings.shutter_speed))
    except gphoto2.GPhoto2Error as e:
        logging.warning('Could not set shutterspeed to %s: %s — trying closest available choice',
                        camera_settings.shutter_speed, e)
        try:
            ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
            closest = _find_closest_shutter_choice(ss_widget, camera_settings.shutter_speed)
            if closest is not None:
                gp.gp_widget_set_value(ss_widget, closest)
                logging.warning('Using closest shutter speed choice: %s', closest)
            else:
                logging.warning('No suitable shutter speed choice found for %s',
                                camera_settings.shutter_speed)
        except gphoto2.GPhoto2Error as e2:
            logging.warning('Could not set closest shutter speed: %s', e2)

    # Always save to the camera's memory card, never to the computer.
    # This must be re-asserted on every shot because some cameras reset
    # capturetarget to 'Internal RAM' when the USB session is re-used.
    # Skip Sony cameras, as this option is set in stone once USB is connected
    try:
        if not _is_sony_camera_instance(camera):
            capture_target_w = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturetarget'))
            card_value = _find_memory_card_choice(capture_target_w)
            gp.gp_widget_set_value(capture_target_w, card_value)
            logging.debug('Asserted capturetarget="%s" before capture', card_value)
    except gphoto2.GPhoto2Error:
        pass  # Widget absent on some cameras — the init-time setting is sufficient

    # Push ISO + shutter speed (+ capturetarget) together — one USB round-trip.
    _set_gp_config(target, config, context)

    # --- Step 3: aperture in an isolated round-trip ---
    # Kept separate so that a failure here (e.g. telescope / fixed-aperture lens)
    # never silently rolls back the ISO and shutter speed that were just applied.
    try:
        if vendor == 'Canon':
            gp.gp_widget_set_value(
                gp.check_result(gp.gp_widget_get_child_by_name(config, 'aperture')),
                str(camera_settings.aperture))
        elif vendor in ('Nikon', 'Sony'):
            try:
                f_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'f-number'))
                f_actual = str(gp.check_result(gp.gp_widget_get_value(f_widget)))
                if f_actual != "f/0":
                    # Inspect choices to detect whether widget expects values like 'f/5.6'
                    try:
                        n_choices = gp.check_result(gp.gp_widget_count_choices(f_widget))
                        sample = gp.check_result(gp.gp_widget_get_choice(f_widget, 0)) if n_choices > 0 else ''
                    except Exception:
                        sample = ''
                    ap_val = str(camera_settings.aperture)
                    if isinstance(sample, str) and sample.startswith('f/') and not ap_val.startswith('f/'):
                        ap_val = f'f/{ap_val}'
                    gp.gp_widget_set_value(f_widget, ap_val)
                    _set_gp_config(target, config, context)
                    logging.debug('Set aperture to %s', camera_settings.aperture)
            except gphoto2.GPhoto2Error:
                # f-number widget absent or not settable — ignore
                raise

        # Read-back check: verify the camera actually applied the requested aperture.
        # Some Sony Alpha bodies (and other cameras) silently accept set_config via PTP
        # without changing the physical aperture — no error is raised, but the setting
        # is ignored.  Reading the value back catches this case and emits a warning.
        #
        # The check is skipped once a particular (camera, aperture) pair has already been
        # verified to avoid an extra USB round-trip on every shot in a tight sequence.
        cam_key = camera_settings.camera_name
        ap_key = str(camera_settings.aperture)
        if ap_key not in _aperture_verified.get(cam_key, set()):
            try:
                config_rb = gp.check_result(gp.gp_camera_get_config(target, context))
                widget_name = 'aperture' if vendor == 'Canon' else 'f-number'
                rb_widget = gp.check_result(gp.gp_widget_get_child_by_name(config_rb, widget_name))
                rb_actual = str(gp.check_result(gp.gp_widget_get_value(rb_widget)))

                def _strip_f(v: str) -> str:
                    return v[2:] if v.startswith('f/') else v

                if _strip_f(rb_actual) != _strip_f(ap_key):
                    logging.warning(
                        'Aperture read-back mismatch on %s: requested f/%s but camera reports %s. '
                        'The camera may not support remote aperture control via USB — '
                        'set the aperture manually on the lens/camera body.',
                        cam_key, _strip_f(ap_key), rb_actual)
                # Mark as checked regardless — mismatch or not, no point repeating the warning.
                _aperture_verified.setdefault(cam_key, set()).add(ap_key)
            except gphoto2.GPhoto2Error:
                pass  # Read-back failure is non-fatal
    except gphoto2.GPhoto2Error:
        # Read-only or absent aperture widget (telescope, fixed-aperture lens) — ignore.
        logging.debug('Aperture widget not settable (telescope/fixed lens) — skipping')

    return context, config


@_serialised_on_camera
def take_burst(camera: Camera, camera_settings: CameraSettings, duration: float) -> None:
    """ Take a burst with the selected camera.  For Canon, the duration is the duration in seconds, for Nikon, the
        duration is the number of pictures to take.

    Args:
        - camera_name: Camera object
        - camera_settings: Settings of the camera (exposure, f, iso)
        - duration: Duration of the burst in seconds (Canon) or number of pictures (Nikon)
    """
    # Canon EOS R live-view / trigger_capture mode conflict: if live view was
    # used before the first capture, the PTP session may need resetting so
    # remote-release based bursts work correctly (same check as in take_picture).
    if (getattr(camera, 'vendor', None) == 'Canon'
            and hasattr(camera, '_camera')
            and not getattr(camera, '_first_capture_done', True)
            and getattr(camera, '_capture_preview_was_called', False)):
        _reset_canon_eos_ptp_session(camera)

    context, config = __adapt_camera_settings(camera, camera_settings)

    # If virtual camera, perform simple repeated captures
    if context is None:
        try:
            # For burst, treat `duration` as number of frames when small,
            # otherwise as seconds: take int(duration) shots.
            n = max(1, int(round(duration)))
            for _ in range(n):
                camera.capture()
            return
        except Exception:
            logging.exception('Virtual burst capture failed')
            raise

    # Take picture for real cameras
    if getattr(camera, 'vendor', None) == 'Canon':
        # For bursts, ensure the camera is in a continuous drive mode so
        # holding the remote release fires repeated frames rather than one.
        try:
            drive_w = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
            gp.gp_widget_set_value(drive_w, 'Continuous')
            _set_gp_config(camera, config, context)
            logging.debug('Set Canon drivemode to Continuous for burst')
        except gphoto2.GPhoto2Error:
            logging.debug('Could not set Canon drivemode to Continuous; proceeding with remote release')

        # Push the button (press & hold for the requested duration)
        remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        gp.gp_widget_set_value(remote_release, "Press Full")
        _set_gp_config(camera, config, context)
        time.sleep(duration)

        # Release the button
        remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        gp.gp_widget_set_value(remote_release, "Release Full")
        _set_gp_config(camera, config, context)
    elif getattr(camera, 'vendor', None) == 'Nikon':
        # Set capture mode to burst/continuous
        # Try different widget names (differs between DSLR and mirrorless models)
        try:
            # Try 'capturemode' first (older DSLRs)
            capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
            gp.gp_widget_set_value(capture_mode, "Burst")
            _set_gp_config(camera, config, context)
            logging.debug('Set capturemode to Burst')
        except gphoto2.GPhoto2Error:
            try:
                # Try 'stillcapturemode' (newer mirrorless like Z8/Z9)
                # Value 2 is typically Continuous Low, higher values for High Speed
                capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'stillcapturemode'))
                gp.gp_widget_set_value(capture_mode, 2)  # Continuous shooting mode
                _set_gp_config(camera, config, context)
                logging.debug('Set stillcapturemode to Continuous (2)')
            except gphoto2.GPhoto2Error as e:
                logging.warning('Could not set Nikon burst/continuous mode: %s', e)

        # Set burst number
        try:
            burst_number = gp.check_result(gp.gp_widget_get_child_by_name(config, 'burstnumber'))
            gp.gp_widget_set_value(burst_number, round(duration))
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not set Nikon burst number: %s', e)

        try:
            camera.capture(gp.GP_CAPTURE_IMAGE, context)
        except Exception:
            logging.exception('Nikon high-level capture failed, trying low-level gp capture')
            try:
                target = camera._camera if hasattr(camera, '_camera') else camera
                ctx = gp.gp_context_new()
                gp.check_result(gp.gp_camera_capture(target, gp.GP_CAPTURE_IMAGE, ctx))
            except Exception:
                logging.exception('Nikon low-level capture failed')
                raise

        # Reset burst number back to 1, to avoid interference with further shooting
        target = camera._camera if hasattr(camera, '_camera') else camera
        config_reset = gp.check_result(gp.gp_camera_get_config(target, context))
        try:
            burst_number_reset = gp.check_result(gp.gp_widget_get_child_by_name(config_reset, 'burstnumber'))
            gp.gp_widget_set_value(burst_number_reset, 1)
            _set_gp_config(camera, config_reset, context)
            logging.debug('Reset Nikon burstnumber to 1 after burst')
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not reset Nikon burstnumber to 1 after burst: %s', e)
    elif getattr(camera, 'vendor', None) == 'Sony':
        # Sony burst: enable continuous capture mode, turn on the bulb,
        # sleep for the chosen amount of time, turn off the bulb and
        # lastly drain camera's events
        target = camera._camera if hasattr(camera, '_camera') else camera

        # Switch to continuous capture mode — look up the actual choice string so
        # we never send an invalid value that would cause set_config to fail.
        try:
            capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
            continuous_choice = _find_capturemode_choice(capture_mode, want_continuous=True, custom_keyword=configuration.SONY_CONTINUOUS_MODE)
            if continuous_choice is not None:
                gp.gp_widget_set_value(capture_mode, continuous_choice)
                _set_gp_config(camera, config, context)
                logging.debug('Set Sony capturemode to "%s" for burst', continuous_choice)
            else:
                logging.debug('Sony capturemode: no "continuous" choice found, firing without mode change')
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not set Sony capturemode to Continuous: %s', e)

        try:
            _drain_camera_events(target, context, timeout_ms=100, max_events=60)
            bulb_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'bulb'))
            gp.gp_widget_set_value(bulb_mode, 1)
            _set_gp_config(camera, config, context)
            logging.debug('Set Sony bulb mode to 1')
            time.sleep(duration)
            gp.gp_widget_set_value(bulb_mode, 0)
            _set_gp_config(camera, config, context)
            logging.debug('Set Sony bulb mode to 0')
            if not (hasattr(camera, '_bg_downloader')
                    and camera._bg_downloader is not None
                    and camera._bg_downloader.is_alive()):
                _drain_camera_events(target, context, timeout_ms=100, max_events=60)
        except gphoto2.GPhoto2Error as e:
            logging.warning('Sony burst capture failed: %s', e)


def _parse_bracket_steps(steps: str) -> int:
    """Parse a bracket steps string to the number of 1/3-stop index increments.

    The camera's shutter speed list from gphoto2 uses 1/3-stop steps, so
    '+/- 1 2/3' (1⅔ stops) maps to 5 index positions away from the base speed.

    Supported formats (with optional '+/-' prefix):
        '+/- 1/3'   → 1,  '+/- 2/3'   → 2,  '+/- 1'     → 3
        '+/- 1 1/3' → 4,  '+/- 1 2/3' → 5,  '+/- 2'     → 6
        '+/- 2 1/3' → 7,  '+/- 2 2/3' → 8,  '+/- 3'     → 9

    Args:
        steps: Bracket step string, e.g. '+/- 1 2/3'.

    Returns:
        Number of 1/3-stop shutter speed index steps for each side of the bracket.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    s = steps.strip()
    if s.startswith('+/-'):
        s = s[3:].strip()

    whole = 0
    frac_num = 0
    frac_den = 3  # denominator assumed to be 3 for all valid bracket fractions

    for part in s.split():
        if '/' in part:
            num, den = part.split('/', 1)
            frac_num = int(num)
            frac_den = int(den)
        else:
            whole = int(part)

    thirds = whole * 3 + (frac_num * 3 // frac_den)
    if thirds <= 0:
        raise ValueError(f"Could not parse bracket steps '{steps}' to a positive stop count")
    return thirds


def calculate_bracket_exposures(bracket_str: str, base_shutter_speed: str | float) -> float:
    """Parses a camera bracketing string and base shutter speed to calculate

    all shot durations and the total execution time.
    """
    # 1. Extract EV step size and number of pictures
    import re as _re
    match = _re.search(r"(\d+\.\d+).+?(\d+)", bracket_str)
    if not match:
        raise ValueError(f"Invalid bracketing string format: '{bracket_str}'")

    ev_step = float(match.group(1))
    num_pictures = int(match.group(2))

    # 2. Parse the base shutter speed into seconds (handles floats or "1/125" fractions)
    if isinstance(base_shutter_speed, str):
        base_shutter_speed = base_shutter_speed.strip()
        if "/" in base_shutter_speed:
            num, denom = base_shutter_speed.split("/")
            base_seconds = float(num) / float(denom)
        else:
            base_seconds = float(base_shutter_speed)
    else:
        base_seconds = float(base_shutter_speed)

    # 3. Calculate EV offsets symmetrically around 0 EV
    # e.g., 5 steps with 0.5 EV step -> [-1.0, -0.5, 0.0, 0.5, 1.0]
    half_count = num_pictures // 2
    ev_offsets = [i * ev_step for i in range(-half_count, half_count + 1)]

    # 4. Calculate exact duration for each exposure (t = base * 2^EV)
    exposures_sec = [base_seconds * (2**ev) for ev in ev_offsets]
    total_duration_sec = sum(exposures_sec)

    return total_duration_sec


@_serialised_on_camera
def take_bracket(camera: Camera, camera_settings: CameraSettings, steps: str) -> None:
    """ Take a bracketing of images with the selected camera.

    For Canon, the built-in AEB widget is used ('aeb') and 5 frames are fired.
    For Nikon, bracketing is implemented in software: the shutter speed is
    shifted by the requested number of stops for each side of the bracket.
    No manual camera AEB setup is required for Nikon.

    Args:
        - camera_name: Camera object
        - camera_settings: Settings of the camera (exposure, f, iso)
        - steps: Bracket half-width, e.g. '+/- 1 2/3' fires 5 shots at
                 base-2*1⅔, base-1⅔, base, base+1⅔, base+2*1⅔ stops.
                 Supported: '+/- 1/3' through '+/- 3'.
    """
    context, config = __adapt_camera_settings(camera, camera_settings)

    # Virtual camera: perform a few captures to simulate bracketing
    if context is None:
        try:
            for _ in range(3):
                camera.capture()
            return
        except Exception:
            logging.exception('Virtual bracket capture failed')
            raise

    if getattr(camera, 'vendor', None) == 'Canon':
        # Set aeb
        aeb = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aeb'))
        gp.gp_widget_set_value(aeb, steps)
        # set config
        _set_gp_config(camera, config, context)

        for _ in range(5):
            try:
                camera.capture(gp.GP_CAPTURE_IMAGE, context)
            except Exception:
                logging.exception('Bracket capture high-level failed, trying low-level gp capture')
                try:
                    target = camera._camera if hasattr(camera, '_camera') else camera
                    ctx = gp.gp_context_new()
                    gp.check_result(gp.gp_camera_capture(target, gp.GP_CAPTURE_IMAGE, ctx))
                except Exception:
                    logging.exception('Bracket low-level capture failed')
                    raise

        # Set aeb
        aeb = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aeb'))
        gp.gp_widget_set_value(aeb, "off")
        # set config
        _set_gp_config(camera, config, context)

    elif getattr(camera, 'vendor', None) == 'Nikon':
        # Nikon does not expose an AEB widget via gphoto2.  Software bracketing:
        # fire 5 shots at base-2*step, base-step, base, base+step, base+2*step,
        # matching the Canon 5-frame bracket count.
        step_count = _parse_bracket_steps(steps)

        choices = _get_shutter_speed_choices(config)
        base_speed = camera_settings.shutter_speed.strip()
        if base_speed not in choices:
            choices_lower = [c.lower() for c in choices]
            if base_speed.lower() in choices_lower:
                base_speed = choices[choices_lower.index(base_speed.lower())]
            else:
                raise CameraError(
                    f"Shutter speed '{base_speed}' is not supported by this camera. "
                    f"Supported speeds: {choices}"
                )

        base_idx = choices.index(base_speed)
        # choices is sorted fastest→slowest; smaller index = less exposure (under)
        indices = [
            max(0, base_idx - 2 * step_count),
            max(0, base_idx - step_count),
            base_idx,
            min(len(choices) - 1, base_idx + step_count),
            min(len(choices) - 1, base_idx + 2 * step_count),
        ]

        logging.info(
            'take_bracket (Nikon): 5-shot sequence: %s',
            [choices[i] for i in indices],
        )

        target = camera._camera if hasattr(camera, '_camera') else camera
        speed_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))

        for idx in indices:
            speed = choices[idx]
            try:
                gp.gp_widget_set_value(speed_widget, speed)
                gp.gp_camera_set_config(target, config, context)
                gp.check_result(gp.gp_camera_trigger_capture(target, context))
                logging.debug('take_bracket (Nikon): triggered capture at %s', speed)
            except gphoto2.GPhoto2Error as e:
                logging.error('take_bracket (Nikon): capture failed at speed %s: %s', speed, e)
                raise
            _wait_for_capture_complete(target, context)

        # Restore base shutter speed
        gp.gp_widget_set_value(speed_widget, choices[base_idx])
        _set_gp_config(camera, config, context)
        logging.info('take_bracket (Nikon): bracket complete')

    elif getattr(camera, 'vendor', None) == 'Sony':
        # Sony bracketing: enable continuous bracketing mode, turn on the bulb,
        # sleep for the chosen amount of time, turn off the bulb and
        # lastly drain camera's events
        target = camera._camera if hasattr(camera, '_camera') else camera
        base_speed = camera_settings.shutter_speed.strip()
        bracket_duration = calculate_bracket_exposures(steps, base_speed)

        # Switch to continuous bracketing mode
        try:
            capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
            if steps is not None:
                gp.gp_widget_set_value(capture_mode, steps)
                _set_gp_config(camera, config, context)
                logging.debug('Set Sony capturemode to "%s" for bracketing', steps)
            else:
                logging.debug('Sony capturemode: no "%s" choice found, firing without mode change', steps)
        except gphoto2.GPhoto2Error as e:
            logging.warning('Could not set Sony capturemode to "%s": %s', steps, e)

        try:
            _drain_camera_events(target, context, timeout_ms=100, max_events=60)
            bulb_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'bulb'))
            gp.gp_widget_set_value(bulb_mode, 1)
            _set_gp_config(camera, config, context)
            logging.debug('Set Sony bulb mode to 1')
            time.sleep(bracket_duration)
            gp.gp_widget_set_value(bulb_mode, 0)
            _set_gp_config(camera, config, context)
            logging.debug('Set Sony bulb mode to 0')
            if not (hasattr(camera, '_bg_downloader')
                    and camera._bg_downloader is not None
                    and camera._bg_downloader.is_alive()):
                _drain_camera_events(target, context, timeout_ms=700, max_events=60)
        except gphoto2.GPhoto2Error as e:
            logging.warning('Sony burst capture failed: %s', e)


def _parse_shutter_speed_seconds(speed_str: str) -> float:
    """Parse a gphoto2 shutter speed string to seconds as a float.

    Handles fractions like '1/2000', decimals like '0.3', and whole seconds like '2'.
    Returns -1.0 for non-numeric values such as 'bulb' or 'auto'.
    """
    s = speed_str.strip().lower()
    if s in ('bulb', 'auto', ''):
        return -1.0
    try:
        if '/' in s:
            num, den = s.split('/', 1)
            return float(num) / float(den)
        return float(s)
    except (ValueError, ZeroDivisionError):
        return -1.0


def _get_shutter_speed_choices(config) -> list:
    """Return an ordered list of shutter speed strings supported by the camera,
    sorted from fastest (shortest exposure) to slowest.

    The list is built directly from the 'shutterspeed' widget choices reported by
    gphoto2 for the connected camera body. This ensures the table is accurate for
    the specific model in use — important because Canon, Nikon, and other cameras
    expose different sets of available speeds. Falls back to a common built-in table
    if the widget cannot be read (e.g. on older drivers or the VirtualCamera).
    """
    _FALLBACK_SPEEDS = [
        "1/8000", "1/6400", "1/5000", "1/4000", "1/3200", "1/2500",
        "1/2000", "1/1600", "1/1250", "1/1000", "1/800", "1/640",
        "1/500", "1/400", "1/320", "1/250", "1/200", "1/160",
        "1/125", "1/100", "1/80", "1/60", "1/50", "1/40",
        "1/30", "1/25", "1/20", "1/15", "1/13", "1/10",
        "1/8", "1/6", "1/5", "1/4", "0.3", "1/3",
        "0.4", "1/2", "0.5", "0.6", "0.8", "1",
        "1.3", "1.6", "2", "2.5", "3", "4",
        "5", "6", "8", "10", "13", "15",
        "20", "25", "30",
    ]
    try:
        speed_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
        n = gp.check_result(gp.gp_widget_count_choices(speed_widget))
        raw = [gp.check_result(gp.gp_widget_get_choice(speed_widget, i)) for i in range(n)]
        parseable = [(s, _parse_shutter_speed_seconds(s)) for s in raw if _parse_shutter_speed_seconds(s) > 0]
        if parseable:
            parseable.sort(key=lambda x: x[1])
            return [s for s, _ in parseable]
    except gphoto2.GPhoto2Error as e:
        logging.warning('Could not read shutterspeed choices from camera, using fallback table: %s', e)
    return _FALLBACK_SPEEDS


@_serialised_on_camera
def take_hdr(camera: Camera, camera_settings: CameraSettings, stops: int) -> None:
    """Take an HDR sequence by ramping shutter speed from the starting speed down by
    *stops* full stops and back up, using gp_camera_trigger_capture for maximum
    throughput.

    The camera configuration is read once and only the shutterspeed widget is changed
    between shots, avoiding repeated round-trips for ISO and aperture. The shutter speed
    choices are queried directly from the camera body at runtime so the sequence always
    stays within the actual speeds the body supports. The sequence is:

        start_speed → (stops steps slower) → start_speed

    Total shots: 2 * stops + 1 (the slowest exposure appears once at the midpoint).

    Camera-model support:
        - Canon EOS: uses gp_camera_trigger_capture; USB events are drained afterwards.
        - Nikon: uses gp_camera_trigger_capture.
        - VirtualCamera: performs repeated camera.capture() calls.

    Args:
        - camera: Camera object.
        - camera_settings: Base settings. shutter_speed is the fastest (shortest)
                           exposure in the sequence (e.g. "1/2000"). aperture and iso
                           are fixed for the entire sequence.
        - stops: Number of full stops to ramp down. Total shots = 2 * stops + 1.

    Raises:
        CameraError: If the requested starting shutter speed is not supported by the camera.
    """
    # Canon EOS R live-view / trigger_capture mode conflict (same as take_picture).
    if (getattr(camera, 'vendor', None) == 'Canon'
            and hasattr(camera, '_camera')
            and not getattr(camera, '_first_capture_done', True)
            and getattr(camera, '_capture_preview_was_called', False)):
        _reset_canon_eos_ptp_session(camera)

    context, config = __adapt_camera_settings(camera, camera_settings)

    # Virtual camera path: just fire repeated captures
    if context is None:
        try:
            n_shots = 2 * stops + 1
            for _ in range(n_shots):
                camera.capture()
            return
        except Exception:
            logging.exception('Virtual camera HDR capture failed')
            raise

    target = camera._camera if hasattr(camera, '_camera') else camera

    # Build the ordered shutter-speed list from this camera's actual capabilities
    choices = _get_shutter_speed_choices(config)
    logging.debug('take_hdr: shutter speed choices from camera: %s', choices)

    # Locate the starting speed in the choices list
    start_speed = camera_settings.shutter_speed.strip()
    if start_speed not in choices:
        choices_lower = [c.lower() for c in choices]
        if start_speed.lower() in choices_lower:
            start_speed = choices[choices_lower.index(start_speed.lower())]
        else:
            raise CameraError(
                f"Shutter speed '{start_speed}' is not supported by this camera. "
                f"Supported speeds: {choices}"
            )

    start_idx = choices.index(start_speed)
    end_idx = min(start_idx + stops, len(choices) - 1)
    actual_stops = end_idx - start_idx
    if actual_stops < stops:
        logging.warning(
            'take_hdr: requested %d stops but camera only supports %d stops slower than %s; '
            'clamping sequence to %d stops.',
            stops, actual_stops, start_speed, actual_stops
        )

    # Symmetric sequence: ramp down (faster→slower) then back up (duplicate peak excluded)
    down = list(range(start_idx, end_idx + 1))
    up = list(range(end_idx - 1, start_idx - 1, -1))
    indices = down + up
    logging.info(
        'take_hdr: %d shots, speeds: %s',
        len(indices), [choices[i] for i in indices]
    )

    # Fetch the shutterspeed widget once to reuse across all shots
    try:
        speed_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
    except gphoto2.GPhoto2Error as e:
        raise CameraError(f"Could not access shutterspeed widget: {e}") from e

    for idx in indices:
        speed = choices[idx]
        try:
            gp.gp_widget_set_value(speed_widget, speed)
            gp.gp_camera_set_config(target, config, context)
            gp.check_result(gp.gp_camera_trigger_capture(target, context))
            logging.debug('take_hdr: triggered capture at %s', speed)
            # First successful trigger_capture establishes eos_remotemode=15 on EOS R.
            if getattr(camera, 'vendor', None) == 'Canon':
                camera._first_capture_done = True
        except gphoto2.GPhoto2Error as e:
            logging.error('take_hdr: capture failed at speed %s: %s', speed, e)
            raise
        # Wait for the shutter to close before changing the shutter speed for the
        # next shot.  Without this, gp_camera_set_config on the next iteration
        # races with the camera's USB processing and raises -110 I/O in progress.
        _wait_for_capture_complete(target, context)

    logging.info('take_hdr: HDR sequence complete (%d shots)', len(indices))


def mirror_lock(camera: Camera, camera_settings: CameraSettings) -> None:
    """ Lock the mirror

    Args:
        - camera_name: Camera object
    """
    # For virtual cameras, nothing to do
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return

    context = gp.gp_context_new()
    target = camera._camera if hasattr(camera, '_camera') else camera
    config = gp.check_result(gp.gp_camera_get_config(target, context))

    if getattr(camera, 'vendor', None) == 'Canon':
        lock = gp.check_result(gp.gp_widget_get_child_by_name(config, 'mirrorlock'))
        gp.gp_widget_set_value(lock, "1")
        # set config
        gp.gp_camera_set_config(target, config, context)

        context, config = __adapt_camera_settings(camera, camera_settings)

        # # Push the button
        # remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        # gp.gp_widget_set_value(remote_release, "Press 2")
        # # set config
        # gp.gp_camera_set_config(camera, config, context)

        # Release the button
        # remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        # gp.gp_widget_set_value(remote_release, "Release Full")
        # # set config
        # gp.gp_camera_set_config(camera, config, context)

        # Set mirror lock back to off
        lock = gp.check_result(gp.gp_widget_get_child_by_name(config, 'mirrorlock'))
        gp.gp_widget_set_value(lock, "0")
        # set config
        gp.gp_camera_set_config(target, config, context)


def get_cameras() -> list:
    """ Returns a list with the cameras.

    Returns: List with all the attached cameras ([name, USB port]).
    """

    locale.setlocale(locale.LC_ALL, '')

    gp.check_result(gp.use_python_logging())
    # make a list of all available cameras
    detected = list(gp.Camera.autodetect())
    logging.debug('gphoto autodetect returned %d entries', len(detected))
    for d in detected:
        logging.debug('Detected camera: %s @ %s', d[0], d[1])
    return detected


def __get_address(camera_name: str) -> str:
    """ Gets the address of the camera if the name is given 
    
    Args:
        - camera_name: Name of the camera
    
    Returns: Address of the camera
    """

    camera_list = get_cameras()
    logging.debug('Searching for camera address for %s among %d cameras', camera_name, len(camera_list))
    camera_tuple = [camera[1] for camera in camera_list if camera[0] == camera_name]
    try:
        return camera_tuple[0]
    except IndexError:
        logging.debug('Camera %s not found in autodetect list', camera_name)
        raise CameraError(f"Camera {camera_name} not found")


def get_camera(camera_name: str):
    """ Returns the initialized camera object of the selected camera

    Args: 
        - camera_name: Name of the camera
    
    Returns: Initialized camera object of the selected camera.
    """

    addr = __get_address(camera_name)
    if addr == '':
        return ''
    logging.debug('get_camera(%s): address=%s', camera_name, addr)

    # prepare variable in case initialization fails early
    camera = None

    # get port info
    port_info_list = gp.PortInfoList()
    port_info_list.load()
    abilities_list = gp.CameraAbilitiesList()
    abilities_list.load()

    camera = gp.Camera()
    idx = port_info_list.lookup_path(addr)
    camera.set_port_info(port_info_list[idx])
    idx = abilities_list.lookup_model(camera_name)
    camera.set_abilities(abilities_list[idx])

    context = gp.gp_context_new()

    # Initialize the camera
    try:
        camera.init(context)
    except gphoto2.GPhoto2Error as e:
        _raise_camera_init_error(camera_name, e)

    # Post-init configuration (capture target, drive mode)
    try:
        config = gp.check_result(gp.gp_camera_get_config(camera, context))
        # Skip Sony cameras, as this option is set in stone once USB is connected
        if not _is_sony_camera_instance(camera):
            # find the capture target config item (to save to the memory card)
            capture_target = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturetarget'))
            # set value — search for the memory-card entry by name, not by blind index
            value = _find_memory_card_choice(capture_target)
            gp.gp_widget_set_value(capture_target, value)
            logging.debug('Set capturetarget to "%s" for %s', value, camera_name)
            # set config
            gp.gp_camera_set_config(camera, config, context)

            # Try to set the drivemode to Continuous high speed (for cameras that support it)
            # Note: Not all cameras have this widget (e.g., Nikon Z-series mirrorless cameras)
            try:
                drive_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
                gp.gp_widget_set_value(drive_mode, "Continuous high speed")
                # set config
                gp.gp_camera_set_config(camera, config, context)
                logging.debug('Set drivemode to Continuous high speed for %s', camera_name)
            except gphoto2.GPhoto2Error as e:
                # drivemode widget doesn't exist or value not supported - this is OK for many cameras
                logging.debug('Could not set drivemode for %s (this is normal for some camera models): %s', camera_name, e)
    except gphoto2.GPhoto2Error as e:
        logging.warning('Post-init config failed for %s (continuing): %s', camera_name, e)

    # Wrap the gphoto camera in a vendor-aware adapter
    if camera is None:
        logging.error('get_camera: camera object was not created for %s', camera_name)
        raise CameraError(f'Could not create camera object for {camera_name}')

    if "Canon" in camera_name:
        logging.debug('Wrapping camera %s as CanonCamera', camera_name)
        return CanonCamera(camera, camera_name)
    elif "Nikon" in camera_name:
        logging.debug('Wrapping camera %s as NikonCamera', camera_name)
        return NikonCamera(camera, camera_name)
    elif _is_sony_model(camera_name):
        logging.debug('Wrapping camera %s as SonyCamera', camera_name)
        return SonyCamera(camera, camera_name)
    else:
        logging.debug('Wrapping camera %s as generic GPhotoCameraAdapter', camera_name)
        return GPhotoCameraAdapter(camera, camera_name)


def get_camera_by_port(model_name: str, port: str, alias: Optional[str] = None) -> 'BaseCamera':
    """Open a gphoto2 camera at a specific USB port.

    Unlike get_camera(), this function connects to the camera at *port* directly,
    so it works correctly when multiple cameras of the same model are connected at
    different USB ports.

    Args:
        model_name: Camera model name as reported by gphoto2 (e.g. "Canon EOS 80D").
        port:       USB port address (e.g. "usb:001,005").
        alias:      Optional display/script name for this camera.  When provided the
                    resulting camera object's `name` attribute is set to *alias* rather
                    than *model_name*, so the name matches the key used in the script.

    Returns: A vendor-specific BaseCamera adapter.

    Raises:
        CameraError: If the camera cannot be opened at the given port.
    """
    display_name = alias if alias else model_name
    logging.debug('get_camera_by_port(%s, %s, alias=%s)', model_name, port, alias)

    port_info_list = gp.PortInfoList()
    port_info_list.load()
    abilities_list = gp.CameraAbilitiesList()
    abilities_list.load()

    camera = gp.Camera()
    idx = port_info_list.lookup_path(port)
    camera.set_port_info(port_info_list[idx])
    idx = abilities_list.lookup_model(model_name)
    camera.set_abilities(abilities_list[idx])

    context = gp.gp_context_new()

    try:
        camera.init(context)
    except gphoto2.GPhoto2Error as e:
        _raise_camera_init_error(model_name, e)

    # Post-init configuration (capture target, drive mode)
    try:
        config = gp.check_result(gp.gp_camera_get_config(camera, context))
        # Skip Sony cameras, as this option is set in stone once USB is connected
        if not _is_sony_model(model_name):
            capture_target = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturetarget'))
            # search for the memory-card entry by name, not by blind index
            value = _find_memory_card_choice(capture_target)
            gp.gp_widget_set_value(capture_target, value)
            logging.debug('Set capturetarget to "%s" for %s', value, display_name)
            gp.gp_camera_set_config(camera, config, context)

            try:
                drive_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
                gp.gp_widget_set_value(drive_mode, "Continuous high speed")
                gp.gp_camera_set_config(camera, config, context)
                logging.debug('Set drivemode to Continuous high speed for %s', display_name)
            except gphoto2.GPhoto2Error as e:
                logging.debug('Could not set drivemode for %s: %s', display_name, e)
    except gphoto2.GPhoto2Error as e:
        logging.warning('Post-init config failed for %s (continuing): %s', display_name, e)

    if camera is None:
        raise CameraError(f'Could not create camera object for {model_name} at {port}')

    if "Canon" in model_name:
        logging.debug('Wrapping camera %s as CanonCamera (alias=%s)', model_name, alias)
        return CanonCamera(camera, display_name)
    elif "Nikon" in model_name:
        logging.debug('Wrapping camera %s as NikonCamera (alias=%s)', model_name, alias)
        return NikonCamera(camera, display_name)
    elif _is_sony_model(model_name):
        logging.debug('Wrapping camera %s as SonyCamera (alias=%s)', model_name, alias)
        return SonyCamera(camera, display_name)
    else:
        logging.debug('Wrapping camera %s as GPhotoCameraAdapter (alias=%s)', model_name, alias)
        return GPhotoCameraAdapter(camera, display_name)


def get_serial_number(camera: 'BaseCamera') -> Optional[str]:
    """Read the camera's serial number via the gphoto2 'serialnumber' config widget.

    Most Canon and Nikon bodies expose this widget.  Returns ``None`` if the
    camera does not expose a serial number or if reading fails (e.g. virtual
    camera, unsupported model, I/O error).
    """
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return None
    try:
        context = gp.gp_context_new()
        target = camera._camera if hasattr(camera, '_camera') else camera
        config = gp.check_result(gp.gp_camera_get_config(target, context))
        ok, widget = gp.gp_widget_get_child_by_name(config, 'serialnumber')
        if ok >= gp.GP_OK:
            serial = widget.get_value()
            if serial:
                return str(serial).strip()
    except Exception:
        pass
    return None


def get_free_space(camera: Camera) -> float:
    """ Return the free space on the card of the selected camera 
    
    Args: 
        - camera: Camera object

    Returns: Free space on the card of the camera [GB]
    """
    try:
        result = round(camera.get_storageinfo()[0].freekbytes / 1024 / 1024, 1)
        try:
            camera._cached_free_space = result  # cache for -53 fallback
        except Exception:
            pass
        return result
    except gphoto2.GPhoto2Error as e:
        # Some Sony bodies (for example ZV-E10 in PC-Remote mode) expose
        # an empty "Storage Devices Summary" over PTP and return -1 for
        # storage info queries. Treat this as unknown storage instead of
        # forcing a camera reinitialisation that can trigger -53 (device busy).
        if getattr(e, 'code', None) == -1 and _is_sony_camera_instance(camera):
            cached = getattr(camera, '_cached_free_space', None)
            if cached is not None:
                return cached
            logging.info(
                'Camera %s does not expose storage info via PTP (Sony -1); returning -1.0',
                getattr(camera, 'name', str(camera)))
            return -1.0
        raise CameraError(f"Could not read storage info for {getattr(camera, 'name', camera)}: {e}") from None
    except IndexError:
        # get_storageinfo() returned an empty list — common on Sony via PTP during
        # the initial handshake or when ptpcamerad briefly relinquishes the device.
        # Return the last cached value if we have one, otherwise -1.0.
        cached = getattr(camera, '_cached_free_space', None)
        if cached is not None:
            logging.debug(
                'Camera %s: get_storageinfo() returned empty list; returning cached %.1f GB',
                getattr(camera, 'name', str(camera)), cached)
            return cached
        logging.debug(
            'Camera %s: get_storageinfo() returned empty list with no cache; returning -1.0',
            getattr(camera, 'name', str(camera)))
        return -1.0
    except Exception:
        # For virtual or non-gphoto cameras return a large default value
        if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
            return 999.9
        raise


def get_space(camera: Camera) -> float:
    """ Return the size of the memory card of the selected camera 
    
    Args: 
        - camera: Camera object

    Returns: Size of memory card of the camera [GB]
    """

    try:
        result = round(camera.get_storageinfo()[0].capacitykbytes / 1024 / 1024, 1)
        try:
            camera._cached_total_space = result  # cache for -53 fallback
        except Exception:
            pass
        return result
    except gphoto2.GPhoto2Error as e:
        # See note in get_free_space(): Sony PTP can legitimately return -1
        # for storage info while still allowing capture control.
        if getattr(e, 'code', None) == -1 and _is_sony_camera_instance(camera):
            cached = getattr(camera, '_cached_total_space', None)
            if cached is not None:
                return cached
            logging.info(
                'Camera %s does not expose storage capacity via PTP (Sony -1); returning -1.0',
                getattr(camera, 'name', str(camera)))
            return -1.0
        raise CameraError(f"Could not read storage capacity for {getattr(camera, 'name', camera)}: {e}") from None
    except IndexError:
        # get_storageinfo() returned an empty list — camera not yet ready to report storage.
        cached = getattr(camera, '_cached_total_space', None)
        if cached is not None:
            logging.debug(
                'Camera %s: get_storageinfo() returned empty list; returning cached total %.1f GB',
                getattr(camera, 'name', str(camera)), cached)
            return cached
        logging.debug(
            'Camera %s: get_storageinfo() returned empty list with no cache; returning -1.0',
            getattr(camera, 'name', str(camera)))
        return -1.0
    except Exception:
        # For virtual or non-gphoto cameras return a large default value
        if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
            return 999.9
        raise


def get_shooting_mode(camera_name: str, camera: Camera) -> str:
    """ Return the shooting mode of the selected camera. Should be "Manual".
    
    Args: 
        - camera: Camera object

    Returns: Shooting mode of the camera
    """
    # For virtual/non-gphoto cameras assume Manual shooting mode
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return "Manual"

    vendor = getattr(camera, 'vendor', None)
    try:
        if vendor == 'Canon':
            return camera.get_config().get_child_by_name('autoexposuremodedial').get_value()
        elif vendor == 'Nikon':
            mode = camera.get_config().get_child_by_name('expprogram').get_value()
            if mode == "M":
                return "Manual"
            else:
                return mode
        elif vendor == 'Sony':
            # Sony uses 'expprogram' with string value "M" for Manual
            mode = camera.get_config().get_child_by_name('expprogram').get_value()
            if mode == "M":
                return "Manual"
            else:
                return mode
        else:
            return ""
    except gphoto2.GPhoto2Error as e:
        logging.warning('gphoto2 error reading shooting mode for %s: %s', getattr(camera, 'name', str(camera)), e)
        return "Manual"
    except Exception:
        # For virtual/non-gphoto cameras assume Manual shooting mode
        if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
            return "Manual"
        raise


def get_focus_mode(camera: Camera) -> str:
    """ Return the focus mode of the selected camera. Should be "Manual"
    
    Args: 
        - camera: Camera object

    Returns: Focus mode of the camera
    """

    try:
        value = camera.get_config().get_child_by_name('focusmode').get_value()
        # gphoto2 may return localized strings (e.g. German "Manuell") or "undefined"
        # when the camera reports manual focus via the lens/body switch.
        if value is None or value.lower() in ('manuell', 'undefined', 'manual'):
            return 'Manual'
        return value
    except gphoto2.GPhoto2Error as e:
        logging.warning('gphoto2 error reading focus mode for %s: %s', getattr(camera, 'name', str(camera)), e)
        return "Manual"
    except Exception:
        # For virtual/non-gphoto cameras assume Manual focus
        if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
            return "Manual"
        raise


def get_battery_level(camera: Camera) -> str:
    """ Return the battery level of the selected camera 
    
    Args: 
        - camera: Name of the camera

    Returns: Current battery level of the camera [%]
    """

    if camera is None:
        return None

    camera_name = getattr(camera, 'name', str(camera))

    try:
        value = camera.get_config().get_child_by_name('batterylevel').get_value()
        # gphoto2 reports 253 (0xFD) for Sony cameras (and some others) when the
        # camera is powered via an AC adapter rather than a battery.
        if str(value).rstrip('%') == '253':
            logging.info("%s: connected to AC. If wrong - press 'Camera(s)' button again", camera_name)
            return 'AC'
        logging.info('%s: battery level is %s', camera_name, str(value))
        return str(value)
    except gphoto2.GPhoto2Error as e:
        logging.debug('gphoto2 error reading batterylevel for %s: %s', camera_name, e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            logging.debug("%s: busy, will try to read battery level again", camera_name)
            time.sleep(0.1)
            return get_battery_level(camera)
        raise CameraError(f"Could not read battery level for {camera_name}: {e}") from None
    except Exception:
        # VirtualCamera and other non-gphoto cameras don't expose battery info
        if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
            return "100%"
        raise


def get_time(camera: Camera) -> str:
    """ Returns the current time of the selected camera

    Args: 
        - camera: Camera object

    Returns: Current time of the camera
    """

    # For virtual/non-gphoto cameras return host time quickly
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return datetime.now().isoformat(' ')

    # get configuration tree
    try:
        config = camera.get_config()
    except gphoto2.GPhoto2Error as e:
        logging.warning('gphoto2 error reading camera time for %s: %s', getattr(camera, 'name', str(camera)), e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            logging.warning(f"Seems like camera is busy, unable to get the time, trying again")
            time.sleep(0.1)
            return get_time(camera)
        else:
            # Attempt reinitialisation and retry once
            try:
                if hasattr(camera, 'name'):
                    logging.info('Reinitialising camera %s to retry time query', camera.name)
                    new_cam = get_camera(camera.name)
                    config = new_cam.get_config()
            except Exception:
                logging.exception('Reinitialisation attempt failed for %s', getattr(camera, 'name', str(camera)))
                # If retry failed, propagate the original error so the caller can handle it
                raise
    except Exception:
        # If any other error, fall back to host time
        return datetime.now().isoformat(' ')
    # find the date/time setting config item and get it
    # name varies with camera driver
    #   Canon EOS - 'datetime'
    #   PTP - 'd034'
    for name, fmt in (('datetime', '%Y-%m-%d %H:%M:%S'),
                      ('d034', None)):
        now = datetime.now()
        ok, datetime_config = gp.gp_widget_get_child_by_name(config, name)
        if ok >= gp.GP_OK:
            widget_type = datetime_config.get_type()
            raw_value = datetime_config.get_value()
            if widget_type == gp.GP_WIDGET_DATE:
                camera_time = datetime.fromtimestamp(raw_value)
            else:
                if fmt:
                    camera_time = datetime.strptime(raw_value, fmt)
                else:
                    camera_time = datetime.utcfromtimestamp(float(raw_value))
            logging.info('Camera clock:  ', camera_time.isoformat(' '))
            logging.info('Computer clock:', now.isoformat(' '))
            err = now - camera_time
            if err.days < 0:
                err = -err
                lead_lag = 'ahead'
                logging.info('Camera clock is ahead by', )
            else:
                lead_lag = 'behind'
            logging.warning('Camera clock is %s by %d days and %d seconds' % (
                lead_lag, err.days, err.seconds))
            break
    else:
        logging.warning('Unknown date/time config item')
        return "Unknown date/time config item"

    return camera_time.isoformat(' ')


def set_time(camera: Camera) -> None:
    """ Set the computer time on the selected camera """
    # For physical gphoto cameras we set the camera clock; for virtual or
    # non-gphoto cameras this is a no-op.
    try:
        config = camera.get_config()
    except gphoto2.GPhoto2Error as e:
        logging.debug('gphoto2 error getting time from %s: %s', getattr(camera, 'name', str(camera)), e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            logging.warning(f"Seems like camera is busy, unable to set the time, trying again")
            time.sleep(0.1)
            return set_time(camera)
        else:
            # Attempt reinitialisation and retry once
            try:
                if hasattr(camera, 'name'):
                    logging.info('Reinitialising camera %s to retry set_time', camera.name)
                    new_cam = get_camera(camera.name)
                    config = new_cam.get_config()
            except Exception:
                logging.exception('Reinitialisation attempt failed for %s', getattr(camera, 'name', str(camera)))
                # If retry failed, propagate the original error so the caller can handle it
                raise
    except Exception:
        # VirtualCamera or other adapters may not expose get_config(); skip
        return

    if __set_datetime(config):
        # apply the changed config
        try:
            camera.set_config(config)
        except Exception:
            logging.error('Could not apply date & time to camera')
    else:
        logging.warning('Could not set date & time (unsupported operation?)')


def __set_datetime(config) -> bool:
    """ Private method to set the date and time of the camera. """
    # Try gphoto widget API first
    try:
        ok, date_config = gp.gp_widget_get_child_by_name(config, 'datetimeutc')
        if ok == -2:
            ok, date_config = gp.gp_widget_get_child_by_name(config, 'datetime')

        if ok >= gp.GP_OK:
            widget_type = date_config.get_type()
            if widget_type == gp.GP_WIDGET_DATE:
                now = int(time.time())
                date_config.set_value(now)
            else:
                now = time.strftime('%Y-%m-%d %H:%M:%S')
                date_config.set_value(now)
            return True
    except Exception:
        # fall back to stub config API
        pass

    # Fallback for VirtualCamera._ConfigStub or other non-gphoto configs
    try:
        if hasattr(config, 'get_child_by_name'):
            for name in ('datetimeutc', 'datetime', 'd034'):
                try:
                    widget = config.get_child_by_name(name)
                except Exception:
                    widget = None
                if not widget:
                    continue
                try:
                    widget_type = widget.get_type()
                except Exception:
                    widget_type = None

                if widget_type == gp.GP_WIDGET_DATE:
                    now = int(time.time())
                    if hasattr(widget, 'set_value'):
                        widget.set_value(now)
                    else:
                        setattr(widget, '_value', now)
                else:
                    now = time.strftime('%Y-%m-%d %H:%M:%S')
                    if hasattr(widget, 'set_value'):
                        widget.set_value(now)
                    else:
                        setattr(widget, '_value', now)
                return True
    except Exception:
        pass

    return False


def get_camera_dict(is_simulator: bool = False, alias_map: Optional[dict] = None) -> dict:
    """Get a dictionary mapping camera names/aliases to their camera objects.

    Args:
        is_simulator: If True, returns a single VirtualCamera (alias_map is ignored).
        alias_map:    Optional dict ``{serial_number: alias_name_or_list}``.
                      When provided, each detected camera's serial number is read
                      via gphoto2 and looked up in the map.  A serial can map to
                      either a single alias string **or** a list of aliases — the
                      latter lets you save the same physical camera under multiple
                      configuration names (e.g. ``"Canon EOS 80D (telescope)"``
                      and ``"Canon EOS 80D (lens)"``).  The camera object is then
                      registered in the returned dict under **every** alias so that
                      whichever name the current script uses will be found.
                      If only one camera of each model is connected and no aliasing
                      is needed, omit this argument — the gphoto2 model name is
                      used as the key, identical to the original behaviour.

    Returns:
        Dict mapping camera name/alias → BaseCamera adapter.
    """
    if is_simulator:
        # Return a single VirtualCamera for simulator mode
        vc = VirtualCamera()
        vc.connect()
        return {vc.name: vc}

    detected = get_cameras()  # [(model_name, port), ...]
    try:
        logging.info('Found cameras: %s', detected)
    except Exception:
        logging.debug('Could not print found cameras to terminal')

    cameras: dict = {}
    for model_name, port in detected:
        cam = get_camera_by_port(model_name, port)

        key = model_name  # default: use the gphoto2 model name

        if alias_map:
            try:
                serial = get_serial_number(cam)
                if serial and serial in alias_map:
                    raw_aliases = alias_map[serial]
                    # Support both a plain string and a list of aliases
                    if isinstance(raw_aliases, str):
                        raw_aliases = [raw_aliases]
                    key = raw_aliases[0]
                    # Rename the camera object so its .name matches the primary alias
                    cam.name = key
                    logging.debug(
                        'Camera %s@%s serial=%s mapped to alias "%s"',
                        model_name, port, serial, key,
                    )
                    # Register under every additional alias (same camera object)
                    for extra_alias in raw_aliases[1:]:
                        cameras[extra_alias] = cam
                        logging.debug(
                            'Camera %s@%s also registered under alias "%s"',
                            model_name, port, extra_alias,
                        )
                else:
                    logging.debug(
                        'Camera %s@%s serial=%s has no alias mapping; using model name',
                        model_name, port, serial,
                    )
            except Exception:
                logging.exception('Could not read serial number for %s@%s', model_name, port)

        if key in cameras:
            logging.warning(
                'Camera key "%s" already exists in the camera dict.  Multiple cameras '
                'of the same model are connected without distinct aliases.  Connect '
                'each camera separately and use "Detect Connected Camera" in the wizard '
                'to assign unique names, or create unique camera names in the script.',
                key,
            )
        cameras[key] = cam

        # Also register the camera under its base model name without any parenthetical
        # suffix (e.g. "(PC Control)", "(PTP)", "(MTP)") so that scripts written with
        # the plain model name still work even though gphoto2 appends the suffix.
        import re as _re
        bare_key = _re.sub(r'\s*\([^)]*\)\s*$', '', key).strip()
        if bare_key and bare_key != key and bare_key not in cameras:
            cameras[bare_key] = cam
            logging.debug(
                'Camera "%s" also registered under bare key "%s"',
                key, bare_key,
            )

    # --- Deduplicate Sony (and other cameras) that appear twice ---
    # gphoto2 exposes Sony cameras with PC Remote enabled at two USB interfaces:
    #   "Model (Control)"  – the PC Remote / remote-shooting interface (full control)
    #   "Model"            – the plain PTP/MTP interface (limited / no trigger_capture)
    # Both end up as separate entries above.  We keep only the "(Control)" object,
    # point the plain-name key at it too, and close the redundant PTP camera so
    # it does not appear as a second entry in the camera overview.
    import re as _re
    for key in list(cameras.keys()):
        bare = _re.sub(r'\s*\([^)]*\)\s*$', '', key).strip()
        if bare != key and bare in cameras and cameras[bare] is not cameras[key]:
            # key has a suffix (e.g. "(Control)"); bare is a separate object
            control_cam = cameras[key]
            plain_cam = cameras[bare]
            logging.info(
                'Deduplicating camera: "%s" and "%s" are the same physical camera. '
                'Keeping "%s" (full-control interface) for both keys.',
                key, bare, key,
            )
            # Close the redundant plain-PTP camera so its USB handle is freed
            try:
                plain_cam.exit()
            except Exception:
                pass
            # Point the plain-name key at the control interface camera
            cameras[bare] = control_cam

    return cameras


def get_camera_overview() -> dict:
    """ Returns a dictionary with information of the connected cameras.

    The keys in the dictionary are the camera names and the values (the camera information) contains information about
    the battery level and space on the memory card of the camera.

    Returns: Dictionary with information of the connected cameras.
    """

    camera_overview = {}

    camera_names = get_cameras()
    for camera_name in camera_names:
        camera = get_camera(camera_name[0])

        try:
            battery_level = get_battery_level(camera)
            free_space = get_free_space(camera)
            total_space = get_space(camera)

            camera_overview[camera_name[0]] = CameraInfo(camera_name, battery_level, free_space, total_space)
            # camera.exit()
        except gp.GPhoto2Error:
            logging.error("Could not connect to the camera.  Did you start Solar Eclipse Workbench in sudo mode?")

    return camera_overview


class CameraInfo:

    def __init__(self, camera_name: str, battery_level: str, free_space: float, total_space: float) -> None:
        """ Create a new CameraInfo object.

        Args:
            - camera_name: Name of the camera
            - battery_level: Battery level [%]
            - free_space: Free space on the camera memory card [GB]
            - total_space: Total space on the camera memory card [GB]
        """

        self.camera_name = camera_name
        self.battery_level = battery_level
        self.free_space = free_space
        self.total_space = total_space

    def get_camera_name(self) -> str:
        """ Returns the name of the camera.

        Returns: Name of the camera.
        """
        return self.camera_name[0]

    def get_battery_level(self) -> str:
        """ Returns the battery level of the camera.

        Returns: Battery level of the camera [%].
        """
        return self.battery_level

    def get_absolute_free_space(self) -> float:
        """ Returns the absolute free space on the memory card of the camera.

        Returns: Free space on the memory card of the camera [GB].
        """

        return self.free_space

    def get_relative_free_space(self) -> float:
        """ Returns the relative free space on the memory card of the camera.

        Returns: Free space on the memory card of the camera [%].
        """

        return self.get_absolute_free_space() / self.get_total_space() * 100

    def get_total_space(self) -> float:
        """ Returns the total space on the memory card of the camera.

        Returns: Total space on the memory card of the camera [GB].
        """
        return self.total_space


def main():
    # Get cameras
    cameras = get_cameras()

    # Get all information for the gui
    get_camera_overview()

    # Get battery and free space
    for camera in cameras:
        try:
            camera_object = get_camera(camera[0])

            # Get general info
            print(f"{camera[0]}: {get_battery_level(camera_object)} - {get_free_space(camera_object)} GB "
                  f"of {get_space(camera_object)} GB free.")

            # Check if the lens and the camera are set to manual
            if get_shooting_mode(camera[0], camera_object) != "Manual":
                print("Set the camera in Manual mode!")
                exit()

            if get_focus_mode(camera_object) != "Manual":
                print("Set the lens in Manual mode!")
                exit()

            # Set the correct time
            print(get_time(camera_object))
            set_time(camera_object)

            # Take picture
            camera_settings = CameraSettings(camera[0], "1/1000", "8", 100)

            take_picture(camera_object, camera_settings)

            time.sleep(1)
            camera_settings = CameraSettings(camera[0], "1/200", "6.3", 400)
            # take_bracket(camera_object, camera_settings, "+/- 1 2/3")
            take_picture(camera_object, camera_settings)

            # Mirror lock
            # mirror_lock(camera_object, camera_settings)

            # take_picture(camera_object, camera_settings)
            
            time.sleep(1)
            camera_settings = CameraSettings(camera[0], "1/400", "6.3", 400)
            # take_bracket(camera_object, camera_settings, "+/- 1 2/3")
            take_picture(camera_object, camera_settings)

            time.sleep(1)
            camera_settings = CameraSettings(camera[0], "1/4000", "5.6", 200)
            take_burst(camera_object, camera_settings, 1)
            time.sleep(3)
            camera_object.exit()

        except gphoto2.GPhoto2Error:
            print("Could not connect to the camera.  Did you start Solar Eclipse Workbench in sudo mode?")


def get_sony_save_destination(camera) -> str | None:
    """Return the Sony PC-Remote 'Save Destination' value string, or None if not found.

    This probes the camera config for widgets whose name/label contains
    keywords like 'save' or 'dest' and returns the widget value (string).
    Returns None when the widget is not exposed via gphoto2.
    """
    if camera is None:
        return None

    sony_camera_name = getattr(camera, 'name', str(camera))

    try:
        sony_capture_target = camera.get_config().get_child_by_name('capturetarget').get_value()
        logging.info("%s: capture target is %s", sony_camera_name, sony_capture_target)
        return sony_capture_target
    except gphoto2.GPhoto2Error as e:
        logging.debug('gphoto2 error reading capturetarget for %s: %s', sony_camera_name, e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            logging.warning("%s: busy, unable to get capture target, trying again", sony_camera_name)
            time.sleep(0.1)
            return get_sony_save_destination(camera)
        else:
            logging.warning("%s: lacks capture target setting", sony_camera_name)
            return None
    except Exception:
        return None


def get_sony_image_quality(camera: Camera) -> str:
    """ Return the image quality of the selected Sony camera.

    Args:
        - camera: Camera object

    Returns: Image quality setting of the camera
    """
    if camera is None:
        return None

    sony_camera_name = getattr(camera, 'name', str(camera))

    try:
        sony_image_quality = camera.get_config().get_child_by_name('imagequality').get_value()
        logging.info("%s: file format / quality is %s", sony_camera_name, sony_image_quality)
        return sony_image_quality
    except gphoto2.GPhoto2Error as e:
        logging.debug('gphoto2 error reading imagequality for %s: %s', getattr(camera, 'name', str(camera)), e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            logging.warning(
                "%s: busy, unable to get image quality, trying again", sony_camera_name)
            time.sleep(0.1)
            return get_sony_image_quality(camera)
    except Exception:
        return None


if __name__ == "__main__":
    main()
