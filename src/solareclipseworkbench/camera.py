import functools
import locale
import logging
import subprocess
import sys
import threading
import time

import gphoto2
import gphoto2 as gp
from datetime import datetime, timezone
import os

from gphoto2 import Camera
from abc import ABC, abstractmethod
from typing import Any, Tuple, Optional
from solareclipseworkbench import configuration
from solareclipseworkbench.logging_setup import camera_log


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
        camera_log(name).debug('GPhotoCameraAdapter created, vendor=%s', self.vendor)
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
            _drain_camera_events(target, context)
        except Exception:
            camera_log(self).debug('SonyCamera.disconnect() event drain raised (non-fatal)')

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
            camera_log(self).info('Background Downloader started')
        except Exception:
            camera_log(self).exception('failed to start Background Downloader')

    def stop_background_downloader(self) -> None:
        if self._bg_downloader is None:
            return

        downloader = self._bg_downloader
        try:
            downloader.stop()
            downloader.join(timeout=2.0)

            # Check if the thread actually exited
            if downloader.is_alive():
                camera_log(self).warning('Background Downloader failed to terminate within timeout.')

                # Force-release the USB lock if the thread is stuck and holding it
                if hasattr(self, '_usb_lock') and self._usb_lock.locked():
                    try:
                        self._usb_lock.release()
                        camera_log(self).warning('forced release of _usb_lock after downloader thread timeout.')
                    except RuntimeError:
                        # Raised if release() is called on an unacquired or cross-thread locked RLock/Lock
                        pass
        except Exception as e:
            camera_log(self).debug('error stopping Background Downloader (%s)', e)
        finally:
            self._bg_downloader = None


# macOS starts ptpcamerad (the daemon behind Image Capture and Photos) as soon as a PTP
# camera is plugged in or touched, and it claims USB interface 0 exclusively — gphoto2 then
# fails with -53.  Killing it opens a window; these bound how hard we try to hit that window.
_PTP_CLAIM_ATTEMPTS = 10
_PTP_CLAIM_RETRY_DELAY = 0.3

# Daemon names to stop.  macOS 13+ uses ptpcamerad; older releases used PTPCamera.
_MACOS_PTP_DAEMONS = ('ptpcamerad', 'PTPCamera')


