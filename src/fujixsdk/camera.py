"""High-level Camera class — main user interface for Fujifilm X SDK."""

from __future__ import annotations

import atexit
import ctypes
import logging
import os
import platform
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

from . import _constants as C
from . import recovery
from ._errors import (BusyError, LDPathError, XSDKError, check_result,
                      raise_for_error_code)

log = logging.getLogger(__name__)
from ._library import XAPILibrary, ensure_ld_library_path
from ._structures import (
    DeviceInformation,
    ImageInformation,
    LensInformation,
)

# A drain runs between shots, so waiting out a busy body is bounded: what cannot
# be deleted inside DRAIN_BUDGET_S goes with the next drain rather than holding
# up the next frame.
DRAIN_BUDGET_S = 2.0
DRAIN_BUSY_BACKOFF_S = 0.1

# The transfer queue holds this many frames.  Taken as a constant rather than
# read per call because the second value GetBufferCapacity returns is not the
# buffer size: while frames are being written it tracks three above the count
# (13/16, 18/21, 20/23, 23/26, 27/30 through one measured burst) and settles
# at 32 only once the body is idle.  Free slots computed as total - captured
# would read three however empty the buffer really was.
BUFFER_SLOTS = 32

# Fraction of those slots that may fill before shooting stops to clear them.
# Measured on an X-T4 in continuous drive, 67 releases at 1/1000" and 1/4000":
#
#   one release adds 2 or 3 frames, never 4
#
#   a release's frames appear in the count all at once, 0.35-0.75s later.  A
#   reading taken sooner shows none of them
#
# So a reading may understate by a whole release (3), and one more release fires
# before the next reading (3): true occupancy can be 6 above what the check saw,
# which puts the ceiling at 26/32.  24 is that with two slots to spare.
DRAIN_AT = 0.75


@dataclass
class CameraInfo:
    """Summary of a detected camera."""
    product: str
    serial_no: str
    ip_address: str
    framework: str
    device_name: str


class BatteryInfo(NamedTuple):
    """Battery levels for the body and, if fitted, the grip.

    The levels are coarse states rather than percentages - the body reports
    "80%" or "nearly flat" as an enum.  See POWERCAPACITY_NAMES.
    """

    body: int
    grip: int
    grip2: int
    body_ratio: int
    grip_ratio: int
    grip2_ratio: int

    @property
    def is_low(self) -> bool:
        """True when the body battery would not be trusted for a totality."""
        return self.body in C.POWERCAPACITY_LOW

    def describe(self) -> str:
        name = C.POWERCAPACITY_NAMES.get(self.body, "0x%04x" % self.body)
        if self.grip in C.POWERCAPACITY_NAMES and self.grip != C.POWERCAPACITY_EMPTY:
            return "%s (grip %s)" % (name, C.POWERCAPACITY_NAMES[self.grip])
        return name


class MediaCapacity(NamedTuple):
    """What is left on a card."""

    blank_frames: int
    remaining_sectors: int
    sector_size: int
    card_size: int

    @property
    def free_bytes(self) -> int:
        return self.remaining_sectors * self.sector_size

    def describe(self) -> str:
        return "%d frames, %.1f GB free" % (
            self.blank_frames, self.free_bytes / 1e9)


class ShutterCount(NamedTuple):
    """Actuation counters.

    `total` is what people mean by shutter count.  `current` resets when the
    shutter unit is replaced.
    """

    current: int
    total: int
    exchanges: int


def _resolve_param(api_code: int, api_param, args: tuple):
    """Work out the api_param, tolerating a caller that omitted it.

    The api_param is how many arguments follow it - not a magic number per
    API.  The SDK's own sample makes this plain, passing 1 alongside one value
    and 0 alongside none:

        set_prop_l(handle, API_CODE_SetLiveViewImageSize, 1, SDK_LIVEVIEW_SIZE_L)
        set_prop(handle, API_CODE_StartLiveView, 0)

    So it is counted here rather than looked up.  A table cannot be trusted for
    this: it describes what the API wants, while the count has to describe what
    is actually on the stack.  Claiming six arguments while passing three does
    not fail, it reads three words of whatever happens to be there - which is a
    segmentation fault, not an error code.

    A value meant as the first variadic argument can arrive in the place of
    ``api_param``.  Anything that is not a plain int is therefore treated as
    the argument it is.
    """
    if api_param is not None and not isinstance(api_param, int):
        args = (api_param,) + args
        api_param = None
    if api_param is None:
        api_param = len(args)
        wanted = C.API_PARAM.get(api_code)
        if wanted is not None and wanted != api_param:
            # The call goes ahead with the honest count and will be refused by
            # the body rather than corrupting the stack.  The header is what
            # says the API is incompletely wired up here.
            log.warning("API 0x%04x takes %d arguments, %d given; the body will "
                        "refuse this call", api_code, wanted, api_param)
    return api_param, args


def _exit_sdk_at_process_end() -> None:
    """The one XSDK_Exit of the process, after which nothing re-inits."""
    with Camera._init_lock:
        if Camera._lib is not None:
            try:
                Camera._lib.XSDK_Exit()
            except Exception:
                pass
            Camera._lib = None
            Camera._init_count = 0


atexit.register(_exit_sdk_at_process_end)


