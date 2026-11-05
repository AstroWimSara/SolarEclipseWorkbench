"""Exception hierarchy for Fujifilm X SDK errors."""

from __future__ import annotations

from . import _constants as C


class LDPathError(RuntimeError):
    """LD_LIBRARY_PATH was updated and the process must restart.

    On Linux, glibc caches LD_LIBRARY_PATH at process startup.
    The caller should re-exec the process (os.execvp) or inform the user.
    """

    def __init__(self, new_path: str):
        self.new_path = new_path
        super().__init__(
            f"LD_LIBRARY_PATH was updated but the process must be restarted "
            f"for changes to take effect. Set before starting Python:\n"
            f"  export LD_LIBRARY_PATH=\"{new_path}\""
        )


class XSDKError(Exception):
    """Base exception for all SDK errors."""

    def __init__(self, code: int, message: str = "", api_code: int = 0):
        self.code = code
        self.api_code = api_code
        super().__init__(f"XSDK error 0x{code:08X}: {message}" if message else f"XSDK error 0x{code:08X}")


class SequenceError(XSDKError):
    """API called in wrong sequence."""


class ParamError(XSDKError):
    """Invalid parameter."""


class InvalidCameraError(XSDKError):
    """Invalid camera handle."""


class LoadLibError(XSDKError):
    """Failed to load model library."""


class UnsupportedError(XSDKError):
    """Feature not supported by this camera model."""


class BusyError(XSDKError):
    """Camera is busy."""


class AFTimeoutError(XSDKError):
    """Autofocus timed out."""


class ShootError(XSDKError):
    """Shooting error."""


class FrameFullError(XSDKError):
    """Frame buffer is full."""


class StandbyError(XSDKError):
    """Camera is in standby."""


class CommunicationError(XSDKError):
    """Communication with camera failed."""


class TimeoutError(XSDKError):
    """Operation timed out."""


class HardwareError(XSDKError):
    """Camera hardware error."""


class InternalError(XSDKError):
    """SDK internal error."""


_ERROR_MAP: dict[int, tuple[type[XSDKError], str]] = {
    C.ERRCODE_SEQUENCE: (SequenceError, "API called in wrong sequence"),
    C.ERRCODE_PARAM: (ParamError, "Invalid parameter"),
    C.ERRCODE_INVALID_CAMERA: (InvalidCameraError, "Invalid camera handle"),
    C.ERRCODE_LOADLIB: (LoadLibError, "Failed to load model library"),
    C.ERRCODE_UNSUPPORTED: (UnsupportedError, "Feature not supported"),
    C.ERRCODE_BUSY: (BusyError, "Camera is busy"),
    C.ERRCODE_AF_TIMEOUT: (AFTimeoutError, "Autofocus timed out"),
    C.ERRCODE_SHOOT_ERROR: (ShootError, "Shooting error"),
    C.ERRCODE_FRAME_FULL: (FrameFullError, "Frame buffer full"),
    C.ERRCODE_STANDBY: (StandbyError, "Camera in standby"),
    C.ERRCODE_NODRIVER: (CommunicationError, "No driver found"),
    C.ERRCODE_NO_MODEL_MODULE: (LoadLibError, "Model module not found"),
    C.ERRCODE_API_NOTFOUND: (UnsupportedError, "API not found in model module"),
    C.ERRCODE_API_MISMATCH: (UnsupportedError, "API version mismatch"),
    C.ERRCODE_INVALID_USBMODE: (SequenceError, "Invalid USB mode"),
    C.ERRCODE_FORCEMODE_BUSY: (BusyError, "Force mode busy"),
    C.ERRCODE_RUNNING_OTHER_FUNCTION: (BusyError, "Another function is running"),
    C.ERRCODE_COMMUNICATION: (CommunicationError, "Communication error"),
    C.ERRCODE_TIMEOUT: (TimeoutError, "Operation timed out"),
    C.ERRCODE_COMBINATION: (ParamError, "Invalid parameter combination"),
    C.ERRCODE_WRITEERROR: (CommunicationError, "Write error"),
    C.ERRCODE_CARDFULL: (FrameFullError, "Memory card full"),
    C.ERRCODE_HARDWARE: (HardwareError, "Hardware error"),
    C.ERRCODE_INTERNAL: (InternalError, "Internal SDK error"),
    C.ERRCODE_MEMFULL: (InternalError, "Memory full"),
    C.ERRCODE_UNKNOWN: (XSDKError, "Unknown error"),
}


def check_result(rc: int, handle: object = None) -> None:
    """Raise an appropriate XSDKError if rc indicates failure.

    Args:
        rc: Return code from an SDK function (0 = success, -1 = error).
        handle: Camera handle for retrieving detailed error info (unused for now,
                reserved for future GetErrorNumber integration).
    """
    if rc == C.COMPLETE:
        return
    # rc == ERROR (-1) means we need to look up the actual error code.
    # Without a handle we can only raise a generic error.
    raise XSDKError(rc, "SDK call returned error")


def raise_for_error_code(error_code: int, api_code: int = 0) -> None:
    """Raise the specific exception matching a retrieved error code."""
    if error_code == C.ERRCODE_NOERR:
        return
    exc_class, message = _ERROR_MAP.get(error_code, (XSDKError, f"Error code 0x{error_code:08X}"))
    raise exc_class(error_code, message, api_code)
