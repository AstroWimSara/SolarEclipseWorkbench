"""Fujifilm X Series Shooting SDK Python bindings.

Usage:
    from fujixsdk import Camera, EclipseShooter, SHUTTER_1_8000, ISO_100

    cameras = Camera.detect("/path/to/sdk/libs")
    with Camera("/path/to/sdk/libs", cameras[0].device_name) as cam:
        cam.set_shutter_speed(SHUTTER_1_8000)
        cam.set_iso(ISO_100)
        cam.shoot()
"""

from .camera import Camera, CameraInfo
from .eclipse import (
    CameraIssue,
    EclipseShooter,
    LiveViewStream,
    validate_for_eclipse,
)
from ._constants import *  # noqa: F401,F403
from ._errors import LDPathError, XSDKError
from ._library import ensure_ld_library_path

__all__ = [
    "Camera",
    "CameraInfo",
    "CameraIssue",
    "EclipseShooter",
    "LiveViewStream",
    "LDPathError",
    "XSDKError",
    "ensure_ld_library_path",
    "validate_for_eclipse",
]
