"""Start the INDI server for the mount, so it does not have to be started by hand.

INDI lists the drivers it has installed in XML files (``drivers.xml`` for the
drivers of INDI itself, one file per package of third-party drivers, all in the
same folder).  ``mount_drivers()`` reads the telescope mounts from them, so the
user can pick the model of the mount once; ``IndiServer`` then starts
``indiserver`` with that driver whenever the mount is connected.

Which mount is connected cannot be found out reliably: most mounts are behind a
USB-serial chip that any other device can have as well, and a mount on Wi-Fi is
not on USB at all.  That is why the model is picked, not detected.

When an INDI server already runs on the port (started by hand, by KStars, on a
Raspberry Pi image), it is used and left alone.  A server started here is
stopped when the mount is disconnected; the mount keeps tracking, as its own
controller does that.
"""

import atexit
import datetime
import logging
import weakref
import os
import re
import shutil
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from solareclipseworkbench.indi_client import DEFAULT_PORT

logger = logging.getLogger(__name__)

#: Where INDI keeps its driver lists, by platform
DRIVER_FOLDERS = [
    Path("/usr/share/indi"),
    Path("/usr/local/share/indi"),
    Path("/opt/homebrew/share/indi"),
    Path("/Applications/KStars.app/Contents/Resources/DriverSupport"),
]

#: Where indiserver may be when it is not on the PATH (the KStars app on macOS)
SERVER_PATHS = [Path("/Applications/KStars.app/Contents/MacOS/indi/indiserver"),
                Path("/Applications/KStars.app/Contents/MacOS/indiserver")]

#: How long to wait for a server that was started to accept connections
START_TIMEOUT_S = 10.0


class IndiServerError(Exception):
    """INDI is not installed, the driver is missing, or the server would not start."""


@dataclass(frozen=True)
class MountDriver:
    """A telescope mount as INDI lists it."""
    manufacturer: str
    model: str
    #: The executable of the driver, e.g. indi_ioptronv3_telescope
    executable: str
    #: The name INDI gives the driver, e.g. iOptronV3
    name: str = ""

    @property
    def label(self) -> str:
        if self.manufacturer and self.manufacturer.lower() not in self.model.lower():
            return f"{self.manufacturer} {self.model}"
        return self.model

    @property
    def network(self) -> bool:
        """Whether INDI lists this model as a mount on Wi-Fi (e.g. "AZ-GTi Alt-Az WiFi")."""
        return re.search(r"\bwi-?fi\b|\bwlan\b", self.label, re.IGNORECASE) is not None

    def installed(self) -> bool:
        return find_executable(self.executable) is not None


def driver_folders() -> List[Path]:
    """The folders with INDI driver lists on this computer (INDIPREFIX first, when set)."""
    folders = []
    prefix = os.environ.get("INDIPREFIX")
    if prefix:
        folders.append(Path(prefix) / "share" / "indi")
    folders.extend(DRIVER_FOLDERS)
    return [folder for folder in folders if (folder / "drivers.xml").exists()]


def parse_drivers(path: Path) -> List[MountDriver]:
    """The telescope mounts in one INDI driver list."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        logger.debug("INDI driver list %s not read: %s", path, exc)
        return []
    mounts = []
    for group in root.iter("devGroup"):
        if group.get("group", "").strip().lower() != "telescopes":
            continue
        for device in group.iter("device"):
            driver = device.find("driver")
            if driver is None or not (driver.text or "").strip():
                continue
            mounts.append(MountDriver(manufacturer=(device.get("manufacturer") or "").strip(),
                                      model=(device.get("label") or "").strip(),
                                      executable=driver.text.strip(),
                                      name=(driver.get("name") or "").strip()))
    return mounts


def mount_drivers(folders: Optional[List[Path]] = None) -> List[MountDriver]:
    """Every telescope mount in the INDI driver lists, sorted by label, each once."""
    seen, mounts = set(), []
    for folder in (folders if folders is not None else driver_folders()):
        for path in sorted(Path(folder).glob("*.xml")):
            for mount in parse_drivers(path):
                key = (mount.label.lower(), mount.executable)
                if key not in seen:
                    seen.add(key)
                    mounts.append(mount)
    return sorted(mounts, key=lambda m: m.label.lower())


def find_executable(name: str) -> Optional[str]:
    path = shutil.which(name)
    if path:
        return path
    for folder in {p.parent for p in SERVER_PATHS}:
        candidate = folder / name
        if candidate.exists():
            return str(candidate)
    return None


def find_server() -> Optional[str]:
    """The indiserver executable, or None when INDI is not installed."""
    return find_executable("indiserver")


_LOCAL_SOCKET_OPTION: dict = {}


def supports_local_socket(server: str) -> bool:
    """Whether this indiserver takes -u (the path of its local socket; INDI 1.9 and later)."""
    if server not in _LOCAL_SOCKET_OPTION:
        try:
            result = subprocess.run([server, "--help"], capture_output=True, text=True, timeout=5)
            _LOCAL_SOCKET_OPTION[server] = "-u path" in (result.stdout + result.stderr)
        except (OSError, subprocess.SubprocessError):
            _LOCAL_SOCKET_OPTION[server] = False
    return _LOCAL_SOCKET_OPTION[server]


def server_running(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> bool:
    """Whether something accepts connections on the port (an INDI server, normally)."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


