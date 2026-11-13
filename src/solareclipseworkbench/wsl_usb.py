"""Attach USB cameras and GPS receivers to WSL from inside Solar Eclipse Workbench.

Under WSL, USB devices belong to Windows until ``usbipd-win`` attaches them to
the Linux side, and that attachment is lost every time a device is unplugged,
switched off or the computer sleeps.  Before this module, users had to open a
PowerShell window and type ``usbipd attach --wsl --busid <id>`` for every
camera, every time.

A device only has to be *shared* (``usbipd bind``) once, which needs
administrator rights; ``scripts/windows/install-sew.ps1`` does that.  Attaching
a shared device does not need administrator rights (usbipd-win 4.0 and later),
and WSL can run Windows programs, so the application attaches every shared,
not-yet-attached device itself before it looks for cameras or a GPS receiver.

Everything here is a no-op outside WSL or when usbipd-win is not installed, and
nothing raises: a failed attach is logged and reported to the user, and camera
detection carries on with whatever is already attached.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Where the usbipd-win installer puts the executable, seen from WSL.  Used when
# the Windows PATH is not appended to the WSL PATH (``appendWindowsPath=false``).
_USBIPD_FALLBACK_PATHS = (
    "/mnt/c/Program Files/usbipd-win/usbipd.exe",
)

# ``usbipd state`` and ``attach`` normally take well under a second; the
# timeouts only stop a hung Windows process from blocking camera detection.
_STATE_TIMEOUT_S = 10
_ATTACH_TIMEOUT_S = 20

# After an attach, the Linux kernel needs a moment to enumerate the device
# before gphoto2 or pyserial can see it.
_SETTLE_TIME_S = 2.0

_lock = threading.Lock()


@dataclass
class UsbDevice:
    """One USB device as usbipd-win reports it."""

    busid: str
    description: str
    shared: bool      # bound with ``usbipd bind`` (persisted)
    attached: bool    # currently attached to a WSL distribution


def is_wsl() -> bool:
    """Return True when running inside a WSL distribution."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/sys/kernel/osrelease", encoding="ascii", errors="ignore") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def find_usbipd() -> Optional[str]:
    """Return the path to ``usbipd.exe`` as seen from WSL, or None."""
    path = shutil.which("usbipd.exe")
    if path:
        return path
    for candidate in _USBIPD_FALLBACK_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def parse_state(output: str) -> list:
    """Parse the JSON printed by ``usbipd state`` into :class:`UsbDevice` objects.

    Only devices that are plugged in (have a bus id) are returned.  A device is
    shared when it has a persisted GUID and attached when it has a client IP
    address.
    """
    data = json.loads(output)
    devices = []
    for entry in data.get("Devices", []):
        busid = entry.get("BusId")
        if not busid:
            continue  # shared, but not plugged in at the moment
        devices.append(UsbDevice(
            busid=busid,
            description=entry.get("Description") or "",
            shared=bool(entry.get("PersistedGuid")),
            attached=bool(entry.get("ClientIPAddress")),
        ))
    return devices


def list_devices(usbipd: Optional[str] = None) -> list:
    """Return the USB devices known to usbipd-win, or an empty list on failure."""
    usbipd = usbipd or find_usbipd()
    if not usbipd:
        return []
    try:
        result = subprocess.run(
            [usbipd, "state"], capture_output=True, text=True, errors="replace", timeout=_STATE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not run usbipd state: %s", e)
        return []
    if result.returncode != 0:
        logger.warning("usbipd state failed (exit code %d): %s",
                       result.returncode, (result.stderr or result.stdout).strip())
        return []
    try:
        return parse_state(result.stdout)
    except (ValueError, AttributeError) as e:
        logger.warning("Could not read the output of usbipd state: %s", e)
        return []


def attach(device: UsbDevice, usbipd: Optional[str] = None) -> bool:
    """Attach one shared device to this WSL distribution.  Return True on success."""
    usbipd = usbipd or find_usbipd()
    if not usbipd:
        return False
    try:
        result = subprocess.run(
            [usbipd, "attach", "--wsl", "--busid", device.busid],
            capture_output=True, text=True, errors="replace", timeout=_ATTACH_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _report_failure(device, str(e))
        return False
    if result.returncode != 0:
        _report_failure(device, (result.stderr or result.stdout).strip())
        return False
    logger.info("Attached USB device %s (%s) to WSL", device.busid, device.description)
    return True


def _report_failure(device: UsbDevice, detail: str) -> None:
    logger.warning("Could not attach USB device %s (%s) to WSL: %s",
                   device.busid, device.description, detail)
    try:
        from solareclipseworkbench import hardware_problems
        hardware_problems.report(
            "WSL USB",
            f"Could not attach {device.description or device.busid} to WSL",
            detail=detail,
            severity="warning",
        )
    except Exception:  # never let reporting break camera detection
        logger.debug("Could not report the attach failure", exc_info=True)


def missing_device_hint() -> Optional[str]:
    """Explain why WSL may not see a camera, or return None when there is nothing to add.

    Meant for when camera detection found nothing: under WSL the usual cause is
    not the camera but that usbipd-win is missing or the camera was never shared.
    """
    if not is_wsl():
        return None
    usbipd = find_usbipd()
    if not usbipd:
        return ("Under WSL, cameras reach Linux through usbipd-win, which is not installed. "
                "Run scripts/windows/install-sew.ps1 on Windows, or see the README.")
    if not any(d.shared for d in list_devices(usbipd)):
        return ("No USB device is shared with WSL. Connect the camera, switch it on and run "
                "'Share cameras with Solar Eclipse Workbench' from the Windows Start menu "
                "(once per camera).")
    return None


def attach_shared_devices(settle: bool = True) -> list:
    """Attach every shared USB device that is plugged in but not attached to WSL.

    Returns the devices that were attached.  Does nothing (and returns an empty
    list) outside WSL, without usbipd-win, or when everything is attached
    already, so it is cheap to call before every camera or GPS detection.
    When *settle* is True and something was attached, waits briefly so the
    device is visible to Linux before returning.
    """
    if not is_wsl():
        return []
    usbipd = find_usbipd()
    if not usbipd:
        logger.debug("WSL without usbipd-win: USB devices cannot be attached automatically")
        return []

    with _lock:  # the GUI and the wizard may detect cameras from several threads
        pending = [d for d in list_devices(usbipd) if d.shared and not d.attached]
        attached = [d for d in pending if attach(d, usbipd)]
        if attached and settle:
            time.sleep(_SETTLE_TIME_S)
    return attached
