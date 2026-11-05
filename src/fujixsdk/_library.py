"""Low-level ctypes bindings for the Fujifilm X SDK native library.

Handles dlopen/LoadLibrary, function resolution, and platform detection.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from pathlib import Path

from ._structures import (
    XSDK_HANDLE,
    LIB_HANDLE,
    CameraList,
    DeviceInformation,
    ImageInformation,
    LensInformation,
)


def find_library(sdk_path: str | Path) -> Path:
    """Locate the XAPI shared library in the SDK directory.

    Args:
        sdk_path: Path to the directory containing the SDK libraries.

    Returns:
        Path to the XAPI shared library.

    Raises:
        FileNotFoundError: If the library cannot be found.
    """
    sdk_path = Path(sdk_path)
    system = platform.system()

    if system == "Linux":
        candidates = ["XAPI.so", "libXAPI.so"]
    elif system == "Darwin":
        # macOS SDK uses .bundle format
        candidates = ["XAPI.dylib", "libXAPI.dylib"]
        bundle_path = sdk_path / "XAPI.bundle" / "Contents" / "MacOS" / "XAPI"
        if bundle_path.exists():
            return bundle_path
        # The redistributables live several levels down (REDISTRIBUTABLES/macOS/
        # SDK_nnnnn/), so callers normally pass the SDK root rather than the
        # directory holding the bundle.
        for bundle in sorted(sdk_path.rglob("XAPI.bundle")):
            binary = bundle / "Contents" / "MacOS" / "XAPI"
            if binary.exists():
                return binary
    elif system == "Windows":
        candidates = ["XAPI.dll"]
    else:
        raise OSError(f"Unsupported platform: {system}")

    for name in candidates:
        path = sdk_path / name
        if path.exists():
            return path

    # Try recursive search
    for name in candidates:
        matches = list(sdk_path.rglob(name))
        if matches:
            return matches[0]

    raise FileNotFoundError(
        f"Cannot find XAPI library in {sdk_path}. "
        f"Expected one of: {', '.join(candidates)} or XAPI.bundle"
    )


def find_model_libraries(sdk_path: str | Path) -> list[Path]:
    """Find model-specific libraries (FF0000API.so etc.) needed by XSDK_Init.

    The SDK loads these dynamically, but they must be in the library search path.
    """
    sdk_path = Path(sdk_path)
    system = platform.system()

    if system == "Linux":
        ext = ".so"
        return sorted(p for p in sdk_path.rglob(f"*API{ext}") if p.name != f"XAPI{ext}")
    elif system == "Darwin":
        # macOS uses .bundle directories; the binary is inside Contents/MacOS/.
        # Recurse, to match the Linux branch: callers pass the SDK root, and the
        # redistributables sit several levels below it.
        libs = []
        for bundle in sdk_path.rglob("FF*API.bundle"):
            binary = bundle / "Contents" / "MacOS" / bundle.stem
            if binary.exists():
                libs.append(binary)
        return sorted(libs)
    elif system == "Windows":
        ext = ".dll"
        return sorted(p for p in sdk_path.rglob(f"*API{ext}") if p.name != f"XAPI{ext}")
    else:
        return []


_linux_deps_loaded = False


def ensure_ld_library_path(sdk_lib_dir: str | Path) -> bool:
    """Ensure LD_LIBRARY_PATH includes the SDK lib directory and dependencies.

    The SDK internally dlopen()s model libraries (FF*API.so) and
    libusb-1.0.so by name, so they must be findable via LD_LIBRARY_PATH.
    On NixOS, libstdc++ also needs to be in the path.

    Returns True if the path was already set, False if it was modified
    (caller may need to re-exec the process for changes to take effect
    with the dynamic linker).
    """
    # macOS doesn't use LD_LIBRARY_PATH; bundles are loaded via @rpath/dlopen
    if platform.system() == "Darwin":
        return True

    # Resolve to the actual directory containing XAPI.so
    try:
        xapi_path = find_library(sdk_lib_dir)
        sdk_dir = str(xapi_path.parent.resolve())
    except FileNotFoundError:
        sdk_dir = str(Path(sdk_lib_dir).resolve())
    ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    paths = ld_path.split(":") if ld_path else []

    needed = []
    if sdk_dir not in paths:
        needed.append(sdk_dir)

    # On NixOS, these libs aren't in the standard search path
    for lib_name, finder in [
        ("libstdc++.so.6", _find_nix_lib_dir_stdcpp),
        ("libusb-1.0.so", _find_nix_lib_dir_usb),
    ]:
        try:
            ctypes.CDLL(lib_name)
        except OSError:
            lib_dir = finder()
            if lib_dir and lib_dir not in paths and lib_dir not in needed:
                needed.append(lib_dir)

    if not needed:
        return True

    new_path = ":".join(needed + paths) if paths else ":".join(needed)
    os.environ["LD_LIBRARY_PATH"] = new_path
    return False


def _find_nix_lib_dir_stdcpp() -> str | None:
    """Find the directory containing libstdc++ on NixOS."""
    import glob as globmod

    for pattern in [
        "/nix/store/*-gcc-*-lib/lib/libstdc++.so.6",
        "/nix/store/*/share/nix-ld/lib/libstdc++.so.6",
    ]:
        hits = globmod.glob(pattern)
        if hits:
            real = os.path.realpath(hits[0])
            return os.path.dirname(real)
    return None


def _find_nix_lib_dir_usb() -> str | None:
    """Find the directory containing libusb-1.0.so on NixOS."""
    import glob as globmod

    hits = globmod.glob("/nix/store/*-libusb-*/lib/libusb-1.0.so")
    if hits:
        real = os.path.realpath(hits[0])
        return os.path.dirname(real)
    return None


_linux_deps_loaded = False


def _preload_linux_deps():
    """Pre-load libstdc++ and libusb with RTLD_GLOBAL.

    Do NOT preload model libs (FF*API.so) — the SDK loads these itself
    during XSDK_Init and will segfault if they're already loaded.
    LD_LIBRARY_PATH must be set (via ensure_ld_library_path) so the
    SDK can find model libs and libusb at runtime.
    """
    global _linux_deps_loaded
    if _linux_deps_loaded:
        return
    _linux_deps_loaded = True

    for lib_name, finder in [
        ("libstdc++.so.6", _find_nix_lib_dir_stdcpp),
        ("libusb-1.0.so", _find_nix_lib_dir_usb),
    ]:
        try:
            ctypes.CDLL(lib_name, mode=ctypes.RTLD_GLOBAL)
        except OSError:
            lib_dir = finder()
            if lib_dir:
                try:
                    ctypes.CDLL(
                        os.path.join(lib_dir, lib_name),
                        mode=ctypes.RTLD_GLOBAL,
                    )
                except OSError:
                    pass


class XAPILibrary:
    """Wrapper around the native XAPI shared library with typed function bindings.

    Usage:
        lib = XAPILibrary("/path/to/sdk/libs")
        lib.XSDK_Init(ctypes.c_void_p(lib._lib._handle))
        # ... use lib.XSDK_* functions ...
        lib.XSDK_Exit()
    """

    def __init__(self, sdk_path: str | Path):
        self._sdk_path = Path(sdk_path).resolve()
        lib_path = find_library(sdk_path)
        lib_dir = str(lib_path.parent.resolve())

        if platform.system() == "Linux":
            _preload_linux_deps()

        self._lib = ctypes.CDLL(str(lib_path.resolve()))
        self._setup_functions()

    def _func(self, name: str, argtypes: list, restype=ctypes.c_long):
        """Resolve a function symbol and set its signature."""
        fn = getattr(self._lib, name)
        fn.argtypes = argtypes
        fn.restype = restype
        return fn

    def _setup_functions(self):
        c_long_p = ctypes.POINTER(ctypes.c_long)
        c_ulong = ctypes.c_ulong
        c_char_p = ctypes.c_char_p
        c_void_p = ctypes.c_void_p
        handle_p = ctypes.POINTER(ctypes.c_void_p)
        c_ubyte_p = ctypes.POINTER(ctypes.c_ubyte)

        # --- Initialize / Finalize ---
        self.XSDK_Init = self._func("XSDK_Init", [c_void_p])
        self.XSDK_Exit = self._func("XSDK_Exit", [])

        # --- Enumeration ---
        self.XSDK_Detect = self._func(
            "XSDK_Detect", [ctypes.c_long, c_char_p, c_char_p, c_long_p]
        )
        self.XSDK_Append = self._func(
            "XSDK_Append",
            [ctypes.c_long, c_char_p, c_char_p, c_long_p, ctypes.POINTER(CameraList)],
        )

        # --- Session management ---
        self.XSDK_OpenEx = self._func(
            "XSDK_OpenEx", [c_char_p, handle_p, c_long_p, c_void_p]
        )
        self.XSDK_Close = self._func("XSDK_Close", [c_void_p])
        self.XSDK_PowerOFF = self._func("XSDK_PowerOFF", [c_void_p])

        # --- Basic functions ---
        self.XSDK_GetErrorNumber = self._func(
            "XSDK_GetErrorNumber", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_GetVersionString = self._func(
            "XSDK_GetVersionString", [c_char_p]
        )
        self.XSDK_GetErrorDetails = self._func(
            "XSDK_GetErrorDetails", [c_void_p, c_long_p]
        )

        # --- Device information ---
        self.XSDK_GetDeviceInfo = self._func(
            "XSDK_GetDeviceInfo", [c_void_p, ctypes.POINTER(DeviceInformation)]
        )
        self.XSDK_WriteDeviceName = self._func(
            "XSDK_WriteDeviceName", [c_void_p, c_char_p]
        )
        self.XSDK_GetFirmwareVersion = self._func(
            "XSDK_GetFirmwareVersion", [c_void_p, c_char_p]
        )
        self.XSDK_GetLensInfo = self._func(
            "XSDK_GetLensInfo", [c_void_p, ctypes.POINTER(LensInformation)]
        )
        self.XSDK_GetLensVersion = self._func(
            "XSDK_GetLensVersion", [c_void_p, c_char_p]
        )
        self.XSDK_GetDeviceInfoEx = self._func(
            "XSDK_GetDeviceInfoEx",
            [c_void_p, ctypes.POINTER(DeviceInformation), c_long_p, c_long_p],
        )

        # --- Priority mode ---
        self.XSDK_CapPriorityMode = self._func(
            "XSDK_CapPriorityMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetPriorityMode = self._func(
            "XSDK_SetPriorityMode", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetPriorityMode = self._func(
            "XSDK_GetPriorityMode", [c_void_p, c_long_p]
        )

        # --- Release control ---
        self.XSDK_CapRelease = self._func(
            "XSDK_CapRelease", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_Release = self._func(
            "XSDK_Release", [c_void_p, ctypes.c_long, c_long_p, c_long_p]
        )
        self.XSDK_CapReleaseEx = self._func(
            "XSDK_CapReleaseEx", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_ReleaseEx = self._func(
            "XSDK_ReleaseEx", [c_void_p, ctypes.c_long, c_long_p, c_long_p]
        )
        self.XSDK_CapReleaseStatus = self._func(
            "XSDK_CapReleaseStatus", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_GetReleaseStatus = self._func(
            "XSDK_GetReleaseStatus", [c_void_p, c_long_p]
        )

        # --- Image acquisition ---
        self.XSDK_GetBufferCapacity = self._func(
            "XSDK_GetBufferCapacity", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_ReadImageInfo = self._func(
            "XSDK_ReadImageInfo", [c_void_p, ctypes.POINTER(ImageInformation)]
        )
        self.XSDK_ReadPreview = self._func(
            "XSDK_ReadPreview", [c_void_p, c_ubyte_p, c_ulong]
        )
        self.XSDK_ReadImage = self._func(
            "XSDK_ReadImage", [c_void_p, c_ubyte_p, c_ulong]
        )
        self.XSDK_DeleteImage = self._func("XSDK_DeleteImage", [c_void_p])

        # --- Exposure control ---
        self.XSDK_CapAEMode = self._func(
            "XSDK_CapAEMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetAEMode = self._func(
            "XSDK_SetAEMode", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetAEMode = self._func(
            "XSDK_GetAEMode", [c_void_p, c_long_p]
        )

        self.XSDK_CapShutterSpeed = self._func(
            "XSDK_CapShutterSpeed", [c_void_p, c_long_p, c_long_p, c_long_p]
        )
        self.XSDK_SetShutterSpeed = self._func(
            "XSDK_SetShutterSpeed", [c_void_p, ctypes.c_long, ctypes.c_long]
        )
        self.XSDK_GetShutterSpeed = self._func(
            "XSDK_GetShutterSpeed", [c_void_p, c_long_p, c_long_p]
        )

        self.XSDK_CapExposureBias = self._func(
            "XSDK_CapExposureBias", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetExposureBias = self._func(
            "XSDK_SetExposureBias", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetExposureBias = self._func(
            "XSDK_GetExposureBias", [c_void_p, c_long_p]
        )

        self.XSDK_CapSensitivity = self._func(
            "XSDK_CapSensitivity", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetSensitivity = self._func(
            "XSDK_SetSensitivity", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetSensitivity = self._func(
            "XSDK_GetSensitivity", [c_void_p, c_long_p]
        )

        self.XSDK_CapDynamicRange = self._func(
            "XSDK_CapDynamicRange", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetDynamicRange = self._func(
            "XSDK_SetDynamicRange", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetDynamicRange = self._func(
            "XSDK_GetDynamicRange", [c_void_p, c_long_p]
        )

        self.XSDK_CapMeteringMode = self._func(
            "XSDK_CapMeteringMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetMeteringMode = self._func(
            "XSDK_SetMeteringMode", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetMeteringMode = self._func(
            "XSDK_GetMeteringMode", [c_void_p, c_long_p]
        )

        # --- Zoom / Aperture ---
        self.XSDK_CapLensZoomPos = self._func(
            "XSDK_CapLensZoomPos", [c_void_p, c_long_p, c_long_p, c_long_p, c_long_p]
        )
        self.XSDK_SetLensZoomPos = self._func(
            "XSDK_SetLensZoomPos", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetLensZoomPos = self._func(
            "XSDK_GetLensZoomPos", [c_void_p, c_long_p]
        )

        self.XSDK_CapAperture = self._func(
            "XSDK_CapAperture", [c_void_p, ctypes.c_long, c_long_p, c_long_p]
        )
        self.XSDK_SetAperture = self._func(
            "XSDK_SetAperture", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetAperture = self._func(
            "XSDK_GetAperture", [c_void_p, c_long_p]
        )

        # --- White balance ---
        self.XSDK_CapWBMode = self._func(
            "XSDK_CapWBMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetWBMode = self._func(
            "XSDK_SetWBMode", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetWBMode = self._func(
            "XSDK_GetWBMode", [c_void_p, c_long_p]
        )
        self.XSDK_CapWBColorTemp = self._func(
            "XSDK_CapWBColorTemp", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetWBColorTemp = self._func(
            "XSDK_SetWBColorTemp", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetWBColorTemp = self._func(
            "XSDK_GetWBColorTemp", [c_void_p, c_long_p]
        )

        # --- Media record ---
        self.XSDK_CapMediaRecord = self._func(
            "XSDK_CapMediaRecord", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetMediaRecord = self._func(
            "XSDK_SetMediaRecord", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetMediaRecord = self._func(
            "XSDK_GetMediaRecord", [c_void_p, c_long_p]
        )

        # --- Force mode ---
        self.XSDK_CapForceMode = self._func(
            "XSDK_CapForceMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetForceMode = self._func(
            "XSDK_SetForceMode", [c_void_p, ctypes.c_long]
        )

        # --- Drive mode ---
        self.XSDK_CapDriveMode = self._func(
            "XSDK_CapDriveMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetDriveMode = self._func(
            "XSDK_SetDriveMode", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetDriveMode = self._func(
            "XSDK_GetDriveMode", [c_void_p, c_long_p]
        )

        # --- Mode ---
        self.XSDK_CapMode = self._func(
            "XSDK_CapMode", [c_void_p, c_long_p, c_long_p]
        )
        self.XSDK_SetMode = self._func(
            "XSDK_SetMode", [c_void_p, ctypes.c_long]
        )
        self.XSDK_GetMode = self._func(
            "XSDK_GetMode", [c_void_p, c_long_p]
        )

        # --- Backup settings ---
        self.XSDK_SetBackupSettings = self._func(
            "XSDK_SetBackupSettings", [c_void_p, ctypes.c_long, c_ubyte_p]
        )
        self.XSDK_GetBackupSettings = self._func(
            "XSDK_GetBackupSettings", [c_void_p, c_long_p, c_ubyte_p]
        )

        # --- Model-dependent (variadic) ---
        #     XSDK_GetProp(XSDK_HANDLE hCamera, long lAPICode, long lAPIParam, ...)
        #
        # argtypes covers the three fixed parameters and stops there.  Leaving
        # it unset - which this did, on the belief that ctypes then works it out
        # - is wrong on arm64 macOS, where a variadic argument is passed
        # differently from a fixed one: fixed arguments go in registers,
        # variadic arguments go on the stack.  With no argtypes ctypes passes
        # everything as fixed, so the callee looks on the stack and finds
        # whatever was there.
        #
        # That is why almost every property call on this Mac answered 0x1002
        # "Invalid parameter" - the focus mode, the image quality, the live view
        # size and quality - while the dedicated non-variadic entry points like
        # XSDK_SetShutterSpeed worked perfectly.  A garbage pointer read back
        # through GetProp is also a segmentation fault waiting to happen.
        fixed = [c_void_p, ctypes.c_long, ctypes.c_long]

        self.XSDK_CapProp = self._func("XSDK_CapProp", fixed)
        self.XSDK_SetProp = self._func("XSDK_SetProp", fixed)
        self.XSDK_GetProp = self._func("XSDK_GetProp", fixed)