class Camera:
    """Pythonic interface to a Fujifilm X Series camera via the Shooting SDK.

    Usage:
        cameras = Camera.detect("/path/to/sdk/libs")
        with Camera("/path/to/sdk/libs", cameras[0].device_name) as cam:
            cam.set_priority(PRIORITY_PC)
            cam.set_ae_mode(AE_OFF)
            cam.set_shutter_speed(SHUTTER_1_1000)
            cam.set_iso(ISO_100)
            cam.shoot()
    """

    _lib: Optional[XAPILibrary] = None
    _lib_sdk_path: Optional[str] = None
    _init_count: int = 0
    _init_lock: threading.Lock = threading.Lock()

    @classmethod
    def _ensure_lib(cls, sdk_path: str | Path) -> XAPILibrary:
        """Lazily load and initialize the SDK library (shared across instances)."""
        with cls._init_lock:
            sdk_str = str(sdk_path)
            if cls._lib is None or cls._lib_sdk_path != sdk_str:
                cls._check_ld_path(sdk_path)
                cls._lib = XAPILibrary(sdk_path)
                cls._lib_sdk_path = sdk_str
                cls._init_count = 0

            if cls._init_count == 0:
                rc = cls._lib.XSDK_Init(cls._lib_handle())
                check_result(rc)

            cls._init_count += 1
            return cls._lib

    @classmethod
    def _lib_handle(cls) -> ctypes.c_void_p:
        """Return the dlopen handle for XSDK_Init.

        On Linux, passing the dlopen handle helps the SDK find model libraries.
        On macOS/Windows, pass NULL (0) as per the official SDK samples.
        """
        if platform.system() == "Linux":
            return ctypes.c_void_p(cls._lib._lib._handle)
        return ctypes.c_void_p(0)

    @staticmethod
    def _check_ld_path(sdk_path: str | Path):
        """Ensure LD_LIBRARY_PATH includes the SDK library directory.

        Raises LDPathError if the path was missing and the process needs
        to be restarted for the changes to take effect (glibc caches
        LD_LIBRARY_PATH at startup).
        """
        if platform.system() != "Linux":
            return
        if not ensure_ld_library_path(sdk_path):
            raise LDPathError(os.environ["LD_LIBRARY_PATH"])

    @classmethod
    def _release_lib(cls):
        """Decrement the reference count.  The SDK stays initialised.

        XSDK_Exit is not called here.  This SDK does not survive an Exit
        followed by another Init in one process: every open after the cycle
        answers a bare -1.  Reopening was refused after a close that called
        Exit, and worked when Exit was not called.

        Exit belongs at process end, where it cannot be followed by an Init.
        """
        with cls._init_lock:
            cls._init_count = max(cls._init_count - 1, 0)

    @staticmethod
    def detect(sdk_path: str | Path, interface: int = C.IF_USB,
               with_info: bool = True) -> list[CameraInfo]:
        """Detect connected cameras.

        For USB cameras, returns one CameraInfo per detected camera with
        device_name set to "ENUM:0", "ENUM:1", etc.  Pass this device_name
        to Camera() to open the connection.

        Args:
            sdk_path: Path to directory containing SDK shared libraries.
            interface: Connection interface (IF_USB, IF_WIFI_LOCAL, IF_WIFI_IP).

        Returns:
            List of CameraInfo for each detected camera.
        """
        # Use the shared library to avoid macOS SDK bug where USB enumeration
        # fails after XSDK_Exit() is called.
        lib = Camera._ensure_lib(sdk_path)

        count = ctypes.c_long(0)
        rc = lib.XSDK_Detect(
            ctypes.c_long(interface), None, None, ctypes.byref(count)
        )
        check_result(rc)

        if count.value == 0:
            return []

        # For USB, the SDK uses "ENUM:N" as device identifiers.
        #
        # with_info=False stops here, with the names and nothing else.  Reading
        # the product means opening a session and closing it again, and a
        # caller that is about to open the camera properly does not need this
        # one: it can read the same information from the session it keeps.
        # Every open/close cycle is a risk - the SDK corrupted the heap
        # during this sequence once, when the device went away mid-call:
        #
        #     malloc: Incorrect checksum for freed object ...
        #             probably modified after being freed
        #
        # which aborts the process outright, past the reach of any handler.
        if not with_info:
            return [CameraInfo(product="(unknown)", serial_no="", ip_address="",
                               framework="USB", device_name=f"ENUM:{i}")
                    for i in range(count.value)]

        # We open each camera briefly to read its device info.
        results = []
        for i in range(count.value):
            device_name = f"ENUM:{i}"
            cam_handle = ctypes.c_void_p()
            cam_mode = ctypes.c_long()

            rc = lib.XSDK_OpenEx(
                device_name.encode("utf-8"),
                ctypes.byref(cam_handle),
                ctypes.byref(cam_mode),
                None,
            )
            if rc != 0:
                results.append(CameraInfo(
                    product="(unknown)",
                    serial_no="",
                    ip_address="",
                    framework="USB",
                    device_name=device_name,
                ))
                continue

            try:
                info = DeviceInformation()
                lib.XSDK_GetDeviceInfo(cam_handle, ctypes.byref(info))
                results.append(CameraInfo(
                    product=info.product,
                    serial_no=info.serial_no,
                    ip_address="",
                    framework="USB",
                    device_name=device_name,
                ))
            finally:
                lib.XSDK_Close(cam_handle)

        return results

    def __init__(
        self,
        sdk_path: str | Path,
        device_name: str,
        interface: int = C.IF_USB,
    ):
        self._sdk_path = sdk_path
        self._device_name = device_name
        self._interface = interface
        self._handle = ctypes.c_void_p()
        self._camera_mode = ctypes.c_long()
        # Counts as closed until OpenEx has given us a handle: when loading the
        # library or the open fails, __del__ must not run a teardown - and reach
        # for a _lib_inst that was never set - on a session that never existed.
        self._closed = True
        #: The body has left the bus - powered off or unplugged mid-session.
        #: Set by whoever meets the first CommunicationError; once set, close()
        #: abandons the handle instead of tearing it down.  See close().
        self.vanished = False

        self._lib_inst = self._ensure_lib(sdk_path)

        # The SDK requires Detect before OpenEx to enumerate USB devices.
        count = ctypes.c_long(0)
        self._lib_inst.XSDK_Detect(
            ctypes.c_long(interface), None, None, ctypes.byref(count)
        )

        rc = self._lib_inst.XSDK_OpenEx(
            device_name.encode("utf-8"),
            ctypes.byref(self._handle),
            ctypes.byref(self._camera_mode),
            None,
        )
        if rc != C.COMPLETE:
            # Nothing was opened, so there is nothing to close.  Without this
            # the exception below abandons a half-built object, __del__ calls
            # close(), and close() runs a full teardown - Release, drain,
            # SetPriorityMode, Close - on a handle the SDK never gave us.
            #
            # That is the heap corruption:
            #
            #     malloc: Incorrect checksum for freed object 0x1309d4e00:
            #             probably modified after being freed
            #     Corrupt value: 0xffffffff00000000
            #
            # which aborts the process outright, past the reach of any handler.
            # It appeared whenever an open failed, and retrying a failed open -
            # three times, with the daemons killed between - turned it from
            # occasional into repeatable.
            self._closed = True
        check_result(rc)
        self._closed = False

        # Clean up any stale state from a previous crashed session.
        # SetPriorityMode fails with BusyError while live view is running or
        # while images are pending.  Strategy: stop live view, cancel, drain,
        # try priority; only if still blocked, fire a shot to flush the
        # pipeline, drain again, retry.
        self._cleanup_stale_state()

    def _cleanup_stale_state(self):
        """Get the body to a state where it will take commands, on open.

        A session inherits whatever the last one left: a live view still
        running, a release that never completed, frames still in the buffer.
        The work is in recovery.unblock, which asks the body what is wrong
        before doing anything about it - see there for why the order matters
        and why the shutter is the last resort rather than the first.
        """
        recovery.unblock(self, C.PRIORITY_CAMERA, why="session open")

    def wait_ready(self, timeout_s: float = 10.0, poll_interval_s: float = 0.3) -> bool:
        """Wait until the camera is no longer busy.

        Polls GetBufferCapacity as a lightweight health check.
        Returns True if camera became ready, False on timeout.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                self.get_buffer_capacity()
                return True
            except BusyError:
                log.debug("Camera busy, waiting %.1fs...", poll_interval_s)
                time.sleep(poll_interval_s)
        log.warning("Camera still busy after %.1fs timeout", timeout_s)
        return False

    def still_on_bus(self) -> bool:
        """Whether a camera is still enumerable on this interface.

        Detect walks the bus and never touches this session's handle, so it
        is the one question that is safe to ask about a body that may already
        be gone - every other call is USB traffic into a handle whose device
        may not be there, which is the SIGSEGV described in close().

        Used to set :attr:`vanished` before a teardown rather than after the
        crash, for the case where nothing has met a CommunicationError yet.
        """
        count = ctypes.c_long(0)
        try:
            self._lib_inst.XSDK_Detect(
                ctypes.c_long(self._interface), None, None, ctypes.byref(count))
        except Exception:
            log.debug("Could not enumerate the bus", exc_info=True)
            return False
        return count.value > 0

    def close(self):
        """Close the camera connection and release SDK resources.

        Drains pending images and returns priority to camera before
        closing, so the camera is not left in a stuck state.
        """
        if not self._closed:
            self._closed = True
            if self.vanished:
                # The body is off the bus.  Every teardown call below is USB
                # traffic into a handle whose device is gone, and the SDK's
                # removal path writes to freed memory when called that way:
                # malloc's checksum abort, or a SIGSEGV on a dispatch thread
                # with no Python frame on the stack.  A leaked handle costs
                # nothing next to that, so the handle is abandoned, not closed.
                log.warning("The camera left the bus mid-session; abandoning "
                            "its handle rather than closing it - power the "
                            "body on and detect it again for a new session")
                self._release_lib()
                return
            try:
                shot_opt = ctypes.c_long(1)
                af_status = ctypes.c_long()
                self._lib_inst.XSDK_Release(
                    self._handle, ctypes.c_long(C.RELEASE_CANCEL),
                    ctypes.byref(shot_opt), ctypes.byref(af_status))
                # Drain buffer — SetPriorityMode fails while images pending
                self.drain_buffer()
                self._lib_inst.XSDK_SetPriorityMode(
                    self._handle, ctypes.c_long(C.PRIORITY_CAMERA))
            except Exception:
                pass
            self._lib_inst.XSDK_Close(self._handle)
            self._release_lib()

    def reconnect(self):
        """Close and reopen the SDK session to clear a stuck camera state."""
        device_name = getattr(self, '_device_name', 'ENUM:0')
        log.info("Reconnecting camera (device=%s)...", device_name)
        # Force-close without draining (camera is stuck anyway)
        if not self._closed:
            self._closed = True
            if not self.vanished:
                try:
                    self._lib_inst.XSDK_Close(self._handle)
                except Exception:
                    pass
        # Reopen
        self._closed = False
        self.vanished = False
        self._handle = ctypes.c_void_p()
        self._camera_mode = ctypes.c_long()
        count = ctypes.c_long(0)
        self._lib_inst.XSDK_Detect(
            ctypes.c_long(self._interface), None, None, ctypes.byref(count))
        if count.value == 0:
            # The bus has no camera at all: powered off or unplugged, not a
            # dead session.  Recorded before the open that is about to fail,
            # so every later teardown knows to abandon the handle rather than
            # dial it - see close().
            self.vanished = True
        rc = self._lib_inst.XSDK_OpenEx(
            device_name.encode("utf-8"),
            ctypes.byref(self._handle),
            ctypes.byref(self._camera_mode),
            None,
        )
        if rc != C.COMPLETE:
            # Nothing was opened, so there is nothing to close.  Without this
            # the exception below abandons a half-built object, __del__ calls
            # close(), and close() runs a full teardown - Release, drain,
            # SetPriorityMode, Close - on a handle the SDK never gave us.
            #
            # That is the heap corruption:
            #
            #     malloc: Incorrect checksum for freed object 0x1309d4e00:
            #             probably modified after being freed
            #     Corrupt value: 0xffffffff00000000
            #
            # which aborts the process outright, past the reach of any handler.
            # It appeared whenever an open failed, and retrying a failed open -
            # three times, with the daemons killed between - turned it from
            # occasional into repeatable.
            self._closed = True
        check_result(rc)
        log.info("Camera reconnected successfully")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        # getattr: an __init__ that raised, or an instance made with __new__,
        # may not have _closed at all.  An exception from __del__ is only
        # printed by the interpreter, so it is logged here instead.
        if getattr(self, "_closed", True):
            return
        try:
            self.close()
        except Exception:
            log.warning("Closing an abandoned camera session failed", exc_info=True)

    @property
    def handle(self) -> ctypes.c_void_p:
        return self._handle

    @property
    def camera_mode(self) -> int:
        return self._camera_mode.value

    # ------------------------------------------------------------------
    # Error info
    # ------------------------------------------------------------------
    def get_error(self) -> tuple[int, int]:
        """Get last error details. Returns (api_code, error_code)."""
        api_code = ctypes.c_long()
        err_code = ctypes.c_long()
        self._lib_inst.XSDK_GetErrorNumber(
            self._handle, ctypes.byref(api_code), ctypes.byref(err_code)
        )
        return api_code.value, err_code.value

    def _check(self, rc: int):
        """Check return code; on failure, retrieve and raise specific error."""
        if rc == C.COMPLETE:
            return
        api_code, err_code = self.get_error()
        raise_for_error_code(err_code, api_code)

    # ------------------------------------------------------------------
    # Device information
    # ------------------------------------------------------------------
    @property
    def device_info(self) -> DeviceInformation:
        info = DeviceInformation()
        self._check(self._lib_inst.XSDK_GetDeviceInfo(self._handle, ctypes.byref(info)))
        return info

    @property
    def lens_info(self) -> LensInformation:
        info = LensInformation()
        self._check(self._lib_inst.XSDK_GetLensInfo(self._handle, ctypes.byref(info)))
        return info

    @property
    def firmware_version(self) -> str:
        buf = ctypes.create_string_buffer(256)
        self._check(self._lib_inst.XSDK_GetFirmwareVersion(self._handle, buf))
        return buf.value.decode("utf-8", errors="replace")

    def get_sdk_version(self) -> str:
        buf = ctypes.create_string_buffer(256)
        self._lib_inst.XSDK_GetVersionString(buf)
        return buf.value.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Priority mode
    # ------------------------------------------------------------------
    def set_priority(self, mode: int):
        self._check(self._lib_inst.XSDK_SetPriorityMode(self._handle, ctypes.c_long(mode)))

    def get_priority(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetPriorityMode(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # AE mode
    # ------------------------------------------------------------------
    def set_ae_mode(self, mode: int):
        self._check(self._lib_inst.XSDK_SetAEMode(self._handle, ctypes.c_long(mode)))

    def get_ae_mode(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetAEMode(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Shutter speed
    # ------------------------------------------------------------------
    def set_shutter_speed(self, speed: int, bulb: int = 0):
        self._check(self._lib_inst.XSDK_SetShutterSpeed(
            self._handle, ctypes.c_long(speed), ctypes.c_long(bulb)
        ))

    def get_shutter_speed(self) -> tuple[int, int]:
        """Returns (speed, bulb)."""
        speed = ctypes.c_long()
        bulb = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetShutterSpeed(
            self._handle, ctypes.byref(speed), ctypes.byref(bulb)
        ))
        return speed.value, bulb.value

    def get_supported_shutter_speeds(self) -> list[int]:
        num = ctypes.c_long()
        # First call to get count
        speeds = (ctypes.c_long * 1024)()
        bulb_capable = ctypes.c_long()
        self._check(self._lib_inst.XSDK_CapShutterSpeed(
            self._handle, ctypes.byref(num), speeds, ctypes.byref(bulb_capable)
        ))
        return [speeds[i] for i in range(num.value)]

    # ------------------------------------------------------------------
    # ISO sensitivity
    # ------------------------------------------------------------------
    def set_iso(self, value: int):
        self._check(self._lib_inst.XSDK_SetSensitivity(self._handle, ctypes.c_long(value)))

    def get_iso(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetSensitivity(self._handle, ctypes.byref(val)))
        return val.value

    def get_supported_iso(self) -> list[int]:
        num = ctypes.c_long()
        values = (ctypes.c_long * 256)()
        self._check(self._lib_inst.XSDK_CapSensitivity(
            self._handle, ctypes.byref(num), values
        ))
        return [values[i] for i in range(num.value)]

    # ------------------------------------------------------------------
    # Aperture
    # ------------------------------------------------------------------
    def set_aperture(self, f_number: int):
        self._check(self._lib_inst.XSDK_SetAperture(self._handle, ctypes.c_long(f_number)))

    def get_aperture(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetAperture(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Exposure bias
    # ------------------------------------------------------------------
    def set_exposure_bias(self, bias: int):
        self._check(self._lib_inst.XSDK_SetExposureBias(self._handle, ctypes.c_long(bias)))

    def get_exposure_bias(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetExposureBias(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # White balance
    # ------------------------------------------------------------------
    def set_wb_mode(self, mode: int):
        self._check(self._lib_inst.XSDK_SetWBMode(self._handle, ctypes.c_long(mode)))

    def get_wb_mode(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetWBMode(self._handle, ctypes.byref(val)))
        return val.value

    def set_wb_color_temp(self, kelvin: int):
        self._check(self._lib_inst.XSDK_SetWBColorTemp(self._handle, ctypes.c_long(kelvin)))

    def get_wb_color_temp(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetWBColorTemp(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Drive mode
    # ------------------------------------------------------------------
    def set_drive_mode(self, mode: int):
        self._check(self._lib_inst.XSDK_SetDriveMode(self._handle, ctypes.c_long(mode)))

    def get_drive_mode(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetDriveMode(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Dynamic range
    # ------------------------------------------------------------------
    def set_dynamic_range(self, dr: int):
        self._check(self._lib_inst.XSDK_SetDynamicRange(self._handle, ctypes.c_long(dr)))

    def get_dynamic_range(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetDynamicRange(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Metering mode
    # ------------------------------------------------------------------
    def set_metering_mode(self, mode: int):
        self._check(self._lib_inst.XSDK_SetMeteringMode(self._handle, ctypes.c_long(mode)))

    def get_metering_mode(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetMeteringMode(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Release / Capture
    # ------------------------------------------------------------------
    def _release(self, mode: int, shot_count: int = 1) -> tuple[int, int]:
        """Issue a Release command. Returns (shot_opt, af_status).

        Args:
            mode: Release mode constant (RELEASE_S1ON, RELEASE_S2_S1OFF, etc.)
            shot_count: Number of frames to request in burst modes (plShotOpt IN).
                        Must be >= 1; the SDK treats 0 as invalid in burst drive modes.
        """
        shot_opt = ctypes.c_long(shot_count)
        af_status = ctypes.c_long()
        self._check(self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(mode),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        ))
        return shot_opt.value, af_status.value

    def shoot(self) -> tuple[int, int]:
        """Take a photo with AF + AE. Returns (shot_opt, af_status).

        Uses the S1ON→S2_S1OFF sequence which is compatible with all
        Fujifilm cameras including the X-T4 in tether mode.
        """
        self._release(C.RELEASE_S1ON)
        return self._release(C.RELEASE_S2_S1OFF)

    def shoot_no_af(self) -> tuple[int, int]:
        """Take a photo without AF. Returns (shot_opt, af_status).

        Uses S1ON → S2_S1OFF sequence. S1ON may return an error
        (e.g. AF fail) but still transitions the camera to S1 state,
        which is required before S2 can fire the shutter.
        """
        # S1ON puts the camera in half-press state; log but don't raise
        # (AF fail is expected when shooting without AF intent)
        shot_opt = ctypes.c_long(1)
        af_status = ctypes.c_long()
        rc = self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(C.RELEASE_S1ON),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        )
        if rc != C.COMPLETE:
            api_code, err_code = self.get_error()
            log.debug("S1ON rc=%d err=0x%08X api=0x%08X", rc, err_code, api_code)
        # Camera needs time to transition to S1 state before S2 can fire.
        # Too short (<0.1s) causes frequent ShootErrors; 0.15s is the sweet spot.
        time.sleep(0.15)
        return self._release(C.RELEASE_S2_S1OFF)

    def half_press(self):
        """S1 on (half-press shutter: AF + AE lock)."""
        shot_opt = ctypes.c_long()
        af_status = ctypes.c_long()
        self._check(self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(C.RELEASE_S1ON),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        ))

    def full_press(self) -> tuple[int, int]:
        """S2 (full press: take shot after S1). Returns (shot_opt, af_status)."""
        shot_opt = ctypes.c_long()
        af_status = ctypes.c_long()
        self._check(self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(C.RELEASE_S2),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        ))
        return shot_opt.value, af_status.value

    def release_all(self):
        """Cancel all active release operations (S1 off, AF off, etc.)."""
        shot_opt = ctypes.c_long()
        af_status = ctypes.c_long()
        self._check(self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(C.RELEASE_CANCEL),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        ))

    def bulb_start(self):
        """Begin bulb exposure."""
        shot_opt = ctypes.c_long()
        af_status = ctypes.c_long()
        self._check(self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(C.RELEASE_BULB_ON),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        ))

    def bulb_stop(self):
        """End bulb exposure."""
        shot_opt = ctypes.c_long()
        af_status = ctypes.c_long()
        self._check(self._lib_inst.XSDK_Release(
            self._handle,
            ctypes.c_long(C.RELEASE_N_BULBOFF),
            ctypes.byref(shot_opt),
            ctypes.byref(af_status),
        ))

    def get_release_status(self) -> int:
        val = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetReleaseStatus(self._handle, ctypes.byref(val)))
        return val.value

    # ------------------------------------------------------------------
    # Image download
    # ------------------------------------------------------------------
    def get_buffer_capacity(self) -> tuple[int, int]:
        """Returns (captured_count, total_capacity).

        captured_count: number of images currently in the volatile buffer.
        total_capacity: maximum number of images the buffer can hold.
        Buffer is full when captured_count >= total_capacity.
        """
        shoot = ctypes.c_long()
        total = ctypes.c_long()
        self._check(self._lib_inst.XSDK_GetBufferCapacity(
            self._handle, ctypes.byref(shoot), ctypes.byref(total)
        ))
        return shoot.value, total.value

    def read_image_info(self) -> ImageInformation:
        info = ImageInformation()
        self._check(self._lib_inst.XSDK_ReadImageInfo(self._handle, ctypes.byref(info)))
        return info

    def read_image(self, size: int) -> bytes:
        buf = (ctypes.c_ubyte * size)()
        self._check(self._lib_inst.XSDK_ReadImage(
            self._handle, buf, ctypes.c_ulong(size)
        ))
        return bytes(buf)

    def read_preview(self, size: int) -> bytes:
        buf = (ctypes.c_ubyte * size)()
        self._check(self._lib_inst.XSDK_ReadPreview(
            self._handle, buf, ctypes.c_ulong(size)
        ))
        return bytes(buf)

    def delete_image(self):
        self._check(self._lib_inst.XSDK_DeleteImage(self._handle))

    def drain_buffer(self, budget_s: float = None) -> int:
        """Delete all pending images from the volatile buffer.

        One pass is enough, and this is measured rather than assumed: filling the
        queue to 30/32 five times over and draining it, the number deleted
        matched the number GetBufferCapacity reported every single time (31/31,
        31/31, 30/30, 31/31, 30/30).  A tap's frames do take 0.35-0.75s to appear
        in the count, so a drain issued immediately after shooting can miss them
        — which is why the caller settles first — but nothing arrives late once
        they are there, and re-reading the buffer only ever returned zero.

        ``budget_s`` overrides how long the pass may take.  A caller draining
        between the frames of a burst has less time than one draining after it,
        and is better served by freeing some slots now than all of them late.

        Returns the number of images drained.
        """
        captured, total = self.get_buffer_capacity()
        if captured <= 0:
            log.debug("No images to drain (buffer: %d/%d)", captured, total)
            return 0

        budget = DRAIN_BUDGET_S if budget_s is None else max(0.0, float(budget_s))
        drained = self._drain_pass(captured, time.monotonic() + budget)
        if drained:
            log.info("Drained %d pending image(s) from buffer", drained)
        if drained != captured:
            log.warning("Drained %d of the %d images the buffer reported; "
                        "the rest go with the next drain", drained, captured)
        return drained

    def _drain_pass(self, captured: int, deadline: float) -> int:
        """Delete up to ``captured`` images, returning how many actually went.

        A busy body is waited out rather than deleted through: an image is only
        ever counted as drained once ReadImageInfo has confirmed one is there and
        DeleteImage has taken it.  Deleting blind on a busy read inflates the
        count with images that may never have existed, and the count is the only
        evidence of how many frames a release really queues.
        """
        drained = 0
        for i in range(captured):
            # The budget bounds the pass, not just each busy wait inside it.
            # With the camera firing, a delete costs about 0.15 s per image, so
            # an unbounded pass over a full buffer runs far past the budget the
            # caller gave it, and delays the next frame.
            if i and time.monotonic() >= deadline:
                log.debug("Drain pass out of budget at entry %d of %d; the "
                          "rest go with the next drain", i, captured)
                break
            try:
                info = self._through_busy(self.read_image_info,
                                          f"read image info at entry {i}", deadline)
            except BusyError:
                log.warning("Drain stopped at entry %d: body still busy", i)
                break
            except XSDKError as e:
                log.warning("Drain stopped at entry %d: %s", i, e)
                break

            fmt = info.format & 0xFF
            log.debug("Buffer entry %d: format=0x%04X size=%d", i, info.format, info.data_size)
            if fmt == C.IMAGEFORMAT_NONE:
                log.debug("No more images in queue (IMAGEFORMAT_NONE)")
                break

            # An image is confirmed present, so waiting out a busy delete is
            # sound: the slot has to come back or the body stops when it fills.
            try:
                self._through_busy(self.delete_image,
                                   f"delete image at entry {i}", deadline)
            except XSDKError as e:
                log.warning("Drain stopped at entry %d: %s", i, e)
                break
            drained += 1
        return drained

    @staticmethod
    def _through_busy(action, what: str, deadline: float):
        """Run a drain call, waiting out 0x1006 while there is budget left."""
        while True:
            try:
                return action()
            except BusyError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                log.debug("Camera busy: %s, %.1fs of drain budget left", what, remaining)
                time.sleep(min(DRAIN_BUSY_BACKOFF_S, remaining))

    def download_image(self, output_path: str | Path) -> str:
        """Convenience: read image info, download full image, save to disk.

        Returns the output file path as a string.
        """
        info = self.read_image_info()
        data = self.read_image(info.data_size)
        output_path = Path(output_path)
        output_path.write_bytes(data)
        return str(output_path)

    # ------------------------------------------------------------------
    # Extended properties (model-dependent via CapProp/SetProp/GetProp)
    # ------------------------------------------------------------------
    def set_prop(self, api_code: int, api_param: int | None = None, *args):
        """Call XSDK_SetProp with variadic arguments.

        api_param is looked up from the API when not given, which is what
        callers should do: every call site here passed 0 by hand and 25 of the
        28 were wrong, so the body answered 0x1002 to most of them.  Pass one
        explicitly only to override the table.

        Pass ctypes-typed values for additional arguments, e.g.:
            cam.set_prop(API_CODE_SetFilmSimulationMode, ctypes.c_long(mode))
        """
        api_param, args = _resolve_param(api_code, api_param, args)
        rc = self._lib_inst.XSDK_SetProp(
            self._handle, ctypes.c_long(api_code), ctypes.c_long(api_param), *args
        )
        self._check(rc)

    def get_prop(self, api_code: int, api_param: int | None = None, *args):
        """Call XSDK_GetProp with variadic arguments.

        api_param is looked up from the API when not given; see set_prop.

        Pass ctypes pointer arguments for output, e.g.:
            val = ctypes.c_long()
            cam.get_prop(API_CODE_GetFilmSimulationMode, ctypes.byref(val))
        """
        api_param, args = _resolve_param(api_code, api_param, args)
        rc = self._lib_inst.XSDK_GetProp(
            self._handle, ctypes.c_long(api_code), ctypes.c_long(api_param), *args
        )
        self._check(rc)

    def cap_prop(self, api_code: int, api_param: int, *args):
        """Call XSDK_CapProp with variadic arguments.

        Pass ctypes pointer arguments for output, e.g.:
            num = ctypes.c_long()
            values = (ctypes.c_long * 64)()
            cam.cap_prop(API_CODE_CapFilmSimulationMode, 0, ctypes.byref(num), values)
        """
        rc = self._lib_inst.XSDK_CapProp(
            self._handle, ctypes.c_long(api_code), ctypes.c_long(api_param), *args
        )
        self._check(rc)

    # ------------------------------------------------------------------
    # Focus mode (extended API)
    # ------------------------------------------------------------------
    def get_focus_mode(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetFocusMode, ctypes.byref(val))
        return val.value

    def set_focus_mode(self, mode: int):
        self.set_prop(C.API_CODE_SetFocusMode, ctypes.c_long(mode))

    # ------------------------------------------------------------------
    # Image quality (extended API)
    # ------------------------------------------------------------------
    def get_image_quality(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetImageQuality, ctypes.byref(val))
        return val.value

    def set_image_quality(self, quality: int):
        self.set_prop(C.API_CODE_SetImageQuality, ctypes.c_long(quality))

    # ------------------------------------------------------------------
    # Long exposure NR (extended API)
    # ------------------------------------------------------------------
    def get_long_exposure_nr(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetLongExposureNR, ctypes.byref(val))
        return val.value

    def set_long_exposure_nr(self, mode: int):
        self.set_prop(C.API_CODE_SetLongExposureNR, ctypes.c_long(mode))

    # ------------------------------------------------------------------
    # IS mode (image stabilization, extended API)
    # ------------------------------------------------------------------
    def get_is_mode(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetISMode, ctypes.byref(val))
        return val.value

    def set_is_mode(self, mode: int):
        self.set_prop(C.API_CODE_SetISMode, ctypes.c_long(mode))

    # ------------------------------------------------------------------
    # Live View (extended API)
    # ------------------------------------------------------------------
    def start_live_view(self):
        self.set_prop(C.API_CODE_StartLiveView)

    def stop_live_view(self):
        self.set_prop(C.API_CODE_StopLiveView)

    def set_live_view_size(self, size: int):
        self.set_prop(C.API_CODE_SetLiveViewImageSize, ctypes.c_long(size))

    def get_live_view_size(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetLiveViewImageSize, ctypes.byref(val))
        return val.value

    def get_live_view_status(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetLiveViewStatus, ctypes.byref(val))
        return val.value

    # ------------------------------------------------------------------
    # MF Assist mode (extended API)
    # ------------------------------------------------------------------
    def get_mf_assist_mode(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetMFAssistMode, ctypes.byref(val))
        return val.value

    def set_mf_assist_mode(self, mode: int):
        self.set_prop(C.API_CODE_SetMFAssistMode, ctypes.c_long(mode))

    def get_supported_mf_assist_modes(self) -> list[int]:
        num = ctypes.c_long()
        values = (ctypes.c_long * 64)()
        self.cap_prop(C.API_CODE_CapMFAssistMode, 0, ctypes.byref(num), values)
        return [values[i] for i in range(num.value)]

    # ------------------------------------------------------------------
    # Focus Check mode (peaking toggle, extended API)
    # ------------------------------------------------------------------
    def get_focus_check_mode(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetFocusCheckMode, ctypes.byref(val))
        return val.value

    def set_focus_check_mode(self, mode: int):
        self.set_prop(C.API_CODE_SetFocusCheckMode, ctypes.c_long(mode))

    def get_supported_focus_check_modes(self) -> list[int]:
        num = ctypes.c_long()
        values = (ctypes.c_long * 64)()
        self.cap_prop(C.API_CODE_CapFocusCheckMode, 0, ctypes.byref(num), values)
        return [values[i] for i in range(num.value)]

    # ------------------------------------------------------------------
    # Focus position (extended API)
    # ------------------------------------------------------------------
    def get_focus_pos(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetFocusPos, ctypes.byref(val))
        return val.value

    def set_focus_pos(self, pos: int):
        self.set_prop(C.API_CODE_SetFocusPos, ctypes.c_long(pos))

    # ------------------------------------------------------------------
    # Through-Image Zoom (extended API)
    # ------------------------------------------------------------------
    def get_through_image_zoom(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetThroughImageZoom, ctypes.byref(val))
        return val.value

    def set_through_image_zoom(self, zoom: int):
        self.set_prop(C.API_CODE_SetThroughImageZoom, ctypes.c_long(zoom))

    def get_supported_through_image_zoom(self) -> list[int]:
        num = ctypes.c_long()
        values = (ctypes.c_long * 64)()
        self.cap_prop(C.API_CODE_CapThroughImageZoom, 0, ctypes.byref(num), values)
        return [values[i] for i in range(num.value)]

    # ------------------------------------------------------------------
    # Live view quality (extended API)
    # ------------------------------------------------------------------
    def get_live_view_quality(self) -> int:
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetLiveViewImageQuality, ctypes.byref(val))
        return val.value

    def set_live_view_quality(self, quality: int):
        self.set_prop(C.API_CODE_SetLiveViewImageQuality, ctypes.c_long(quality))

    # ------------------------------------------------------------------
    # Battery info (extended API)
    # ------------------------------------------------------------------
    def get_battery_info(self) -> "BatteryInfo":
        """The body and grip battery levels.

        Six out-parameters, per the reference manual for every model except the
        GFX 100 family:

            XSDK_GetProp(hCamera, lAPICode, lAPIParam,
                         plBodyBatteryInfo,  plGripBatteryInfo,
                         plGripBattery2Info, plBodyBatteryRatio,
                         plGripBatteryRatio, plGripBattery2Ratio)

        Three were passed before, so the call was refused and no battery level
        was ever read from this body - which matters on a day where the camera
        has to last the whole of totality on the charge it starts with.

        The levels are coarse states, not percentages: see POWERCAPACITY_NAMES
        for what they mean and POWERCAPACITY_PERCENT for an approximation.
        """
        body, grip, grip2 = (ctypes.c_long(), ctypes.c_long(), ctypes.c_long())
        body_r, grip_r, grip2_r = (ctypes.c_long(), ctypes.c_long(),
                                   ctypes.c_long())
        self.get_prop(
            C.API_CODE_CheckBatteryInfo,
            ctypes.byref(body), ctypes.byref(grip), ctypes.byref(grip2),
            ctypes.byref(body_r), ctypes.byref(grip_r), ctypes.byref(grip2_r),
        )
        return BatteryInfo(
            body=body.value, grip=grip.value, grip2=grip2.value,
            body_ratio=body_r.value, grip_ratio=grip_r.value,
            grip2_ratio=grip2_r.value,
        )

    # ------------------------------------------------------------------
    # Media status / capacity (extended API)
    # ------------------------------------------------------------------
    def get_media_status(self, slot: int = C.ITEM_MEDIASLOT1) -> int:
        """Whether the card in the given slot can be written to.

        Takes the slot as an input parameter before the answer:

            XSDK_GetProp(hCamera, lAPICode, lAPIParam, lCategory, pStatus)

        The slot was never passed, so this never answered.  Compare against
        MEDIASTATUS_CANNOT_WRITE, or name it with MEDIASTATUS_NAMES.
        """
        val = ctypes.c_long()
        self.get_prop(C.API_CODE_GetMediaStatus,
                      ctypes.c_long(slot), ctypes.byref(val))
        return val.value

    def get_media_capacity(self, slot: int = C.ITEM_MEDIASLOT1) -> "MediaCapacity":
        """How much room is left on the card in the given slot.

            XSDK_GetProp(hCamera, lAPICode, lAPIParam, lCategory,
                         pBlankFrameNum, pRemainSectorNum, pSectorSize,
                         pCardSize)

        The old signature claimed to return "free capacity in KB" from a single
        out-parameter and a missing slot, and returned nothing at all.

        blank_frames is the number the body itself thinks it can still take,
        which is the figure worth showing before an eclipse - it accounts for
        the format and compression actually set.
        """
        frames, sectors, sector_size, card = (ctypes.c_long(), ctypes.c_long(),
                                              ctypes.c_long(), ctypes.c_long())
        self.get_prop(
            C.API_CODE_GetMediaCapacity, ctypes.c_long(slot),
            ctypes.byref(frames), ctypes.byref(sectors),
            ctypes.byref(sector_size), ctypes.byref(card),
        )
        return MediaCapacity(
            blank_frames=frames.value, remaining_sectors=sectors.value,
            sector_size=sector_size.value, card_size=card.value,
        )

    # ------------------------------------------------------------------
    # Shutter count (extended API)
    # ------------------------------------------------------------------
    def get_shutter_count(self) -> "ShutterCount":
        """The actuation counters.

            XSDK_GetProp(hCamera, lAPICode, lAPIParam,
                         pShutterCount, pTotalShutterCount, pExchangeCount)

        One out-parameter was passed of the three.  `total` is the figure people
        mean by shutter count; `current` resets when the shutter unit is
        replaced, and `exchanges` says how many times that has happened.
        """
        current, total, exchanges = (ctypes.c_long(), ctypes.c_long(),
                                     ctypes.c_long())
        self.get_prop(
            C.API_CODE_GetShutterCount,
            ctypes.byref(current), ctypes.byref(total), ctypes.byref(exchanges),
        )
        return ShutterCount(current=current.value, total=total.value,
                            exchanges=exchanges.value)

    # ------------------------------------------------------------------
    # Command dial status (extended API)
    # ------------------------------------------------------------------
    def get_command_dial_status(self) -> int:
        """Not wired up - the X-T4 header says this takes four arguments.

        Raises rather than returning a number that was never read.  It passed
        one out-parameter of four, so the body refused the call and the value
        returned was whatever the uninitialised long happened to hold.  The
        reference manual does not document this API, so the remaining three
        parameters cannot be guessed; nothing in this project calls it.
        """
        raise NotImplementedError(
            "GetCommandDialStatus takes four arguments on the X-T4 and the SDK "
            "reference does not document them")