def _release_macos_ptp_daemon() -> bool:
    """Stop macOS' PTP daemon so gphoto2 can claim the camera.

    Returns True when a daemon process was actually signalled.

    The daemon runs as the logged-in user, so no privileges are required to stop it —
    ``sudo`` is not needed and is deliberately not used.  launchd restarts it on demand
    afterwards, which is harmless: the kill only has to open a window long enough for
    ``camera.init()`` to claim the interface.  Once we hold it, a respawned daemon cannot
    take it back, so this is a start-up race rather than a permanent conflict.

    Note that ``launchctl disable`` is *not* a reliable alternative on recent macOS: the
    daemon is also started on demand through ImageCaptureCore's XPC service, which bypasses
    the disabled launchd job, and SIP refuses ``launchctl bootout``.
    """
    if sys.platform != 'darwin':
        return False

    killed = False
    for daemon in _MACOS_PTP_DAEMONS:
        try:
            # -u limits the kill to this user's processes, so a shared machine is unaffected.
            result = subprocess.run(
                ['/usr/bin/pkill', '-9', '-u', str(os.getuid()), '-x', daemon],
                capture_output=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logging.debug('Could not run pkill for %s: %s', daemon, e)
            continue
        # pkill exits 0 when it matched something, 1 when nothing matched.
        if result.returncode == 0:
            logging.info('Stopped macOS %s so the camera can be claimed', daemon)
            killed = True
    return killed


def _init_camera_claiming_usb(camera, context, camera_name: str) -> None:
    """Initialise *camera*, working around macOS' PTP daemon holding the USB device.

    On a -53 (USB claim) failure on macOS the PTP daemon is stopped and the init retried,
    because the daemon reliably wins the race against application start-up.  Any other
    error, or a -53 on another platform, is reported immediately — there the fix is a
    driver or permissions change that no amount of retrying will achieve.
    """
    try:
        camera.init(context)
        return
    except gphoto2.GPhoto2Error as e:
        if getattr(e, 'code', None) != -53 or sys.platform != 'darwin':
            _raise_camera_init_error(camera_name, e)
        last_error = e

    log = camera_log(camera_name)
    log.info('busy (macOS PTP daemon); reclaiming the USB device')
    for attempt in range(1, _PTP_CLAIM_ATTEMPTS + 1):
        _release_macos_ptp_daemon()
        time.sleep(_PTP_CLAIM_RETRY_DELAY)
        try:
            camera.init(context)
            log.info('claimed after %d attempt(s)', attempt)
            return
        except gphoto2.GPhoto2Error as e:
            last_error = e
            if getattr(e, 'code', None) != -53:
                break
            log.debug('claim attempt %d/%d failed', attempt, _PTP_CLAIM_ATTEMPTS)

    _raise_camera_init_error(camera_name, last_error)


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

    * **macOS**: the system PTP daemon grabs the device immediately.  Quit Image Capture,
      Photos and Sony Imaging Edge, then stop the daemon.  It is called ``ptpcamerad`` on
      macOS 13 and later and ``PTPCamera`` on older releases; the binary does not exist
      under the old name on current systems, so kill both:
          pkill -9 ptpcamerad; pkill -9 PTPCamera
      The daemon runs as the logged-in user, so no privileges are needed.  launchd restarts
      it on demand, but once gphoto2 holds the interface it cannot be taken back.

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
            "On macOS: quit Image Capture / Photos / Sony Imaging Edge, then stop the system\n"
            "PTP daemon: pkill -9 ptpcamerad  (older macOS: pkill -9 PTPCamera).\n"
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


def _widget_choices(widget) -> list[str]:
    """Return all choice strings of a gphoto2 radio/menu widget (empty list on error)."""
    try:
        n = gp.check_result(gp.gp_widget_count_choices(widget))
        return [gp.check_result(gp.gp_widget_get_choice(widget, i)) for i in range(n)]
    except gphoto2.GPhoto2Error:
        return []


def _canon_remote_release_values(widget) -> tuple[str, str]:
    """Return the (press, release) ``eosremoterelease`` values for a full manual-focus press.

    libgphoto2 2.5.34 renamed these choices (python-gphoto2 2.6.4 bundles it):

    ==================  ==================  ==========================
    PTP call            libgphoto2 <= 2.5.33  libgphoto2 >= 2.5.34
    ==================  ==================  ==========================
    RemoteReleaseOn 3,1  "Press Full"        "Press Full MF"
    RemoteReleaseOff 3   "Release Full"      "Release"
    ==================  ==================  ==========================

    In 2.5.34 "Release Full" still exists but sends RemoteReleaseOff(2), which
    does not release a press that was started with RemoteReleaseOn(3).  Pick the
    pair matching the installed libgphoto2 by inspecting the widget's choices.
    """
    choices = _widget_choices(widget)
    if "Press Full MF" in choices:
        return "Press Full MF", "Release"
    return "Press Full", "Release Full"


# Continuous drive modes in order of preference.  Canon bodies only accept the
# values in their own enumeration (e.g. the EOS R10 has no plain "Continuous"),
# so the first one the camera actually offers is used.  Silent (electronic
# shutter) modes are last because of rolling-shutter distortion.
_CANON_CONTINUOUS_DRIVE_MODES = (
    "Continuous high speed",
    "Continuous",
    "Super high speed continuous shooting",
    "Continuous low speed",
    "Silent HS continuous",
    "Continuous silent",
    "Silent LS continuous",
)


def _find_canon_continuous_drivemode(widget) -> Optional[str]:
    """Return the best continuous ``drivemode`` choice offered by a Canon camera, or None."""
    choices = _widget_choices(widget)
    for mode in _CANON_CONTINUOUS_DRIVE_MODES:
        if mode in choices:
            return mode
    for choice in choices:
        if "continuous" in choice.lower() and "timer" not in choice.lower():
            return choice
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
            camera_log(camera).warning(
                '%s dropped — camera was still busy after %.1fs '
                '(shot is too late; timing accuracy preserved)',
                func.__name__, _MAX_LOCK_WAIT_S,
            )
            return
        try:
            return func(camera, *args, **kwargs)
        finally:
            camera._last_usb_activity = time.monotonic()
            camera._usb_lock.release()
    return wrapper


def _wait_for_capture_complete(target, context, timeout_ms: int = 3000, max_events: int = 30) -> None:
    """Wait until the camera signals GP_EVENT_CAPTURE_COMPLETE after a trigger_capture call.

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
            event_type, _ = gp.check_result(gp.gp_camera_wait_for_event(target, timeout_ms, context))
            if event_type in (gp.GP_EVENT_CAPTURE_COMPLETE, gp.GP_EVENT_TIMEOUT):
                break
        except gphoto2.GPhoto2Error:
            break


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
        self._log = camera_log(self.camera_name)

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
        self._log.info("queued %s", name)

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
        self._log.info("saved %s (%d bytes)", save_path, size)
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
                    self._log.debug("Background Downloader: wait_for_event failed: %s", e)
                    event_type, event_data = gp.GP_EVENT_TIMEOUT, None
                    error_str = str(e).lower()
                    if any(x in error_str for x in ['-52', 'could not find the requested device']):
                        self._log.warning("Background Downloader: camera got disconnected, shutting down")
                        self.stop()
                    if any(x in error_str for x in ['-110', 'i/o in progress']):
                        self._log.info("Background Downloader: camera is busy, safe to ignore")

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
                        self._log.debug("Background Downloader: fallback list failed: %s", exc)
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
                        self._log.debug(
                            "Background Downloader: download not ready for %s: %s (retry in %.1fs)",
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
                        self._log.warning(
                            "Background Downloader: download failed for %s: %s (retry in %.1fs)",
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
            camera_log(self._camera).info("LiveViewThread: requested exit live view")

            # Optional: small delay + re-init can help some bodies
            time.sleep(0.3)
            # gp.gp_camera_init(target, context)  # uncomment if needed
        except Exception as e:
            camera_log(self._camera).debug("LiveViewThread: could not exit live view: %s", e)

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def run(self):
        # If the camera provides a capture_preview() method (e.g. VirtualCamera
        # in simulator mode), use that path — no gphoto2 calls or USB lock needed.
        # Do not use this path for wrapped gphoto2 cameras: delegated
        # capture_preview() may return a CameraFile object (not JPEG bytes).
        _has_virtual_preview = isinstance(self._camera, VirtualCamera)

        log = camera_log(self._camera)
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
                    log.exception('LiveViewThread: virtual preview failed')
                continue

            acquired = False
            try:
                acquired = self._camera._usb_lock.acquire(timeout=self._lock_timeout)
                if not acquired:
                    log.debug('LiveViewThread: USB lock busy, skipping frame')
                    continue

                cam_file = gp.CameraFile()
                # Signal that capture_preview has been called on this camera.
                # Used by take_picture / take_hdr to detect the Canon EOS R
                # eos_remotemode conflict (see _reset_canon_eos_ptp_session).
                self._camera._capture_preview_was_called = True
                gp.check_result(gp.gp_camera_capture_preview(target, cam_file, context))
                file_data = gp.check_result(gp.gp_file_get_data_and_size(cam_file))
                self._camera._last_usb_activity = time.monotonic()
                self._frame_callback(bytes(file_data))
            except gphoto2.GPhoto2Error as exc:
                log.debug('LiveViewThread: preview capture failed: %s', exc)
            except Exception:
                log.exception('LiveViewThread: unexpected error')
            finally:
                if acquired:
                    try:
                        self._camera._usb_lock.release()
                    except Exception:
                        pass


# Interval between keep-alive pings.  Well below the shortest auto power off
# the supported bodies allow (Canon: 30 s / 1 min), so one ping always lands
# before the camera's idle timer expires.
KEEP_ALIVE_INTERVAL_S: float = 20.0


class CameraKeepAliveThread(threading.Thread):
    """Background thread that keeps idle cameras from going to sleep.

    Between connecting the cameras and the first scheduled shot there can be
    an hour or more without any USB traffic, long enough for the camera's own
    auto power off to put it to sleep, after which gphoto2 cannot wake it.
    Every *interval_s* this thread does a cheap config read (the battery
    level) on each camera that has not been used over USB within the last
    interval, which resets the idle timer on most Canon and Nikon bodies.

    Like LiveViewThread it never competes with a scheduled shot: the USB lock
    is taken with a short timeout and the ping is skipped when it is busy.
    The caller-supplied *should_ping* hook lets the GUI suspend pings
    altogether, e.g. around totality or just before a scheduled command.

    Parameters
    ----------
    cameras_provider : callable[[], iterable]
        Returns the currently connected cameras.  Called every cycle so that a
        camera refresh in the GUI is picked up without restarting the thread.
    interval_s : float
        Interval between pings in seconds.
    lock_timeout : float
        Maximum seconds to wait for the USB lock before skipping a ping.
    should_ping : callable[[], bool], optional
        Returns False while pings must be suspended.  Must be thread-safe.
    """

    def __init__(self, cameras_provider, interval_s: float = KEEP_ALIVE_INTERVAL_S,
                 lock_timeout: float = 0.05, should_ping=None):
        super().__init__(daemon=True, name='CameraKeepAlive')
        self._cameras_provider = cameras_provider
        self._interval_s = interval_s
        self._lock_timeout = lock_timeout
        self._should_ping = should_ping
        self._stop_event = threading.Event()
        # Names of cameras that failed their last ping, so the problem is
        # reported once rather than every cycle.
        self._unresponsive: set = set()

    def stop(self):
        """Signal the thread to stop."""
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(self._interval_s):
            try:
                if self._should_ping is not None and not self._should_ping():
                    continue
                self.ping_all()
            except Exception:
                logging.exception('CameraKeepAlive: unexpected error')

    def ping_all(self) -> None:
        """Ping every connected camera that has been idle for a full interval."""
        seen: set = set()
        for camera in list(self._cameras_provider() or []):
            # Aliases map several names onto the same camera object
            if camera is None or id(camera) in seen:
                continue
            seen.add(id(camera))
            # Virtual cameras never sleep; disconnected ones are being replaced
            if not hasattr(camera, '_camera') or isinstance(camera, VirtualCamera):
                continue
            if hasattr(camera, 'is_connected') and not camera.is_connected():
                continue
            idle_s = time.monotonic() - getattr(camera, '_last_usb_activity', 0.0)
            if idle_s < self._interval_s:
                continue
            self._ping(camera)

    def _ping(self, camera) -> None:
        camera_name = getattr(camera, 'name', str(camera))
        log = camera_log(camera_name)
        acquired = camera._usb_lock.acquire(timeout=self._lock_timeout)
        if not acquired:
            log.debug('CameraKeepAlive: USB lock busy, skipping ping')
            return
        try:
            _keep_alive_request(camera)
            camera._last_usb_activity = time.monotonic()
            if camera_name in self._unresponsive:
                self._unresponsive.discard(camera_name)
                log.info('CameraKeepAlive: responding again')
            log.debug('CameraKeepAlive: pinged')
        except gphoto2.GPhoto2Error as exc:
            if exc.code == gp.GP_ERROR_CAMERA_BUSY:
                log.debug('CameraKeepAlive: busy, skipping ping')
                return
            if camera_name not in self._unresponsive:
                self._unresponsive.add(camera_name)
                from solareclipseworkbench import hardware_problems
                hardware_problems.report(
                    camera_name,
                    "Camera stopped responding - it may have gone to sleep (auto power off) or been "
                    "disconnected. Wake it up and press 'Camera(s)'",
                    detail=str(exc),
                )
        finally:
            camera._usb_lock.release()


def _keep_alive_request(camera) -> None:
    """Do the cheapest config read that still counts as USB activity for the camera."""
    target = camera._camera if hasattr(camera, '_camera') else camera
    context = gp.gp_context_new()
    try:
        gp.check_result(gp.gp_camera_get_single_config(target, 'batterylevel', context))
    except gphoto2.GPhoto2Error as exc:
        if exc.code not in (gp.GP_ERROR_NOT_SUPPORTED, gp.GP_ERROR_BAD_PARAMETERS):
            raise
        # Older drivers cannot read a single widget; fall back to the full tree
        gp.check_result(gp.gp_camera_get_config(target, context))


# Auto power off settings shorter than this get a warning at connect time.
# The keep-alive pings normally stop the timer from ever running out, but they
# are paused around totality and not every body honours them, so the camera's
# own setting is the real safety net.
MIN_AUTO_POWER_OFF_S: float = 30 * 60

# Config widgets that hold the camera's sleep timer, per vendor.  Sony bodies
# do not expose theirs over PTP.
_AUTO_POWER_OFF_WIDGETS = {
    'Canon': ['autopoweroff'],
    'Nikon': ['autopoweroff', 'meterofftime'],
}

_DISABLED_WORDS = ('disable', 'off', 'never', 'no limit', 'unlimited', 'infinite', 'none')

_DURATION_UNITS = {
    's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
    'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
    'h': 3600, 'hr': 3600, 'hour': 3600, 'hours': 3600,
}


def parse_power_off_delay(value) -> Optional[float]:
    """Convert an auto power off / standby timer widget value to seconds.

    gphoto2 reports these either as a bare number of seconds (Canon EOS,
    where 0 means disabled) or as text such as "30 minutes", "1m", "16 s" or
    "No limit" (Nikon).

    Returns:
        The delay in seconds, or None when the timer is disabled.

    Raises:
        ValueError: when the value cannot be interpreted.
    """
    text = str(value).strip().lower()
    if not text:
        raise ValueError('empty auto power off value')
    if any(word in text for word in _DISABLED_WORDS):
        return None
    try:
        seconds = float(text)
    except ValueError:
        pass
    else:
        # 0 and the all-ones UINT32 sentinel both mean "never"
        return None if seconds <= 0 or seconds >= 0xFFFFFFFF else seconds

    number = ''
    for i, char in enumerate(text):
        if char.isdigit() or char == '.':
            number += char
        else:
            unit = text[i:].strip()
            break
    else:
        unit = ''
    if not number or unit not in _DURATION_UNITS:
        raise ValueError(f'unrecognised auto power off value: {value!r}')
    return float(number) * _DURATION_UNITS[unit]


def get_auto_power_off(camera) -> Optional[Tuple[str, str, Optional[float]]]:
    """Read the camera's auto power off (or standby) timer.

    Args:
        - camera: Camera object

    Returns:
        (widget label, raw value, delay in seconds or None when disabled), or
        None when the camera does not expose such a setting.
    """
    if not hasattr(camera, '_camera') or isinstance(camera, VirtualCamera):
        return None

    target = camera._camera
    context = gp.gp_context_new()
    for widget_name in _AUTO_POWER_OFF_WIDGETS.get(getattr(camera, 'vendor', None), []):
        try:
            widget = gp.check_result(gp.gp_camera_get_single_config(target, widget_name, context))
        except gphoto2.GPhoto2Error:
            continue
        label = widget.get_label() or widget_name
        raw_value = widget.get_value()
        try:
            return label, str(raw_value), parse_power_off_delay(raw_value)
        except ValueError:
            camera_log(camera).debug('could not interpret %s = %r', widget_name, raw_value)
            continue
    return None


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
        camera_log(camera).info(
            'Canon EOS: PTP session reset before first capture '
            '(live view had initialised eos_remotemode=1; cleared for trigger_capture)'
        )
    except gphoto2.GPhoto2Error as e:
        camera_log(camera).warning(
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
    vendor = getattr(camera, 'vendor', None)
    log = camera_log(camera)

    # Canon EOS R live-view / trigger_capture mode conflict:
    # If capture_preview (live view) was called before the first trigger_capture
    # on a Canon EOS R mirrorless body, gphoto2's internal eos_remotemode is set
    # to 1, preventing trigger_capture from initialising it to 15.  Reset the PTP
    # session once to clear the stale remote mode.  Only applies before the first
    # successful capture; subsequent shots are unaffected.
    if (vendor == 'Canon'
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
            log.exception('Virtual camera capture failed: %s', e)
            raise

    target = camera._camera if hasattr(camera, '_camera') else camera

    # For Nikon cameras, defensively ensure single-frame mode is active before
    # taking a single picture, in case a previous take_burst left the camera in
    # continuous/burst mode.
    # For Sony cameras, ensure single-frame capture mode is active before taking
    # a single picture (separate set_config call so a bad capturemode value can
    # never poison the ISO/shutter batch).
    if vendor in ('Nikon', 'Sony'):
        try:
            cfg2 = gp.check_result(gp.gp_camera_get_config(target, context))
            capture_mode_widget = gp.check_result(gp.gp_widget_get_child_by_name(cfg2, 'capturemode'))
            single_choice = _find_capturemode_choice(capture_mode_widget, want_continuous=False)
            if single_choice is not None:
                gp.gp_widget_set_value(capture_mode_widget, single_choice)
                _set_gp_config(camera, cfg2, context)
                log.debug('ensured capturemode="%s" before take_picture', single_choice)
            else:
                log.warning('no "single" choice found for capture mode, leaving as-is')
        except gphoto2.GPhoto2Error as exc:
            if vendor == "Nikon":
                try:
                    capture_mode_widget = gp.check_result(
                        gp.gp_widget_get_child_by_name(config, 'stillcapturemode'))
                    gp.gp_widget_set_value(capture_mode_widget, 0)  # 0 = Single Frame
                    _set_gp_config(camera, config, context)
                    log.debug(
                        'ensured stillcapturemode is Single Frame (0) before take_picture')
                except gphoto2.GPhoto2Error as e:
                    log.warning(
                        'could not ensure single-frame mode before take_picture: %s', e)
            else:
                log.warning(
                    'could not ensure single-frame mode before take_picture: %s', exc)

    # Ensure that no lingering events are left before proceeding.
    # Sony in PC mode must be skipped, to avoid disrupting Background Downloader.
    if not (hasattr(camera, '_bg_downloader')
            and camera._bg_downloader is not None
            and camera._bg_downloader.is_alive()):
        _drain_camera_events(target, context)

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
        log.debug('take_picture fired trigger_capture')
        # For all cameras except Sony set in PC only mode - wait for
        # the image capture and flush the PTP events.
        if not (hasattr(camera, '_bg_downloader')
                and camera._bg_downloader is not None
                and camera._bg_downloader.is_alive()):
            speed_ms = int(_parse_shutter_speed_seconds(camera_settings.shutter_speed) * 1000)
            timeout_ms = speed_ms + 3000
            _wait_for_capture_complete(target, context, timeout_ms = timeout_ms)
            _drain_camera_events(target, context)
        # First successful trigger_capture: eos_remotemode is now 15 (EOS R) or
        # unchanged (DSLR).  Mark as done so no further PTP session reset is needed.
        if vendor == 'Canon':
            camera._first_capture_done = True
    except gphoto2.GPhoto2Error as e:
        log.warning('trigger_capture failed (%s), falling back to GP_CAPTURE_IMAGE', e)
        try:
            camera.capture(gp.GP_CAPTURE_IMAGE, context)
        except Exception:
            log.debug('GP_CAPTURE_IMAGE fallback also failed')
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
    log = camera_log(camera)

    # --- Step 1: mutate exposure mode in memory (no separate set_config) ---
    # The mode widget is included in the ISO+shutter batch below so that all
    # three reach the camera in a single USB round-trip instead of two.
    if vendor == 'Nikon':
        try:
            exp_program = gp.check_result(gp.gp_widget_get_child_by_name(config, 'expprogram'))
            gp.gp_widget_set_value(exp_program, "1")  # 1 = Manual
            log.debug('Queued Nikon expprogram=Manual for next set_config')
        except gphoto2.GPhoto2Error as e:
            log.warning('Could not queue Nikon expprogram: %s', e)
    elif vendor == 'Canon':
        try:
            ae_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'autoexposuremodedial'))
            gp.gp_widget_set_value(ae_mode, "Manual")
            log.debug('Queued Canon autoexposuremodedial=Manual for next set_config')
        except gphoto2.GPhoto2Error as e:
            log.debug('Could not queue Canon autoexposuremodedial: %s', e)
        # Force single-frame drive mode so that eosremoterelease='Immediate' fires
        # exactly one shot even if the camera was left in continuous/burst mode.
        try:
            drive_w = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
            gp.gp_widget_set_value(drive_w, 'Single')
            log.debug('Queued Canon drivemode=Single for next set_config')
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
            log.debug('Could not disable auto ISO: %s', e)

    try:
        gp.gp_widget_set_value(
            gp.check_result(gp.gp_widget_get_child_by_name(config, 'iso')), str(camera_settings.iso))
    except gphoto2.GPhoto2Error as e:
        log.warning('Could not set ISO to %s: %s', camera_settings.iso, e)

    try:
        ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
        closest = _find_closest_shutter_choice(ss_widget, camera_settings.shutter_speed)
        if closest is not None:
            gp.gp_widget_set_value(ss_widget, closest)
            log.info('Using closest shutter speed choice: %s', closest)
        else:
            ss2_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed2'))
            closest = _find_closest_shutter_choice(ss2_widget, camera_settings.shutter_speed)
            if closest is not None:
                gp.gp_widget_set_value(ss2_widget, closest)
                log.info('Using closest shutter speed choice: %s', closest)
            else:
                log.warning('No suitable shutter speed choice found for %s',
                            camera_settings.shutter_speed)
    except gphoto2.GPhoto2Error as e:
        log.warning('Could not set closest shutter speed: %s', e)

    # Always save to the camera's memory card, never to the computer.
    # This must be re-asserted on every shot because some cameras reset
    # capturetarget to 'Internal RAM' when the USB session is re-used.
    # Skip Sony cameras, as this option is set in stone once USB is connected.
    try:
        if not _is_sony_camera_instance(camera):
            capture_target_w = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturetarget'))
            card_value = _find_memory_card_choice(capture_target_w)
            gp.gp_widget_set_value(capture_target_w, card_value)
            log.debug('Asserted capturetarget="%s" before capture', card_value)
    except gphoto2.GPhoto2Error:
        pass  # Widget absent on some cameras — the init-time setting is sufficient

    # Push ISO + shutter speed (+ capturetarget) together — one USB round-trip.
    _set_gp_config(target, config, context)

    # --- Step 3: aperture in an isolated round-trip ---
    # Kept separate so that a failure here (e.g. telescope / fixed-aperture lens)
    # never silently rolls back the ISO and shutter speed that were just applied.
    try:
        ap_key = str(camera_settings.aperture)
        cam_key = camera_settings.camera_name

        if vendor == 'Canon':
            ap_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aperture'))
            gp.gp_widget_set_value(ap_widget, ap_key)
            _set_gp_config(camera, config, context)
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
                    if isinstance(sample, str) and sample.startswith('f/') and not ap_key.startswith('f/'):
                        ap_key = f'f/{ap_key}'
                    gp.gp_widget_set_value(f_widget, ap_key)
                    _set_gp_config(target, config, context)
                    log.debug('Set aperture to %s', camera_settings.aperture)
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
        if ap_key not in _aperture_verified.get(cam_key, set()):
            try:
                config_rb = gp.check_result(gp.gp_camera_get_config(target, context))
                widget_name = 'aperture' if vendor == 'Canon' else 'f-number'
                rb_widget = gp.check_result(gp.gp_widget_get_child_by_name(config_rb, widget_name))
                rb_actual = str(gp.check_result(gp.gp_widget_get_value(rb_widget)))

                def _strip_f(v: str) -> str:
                    return v[2:] if v.startswith('f/') else v

                if _strip_f(rb_actual) != _strip_f(ap_key):
                    log.warning(
                        'aperture read-back mismatch, requested f/%s but camera reports %s. '
                        'The camera may not support remote aperture control via USB — '
                        'set the aperture manually on the lens/camera body.',
                        _strip_f(ap_key), rb_actual)
                # Mark as checked regardless — mismatch or not, no point repeating the warning.
                _aperture_verified.setdefault(cam_key, set()).add(ap_key)
            except gphoto2.GPhoto2Error:
                pass  # Read-back failure is non-fatal
    except gphoto2.GPhoto2Error:
        # Read-only or absent aperture widget (telescope, fixed-aperture lens) — ignore.
        log.debug('Aperture widget not settable (telescope/fixed lens) — skipping')

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
    vendor = getattr(camera, 'vendor', None)
    log = camera_log(camera)

    # Canon EOS R live-view / trigger_capture mode conflict: if live view was
    # used before the first capture, the PTP session may need resetting so
    # remote-release based bursts work correctly (same check as in take_picture).
    if (vendor == 'Canon'
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
            log.exception('Virtual burst capture failed')
            raise

    target = camera._camera if hasattr(camera, '_camera') else camera

    # Ensure that no lingering events are left before proceeding.
    # Sony in PC mode must be skipped, to avoid disrupting Background Downloader.
    if not (hasattr(camera, '_bg_downloader')
            and camera._bg_downloader is not None
            and camera._bg_downloader.is_alive()):
        _drain_camera_events(target, context)

    # Take picture for real cameras
    if vendor == 'Canon':
        # For bursts, ensure the camera is in a continuous drive mode so
        # holding the remote release fires repeated frames rather than one.
        # The return code must be checked: gp_camera_set_config does not raise,
        # and a drive mode the body does not support would otherwise silently
        # leave it in Single (one frame per burst, e.g. on the EOS R10).
        try:
            drive_w = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
            continuous = _find_canon_continuous_drivemode(drive_w)
            if continuous is None:
                log.warning('no continuous drive mode available; take_burst will take a single '
                            'frame. Set the drive mode to continuous on the camera.')
            else:
                gp.gp_widget_set_value(drive_w, continuous)
                gp.check_result(_set_gp_config(camera, config, context))
                log.debug('Set Canon drivemode to "%s" for burst', continuous)
        except gphoto2.GPhoto2Error as e:
            log.warning('could not set a continuous drive mode (%s); take_burst may take a single '
                        'frame. Set the drive mode to continuous on the camera.', e)

        try:
            # Push the button (press & hold for the requested duration)
            remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
            press, release = _canon_remote_release_values(remote_release)
            gp.gp_widget_set_value(remote_release, press)
            gp.check_result(_set_gp_config(camera, config, context))
        except gphoto2.GPhoto2Error as e:
            # If 'eosremoterelease' is not supported (e.g. Canon 1000D), then
            # fallback to just take as number of shots equal to `burst_number`
            log.warning("'eosremoterelease' is not supported (%s), will take %s shots instead",
                        e, str(duration))
            for fallback_shot in range(int(duration)):
                take_picture(camera, camera_settings)
        else:
            try:
                time.sleep(duration)
            finally:
                # Always release the button, or the camera keeps shooting
                try:
                    remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
                    gp.gp_widget_set_value(remote_release, release)
                    gp.check_result(_set_gp_config(camera, config, context))
                except gphoto2.GPhoto2Error as e:
                    log.error("could not release the shutter after take_burst ('%s' failed: %s)",
                              release, e)

            # Ensure that the camera truly finished, so it won't affect next commands
            _wait_for_capture_complete(target, context)
            _drain_camera_events(target, context)
    elif vendor == 'Nikon':
        # Set capture mode to burst/continuous
        # Try different widget names (differs between DSLR and mirrorless models)
        try:
            # Try 'capturemode' first (older DSLRs)
            capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
            gp.gp_widget_set_value(capture_mode, "Burst")
            _set_gp_config(camera, config, context)
            log.debug('Set capturemode to Burst')
        except gphoto2.GPhoto2Error:
            try:
                # Try 'stillcapturemode' (newer mirrorless like Z8/Z9)
                # Value 2 is typically Continuous Low, higher values for High Speed
                capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'stillcapturemode'))
                gp.gp_widget_set_value(capture_mode, 2)  # Continuous shooting mode
                _set_gp_config(camera, config, context)
                log.debug('Set stillcapturemode to Continuous (2)')
            except gphoto2.GPhoto2Error as e:
                log.warning('Could not set Nikon burst/continuous mode: %s', e)

        # Set burst number
        try:
            burst_number = gp.check_result(gp.gp_widget_get_child_by_name(config, 'burstnumber'))
            gp.gp_widget_set_value(burst_number, round(duration))
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning('Could not set Nikon burst number: %s', e)

        try:
            camera.capture(gp.GP_CAPTURE_IMAGE, context)
        except Exception:
            log.exception('high-level capture failed, trying low-level gp capture')
            try:
                ctx = gp.gp_context_new()
                gp.check_result(gp.gp_camera_capture(target, gp.GP_CAPTURE_IMAGE, ctx))
            except Exception:
                log.exception('low-level capture failed')
                raise

        # Rest burst number back to 1, to avoid interference with future commands.
        try:
            gp.gp_widget_set_value(burst_number, 1)
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning("could not reset Nikon burst number to 1 due to '%s'", e)
    elif vendor == 'Sony':
        # Sony burst: enable continuous capture mode, turn on the bulb,
        # sleep for the chosen amount of time, turn off the bulb and
        # lastly drain camera's events
        # Switch to continuous capture mode — look up the actual choice string so
        # we never send an invalid value that would cause set_config to fail.
        try:
            capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
            continuous_choice = _find_capturemode_choice(capture_mode, want_continuous=True, custom_keyword=configuration.SONY_CONTINUOUS_MODE)
            if continuous_choice is not None:
                gp.gp_widget_set_value(capture_mode, continuous_choice)
                _set_gp_config(camera, config, context)
                log.info('set capturemode to "%s" for burst', continuous_choice)
            else:
                log.debug('Sony capturemode: no "continuous" choice found, firing without mode change')
        except gphoto2.GPhoto2Error as e:
            log.warning('Could not set Sony capturemode to Continuous: %s', e)

        try:
            bulb_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'bulb'))
            gp.gp_widget_set_value(bulb_mode, 1)
            _set_gp_config(camera, config, context)
            log.debug('Set Sony bulb mode to 1')
            time.sleep(duration)
            gp.gp_widget_set_value(bulb_mode, 0)
            _set_gp_config(camera, config, context)
            log.debug('Set Sony bulb mode to 0')
            if not (hasattr(camera, '_bg_downloader')
                    and camera._bg_downloader is not None
                    and camera._bg_downloader.is_alive()):
                _drain_camera_events(target, context)
        except gphoto2.GPhoto2Error as e:
            log.warning('Sony burst capture failed: %s', e)


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


def parse_bracketing_string(bracket_str: str) -> tuple[float, int]:
    """Extract EV step size and number of pictures from a bracketing string."""
    import re as _re
    match = _re.search(r"(\d+\.\d+).+?(\d+)", bracket_str)
    if not match:
        raise ValueError(f"Invalid bracketing string format: '{bracket_str}'")

    ev_step = float(match.group(1))
    num_pictures = int(match.group(2))
    return ev_step, num_pictures


def ev_step_to_string(ev_step: float) -> str:
    """Map a numeric EV step to its common string representation."""
    mapping = {
        0.3: "1/3",
        0.5: "1/2",
        0.7: "2/3",
        1.0: "1",
        2.0: "2",
        3.0: "3",
    }
    # Allow small floating-point tolerance
    for value, label in mapping.items():
        if abs(ev_step - value) < 1e-6:
            return label
    raise ValueError(f"Unsupported EV step: {ev_step}")


def calculate_bracketing_duration(
    ev_step: float,
    num_pictures: int,
    base_shutter_speed: str | float,
) -> float:
    """Calculate total bracketing duration from EV step, number of pictures,
    and base shutter speed.
    """
    # Parse the base shutter speed into seconds (handles floats or "1/125" fractions)
    if isinstance(base_shutter_speed, str):
        base_shutter_speed = base_shutter_speed.strip()
        if "/" in base_shutter_speed:
            num, denom = base_shutter_speed.split("/")
            base_seconds = float(num) / float(denom)
        else:
            base_seconds = float(base_shutter_speed)
    else:
        base_seconds = float(base_shutter_speed)

    # Calculate EV offsets symmetrically around 0 EV
    # e.g., 5 steps with 0.5 EV step -> [-1.0, -0.5, 0.0, 0.5, 1.0]
    half_count = num_pictures // 2
    ev_offsets = [i * ev_step for i in range(-half_count, half_count + 1)]

    # Calculate exact duration for each exposure (t = base * 2^EV)
    exposures_sec = [base_seconds * (2 ** ev) for ev in ev_offsets]
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
    vendor = getattr(camera, 'vendor', None)
    log = camera_log(camera)
    context, config = __adapt_camera_settings(camera, camera_settings)

    # Software bracketing:
    # fire 5 shots at base-2*step, base-step, base, base+step, base+2*step,
    # matching the Canon 5-frame bracket count.
    def simulated_bracketing(bracket_str: str) -> None:
        step_count = _parse_bracket_steps(bracket_str)

        base_idx = choices.index(base_speed)
        # choices is sorted fastest→slowest; smaller index = less exposure (under)
        indices = [
            max(0, base_idx - 2 * step_count),
            max(0, base_idx - step_count),
            base_idx,
            min(len(choices) - 1, base_idx + step_count),
            min(len(choices) - 1, base_idx + 2 * step_count),
        ]

        log.debug(
            'take_bracket 5-shot sequence: %s', [choices[i] for i in indices],
        )

        for idx in indices:
            speed = choices[idx]
            try:
                gp.gp_widget_set_value(ss_widget, speed)
                gp.gp_camera_set_config(target, config, context)
                gp.check_result(gp.gp_camera_trigger_capture(target, context))
                log.info('take_bracket triggered capture at %s', speed)
            except gphoto2.GPhoto2Error as e:
                log.warning('take_bracket capture failed at speed %s: %s', speed, e)
                raise
            speed_ms = int(_parse_shutter_speed_seconds(speed) * 1000)
            timeout_ms = speed_ms + 3000
            _wait_for_capture_complete(target, context, timeout_ms = timeout_ms)
            _drain_camera_events(target, context)

        # Restore base shutter speed
        gp.gp_widget_set_value(ss_widget, choices[base_idx])
        _set_gp_config(camera, config, context)
        log.debug('take_bracket complete')

    # Virtual camera: perform a few captures to simulate bracketing
    if context is None:
        try:
            for _ in range(3):
                camera.capture()
            return
        except Exception:
            log.exception('Virtual bracket capture failed')
            raise

    # Check if the base speed is actually supported by the camera.
    # If not - set one closest to it.
    try:
        ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed2'))
    except gphoto2.GPhoto2Error:
        ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
    choices = _get_shutter_speed_choices(config)
    base_speed = camera_settings.shutter_speed.strip()
    if base_speed not in choices:
        base_speed = _find_closest_shutter_choice(ss_widget, base_speed)

    target = camera._camera if hasattr(camera, '_camera') else camera

    # Ensure that no lingering events are left before proceeding.
    # Sony in PC mode must be skipped, to avoid disrupting Background Downloader.
    if not (hasattr(camera, '_bg_downloader')
            and camera._bg_downloader is not None
            and camera._bg_downloader.is_alive()):
        _drain_camera_events(target, context)

    if vendor == 'Canon':
        try:
            # Turn on aeb
            aeb = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aeb'))
            gp.gp_widget_set_value(aeb, steps)
            _set_gp_config(camera, config, context)

            for br_shot in range(5):
                try:
                    if br_shot == 3:
                        current_speed = gp.check_result(gp.gp_widget_get_value(ss_widget))
                        if current_speed == base_speed:
                            log.warning("5 frames AEB not supported, stopping at 3")
                            break
                    camera.capture(gp.GP_CAPTURE_IMAGE, context)
                except Exception:
                    log.exception('Bracket capture high-level failed, trying low-level gp capture')
                    try:
                        ctx = gp.gp_context_new()
                        gp.check_result(gp.gp_camera_capture(target, gp.GP_CAPTURE_IMAGE, ctx))
                    except Exception:
                        log.exception('Bracket low-level capture failed')
                        raise

            # Turn off aeb
            aeb = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aeb'))
            gp.gp_widget_set_value(aeb, "off")
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error:
            log.warning("'aeb' is not supported, will fallback to simulated bracketing")
            simulated_bracketing(steps)
    elif vendor == 'Nikon':
        ev_step, num_pictures = parse_bracketing_string(steps)
        nikon_ev_step = ev_step_to_string(ev_step)

        try:
            br_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'bracketing'))
            gp.gp_widget_set_value(br_widget, 'On')
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error:
            log.warning(
                "'bracketing' is not supported, will fallback to simulated bracketing")
            simulated_bracketing(nikon_ev_step)
            return

        try:
            bs_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'bracketset'))
            gp.gp_widget_set_value(bs_widget, 'AE only')
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning(
                "failed to set 'bracketset' due to '%s'", e)

        try:
            aeb_bs_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aebracketingstep'))
            gp.gp_widget_set_value(aeb_bs_widget, nikon_ev_step + ' EV')
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning(
                "failed to set 'aebracketingstep' due to '%s'", e)

        try:
            aeb_bp_widget = gp.check_result(
                gp.gp_widget_get_child_by_name(config, 'aebracketingpattern'))
            n_aeb_bp_choices = gp.check_result(gp.gp_widget_count_choices(aeb_bp_widget))
            aeb_bp_choices = [gp.check_result(gp.gp_widget_get_choice(aeb_bp_widget, i))
                                for i in range(n_aeb_bp_choices)]
            final_aeb_bp_choice = None
            for aeb_bp_choice in aeb_bp_choices:
                if aeb_bp_choice.startswith(str(num_pictures) + ' images'):
                    final_aeb_bp_choice = aeb_bp_choice
                    break
            if final_aeb_bp_choice is None:
                final_aeb_bp_choice = aeb_bp_choices[-1]
                supported_num_pictures = final_aeb_bp_choice[0]
                log.warning("failed to set 'aebracketingpattern' at %s images, chose %s instead",
                            str(num_pictures),
                            supported_num_pictures)
                num_pictures = int(supported_num_pictures)
            gp.gp_widget_set_value(aeb_bp_widget, final_aeb_bp_choice)
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning(
                "failed to set 'aebracketingpattern' due to '%s'", e)

        # Set burst number
        try:
            burst_number = gp.check_result(gp.gp_widget_get_child_by_name(config, 'burstnumber'))
            gp.gp_widget_set_value(burst_number, num_pictures)
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning(
                "failed to set 'burstnumber' to %d due to '%s'", num_pictures, e)

        try:
            camera.capture(gp.GP_CAPTURE_IMAGE, context)
        except Exception:
            log.exception('high-level capture failed, trying low-level gp capture')
            try:
                ctx = gp.gp_context_new()
                gp.check_result(gp.gp_camera_capture(target, gp.GP_CAPTURE_IMAGE, ctx))
            except Exception:
                log.exception('low-level capture failed')
                raise

        # Rest burst number back to 1, to avoid interference with future commands.
        try:
            gp.gp_widget_set_value(burst_number, 1)
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning("could not reset Nikon burst number to 1 due to '%s'", e)

        # Disable the bracketing
        try:
            gp.gp_widget_set_value(br_widget, 'Off')
            _set_gp_config(camera, config, context)
        except gphoto2.GPhoto2Error as e:
            log.warning(
                "failed to disable bracketing due to '%s'", e)
    elif vendor == 'Sony':
        # Sony bracketing: enable continuous bracketing mode, turn on the bulb,
        # sleep for the chosen amount of time, turn off the bulb and
        # lastly drain camera's events in case 'PC+Camera' mode was chosen.
        ev_step, num_pictures = parse_bracketing_string(steps)
        bracket_duration = calculate_bracketing_duration(ev_step, num_pictures, base_speed)

        # Switch to continuous bracketing mode
        try:
            capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
            if steps is not None:
                gp.gp_widget_set_value(capture_mode, steps)
                _set_gp_config(camera, config, context)
                log.info('set capturemode to "%s" for bracketing', steps)
            else:
                log.warning(
                    'capturemode "%s" choice not found, firing without mode change', steps)
        except gphoto2.GPhoto2Error as e:
            log.warning('Could not set Sony capturemode to "%s": %s', steps, e)

        try:
            bulb_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'bulb'))
            gp.gp_widget_set_value(bulb_mode, 1)
            _set_gp_config(camera, config, context)
            log.debug('Set Sony bulb mode to 1')
            time.sleep(bracket_duration)
            gp.gp_widget_set_value(bulb_mode, 0)
            _set_gp_config(camera, config, context)
            log.debug('Set Sony bulb mode to 0')
            if not (hasattr(camera, '_bg_downloader')
                    and camera._bg_downloader is not None
                    and camera._bg_downloader.is_alive()):
                # The timeout is longer here because of the Sony A7R IIIA.
                # If it's shorter than 700ms, the last frame won't be written to SD
                # and camera will get stuck.
                _drain_camera_events(target, context, timeout_ms=700)
        except gphoto2.GPhoto2Error as e:
            log.warning('Sony burst capture failed: %s', e)


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
        # Nikon is a weirdo - 'shutterspeed' returns all values in float seconds!
        # 'shutterspeed2' contains the expected values instead -_-
        try:
            speed_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed2'))
        except gphoto2.GPhoto2Error:
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
    vendor = getattr(camera, 'vendor', None)
    log = camera_log(camera)

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
            log.exception('Virtual camera HDR capture failed')
            raise

    target = camera._camera if hasattr(camera, '_camera') else camera

    # For Nikon cameras, defensively ensure single-frame mode is active before
    # taking a single picture, in case a previous take_burst left the camera in
    # continuous/burst mode.
    # For Sony cameras, ensure single-frame capture mode is active before taking
    # a single picture (separate set_config call so a bad capturemode value can
    # never poison the ISO/shutter batch).
    if vendor in ('Nikon', 'Sony'):
        try:
            cfg2 = gp.check_result(gp.gp_camera_get_config(target, context))
            capture_mode_widget = gp.check_result(gp.gp_widget_get_child_by_name(cfg2, 'capturemode'))
            single_choice = _find_capturemode_choice(capture_mode_widget, want_continuous=False)
            if single_choice is not None:
                gp.gp_widget_set_value(capture_mode_widget, single_choice)
                _set_gp_config(camera, cfg2, context)
                log.debug('ensured capturemode="%s" before take_picture', single_choice)
            else:
                log.warning('no "single" choice found for capture mode, leaving as-is')
        except gphoto2.GPhoto2Error as exc:
            if vendor == "Nikon":
                try:
                    capture_mode_widget = gp.check_result(
                        gp.gp_widget_get_child_by_name(config, 'stillcapturemode'))
                    gp.gp_widget_set_value(capture_mode_widget, 0)  # 0 = Single Frame
                    _set_gp_config(camera, config, context)
                    log.debug(
                        'ensured stillcapturemode is Single Frame (0) before take_picture')
                except gphoto2.GPhoto2Error as e:
                    log.warning(
                        'could not ensure single-frame mode before take_picture: %s', e)
            else:
                log.warning(
                    'could not ensure single-frame mode before take_picture: %s', exc)

    # Build the ordered shutter-speed list from this camera's actual capabilities
    choices = _get_shutter_speed_choices(config)
    log.debug('take_hdr: shutter speed choices from camera: %s', choices)

    # Fetch the shutterspeed widget once to reuse across all shots
    try:
        ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed2'))
    except gphoto2.GPhoto2Error:
        ss_widget = gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed'))

    # Locate the starting speed in the choices list
    start_speed = camera_settings.shutter_speed.strip()
    if start_speed not in choices:
        start_speed = _find_closest_shutter_choice(ss_widget, start_speed)

    start_idx = choices.index(start_speed)
    # Defining here a multipler, so we can make full stops.
    # We assume that exposure step is already set to 0.3EV on the camera!
    full_stop_multiplier=3
    end_idx = min(start_idx + stops * full_stop_multiplier, len(choices) - 1)
    end_idx = start_idx + ((end_idx - start_idx) // full_stop_multiplier) * full_stop_multiplier
    actual_stops = end_idx - start_idx
    if actual_stops < stops:
        log.warning(
            'take_hdr: requested %d stops but camera only supports %d stops slower than %s; '
            'clamping sequence to %d stops.',
            stops, actual_stops, start_speed, actual_stops
        )

    # Symmetric sequence: ramp down (faster→slower) then back up (duplicate peak excluded)
    down = list(range(start_idx, end_idx + 1, full_stop_multiplier))
    up = list(range(end_idx - full_stop_multiplier, start_idx - 1, -full_stop_multiplier))
    indices = down + up
    log.info('take_hdr will take %d shots, with these speeds: %s',
             len(indices),
             [choices[i] for i in indices]
    )

    # Ensure that no lingering events are left before proceeding.
    # Sony in PC mode must be skipped, to avoid disrupting Background Downloader.
    if not (hasattr(camera, '_bg_downloader')
            and camera._bg_downloader is not None
            and camera._bg_downloader.is_alive()):
        _drain_camera_events(target, context)

    for idx in indices:
        speed = choices[idx]
        try:
            gp.gp_widget_set_value(ss_widget, speed)
            gp.gp_camera_set_config(target, config, context)
            gp.check_result(gp.gp_camera_trigger_capture(target, context))
            # Sony requires this hack. It allows avoiding
            # wrong shutter speed values being set or
            # outright skipped frames in the sequence.
            # Sadly, it's not fully solving this issue.
            if vendor == 'Sony':
                curr_speed = camera.get_config().get_child_by_name('shutterspeed').get_value()
                if curr_speed != speed:
                    log.warning('take_hdr has failed to set the shutter speed to %s',
                                speed)
                    speed = curr_speed
                speed_s = _parse_shutter_speed_seconds(speed)
                time.sleep(speed_s)
            log.info('take_hdr has triggered capture at %s', speed)
            # First successful trigger_capture establishes eos_remotemode=15 on EOS R.
            if vendor == 'Canon':
                camera._first_capture_done = True
        except gphoto2.GPhoto2Error as e:
            log.warning('take_hdr has failed capture at speed %s: %s', speed, e)
            raise
        # For all cameras except Sony set in PC only mode - wait for
        # the image capture and flush the PTP events.
        # Note: Sony won't throw -110 error when jumping to the next shot.
        if not (hasattr(camera, '_bg_downloader')
                and camera._bg_downloader is not None
                and camera._bg_downloader.is_alive()):
            speed_ms = int(_parse_shutter_speed_seconds(speed) * 1000)
            timeout_ms = speed_ms + 3000
            _wait_for_capture_complete(target, context, timeout_ms = timeout_ms)
            _drain_camera_events(target, context)

    log.debug('take_hdr has completed HDR sequence (%d shots)', len(indices))


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
    camera_log(camera_name).debug('get_camera: address=%s', addr)

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
    _init_camera_claiming_usb(camera, context, camera_name)

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
            camera_log(camera_name).debug('Set capturetarget to "%s"', value)
            # set config
            gp.gp_camera_set_config(camera, config, context)

            # Try to set the drivemode to Continuous high speed (for cameras that support it)
            # Note: Not all cameras have this widget (e.g., Nikon Z-series mirrorless cameras)
            try:
                drive_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
                gp.gp_widget_set_value(drive_mode, "Continuous high speed")
                # set config
                gp.gp_camera_set_config(camera, config, context)
                camera_log(camera_name).debug('Set drivemode to Continuous high speed')
            except gphoto2.GPhoto2Error as e:
                # drivemode widget doesn't exist or value not supported - this is OK for many cameras
                camera_log(camera_name).debug('Could not set drivemode (this is normal for some camera models): %s', e)
    except gphoto2.GPhoto2Error as e:
        camera_log(camera_name).warning('Post-init config failed (continuing): %s', e)

    # Wrap the gphoto camera in a vendor-aware adapter
    if camera is None:
        camera_log(camera_name).error('get_camera: camera object was not created')
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

    _init_camera_claiming_usb(camera, context, model_name)

    # Post-init configuration (capture target, drive mode)
    try:
        config = gp.check_result(gp.gp_camera_get_config(camera, context))
        # Skip Sony cameras, as this option is set in stone once USB is connected
        if not _is_sony_model(model_name):
            capture_target = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturetarget'))
            # search for the memory-card entry by name, not by blind index
            value = _find_memory_card_choice(capture_target)
            gp.gp_widget_set_value(capture_target, value)
            camera_log(display_name).debug('Set capturetarget to "%s"', value)
            gp.gp_camera_set_config(camera, config, context)

            try:
                drive_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
                gp.gp_widget_set_value(drive_mode, "Continuous high speed")
                gp.gp_camera_set_config(camera, config, context)
                camera_log(display_name).debug('Set drivemode to Continuous high speed')
            except gphoto2.GPhoto2Error as e:
                camera_log(display_name).debug('Could not set drivemode: %s', e)
    except gphoto2.GPhoto2Error as e:
        camera_log(display_name).warning('Post-init config failed (continuing): %s', e)

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
            camera_log(camera).info('does not expose storage info via PTP (Sony -1); returning -1.0')
            return -1.0
        raise CameraError(f"Could not read storage info for {getattr(camera, 'name', camera)}: {e}") from None
    except IndexError:
        # get_storageinfo() returned an empty list — common on Sony via PTP during
        # the initial handshake or when ptpcamerad briefly relinquishes the device.
        # Return the last cached value if we have one, otherwise -1.0.
        cached = getattr(camera, '_cached_free_space', None)
        if cached is not None:
            camera_log(camera).debug('get_storageinfo() returned empty list; returning cached %.1f GB', cached)
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
            camera_log(camera).info('does not expose storage capacity via PTP (Sony -1); returning -1.0')
            return -1.0
        raise CameraError(f"Could not read storage capacity for {getattr(camera, 'name', camera)}: {e}") from None
    except IndexError:
        # get_storageinfo() returned an empty list — camera not yet ready to report storage.
        cached = getattr(camera, '_cached_total_space', None)
        if cached is not None:
            camera_log(camera).debug('get_storageinfo() returned empty list; returning cached total %.1f GB', cached)
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
        camera_log(camera).warning('gphoto2 error reading shooting mode: %s', e)
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
        camera_log(camera).warning('gphoto2 error reading focus mode: %s', e)
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
    log = camera_log(camera_name)

    try:
        value = camera.get_config().get_child_by_name('batterylevel').get_value()
        # gphoto2 reports 253 (0xFD) for Sony cameras (and some others) when the
        # camera is powered via an AC adapter rather than a battery.
        if str(value).rstrip('%') == '253':
            log.info("connected to AC. If wrong - press 'Camera(s)' button again")
            return 'AC'
        log.info('battery level is %s', str(value))
        return str(value)
    except gphoto2.GPhoto2Error as e:
        log.debug('gphoto2 error reading batterylevel: %s', e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            log.debug("busy, will try to read battery level again")
            time.sleep(0.1)
            return get_battery_level(camera)
        raise CameraError(f"Could not read battery level for {camera_name}: {e}") from None
    except Exception:
        # VirtualCamera and other non-gphoto cameras don't expose battery info
        if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
            return "100%"
        raise


# --- Camera clock -----------------------------------------------------------
#
# The clock is set when cameras are connected and by every sync_cameras command
# in a script.  Cameras expose it under different names and encodings
# (libgphoto2 2.5.x):
#
#   datetimeutc  Canon EOS (newer bodies): UTC, as a date widget
#   datetime     Canon EOS / Nikon / PTP DateTime: local time, as a date widget,
#                or as text on some drivers
#   d034         Raw PTP DateTime property (no libgphoto2 mapping): text in the
#                PTP format "YYYYMMDDThhmmss"
#
# libgphoto2 also offers syncdatetime / syncdatetimeutc toggles, which set the
# clock to the computer time with whatever conversion that model needs; they
# are preferred when present.
#
# Writing a value the camera does not understand makes some (older) bodies fall
# back to a default date such as 1980 or the year the model came out.  The
# clock is therefore only written when its current value can be read, and is
# read back afterwards: if it is not within CLOCK_TOLERANCE_S of the computer
# time, the previous value is restored, the problem is reported, and the clock
# of that camera is left alone for the rest of the session.

_CLOCK_WIDGETS = ('datetimeutc', 'datetime', 'd034')
_PTP_DATETIME_FORMAT = '%Y%m%dT%H%M%S'
_TEXT_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# How far the camera clock may be off after setting it before it counts as failed.
CLOCK_TOLERANCE_S = 15.0
# A clock this close to the computer time is not rewritten.
_CLOCK_IN_SYNC_S = 1.0
# How long setting the clock may wait for the camera (e.g. while a shot runs).
_CLOCK_LOCK_WAIT_S = 2.0

# Names of the cameras whose clock could not be set reliably in this session.
_clock_sync_disabled: set = set()


class ClockReading:
    """The camera clock as read through one config widget.

    Attributes:
        - widget: Name of the config widget ('datetimeutc', 'datetime' or 'd034')
        - raw: Value as read, kept so that it can be written back unchanged
        - camera_time: Camera time as a naive local datetime, or None if the value could not be interpreted
        - error_s: Camera time minus computer time in seconds, or None if the value could not be interpreted
    """

    def __init__(self, widget: str, raw: Any, camera_time: Optional[datetime], error_s: Optional[float]):
        self.widget = widget
        self.raw = raw
        self.camera_time = camera_time
        self.error_s = error_s

    @property
    def readable(self) -> bool:
        return self.error_s is not None

    def __repr__(self):
        return f"ClockReading({self.widget!r}, {self.raw!r}, error_s={self.error_s})"


def _get_widget(config, name: str):
    """Child widget by name, or None when the camera does not have it."""
    try:
        return config.get_child_by_name(name)
    except Exception:
        return None


def _text_clock_format(value: str) -> Optional[str]:
    """strptime format of a textual clock value, or None if it is not understood."""
    value = str(value).strip()
    for fmt, length in ((_PTP_DATETIME_FORMAT, 15), (_TEXT_DATETIME_FORMAT, 19)):
        try:
            datetime.strptime(value[:length], fmt)
            return fmt
        except ValueError:
            continue
    return None


def _interpret_clock(widget_type, raw, now: float) -> Tuple[Optional[datetime], Optional[float]]:
    """Camera time (naive local) and its offset from the computer time.

    Drivers differ in whether the value is UTC or local wall-clock time, so both
    readings are tried and the one closest to the computer time is used: what
    has to be caught is a clock that is wrong by years, not by a time zone.
    """
    utc_offset = datetime.fromtimestamp(now) - datetime.fromtimestamp(now, timezone.utc).replace(tzinfo=None)
    try:
        if widget_type == gp.GP_WIDGET_DATE:
            value = float(raw)
            candidates = [value - now, value - (now + utc_offset.total_seconds())]
            camera_time = datetime.fromtimestamp(value)
        else:
            fmt = _text_clock_format(raw)
            if fmt is None:
                return None, None
            length = 15 if fmt == _PTP_DATETIME_FORMAT else 19
            camera_time = datetime.strptime(str(raw).strip()[:length], fmt)
            local_now = datetime.fromtimestamp(now)
            candidates = [(camera_time - local_now).total_seconds(),
                          (camera_time - (local_now - utc_offset)).total_seconds()]
    except (TypeError, ValueError, OverflowError, OSError):
        return None, None
    return camera_time, min(candidates, key=abs)


def _read_clock(config, names=_CLOCK_WIDGETS) -> Optional[ClockReading]:
    """Read the camera clock from the first of the given widgets the camera has."""
    for name in names:
        widget = _get_widget(config, name)
        if widget is None:
            continue
        try:
            raw = widget.get_value()
            widget_type = widget.get_type()
        except Exception:
            continue
        camera_time, error_s = _interpret_clock(widget_type, raw, time.time())
        return ClockReading(name, raw, camera_time, error_s)
    return None


def _write_clock(config, reading: ClockReading) -> str:
    """Set the clock in config (not yet sent to the camera) to the computer time.

    Returns: Description of how the clock was set, for the log.
    """
    toggle_name = 'syncdatetimeutc' if reading.widget == 'datetimeutc' else 'syncdatetime'
    toggle = _get_widget(config, toggle_name)
    if toggle is not None and reading.widget != 'd034':
        toggle.set_value(1)
        return toggle_name

    widget = config.get_child_by_name(reading.widget)
    if widget.get_type() == gp.GP_WIDGET_DATE:
        widget.set_value(int(time.time()))
        return f'{reading.widget} (date)'
    # Write text in the same format the camera reported.
    fmt = _text_clock_format(reading.raw)
    widget.set_value(time.strftime(fmt))
    return f'{reading.widget} ("{fmt}")'


def read_camera_clock(camera) -> Optional[ClockReading]:
    """Read the camera clock without changing it.

    Returns: The reading (check .readable), or None if the camera does not expose its clock.
    """
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return ClockReading('datetime', time.strftime(_TEXT_DATETIME_FORMAT), datetime.now(), 0.0)
    lock = getattr(camera, '_usb_lock', None)
    if lock is not None and not lock.acquire(timeout=_CLOCK_LOCK_WAIT_S):
        camera_log(camera).warning('camera busy, clock not read')
        return None
    try:
        # Prefer the local clock for display: it is what ends up in the EXIF data.
        return _read_clock(camera.get_config(), ('datetime', 'datetimeutc', 'd034'))
    finally:
        if lock is not None:
            lock.release()


def get_time(camera: Camera) -> str:
    """ Returns the current time of the selected camera

    Args:
        - camera: Camera object

    Returns: Current time of the camera
    """
    reading = read_camera_clock(camera)
    if reading is None:
        camera_log(camera).warning('Unknown date/time config item')
        return "Unknown date/time config item"
    if not reading.readable:
        return str(reading.raw)
    camera_log(camera).info('camera clock %s, %+.1f s from the computer clock',
                            reading.camera_time.isoformat(' '), reading.error_s)
    return reading.camera_time.isoformat(' ')


def set_time(camera: Camera) -> bool:
    """ Set the computer time on the selected camera, and check that the camera took it.

    The clock is only written when its current value can be read, and it is read
    back afterwards.  If it did not take the computer time, the previous value is
    restored, the problem is reported to the user, and the clock of this camera is
    not touched again in this session.

    Args:
        - camera: Camera object

    Returns: True if the camera clock now matches the computer clock.
    """
    # Virtual or non-gphoto cameras have no clock to set.
    if isinstance(camera, BaseCamera) and not hasattr(camera, '_camera'):
        return True

    name = getattr(camera, 'name', str(camera))
    log = camera_log(name)
    if name in _clock_sync_disabled:
        log.info('clock not set (setting it failed earlier in this session)')
        return False

    lock = getattr(camera, '_usb_lock', None)
    if lock is not None and not lock.acquire(timeout=_CLOCK_LOCK_WAIT_S):
        log.warning('camera busy, clock not set this time')
        return False
    try:
        for attempt in range(2):
            try:
                return _set_time_verified(camera, name)
            except gphoto2.GPhoto2Error as e:
                if attempt == 0 and any(x in str(e).lower() for x in ('-110', 'i/o in progress')):
                    time.sleep(0.1)
                    continue
                log.warning('could not set the camera clock: %s', e)
                return False
        return False
    finally:
        if lock is not None:
            camera._last_usb_activity = time.monotonic()
            lock.release()


def _set_time_verified(camera, name: str) -> bool:
    from solareclipseworkbench import hardware_problems

    log = camera_log(name)
    config = camera.get_config()
    before = _read_clock(config)
    if before is None:
        log.warning('camera does not expose its clock; date and time not set')
        return False
    if not before.readable:
        _clock_sync_disabled.add(name)
        hardware_problems.report(
            name,
            f'The camera clock reads "{before.raw}", which SEW does not understand, so SEW does not set it.  '
            'Set the date and time on the camera by hand.',
            severity="warning",
        )
        return False
    if abs(before.error_s) <= _CLOCK_IN_SYNC_S:
        log.info('camera clock already in sync (%+.1f s)', before.error_s)
        return True

    method = _write_clock(config, before)
    camera.set_config(config)

    after = None
    for delay in (0.2, 0.5, 1.0):
        time.sleep(delay)
        after = _read_clock(camera.get_config(), (before.widget,))
        if after is not None and after.readable and abs(after.error_s) <= CLOCK_TOLERANCE_S:
            log.info('camera clock set via %s (was %+.1f s, now %+.1f s)',
                     method, before.error_s, after.error_s)
            return True

    # The camera did not take the time: put back what was there.
    restored = False
    try:
        config = camera.get_config()
        config.get_child_by_name(before.widget).set_value(before.raw)
        camera.set_config(config)
        restored = True
    except Exception as e:
        log.warning('could not restore the previous clock value: %s', e)

    _clock_sync_disabled.add(name)
    shown = after.camera_time.strftime('%Y-%m-%d %H:%M:%S') if after is not None and after.camera_time else (
        after.raw if after is not None else 'nothing')
    hardware_problems.report(
        name,
        f'Setting the camera clock failed: it read back as {shown} instead of the computer time.  '
        + ('The previous date and time were restored.  ' if restored else
           'The previous date and time could not be restored.  ')
        + 'SEW will not set the clock of this camera again; set the date and time on the camera by hand.',
        detail=f'via {method}; before: {before.raw!r}, after: {after.raw if after is not None else None!r}',
        severity="warning",
    )
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

    log = camera_log(camera)

    try:
        sony_capture_target = camera.get_config().get_child_by_name('capturetarget').get_value()
        log.info("capture target is %s", sony_capture_target)
        return sony_capture_target
    except gphoto2.GPhoto2Error as e:
        log.debug('gphoto2 error reading capturetarget: %s', e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            log.warning("busy, unable to get capture target, trying again")
            time.sleep(0.1)
            return get_sony_save_destination(camera)
        else:
            log.warning("lacks capture target setting")
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

    log = camera_log(camera)

    try:
        sony_image_quality = camera.get_config().get_child_by_name('imagequality').get_value()
        log.info("file format / quality is %s", sony_image_quality)
        return sony_image_quality
    except gphoto2.GPhoto2Error as e:
        log.debug('gphoto2 error reading imagequality: %s', e)
        error_str = str(e).lower()
        if any(x in error_str for x in ['-110', 'i/o in progress']):
            log.warning("busy, unable to get image quality, trying again")
            time.sleep(0.1)
            return get_sony_image_quality(camera)
    except Exception:
        return None


if __name__ == "__main__":
    main()
