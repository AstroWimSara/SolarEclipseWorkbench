"""Sensor size of common camera bodies, to work out the pixel size from the camera model.

gphoto2 tells the camera model, but not the size of its sensor or of its pixels.
The pixel size (with the focal length) decides how soon the Moon's bite shows
after first contact (see contact_visibility), so Test Camera looks the model up
here.  A model that is not listed keeps the pixel size entered in the wizard.
"""

import re
from typing import Optional, Tuple

# Sensor width (mm) and image width (pixels), keyed by the model as gphoto2 names it, without
# spaces, hyphens or case.  Several keys for one body cover the names gphoto2 uses
# ("Sony Alpha-A7r III" and "ILCE-7RM3").  A key has to match whole words: "EOS R5" is not
# found in "EOS R50", nor "D750" in "D7500", nor "EOS R6" in "EOS R6 Mark III", so a model that
# is not listed gets no value rather than the value of a similar one.
SENSORS = {
    # Sony full frame
    "ilce7m2": (35.8, 6000), "a7ii": (35.8, 6000),
    "ilce7m3": (35.6, 6000), "a7iii": (35.6, 6000),
    "ilce7m4": (35.9, 7008), "a7iv": (35.9, 7008),
    "ilce7rm2": (35.9, 7952), "a7rii": (35.9, 7952),
    "ilce7rm3": (35.9, 7952), "ilce7rm3a": (35.9, 7952), "a7riii": (35.9, 7952),
    "ilce7rm4": (35.7, 9504), "ilce7rm4a": (35.7, 9504), "a7riv": (35.7, 9504),
    "ilce7rm5": (35.7, 9504), "a7rv": (35.7, 9504),
    "ilce7sm3": (35.6, 4240), "a7siii": (35.6, 4240),
    "ilce9": (35.6, 6000), "a9": (35.6, 6000), "ilce9m2": (35.6, 6000), "a9ii": (35.6, 6000),
    "ilce1": (35.9, 8640), "alpha1": (35.9, 8640),
    # Sony APS-C
    "ilce6100": (23.5, 6000), "a6100": (23.5, 6000),
    "ilce6400": (23.5, 6000), "a6400": (23.5, 6000),
    "ilce6600": (23.5, 6000), "a6600": (23.5, 6000),
    "ilce6700": (23.3, 6192), "a6700": (23.3, 6192),
    # Canon full frame
    "eosr": (36.0, 6720), "eosra": (36.0, 6720),
    "eosrp": (35.9, 6240),
    "eosr3": (36.0, 6000),
    "eosr8": (35.9, 6000),
    "eosr5": (36.0, 8192),
    "eosr6": (35.9, 5472),
    "eosr6markii": (35.9, 6000),
    "eos5dmarkiii": (36.0, 5760),
    "eos5dmarkiv": (36.0, 6720),
    "eos6d": (35.8, 5472),
    "eos6dmarkii": (35.9, 6240),
    # Canon APS-C
    "eosr7": (22.3, 6960),
    "eosr10": (22.3, 6000),
    "eosr50": (22.3, 6000),
    "eosr100": (22.3, 6000),
    "eos7dmarkii": (22.4, 5472),
    "eos80d": (22.5, 6000),
    "eos90d": (22.3, 6960),
    # Nikon full frame
    "z5": (35.9, 6016),
    "z6": (35.9, 6048),
    "z7": (35.9, 8256),
    "z8": (35.9, 8256),
    "z9": (35.9, 8256),
    "zf": (35.9, 6048),
    "d750": (35.9, 6016),
    "d810": (35.9, 7360),
    "d850": (35.9, 8256),
    # Nikon APS-C
    "z50": (23.5, 5568),
    "zfc": (23.5, 5568),
    "d7500": (23.5, 5568),
}


# A version that follows the model: "Mark II", "II", "III", "IV", "V", "M2"
_VERSION_AFTER = r"(?![\s\-]*(?:mark|ii|iii|iv|v|m\d)(?![a-z]))"


def _key_pattern(key: str) -> "re.Pattern":
    """The key as whole words of a model name, with any spaces, hyphens or underscores in between,
    and not followed by a version (an "EOS R6 Mark III" is not an "EOS R6")."""
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-_]*".join(map(re.escape, key)) + r"(?![a-z0-9])"
                      + _VERSION_AFTER)


_PATTERNS = {key: _key_pattern(key) for key in SENSORS}


def sensor_for_model(model: str) -> Optional[Tuple[float, int]]:
    """Sensor width (mm) and image width (pixels) of a camera model, or None when it is not listed."""
    name = (model or "").lower()
    matches = [key for key, pattern in _PATTERNS.items() if pattern.search(name)]
    if not matches:
        return None
    return SENSORS[max(matches, key=len)]


def pixel_size_for_model(model: str) -> Optional[float]:
    """Pixel size (micrometres, to 0.01) of a camera model, or None when it is not listed."""
    sensor = sensor_for_model(model)
    if sensor is None:
        return None
    width_mm, width_px = sensor
    return round(width_mm / width_px * 1000, 2)