#: The servers started here, stopped when the program ends (also when it ends on an error):
#: started in a session of their own, they would otherwise outlive it
_STARTED: "weakref.WeakSet" = weakref.WeakSet()


@atexit.register
def _stop_started_servers() -> None:
    for server in list(_STARTED):
        try:
            server.stop()
        except Exception:
            pass


class IndiServer:
    """An indiserver with one mount driver, started by Solar Eclipse Workbench.

    Args:
        - driver: The executable of the driver (MountDriver.executable)
        - port: TCP port of the server
        - server: The indiserver executable; found on the PATH when not given
        - log_dir: Where the output of the server goes (a file per start)
    """

    def __init__(self, driver: str, port: int = DEFAULT_PORT, server: Optional[str] = None,
                 log_dir: Optional[Path] = None):
        self.driver = driver
        self.port = int(port)
        self.server = server
        self.log_dir = log_dir
        self.log_path: Optional[Path] = None
        self._process: Optional[subprocess.Popen] = None
        #: Whether the server was already running (and is left alone)
        self.borrowed = False

    @property
    def owned(self) -> bool:
        """Whether this started the server (and will stop it)."""
        return self._process is not None

    @property
    def running(self) -> bool:
        if self._process is not None:
            return self._process.poll() is None
        return self.borrowed and server_running(self.port)

    def describe(self) -> str:
        if self.borrowed:
            return f"the INDI server that already runs on port {self.port}"
        return f"indiserver with {self.driver} on port {self.port}"

    def start(self) -> None:
        """Start the server, or use the one that already runs on the port."""
        if self.running:
            return
        if server_running(self.port):
            self.borrowed = True
            logger.info("An INDI server already runs on port %d: using it", self.port)
            return
        server = self.server or find_server()
        if server is None:
            raise IndiServerError("INDI is not installed: install it (on Ubuntu and in WSL: "
                                  "sudo apt install indi-bin), or start the INDI server yourself")
        driver_path = self.driver if os.path.sep in self.driver else find_executable(self.driver)
        if driver_path is None:
            raise IndiServerError(f"the INDI driver {self.driver} is not installed: it may be in another package "
                                  f"(on Ubuntu: the indi-full package of the INDI PPA, or a package of "
                                  f"third-party drivers)")
        log_dir = self.log_dir or Path.home() / ".SolarEclipseWorkbench" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.log_path = log_dir / f"indiserver-{stamp}Z.log"
        log = open(self.log_path, "w")
        command = [server, "-v", "-p", str(self.port)]
        if supports_local_socket(server):
            # Besides its port, indiserver listens on a local socket, by default the same for every
            # server: a second server (of another program, on another port) would not start
            command += ["-u", f"/tmp/indiserver-sew-{self.port}"]
        command.append(driver_path)
        logger.info("Starting the INDI server: %s (output in %s)", " ".join(command), self.log_path)
        try:
            self._process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            log.close()
            raise IndiServerError(f"indiserver could not be started: {exc}") from exc
        finally:
            log.close()         # the process has its own copy
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                tail = self.log_tail()
                self._process = None
                raise IndiServerError(f"indiserver stopped at once{': ' + tail if tail else ''}")
            if server_running(self.port):
                _STARTED.add(self)
                return
            time.sleep(0.1)
        self.stop()
        raise IndiServerError(f"indiserver did not accept connections on port {self.port} within "
                              f"{START_TIMEOUT_S:.0f} s")

    def stop(self) -> None:
        """Stop the server if it was started here.  The mount keeps tracking on its own controller."""
        process, self._process = self._process, None
        self.borrowed = False
        if process is None or process.poll() is not None:
            return
        logger.info("Stopping the INDI server")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def log_tail(self, lines: int = 5) -> str:
        """The last lines the server wrote, for an error message."""
        if self.log_path is None or not self.log_path.exists():
            return ""
        text = self.log_path.read_text(errors="replace").strip().splitlines()
        return " / ".join(text[-lines:])
