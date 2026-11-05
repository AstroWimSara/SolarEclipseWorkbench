"""
The solar radius used to predict the contact times.

We generate our own Besselian elements, so the solar radius sets the size of the
umbra and with it the duration of totality.  It is the largest systematic in the
contact times, larger than the lunar limb correction: a larger Sun shortens
totality, by about 1 s on 100 s of totality for the 0.3" between the two values
below, and much more close to the path limits.  The midpoint of totality barely
moves (Issue #197).

Default: 959.95" (Quaglia et al. 2021)
--------------------------------------
Quaglia, Irwin, Emmanouilidis and Pessi (arXiv:2107.09416) derive 959.95" ± 0.05"
from flash-spectrum video at the southern limit of the 2017 eclipse.  It is
measured *from eclipse contacts*, which is exactly the quantity contact-time
prediction needs: the radius at which the photosphere is completely hidden.
Other techniques measure a different edge of the Sun.  Independent eclipse
determinations agree with it: IOTA's Baily's bead timings give 959.99" ± 0.06",
and Jubier suggests 959.98".  The standard value below lies well outside that
cluster, so we use the modern eclipse-derived value.

Alternative: 959.63" (Auwers 1891)
----------------------------------
The conventional value adopted for eclipse prediction, used by Espenak's canon,
Solar Eclipse Maestro (default) and eclipse-chaser-log.  It is a reference
convention, not a current measurement.  Choose it to compare our contact times
directly with published predictions: with it, any remaining difference has
another cause.

Any other value can be entered as well, within ``MIN_ARCSEC``..``MAX_ARCSEC``.

The radius is the apparent angular radius at 1 au, so the radius in metres is
``AU * sin(radius)``.  (With ``atan`` instead of ``asin`` the same radius in
metres reads 0.01" smaller: 959.94" instead of 959.95".)
"""
import logging
import math
from pathlib import Path

# Astronomical unit [m] (IAU 2012)
AU_M = 149_597_870_700.0

QUAGLIA_ARCSEC = 959.95
AUWERS_ARCSEC = 959.63
DEFAULT_ARCSEC = QUAGLIA_ARCSEC

# Named choices offered in the user interface, default first
PRESETS = {
    "quaglia": (QUAGLIA_ARCSEC, "Quaglia et al. 2021 (default)"),
    "auwers": (AUWERS_ARCSEC, "Auwers 1891, as in published predictions"),
}

# Key under which sew remembers the choice in ~/.SolarEclipseWorkbench.ini
SETTINGS_KEY = "solar_radius_arcsec"

# Bounds for a value typed in by the user: a few arcseconds around the
# published determinations, so a typing error cannot move the contacts by minutes
MIN_ARCSEC = 955.0
MAX_ARCSEC = 965.0

_radius_arcsec = DEFAULT_ARCSEC


def arcsec_to_m(radius_arcsec: float) -> float:
    """Radius of the Sun [m] for an apparent radius at 1 au [arcseconds]."""
    return AU_M * math.sin(math.radians(radius_arcsec / 3600.0))


def m_to_arcsec(radius_m: float) -> float:
    """Apparent radius at 1 au [arcseconds] for a radius of the Sun [m]."""
    return math.degrees(math.asin(radius_m / AU_M)) * 3600.0


def validate(radius_arcsec) -> float:
    """The radius as a float, or ValueError when it is not a plausible solar radius."""
    try:
        value = float(radius_arcsec)
    except (TypeError, ValueError):
        raise ValueError(f"Solar radius must be a number of arcseconds, not {radius_arcsec!r}") from None
    if not math.isfinite(value) or not MIN_ARCSEC <= value <= MAX_ARCSEC:
        raise ValueError(f"Solar radius must be between {MIN_ARCSEC}\" and {MAX_ARCSEC}\", not {value}\"")
    return value


def set_radius_arcsec(radius_arcsec: float) -> None:
    """Use this solar radius [arcseconds at 1 au] for all contact times from now on."""
    global _radius_arcsec
    _radius_arcsec = validate(radius_arcsec)


def get_radius_arcsec() -> float:
    """The solar radius in use [arcseconds at 1 au]."""
    return _radius_arcsec


def get_radius_m() -> float:
    """The solar radius in use [m]."""
    return arcsec_to_m(_radius_arcsec)


def preset_for(radius_arcsec: float):
    """The key of the preset with this radius, or None for a custom value."""
    for key, (value, _) in PRESETS.items():
        if abs(value - radius_arcsec) < 1e-6:
            return key
    return None


def describe(radius_arcsec: float = None) -> str:
    """Short description for the log, e.g. '959.95" (Quaglia et al. 2021, ...)'."""
    value = get_radius_arcsec() if radius_arcsec is None else radius_arcsec
    key = preset_for(value)
    return f'{value:.2f}" ({PRESETS[key][1]})' if key else f'{value:.2f}" (custom)'


def load_saved(settings=None) -> float:
    """Use the solar radius remembered by sew, and return it.

    ``settings`` is a QSettings (or anything with ``contains`` and ``value``);
    by default the one sew writes, ``~/.SolarEclipseWorkbench.ini``, so the
    wizard and the command-line modes use the same radius as the window.  A
    missing or invalid value leaves the default in place.
    """
    try:
        if settings is None:
            from PyQt6.QtCore import QSettings
            settings = QSettings(str(Path.home() / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)
        if settings.contains(SETTINGS_KEY):
            set_radius_arcsec(settings.value(SETTINGS_KEY))
    except ValueError as exc:
        logging.warning("Ignoring the saved solar radius: %s", exc)
    except Exception as exc:  # never keep the application from starting
        logging.warning("Could not read the saved solar radius: %s", exc)
    return get_radius_arcsec()
