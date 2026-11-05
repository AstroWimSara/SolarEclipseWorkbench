"""Mount driver registry.

Drivers are discovered from two places:

    - modules shipped inside this package, imported on first use
    - the ``solareclipseworkbench.mount_drivers`` entry point group, so a driver
      can live in its own installable package without being vendored here

Writing a driver:

    from solareclipseworkbench.mounts import MountDriver, register_driver

    @register_driver
    class MyMount(MountDriver):
        name = "mymount"
        display_name = "My Mount"
        def connect(self): ...
        def close(self): ...
        def describe(self): ...
        def status(self): ...
        def get_radec(self): ...
        def goto(self, ra_hours, dec_degrees, wait=False, timeout=180.0): ...
        def abort(self): ...
        def tracking_on(self): ...
        def tracking_off(self): ...

A driver does not have to implement everything.  For a feature that the mount
does not have, the base class raises :class:`MountNotSupported`.
:attr:`MountDriver.capabilities` tells callers in advance which features are
available.
"""

import logging
import pkgutil
from importlib import import_module
from importlib.metadata import entry_points
from typing import Optional

from solareclipseworkbench.mounts.base import (
    Candidate,
    Capabilities,
    MountDriver,
    MountError,
    MountNotSupported,
    MountStatus,
    format_dec,
    format_ra,
    parse_dec,
    parse_ra,
    sun_radec,
)

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "solareclipseworkbench.mount_drivers"

_registry: dict = {}
_discovered = False


def register_driver(driver_class):
    """Register a driver class.  Usable as a decorator."""
    if not issubclass(driver_class, MountDriver):
        raise TypeError(f"{driver_class!r} is not a MountDriver")
    if not driver_class.name:
        raise ValueError(f"{driver_class!r} must set a 'name'")
    if driver_class.name in _registry and _registry[driver_class.name] is not driver_class:
        logger.warning("Mount driver %r is being replaced by %r", driver_class.name, driver_class)
    _registry[driver_class.name] = driver_class
    logger.debug("Registered mount driver: %s", driver_class.name)
    return driver_class


def _discover_builtin() -> None:
    """Import every module in this package so its drivers self-register."""
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_") or module.name == "base":
            continue
        try:
            import_module(f"{__name__}.{module.name}")
        except Exception:
            # A driver whose optional dependency is missing must not stop the
            # others from loading.
            logger.warning("Could not load built-in mount driver %r", module.name, exc_info=True)


def _discover_plugins() -> None:
    """Load drivers published by other installed packages."""
    try:
        points = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Older importlib.metadata returns a dict keyed by group.
        points = entry_points().get(ENTRY_POINT_GROUP, [])
    for point in points:
        try:
            loaded = point.load()
            if isinstance(loaded, type) and issubclass(loaded, MountDriver):
                register_driver(loaded)
            else:
                logger.warning("Entry point %r did not provide a MountDriver", point.name)
        except Exception:
            logger.warning("Could not load mount driver plugin %r", point.name, exc_info=True)


def discover_drivers(force: bool = False) -> dict:
    """Load all drivers once, and return the registry."""
    global _discovered
    if _discovered and not force:
        return dict(_registry)
    _discover_builtin()
    _discover_plugins()
    _discovered = True
    return dict(_registry)


def list_drivers() -> list:
    """Every registered driver class, sorted by name."""
    return [_registry[name] for name in sorted(discover_drivers())]


def get_driver(name: str):
    """Look up one driver class by name."""
    drivers = discover_drivers()
    try:
        return drivers[name]
    except KeyError:
        available = ", ".join(sorted(drivers)) or "none"
        raise MountError(f"unknown mount driver {name!r} (available: {available})") from None


def discover_mounts(driver: Optional[str] = None) -> list:
    """Ask drivers where their mounts might be.

    A driver that fails to enumerate is skipped rather than allowed to break
    discovery for the rest.
    """
    classes = [get_driver(driver)] if driver else list_drivers()
    candidates = []
    for driver_class in classes:
        try:
            candidates.extend(driver_class.discover())
        except Exception:
            logger.debug("Driver %s failed to enumerate", driver_class.name, exc_info=True)
    return candidates


