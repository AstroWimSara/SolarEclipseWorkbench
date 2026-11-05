"""ctypes Structure classes matching Fujifilm X SDK C structs.

All structures use _pack_ = 1 to match the SDK's #pragma pack(1), with the
MSVC layout that ctypes has always used for a packed structure.  Python 3.14
asks for that layout to be stated, as _layout_.
"""

import ctypes
import sys

# XSDK_HANDLE is void* on Linux/macOS, HANDLE on Windows
XSDK_HANDLE = ctypes.c_void_p

# LIB_HANDLE is void* on Linux, CFBundleRef on macOS, HINSTANCE on Windows
LIB_HANDLE = ctypes.c_void_p


class CameraList(ctypes.Structure):
    """XSDK_CameraList — camera detection result entry."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("strProduct", ctypes.c_char * 256),
        ("strSerialNo", ctypes.c_char * 256),
        ("strIPAddress", ctypes.c_char * 256),
        ("strFramework", ctypes.c_char * 256),
        ("bValid", ctypes.c_bool),
    ]

    @property
    def product(self) -> str:
        return self.strProduct.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def serial_no(self) -> str:
        return self.strSerialNo.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def ip_address(self) -> str:
        return self.strIPAddress.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def framework(self) -> str:
        return self.strFramework.decode("utf-8", errors="replace").rstrip("\x00")


class DeviceInformation(ctypes.Structure):
    """XSDK_DeviceInformation — detailed device info after connection."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("strVendor", ctypes.c_char * 256),
        ("strManufacturer", ctypes.c_char * 256),
        ("strProduct", ctypes.c_char * 256),
        ("strFirmware", ctypes.c_char * 256),
        ("strDeviceType", ctypes.c_char * 256),
        ("strSerialNo", ctypes.c_char * 256),
        ("strFramework", ctypes.c_char * 256),
        ("bDeviceId", ctypes.c_uint8),
        ("strDeviceName", ctypes.c_char * 32),
        ("strYNo", ctypes.c_char * 32),
    ]

    def _decode(self, field: str) -> str:
        return getattr(self, field).decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def vendor(self) -> str:
        return self._decode("strVendor")

    @property
    def manufacturer(self) -> str:
        return self._decode("strManufacturer")

    @property
    def product(self) -> str:
        return self._decode("strProduct")

    @property
    def firmware(self) -> str:
        return self._decode("strFirmware")

    @property
    def device_type(self) -> str:
        return self._decode("strDeviceType")

    @property
    def serial_no(self) -> str:
        return self._decode("strSerialNo")

    @property
    def framework(self) -> str:
        return self._decode("strFramework")

    @property
    def device_name(self) -> str:
        return self._decode("strDeviceName")


class DataInt(ctypes.Structure):
    """XSDK_DATA_INT — 10-long integer data block."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("n1", ctypes.c_long),
        ("n2", ctypes.c_long),
        ("n3", ctypes.c_long),
        ("n4", ctypes.c_long),
        ("n5", ctypes.c_long),
        ("n6", ctypes.c_long),
        ("n7", ctypes.c_long),
        ("n8", ctypes.c_long),
        ("n9", ctypes.c_long),
        ("n10", ctypes.c_long),
    ]


class Data(ctypes.Union):
    """XSDK_DATA — union of integer data or 40-byte char buffer."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("n", DataInt),
        ("c", ctypes.c_char * 40),
    ]


class Property(ctypes.Structure):
    """XSDK_PROPERTY — single property entry (apiCode + data)."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("apiCode", ctypes.c_long),
        ("data", Data),
    ]


class ChangedProperty(ctypes.Structure):
    """XSDK_CHANGEDPROPERTY — batch of up to 200 changed properties."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("propCnt", ctypes.c_ushort),
        ("prop", Property * 200),
    ]


class ImageInformation(ctypes.Structure):
    """XSDK_ImageInformation — metadata for a captured image."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("strInternalName", ctypes.c_char * 32),
        ("lFormat", ctypes.c_long),
        ("lDataSize", ctypes.c_long),
        ("lImagePixHeight", ctypes.c_long),
        ("lImagePixWidth", ctypes.c_long),
        ("lImageBitDepth", ctypes.c_long),
        ("lPreviewSize", ctypes.c_long),
        ("hImage", XSDK_HANDLE),
    ]

    @property
    def internal_name(self) -> str:
        return self.strInternalName.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def format(self) -> int:
        return self.lFormat

    @property
    def data_size(self) -> int:
        return self.lDataSize

    @property
    def width(self) -> int:
        return self.lImagePixWidth

    @property
    def height(self) -> int:
        return self.lImagePixHeight

    @property
    def bit_depth(self) -> int:
        return self.lImageBitDepth

    @property
    def preview_size(self) -> int:
        return self.lPreviewSize


class LensInformation(ctypes.Structure):
    """XSDK_LensInformation — lens metadata."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("strModel", ctypes.c_char * 20),
        ("strProductName", ctypes.c_char * 100),
        ("strSerialNo", ctypes.c_char * 20),
        ("lISCapability", ctypes.c_long),
        ("lMFCapability", ctypes.c_long),
        ("lZoomPosCapability", ctypes.c_long),
    ]

    @property
    def model(self) -> str:
        return self.strModel.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def product_name(self) -> str:
        return self.strProductName.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def serial_no(self) -> str:
        return self.strSerialNo.decode("utf-8", errors="replace").rstrip("\x00")

    @property
    def has_is(self) -> bool:
        return bool(self.lISCapability)

    @property
    def has_mf(self) -> bool:
        return bool(self.lMFCapability)

    @property
    def has_zoom(self) -> bool:
        return bool(self.lZoomPosCapability)


class FocusArea(ctypes.Structure):
    """SDK_FocusArea — focus area position and size."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("h", ctypes.c_long),
        ("v", ctypes.c_long),
        ("size", ctypes.c_long),
    ]


class ISOAuto(ctypes.Structure):
    """SDK_ISOAuto — ISO auto setting parameters."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("defaultISO", ctypes.c_long),
        ("maxISO", ctypes.c_long),
        ("minShutterSpeed", ctypes.c_long),
        ("pName", ctypes.c_char * 32),
    ]


class FocusPosCap(ctypes.Structure):
    """SDK_FOCUS_POS_CAP — focus position capabilities."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("lSizeFocusPosCap", ctypes.c_long),
        ("lStructVer", ctypes.c_long),
        ("lFocusPlsINF", ctypes.c_long),
        ("lFocusPlsMOD", ctypes.c_long),
        ("lFocusOverSearchPlsINF", ctypes.c_long),
        ("lFocusOverSearchPlsMOD", ctypes.c_long),
        ("lFocusPlsFCSDepthCap", ctypes.c_long),
        ("lMinDriveStepMFDriveEndThresh", ctypes.c_long),
    ]


class FrameGuideGridInfo(ctypes.Structure):
    """SDK_FrameGuideGridInfo — frame guide grid configuration."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("lGridH", ctypes.c_long * 5),
        ("lGridV", ctypes.c_long * 5),
        ("lLineWidthH", ctypes.c_long),
        ("lLineWidthV", ctypes.c_long),
        ("lLineColorIndex", ctypes.c_long),
        ("lLineAlpha", ctypes.c_long),
    ]
