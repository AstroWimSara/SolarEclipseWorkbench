"""Log files that survive the eclipse.

Every run writes to its own file, named after the moment it started, in a
directory that is not cleared on reboot.  A log is never overwritten or deleted
by the application, so the log of an eclipse is still there when you look for it
afterwards, however often the application was restarted in the meantime.

Timestamps are in UTC with milliseconds, the same time base as the contact
times and the scheduled commands, so the log can be lined up directly with the
script and with the EXIF times of the pictures.
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
_CONSOLE_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Libraries that are chatty at DEBUG level without saying anything useful about
# the eclipse.  Their warnings and errors are still logged.
_QUIET_LOGGERS = ("matplotlib", "PIL", "urllib3", "asyncio", "apscheduler.scheduler",
                  "geopandas", "fiona", "pyogrio", "shapely")

_log_path: Optional[Path] = None


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
                  console_level: int = logging.INFO) -> Path:
    """Send all logging to a new file for this run, and INFO and above to the console.

    Safe to call more than once: later calls return the file of the first one.

    Args:
        - prefix: Start of the log file name (e.g. "sew", "sew_wizard")
        - log_dir: Directory for the log files.  Defaults to ~/.SolarEclipseWorkbench/logs, falling back to the
                   temporary directory when that cannot be written.
        - console_level: Level from which messages are also printed to the terminal

    Returns: Path of the log file.
    """
    global _log_path
    if _log_path is not None:
        return _log_path

    directory = log_dir if log_dir is not None else LOG_DIR
    try:
        file_handler = _open_new_log_file(directory, prefix)
    except OSError:
        file_handler = _open_new_log_file(Path(tempfile.gettempdir()) / "SolarEclipseWorkbench", prefix)

    file_formatter = logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT)
    file_formatter.converter = time.gmtime
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    console_handler.setLevel(console_level)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)

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


def file_handlers_only(handlers: list) -> list:
    """The handlers that write to a log file.

    Code that silences the console while a noisy library runs should keep these:
    removing every handler would also drop whatever the camera and scheduler
    threads log in the meantime.
    """
    return [h for h in handlers if isinstance(h, logging.FileHandler)]
