"""When the Moon's first bite (C1) and last bite (C4) show on the camera sensor.

At first contact the Moon only touches the Sun: nothing is visible yet.  The
notch it cuts grows with the eclipse magnitude, which is the fraction of the
Sun's diameter that is covered, so the notch is magnitude x the Sun's diameter
deep.  It shows once it is a couple of pixels deep, and deeper than the
seeing blurs it.  With a short lens that takes tens of seconds; with a long
telescope a few seconds (discussion #192: at 75 mm, a burst at C1 could not
show first contact).  C4 is the same in reverse.

The wizard uses this to place the contact shots: C1 - step (the whole Sun),
C1, and C1 + step (the first visible bite), and the same around C4.
"""

import math
from datetime import date as Date
from typing import Optional

from solareclipseworkbench.solar_eclipse import get_element_coeffs, get_elements, get_local_circumstances

# The notch has to be this many pixels deep to be seen
MIN_PIXELS = 2.0
# ... and deeper than the seeing (arcseconds); the Sun is often low at C1 or C4
SEEING_ARCSEC = 3.0
# Mean apparent diameter of the Sun (arcseconds) at 1 AU
SUN_DIAMETER_1AU_ARCSEC = 2 * 959.63
# Pixel size used when none is known (micrometres): a typical full-frame body of 24 to 45 MP
DEFAULT_PIXEL_SIZE_UM = 4.5
# Never look further than this from the contact
MAX_STEP_S = 600


def pixel_scale_arcsec(focal_length_mm: float, pixel_size_um: float) -> float:
    """Arcseconds of sky per pixel."""
    return 206.265 * pixel_size_um / focal_length_mm


def visible_depth_arcsec(focal_length_mm: float, pixel_size_um: float) -> float:
    """How deep (arcseconds) the Moon's notch has to be to show in the picture."""
    return max(MIN_PIXELS * pixel_scale_arcsec(focal_length_mm, pixel_size_um), SEEING_ARCSEC)


def sun_diameter_arcsec(day: Date) -> float:
    """Apparent diameter of the Sun on this day (Earth-Sun distance to about 0.1 %)."""
    days_from_perihelion = day.timetuple().tm_yday - 4
    distance_au = 1 - 0.01671 * math.cos(2 * math.pi * days_from_perihelion / 365.25)
    return SUN_DIAMETER_1AU_ARCSEC / distance_au


def contact_step_s(eclipse_date: str, latitude: float, longitude: float, altitude: float,
                   focal_length_mm: float, pixel_size_um: float) -> Optional[dict]:
    """Seconds after C1 and before C4 at which the Moon's bite shows in the picture.

    Args:
        - eclipse_date: Date of the eclipse, 'YYYY-MM-DD'
        - latitude, longitude: Location in degrees (longitude positive east)
        - altitude: Height above sea level in metres
        - focal_length_mm: Focal length of the lens or telescope
        - pixel_size_um: Pixel size of the camera sensor, in micrometres

    Returns: {'C1': seconds, 'C4': seconds}, whole seconds of at least 1, or None when
             there is no eclipse at this location or the bite never becomes visible.
    """
    if focal_length_mm <= 0 or pixel_size_um <= 0:
        return None
    circumstances = get_local_circumstances(latitude, longitude, altitude, eclipse_date)
    if circumstances['type'] == "No eclipse":
        return None
    elements = get_element_coeffs(eclipse_date)
    year, month, day = (int(part) for part in eclipse_date.split('-'))
    depth = visible_depth_arcsec(focal_length_mm, pixel_size_um)
    diameter = sun_diameter_arcsec(Date(year, month, day))

    def magnitude(ut_hours: float) -> float:
        # Meeus, Elements of Solar Eclipses: (L1' - m) / (L1' + L2'), the covered fraction of the diameter
        o = get_elements(elements, ut_hours + elements['Δt'] / 3600 - elements['T0'], latitude, -longitude, altitude)
        return (o['L1p'] - math.hypot(o['u'], o['v'])) / (o['L1p'] + o['L2p'])

    steps = {}
    for contact, ut_contact, direction in (("C1", circumstances['ut_first_contact'], 1),
                                           ("C4", circumstances['ut_last_contact'], -1)):
        for seconds in range(1, MAX_STEP_S + 1):
            if magnitude(ut_contact + direction * seconds / 3600) * diameter >= depth:
                steps[contact] = seconds
                break
        else:
            return None
    return steps
