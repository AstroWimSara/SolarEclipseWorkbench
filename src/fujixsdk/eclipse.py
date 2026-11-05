"""Eclipse helpers for Fujifilm X cameras.

The pre-flight check of the body settings, live view streaming, and
no-download shooting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from . import _constants as C
from ._errors import BusyError, CommunicationError, XSDKError
from .camera import BUFFER_SLOTS, DRAIN_AT, Camera

log = logging.getLogger(__name__)


# ======================================================================
# Camera validation
# ======================================================================

@dataclass
class CameraIssue:
    """A single camera configuration issue found during validation."""
    severity: str  # "error", "warning", "info"
    setting: str
    current: str
    expected: str
    message: str


#: The body saying it does not implement an API at all, as opposed to refusing
#: the call.  Reported by XSDK_GetErrorNumber as 0x1013, and confirmed against
#: XSDK_GetDeviceInfoEx, which lists the API codes a model's module carries -
#: CheckBatteryInfo is absent from the X-T4's list, whatever the manual says.
API_NOT_IMPLEMENTED = 0x1013


def _cannot_be_asked(exc: XSDKError) -> bool:
    """Whether this body simply has no such API.

    Worth separating from every other failure: a missing API is not a fault to
    be fixed before an eclipse, and reporting it as one every session teaches
    the reader to skim past warnings that do matter.
    """
    return (exc.code & 0xFFFF) == API_NOT_IMPLEMENTED


def _unavailable(setting: str, expected: str, by_hand: str) -> CameraIssue:
    """A setting this body cannot report: stated once, as information."""
    return CameraIssue("info", setting, "not available on this body", expected,
                       by_hand)


def validate_for_eclipse(cam: Camera) -> list[CameraIssue]:
    """Check all camera settings and report what needs to change for eclipse shooting."""
    issues = []

    # --- ERRORS (will prevent eclipse shooting) ---

    # AE mode must be Manual
    try:
        ae = cam.get_ae_mode()
        ae_name = C.AE_MODE_NAMES.get(ae, f"0x{ae:04X}")
        if ae != C.AE_OFF:
            issues.append(CameraIssue(
                "error", "AE Mode", ae_name, "Manual",
                "Set AE mode to Manual (M on mode dial)",
            ))
    except XSDKError:
        pass

    # Focus must be Manual
    try:
        fm = cam.get_focus_mode()
        fm_name = C.FOCUS_MODE_NAMES.get(fm, f"0x{fm:04X}")
        if fm != C.SDK_FOCUS_MANUAL:
            issues.append(CameraIssue(
                "error", "Focus Mode", fm_name, "MF",
                "Switch lens/body focus selector to M",
            ))
    except XSDKError as exc:
        # Swallowing this hides the setting most likely to cost frames: a body
        # left in AF refuses S2 whenever focus does not confirm.  Say that the
        # check could not run rather than implying it passed.
        if _cannot_be_asked(exc):
            issues.append(_unavailable("Focus Mode", "MF",
                                       "check the selector is on M"))
        else:
            # Not swallowed: a body left in AF refuses S2 whenever focus does
            # not confirm, which is the setting most likely to cost frames.
            issues.append(CameraIssue(
                "warning", "Focus Mode",
                f"unreadable (0x{exc.code & 0xFFFF:04x})", "MF",
                "Could not read the focus mode - check the selector is on M "
                "by hand",
            ))

    # ISO must be a fixed value.  On auto the body meters every frame, which for
    # a corona means metering off a mostly black sky, and every ISO the script
    # asks for is ignored.
    try:
        iso = cam.get_iso()
        if iso < 0:
            issues.append(CameraIssue(
                "error", "ISO", f"Auto ({iso})", "a fixed value",
                "ISO is on Auto: turn the ISO dial to C so the script can set it",
            ))
    except XSDKError:
        pass

    # Camera must be in tether mode
    try:
        mode = cam.camera_mode
        if not (mode & 0x0001):
            issues.append(CameraIssue(
                "error", "Camera Mode", f"0x{mode:04X}", "Tether",
                "Set USB mode to TETHER in camera connection settings",
            ))
    except XSDKError:
        pass

    # --- WARNINGS (suboptimal) ---

    # Drive mode: the SDK reports only S/MOVIE/INVALID on a dial-equipped body.
    # DRIVE_MODE_S means stills rather than single-frame drive - an X-T4 with the
    # dial physically on CH still reads back 0x0004 - so S, CL and CH cannot be
    # told apart from here and the dial has to be checked by eye.  It matters:
    # with the dial on CH the SDK release is refused (0x1008), so every frame of
    # the script is lost.  The SDK releases one frame at a time, so S is the
    # position it is used with.
    try:
        dm = cam.get_drive_mode()
        if dm == C.DRIVE_MODE_MOVIE:
            issues.append(CameraIssue(
                "error", "Drive Mode", "Movie", "S",
                "Camera is in Movie mode. Set the drive dial to S.",
            ))
        elif dm == C.DRIVE_MODE_INVALID:
            issues.append(CameraIssue(
                "error", "Drive Mode", "Invalid", "S",
                "Drive mode dial in unsupported position. Set it to S.",
            ))
        else:
            issues.append(CameraIssue(
                "info", "Drive Mode", "Stills",
                "S (verify on camera dial)",
                "The SDK cannot tell S from CL or CH. Verify the drive dial is on S: "
                "on CH the SDK cannot release the shutter.",
            ))
    except XSDKError:
        pass

    # Exposure bias should be 0
    try:
        eb = cam.get_exposure_bias()
        if eb != 0:
            ev = eb / 30.0
            issues.append(CameraIssue(
                "warning", "Exposure Bias", f"{ev:+.1f} EV", "0 EV",
                "Reset exposure compensation to 0",
            ))
    except XSDKError:
        pass

    # Image quality must be RAW alone.  Measured on an X-T4 at 1/1000: recording
    # a JPEG alongside the RAW put two entries in the volatile buffer per frame
    # and dropped the rate from 1.85 fps to 0.61 - so it both halves the number
    # of frames the buffer holds and takes three times as long to get them.  The
    # old check accepted FINE+RAW and NORMAL+RAW silently.
    #
    # The SDK exposes no RAW compression property, so lossless-compressed versus
    # uncompressed cannot be checked here; set it on the body and see fuji-xt4.md.
    try:
        iq = cam.get_image_quality()
        iq_name = C.IMAGE_QUALITY_NAMES.get(iq, f"0x{iq:04X}")
        if iq in (C.IMAGE_QUALITY_FINE_PLUS_RAW, C.IMAGE_QUALITY_NORMAL_PLUS_RAW):
            issues.append(CameraIssue(
                "error", "Image Quality", iq_name, "RAW",
                "A JPEG per frame doubles buffer use and triples the time per "
                "frame - set image quality to RAW alone",
            ))
        elif iq != C.IMAGE_QUALITY_RAW:
            issues.append(CameraIssue(
                "error", "Image Quality", iq_name, "RAW",
                "Set image quality to RAW",
            ))
    except XSDKError as exc:
        if _cannot_be_asked(exc):
            # The X-T4's module carries no image quality API.  It is set on the
            # body and cannot be read back, which is a fact about the camera,
            # not a problem with it.
            issues.append(_unavailable(
                "Image Quality", "RAW",
                "confirm RAW, lossless compressed, no JPEG, on the camera"))
        else:
            issues.append(CameraIssue(
                "warning", "Image Quality",
                f"unreadable (0x{exc.code & 0xFFFF:04x})", "RAW",
                "Could not read image quality - confirm RAW, lossless "
                "compressed, no JPEG, on the camera by hand",
            ))

    # White balance: Daylight
    try:
        wb = cam.get_wb_mode()
        wb_name = C.WB_MODE_NAMES.get(wb, f"0x{wb:04X}")
        if wb != C.WB_DAYLIGHT:
            issues.append(CameraIssue(
                "warning", "White Balance", wb_name, "Daylight",
                "Set WB to Daylight for consistent color across bracket",
            ))
    except XSDKError:
        pass

    # Long exposure NR should be OFF
    try:
        nr = cam.get_long_exposure_nr()
        if nr != C.OFF:
            issues.append(CameraIssue(
                "warning", "Long Exposure NR", "ON", "OFF",
                "Turn off Long Exposure NR (wastes time between shots)",
            ))
    except XSDKError:
        pass

    # --- INFO (nice to know) ---

    # Current exposure settings
    try:
        speed, _ = cam.get_shutter_speed()
        iso = cam.get_iso()
        aperture = cam.get_aperture()
        speed_name = C.SHUTTER_SPEED_NAMES.get(speed, f"{speed}")
        f_str = f"f/{aperture / 100:.1f}" if aperture > 0 else "Auto"
        issues.append(CameraIssue(
            "info", "Exposure", f"{speed_name}  ISO {iso}  {f_str}", "",
            "Current exposure settings",
        ))
    except XSDKError:
        pass

    # Buffer capacity
    try:
        captured, total_frames = cam.get_buffer_capacity()
        available = total_frames - captured
        issues.append(CameraIssue(
            "info", "Buffer", f"{available}/{total_frames} available", "",
            "Available buffer capacity",
        ))
    except XSDKError:
        pass

    # Battery.  A coarse state, not a percentage - it was printed as one.
    # Bodies whose SDK module omits the API (the X-T4 among them) cannot be
    # asked at all, so the check says to look at the body rather than staying
    # silent about a thing that has to last the whole of totality.
    try:
        battery = cam.get_battery_info()
        issues.append(CameraIssue(
            "warning" if battery.is_low else "info", "Battery",
            battery.describe(), "fit a fresh battery" if battery.is_low else "",
            "Battery level",
        ))
    except XSDKError:
        issues.append(_unavailable("Battery", "charged",
                                   "check the level on the camera"))

    # Card.  Whether each card will take a frame at all matters more than how
    # many it will take, and unlike the capacity it is a question this body
    # answers.
    for slot in (C.ITEM_MEDIASLOT1, C.ITEM_MEDIASLOT2):
        try:
            status = cam.get_media_status(slot)
        except XSDKError:
            continue
        name = C.MEDIASTATUS_NAMES.get(status, "0x%04x" % status)
        blocked = status in C.MEDIASTATUS_CANNOT_WRITE
        issues.append(CameraIssue(
            "error" if blocked else "info", f"Card slot {slot}", name,
            "no frame can be written to this card" if blocked else "",
            "Recording media status",
        ))
        try:
            capacity = cam.get_media_capacity(slot)
        except XSDKError:
            continue          # the X-T4 lists this API but will not answer it
        issues.append(CameraIssue(
            "info", f"Card slot {slot} space", capacity.describe(), "",
            "Room left on the card",
        ))

    # Shutter count
    try:
        count = cam.get_shutter_count()
        issues.append(CameraIssue(
            "info", "Shutter Count", f"{count.total} actuations", "",
            "Total shutter actuations",
        ))
    except XSDKError:
        pass

    # Lens info
    try:
        lens = cam.lens_info
        issues.append(CameraIssue(
            "info", "Lens", lens.product_name or lens.model, "",
            "Attached lens",
        ))
    except XSDKError:
        pass

    return issues


class LiveViewStream:
    """Stream live view JPEG frames from camera for focus preview."""

    _LIVE_FORMATS = {
        C.IMAGEFORMAT_LIVE,
        C.IMAGEFORMAT_LIVE_90,
        C.IMAGEFORMAT_LIVE_180,
        C.IMAGEFORMAT_LIVE_270,
    }

    def __init__(
        self,
        camera: Camera,
        size: int = C.LIVEVIEW_SIZE_XGA,
        quality: int = C.LIVEVIEW_QUALITY_FINE,
    ):
        self.camera = camera
        self.size = size
        self.quality = quality
        self._running = False

    def start(self):
        try:
            self.camera.set_live_view_size(self.size)
        except XSDKError as e:
            log.warning("Could not set live view size: %s", e)
        try:
            self.camera.set_live_view_quality(self.quality)
        except XSDKError as e:
            log.warning("Could not set live view quality: %s", e)
        self.camera.start_live_view()
        self._running = True

    def stop(self):
        self._running = False
        if self.camera.vanished:
            # There is nothing to say goodbye to, and saying it anyway walks
            # the SDK's device-removal path - the one that corrupts the heap.
            return
        try:
            self.camera.stop_live_view()
        except CommunicationError:
            self.camera.vanished = True
        except XSDKError:
            pass

    def read_frame(self) -> bytes | None:
        """Read one JPEG frame. Returns None if no frame ready."""
        if not self._running or self.camera.vanished:
            return None
        try:
            info = self.camera.read_image_info()
            fmt = info.format & 0xFF
            if fmt == (C.IMAGEFORMAT_LIVE & 0xFF) and info.data_size > 0:
                return self.camera.read_image(info.data_size)
        except CommunicationError as e:
            # The body left the bus - powered off or unplugged.  Swallowing
            # this like the errors above would poll the corpse a few times a
            # second until somebody closed the window; raising ends the loop
            # with the first failure.
            self.camera.vanished = True
            raise RuntimeError(
                "the camera has left the bus - powered off or unplugged "
                f"({e})") from e
        except XSDKError:
            pass
        return None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


# ======================================================================
# Eclipse Shooter
# ======================================================================

class EclipseShooter:
    """Shutter release over the SDK, without image download.

    Each frame stays on the card.  The SDK still queues a PC transfer per
    frame, so the shooter empties that queue before it fills.

    Usage:
        with Camera(sdk_path, device_name) as cam:
            shooter = EclipseShooter(cam)
            shooter.bracket_no_download([
                C.SHUTTER_1_2000, C.SHUTTER_1_500, C.SHUTTER_1_125,
            ])
    """

    def __init__(self, camera: Camera):
        self.camera = camera

    # ------------------------------------------------------------------
    # High-speed no-download shooting
    # ------------------------------------------------------------------
    def _keep_buffer_clear(self) -> None:
        """Clear the volatile buffer before it fills.

        Nothing else empties it: shooting no-download leaves every frame queued
        for a PC transfer that never comes, and at BUFFER_SLOTS a run of any
        length simply stops.  Draining costs 0.018 s per image on an X-T4, so
        clearing two dozen mid-totality is under half a second.

        The images are on the card - this only discards the queued PC transfer.

        Measured against BUFFER_SLOTS and not against the total returned beside
        the count: that total sits three above the count while frames are being
        written, so `captured >= total * DRAIN_AT` would have fired at thirteen
        frames as readily as at twenty-five.
        """
        captured, _ = self.camera.get_buffer_capacity()
        if captured >= BUFFER_SLOTS * DRAIN_AT:
            drained = self.camera.drain_buffer()
            log.info("Drained %d image(s) at %d/%d to keep shooting",
                     drained, captured, BUFFER_SLOTS)

    def shoot_fast(self, retries: int = 5) -> bool:
        """Fire one shot, no download. Returns False if buffer full."""
        self._keep_buffer_clear()
        captured, total = self.camera.get_buffer_capacity()
        if captured >= total:
            log.warning("Buffer full (%d/%d), cannot shoot", captured, total)
            return False
        from ._errors import ShootError
        # The body refuses S2 about half the time while it is still finishing the
        # previous frame, and there is no way to ask whether it is ready:
        # GetReleaseStatus answers 0 throughout, and an explicit wait on it makes
        # no measurable difference (8/8 either way, 1.8 fps either way).  Retrying
        # is what works - do not replace this loop with a readiness check.
        for attempt in range(retries):
            try:
                self.camera.shoot_no_af()
                return True
            except BusyError:
                log.debug("Camera busy on shoot attempt %d/%d", attempt + 1, retries)
                time.sleep(0.3)
            except ShootError:
                log.warning("ShootError on attempt %d/%d, retrying", attempt + 1, retries)
                time.sleep(0.2)
        log.error("Camera still failing after %d shoot attempts", retries)
        return False

    def burst_no_download(self, count: int, min_interval_ms: int = 0) -> int:
        """Fire N shots without downloading. Returns actual shots taken."""
        taken = 0
        interval_s = min_interval_ms / 1000.0
        for i in range(count):
            if not self.shoot_fast():
                log.info("Burst stopped at frame %d/%d", i, count)
                break
            taken += 1
            if interval_s > 0:
                time.sleep(interval_s)
        return taken

    def bracket_no_download(
        self,
        speeds: list[int],
        iso: Optional[int] = None,
        aperture: Optional[int] = None,
    ) -> int:
        """Bracket at different speeds without downloading. Returns shots taken.

        ISO and aperture are left alone unless given: the caller has usually
        just dialled them in, and defaulting to a value here would silently
        photograph the bracket at an ISO nobody asked for.

        Nothing here is allowed to abandon the bracket.  The body answers 0x1006
        while it is finishing a frame, so every setting is retried, and one that
        will not take still gets its frame — at the previous exposure, which is
        worth more than a gap at a contact that happens once.
        """
        self._settle(self.camera.set_ae_mode, C.AE_OFF, "AE mode")
        if iso is not None:
            self._settle(self.camera.set_iso, iso, "ISO")
        if aperture is not None:
            self._settle(self.camera.set_aperture, aperture, "aperture")
        taken = 0
        for speed in speeds:
            self._settle(self.camera.set_shutter_speed, speed, "shutter speed")
            if not self.shoot_fast():
                break
            taken += 1
        return taken

    def _settle(self, setter, value, what: str, retries: int = 5) -> bool:
        """Apply one setting, waiting out the busy window.  False if it never took."""
        for attempt in range(retries):
            try:
                setter(value)
                return True
            except BusyError:
                log.debug("Camera busy setting %s, attempt %d/%d", what, attempt + 1, retries)
                time.sleep(0.3)
            except XSDKError as exc:
                log.warning("Could not set %s to %s: %s", what, value, exc)
                return False
        log.warning("Camera still busy after %d attempts to set %s", retries, what)
        return False