def connect(driver: Optional[str] = None, **config) -> MountDriver:
    """Open a mount.

    With an explicit ``driver``, the named driver is used.  Without one, every
    driver is asked where its mounts can be, and the first candidate that
    connects is used, in the order that :func:`discover_mounts` returns them.
    """
    if driver:
        mount = get_driver(driver)(**config)
        mount.connect()
        logger.info("Connected mount: %s", mount.describe())
        return mount

    errors = []
    for candidate in discover_mounts():
        merged = dict(candidate.config)
        merged.update(config)
        try:
            mount = get_driver(candidate.driver)(**merged)
            mount.connect()
            logger.info("Connected mount: %s", mount.describe())
            return mount
        except MountError as exc:
            errors.append(f"{candidate}: {exc}")
            logger.debug("Candidate %s did not answer: %s", candidate, exc)

    detail = ("  " + "\n  ".join(errors)) if errors else "  (nothing found to try)"
    raise MountError(
        "no mount could be connected.  Tried:\n" + detail +
        "\nPass an explicit driver and address, or use the 'simulator' driver to "
        "rehearse without hardware."
    )


def push_site_and_time(mount: MountDriver, latitude: Optional[float] = None,
                       longitude: Optional[float] = None) -> None:
    """Tell a mount the time of this computer and, when it is known, the site.

    An OnStepX stays in standby and does not track until it knows both.  A
    driver without :attr:`Capabilities.site_time` is left alone.  Longitude is
    in degrees, east positive.
    """
    if not mount.capabilities.site_time:
        return
    mount.set_datetime()
    if latitude is not None and longitude is not None:
        mount.set_site(latitude, longitude)
        logger.info("Mount clock and site set")
    else:
        logger.info("Mount clock set; no observing location is known yet")


# ------------------------------------------------------------ scheduler commands
#
# Eclipse scripts call these.  The scheduler gives the connected mount as the
# first argument.

def mount_track_sun(mount: MountDriver) -> None:
    """Switch to solar rate and start tracking."""
    logger.info("mount_track_sun")
    if "solar" in mount.capabilities.tracking_rates:
        mount.set_tracking_rate("solar")
    else:
        logger.warning("%s has no solar tracking rate; leaving the rate unchanged", mount.name)
    mount.tracking_on()


def mount_goto_sun(mount: MountDriver, wait: str = "false") -> None:
    """Slew to the Sun, optionally blocking until the slew completes."""
    should_wait = str(wait).strip().lower() in ("1", "true", "yes", "wait")
    ra_hours, dec_degrees = mount.goto_sun(wait=should_wait)
    logger.info("mount_goto_sun: RA %s Dec %s", format_ra(ra_hours), format_dec(dec_degrees))


def mount_tracking(mount: MountDriver, state: str = "on") -> None:
    """Turn tracking on or off."""
    if str(state).strip().lower() in ("on", "1", "true", "yes"):
        mount.tracking_on()
    else:
        mount.tracking_off()


def mount_park(mount: MountDriver) -> None:
    logger.info("mount_park")
    mount.park()


def mount_unpark(mount: MountDriver) -> None:
    logger.info("mount_unpark")
    mount.unpark()


def mount_stop(mount: MountDriver) -> None:
    """Abort all motion.  Safe to schedule defensively."""
    logger.info("mount_stop")
    mount.abort()


__all__ = [
    "Candidate", "Capabilities", "MountDriver", "MountError", "MountNotSupported", "MountStatus",
    "register_driver", "discover_drivers", "list_drivers", "get_driver", "discover_mounts", "connect",
    "push_site_and_time",
    "format_ra", "format_dec", "parse_ra", "parse_dec", "sun_radec",
    "mount_track_sun", "mount_goto_sun", "mount_tracking", "mount_park", "mount_unpark", "mount_stop",
]
