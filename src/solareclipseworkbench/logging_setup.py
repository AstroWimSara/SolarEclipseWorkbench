"""Log files that survive the eclipse.

Every run writes to its own file, named after the moment it started, in a
directory that is not cleared on reboot.  A log is never overwritten or deleted
by the application, so the log of an eclipse is still there when you look for it
afterwards, however often the application was restarted in the meantime.

Timestamps are ISO 8601 in UTC with milliseconds (2026-08-12T17:46:38.123Z),
in the log file and on the console, the same time base as the contact times and
the scheduled commands, so the log can be lined up directly with the script and
with the EXIF times of the pictures.
"""

import logging
import platform
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

LOG_DIR = Path.home() / ".SolarEclipseWorkbench" / "logs"

_FILE_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)s %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Libraries that are chatty at DEBUG level without saying anything useful about
# the eclipse.  Their warnings and errors are still logged.
_QUIET_LOGGERS = ("matplotlib", "PIL", "urllib3", "asyncio", "apscheduler.scheduler",
                  "geopandas", "fiona", "pyogrio", "shapely")

_log_path: Optional[Path] = None
# Set when no log file could be created anywhere, so a second call does not add the handlers again
_configured_without_file = False


def _open_new_log_file(directory: Path, prefix: str) -> logging.FileHandler:
    """Create a handler on a log file that did not exist before."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    for attempt in range(100):
        suffix = "" if attempt == 0 else f"-{attempt}"
        path = directory / f"{prefix}-{stamp}Z{suffix}.log"
        try:
            # Mode "x" fails if the file exists: an existing log is never overwritten.
            return logging.FileHandler(path, mode="x", encoding="utf-8")
        except FileExistsError:
            continue
    raise FileExistsError(f"could not create a new log file in {directory}")


def setup_logging(prefix: str = "sew", log_dir: Optional[Path] = None,
                  console_level: int = logging.INFO) -> Optional[Path]:
    """Send all logging to a new file for this run, and INFO and above to the console.

    Safe to call more than once: later calls return the file of the first one.

    Args:
        - prefix: Start of the log file name (e.g. "sew", "sew_wizard")
        - log_dir: Directory for the log files.  Defaults to ~/.SolarEclipseWorkbench/logs, falling back to the
                   temporary directory when that cannot be written.
        - console_level: Level from which messages are also printed to the terminal

    Returns: Path of the log file, None when no log file could be created (logging goes to the console only).
    """
    global _log_path, _configured_without_file
    if _log_path is not None or _configured_without_file:
        return _log_path

    directory = log_dir if log_dir is not None else LOG_DIR
    try:
        file_handler = _open_new_log_file(directory, prefix)
    except OSError:
        try:
            file_handler = _open_new_log_file(Path(tempfile.gettempdir()) / "SolarEclipseWorkbench", prefix)
        except OSError as exc:
            # A full or read-only disk must not stop the application: log to the console only
            file_handler = None
            print(f"WARNING: no log file could be created ({exc}); logging to the console only", file=sys.stderr)

    if file_handler is not None:
        file_formatter = logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT)
        file_formatter.converter = time.gmtime
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT)
    console_formatter.converter = time.gmtime
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(console_level)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if file_handler is not None:
        root.addHandler(file_handler)
    root.addHandler(console_handler)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)

    if file_handler is None:
        _configured_without_file = True
        return None
    _log_path = Path(file_handler.baseFilename)
    logging.info("Logging to %s (timestamps in UTC)", _log_path)
    logging.info("Python %s on %s; command line: %s",
                 platform.python_version(), platform.platform(), " ".join(sys.argv))
    try:
        from importlib.metadata import version
        logging.info("Solar Eclipse Workbench %s", version("solareclipseworkbench"))
    except Exception:
        pass
    return _log_path


def get_log_path() -> Optional[Path]:
    """Path of this run's log file, or None if setup_logging has not been called."""
    return _log_path


class _CameraLogAdapter(logging.LoggerAdapter):
    """Puts "<camera name>: " in front of every message."""

    def log(self, level, msg, *args, **kwargs):
        name = self.extra["camera"]
        if args:
            # The prefix goes through %-formatting with the message: a "%" in the name must not act as a placeholder.
            name = name.replace("%", "%%")
        self.logger.log(level, f"{name}: {msg}", *args, **kwargs)


def camera_log(camera) -> logging.LoggerAdapter:
    """Logger whose messages all start with the name of the given camera.

    With more than one camera connected, a message without the camera's name
    cannot be traced back to a body.  Log through this instead of through
    `logging` directly for everything that concerns one camera:

        log = camera_log(camera)
        log.debug("set aperture to %s", aperture)   # -> "Sun Wide: set aperture to f/8"

    Args:
        - camera: Camera object (its `name` is used, which is the alias when one is configured), or a camera name

    Returns: Logger adapter on the root logger.
    """
    name = camera if isinstance(camera, str) else getattr(camera, "name", None) or str(camera)
    return _CameraLogAdapter(logging.getLogger(), {"camera": name})


def file_handlers_only(handlers: list) -> list:
    """The handlers that write to a log file.

    Code that silences the console while a noisy library runs should keep these:
    removing every handler would also drop whatever the camera and scheduler
    threads log in the meantime.  A handler with a true `keep_when_quiet`
    attribute (the Error Log dock) is kept too.
    """
    return [h for h in handlers
            if isinstance(h, logging.FileHandler) or getattr(h, "keep_when_quiet", False)]
