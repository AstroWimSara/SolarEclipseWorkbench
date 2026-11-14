"""Where sew keeps its astronomical data files.

The JPL ephemerides (de421.bsp, de440s.bsp), the lunar orientation kernels and
the lunar limb profile used to be looked up in the current directory, which is
skyfield's default.  Started from another directory while offline, sew then
had no ephemeris and could not compute any contact times.

All of them now live in the user's data directory, ~/.SolarEclipseWorkbench,
which is also where skyfield downloads them to when they are missing.  Files
shipped in the package are used where they are; files found in a source
checkout or in the current directory are copied into the data directory, so
the next start works from anywhere.
"""

import logging
import shutil
from pathlib import Path

from skyfield.iokit import Loader
from skyfield.jpllib import SpiceKernel

USER_DATA_DIRECTORY = Path.home() / ".SolarEclipseWorkbench"
PACKAGE_DIRECTORY = Path(__file__).resolve().parent
# The repository root when running from a source checkout (src/solareclipseworkbench/..).
CHECKOUT_DIRECTORY = PACKAGE_DIRECTORY.parents[1]

_loader = None


def loader() -> Loader:
    """A skyfield loader that downloads into the user's data directory."""
    global _loader
    if _loader is None or Path(_loader.directory) != USER_DATA_DIRECTORY:
        _loader = Loader(str(USER_DATA_DIRECTORY), verbose=False)
    return _loader


def find_data_file(name: str):
    """The path of an installed data file, or None when it is nowhere to be found.

    The user's data directory and the package are looked in first.  A file
    found only in a source checkout or in the current directory (where older
    versions of sew expected it) is copied into the user's data directory, so
    the next start finds it there from any directory.

    Args:
        - name: File name, e.g. "de421.bsp".
    """
    for directory in (USER_DATA_DIRECTORY, PACKAGE_DIRECTORY):
        candidate = directory / name
        if candidate.is_file():
            return candidate

    for directory in (CHECKOUT_DIRECTORY, CHECKOUT_DIRECTORY / "data", Path.cwd()):
        candidate = directory / name
        if candidate.is_file():
            return _copy_to_user_data(candidate)
    return None


def _copy_to_user_data(source: Path) -> Path:
    """Copy a data file into the user's data directory; the copy, or the source when copying fails."""
    target = USER_DATA_DIRECTORY / source.name
    partial = target.with_name(target.name + ".part")
    try:
        USER_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, partial)
        partial.replace(target)
    except OSError as exc:
        logging.warning("Could not copy %s to %s: %s", source, USER_DATA_DIRECTORY, exc)
        partial.unlink(missing_ok=True)
        return source
    logging.info("Copied %s from %s to %s", source.name, source.parent, USER_DATA_DIRECTORY)
    return target


def data_path(name: str) -> Path:
    """Where a data file is, or where it will be downloaded to when it is not installed."""
    return find_data_file(name) or USER_DATA_DIRECTORY / name


def load_ephemeris(name: str = "de421.bsp") -> SpiceKernel:
    """Open a JPL ephemeris, downloading it into the user's data directory when it is missing.

    Args:
        - name: Ephemeris file name, e.g. "de421.bsp" or "de440s.bsp".

    Raises: OSError when the file is not installed and cannot be downloaded.
    """
    path = find_data_file(name)
    if path is not None:
        return SpiceKernel(str(path))
    logging.info("Downloading %s to %s", name, USER_DATA_DIRECTORY)
    return loader()(name)


def open_kernel(name: str):
    """An open binary handle on a SPICE text/binary kernel (.tf, .bpc), downloaded when missing."""
    path = find_data_file(name)
    if path is not None:
        return open(path, "rb")
    logging.info("Downloading %s to %s", name, USER_DATA_DIRECTORY)
    return loader()(name)


def timescale():
    """The skyfield timescale, from skyfield's built-in data (no download needed)."""
    return loader().timescale(builtin=True)
