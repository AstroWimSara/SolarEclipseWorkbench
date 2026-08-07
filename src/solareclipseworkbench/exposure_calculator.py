"""
Eclipse Exposure Calculator

This module calculates optimal camera exposure settings for solar eclipse photography
based on Xavier Jubier's exposure calculator data (http://xjubier.free.fr).

The exposure calculations take into account:
- Eclipse phenomenon type (partial, Baily's beads, corona, etc.)
- Sun altitude angle (0-60 degrees) - primary factor for atmospheric extinction
- Observer altitude above sea level (0-3000m) - secondary atmospheric factor
- Camera ISO setting
- Lens aperture (f-stop)
- Solar filter ND value (for partial phases)

All base values are for ISO 100, f/8, at 1000m observer altitude.
"""

from typing import Dict, Tuple, Optional, Any
import math


# Import solar eclipse workbench components for sun position calculation
try:
    from solareclipseworkbench.reference_moments import calculate_reference_moments
    HAS_REFERENCE_MOMENTS = True
except ImportError:
    HAS_REFERENCE_MOMENTS = False


PHENOMENON_BRIGHTNESS = {
    # Partial phases with fixed ND filters
    "partial_nd_5_6": 128.0,
    "partial_nd_5_0": 512.0,
    "partial_nd_4_0": 4096.0,

    # Totality phenomena
    "baileys_beads": 4096.0,
    "chromosphere": 2048.0,
    "prominences": 1024.0,
    "corona_lower": 256.0,
    "diamond_ring": 80.0,

    "corona_inner_0.2R": 32.0,
    "corona_inner_0.5R": 16.0,
    "corona_middle": 4.0,

    "corona_upper_2R": 2.0,
    "corona_upper_3R": 1.0,
    "corona_upper_4R": 0.5,
    "corona_upper_8R": 0.2,

    "earthshine": 0.09,
}

# Reference used for phenomenon="partial" with an arbitrary ND filter.
#
PARTIAL_REFERENCE_ND = 5.0
PARTIAL_REFERENCE_BRIGHTNESS = PHENOMENON_BRIGHTNESS["partial_nd_5_0"]
PARTIAL_UNFILTERED_BRIGHTNESS = (
    PARTIAL_REFERENCE_BRIGHTNESS * 10 ** PARTIAL_REFERENCE_ND
)


PHENOMENON_ALIASES = {
    # Common spelling variants
    "bailys_beads": "baileys_beads",
    "baily_beads": "baileys_beads",
    "baily's_beads": "baileys_beads",
    "baileys_beads": "baileys_beads",

    # Lower-case R variants
    "corona_inner_0.2r": "corona_inner_0.2R",
    "corona_inner_0.5r": "corona_inner_0.5R",
    "corona_upper_2r": "corona_upper_2R",
    "corona_upper_3r": "corona_upper_3R",
    "corona_upper_4r": "corona_upper_4R",
    "corona_upper_8r": "corona_upper_8R",

    # Names used in your old code
    "corona_upper": "corona_upper_2R",
    "corona_outer_3R": "corona_upper_3R",
    "corona_outer_4R": "corona_upper_4R",
    "corona_outer_8R": "corona_upper_8R",

    # Generic partial mode
    "partial": "partial",
}



def _interpolate_1d(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Linear interpolation between two points."""
    if x1 == x0:
        return y0
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def _interpolate_2d(sun_angle: float, observer_alt: float, lookup_table: Dict) -> float:
    """
    2D interpolation of exposure time from lookup table.
    
    Args:
        sun_angle: Sun altitude angle in degrees (0-60)
        observer_alt: Observer altitude in meters (0-3000)
        lookup_table: Dictionary with structure {sun_angle: {observer_alt: exposure_time}}
    
    Returns:
        Interpolated exposure time in seconds
    """
    # Clamp inputs to valid ranges
    sun_angle = max(0, min(60, sun_angle))
    observer_alt = max(0, min(3000, observer_alt))
    
    # Find surrounding sun angle values
    sun_angles = sorted(lookup_table.keys())
    sun_lower = max([s for s in sun_angles if s <= sun_angle])
    sun_upper = min([s for s in sun_angles if s >= sun_angle])
    
    # Find surrounding observer altitude values
    obs_alts = sorted(lookup_table[sun_lower].keys())
    obs_lower = max([o for o in obs_alts if o <= observer_alt])
    obs_upper = min([o for o in obs_alts if o >= observer_alt])
    
    # Get the four corner values
    v00 = lookup_table[sun_lower][obs_lower]
    v01 = lookup_table[sun_lower][obs_upper]
    v10 = lookup_table[sun_upper][obs_lower]
    v11 = lookup_table[sun_upper][obs_upper]
    
    # Interpolate in observer altitude direction
    if obs_lower == obs_upper:
        v0 = v00
        v1 = v10
    else:
        v0 = _interpolate_1d(observer_alt, obs_lower, obs_upper, v00, v01)
        v1 = _interpolate_1d(observer_alt, obs_lower, obs_upper, v10, v11)
    
    # Interpolate in sun angle direction
    if sun_lower == sun_upper:
        return v0
    return _interpolate_1d(sun_angle, sun_lower, sun_upper, v0, v1)


def normalise_phenomenon_name(phenomenon: str) -> str:
    """
    Normalise phenomenon names to the keys used by PHENOMENON_BRIGHTNESS.
    """

    key = phenomenon.strip()

    if key in PHENOMENON_BRIGHTNESS:
        return key

    if key in PHENOMENON_ALIASES:
        return PHENOMENON_ALIASES[key]

    lower_key = key.lower()

    if lower_key in PHENOMENON_ALIASES:
        return PHENOMENON_ALIASES[lower_key]

    return key


def atmos_extinction_factor(
    obj_altitude_deg: float,
    observer_altitude_m: float,
) -> float:
    """
    Python implementation of the JavaScript atmosExtinctionFactor function.

    Parameters
    ----------
    obj_altitude_deg:
        Object altitude above the horizon in degrees.

    observer_altitude_m:
        Observer altitude above sea level in metres.

    Returns
    -------
    float
        Atmospheric extinction factor.
    """

    if obj_altitude_deg > 0.0:
        deg_to_rad = math.pi / 180.0
        cos_z = math.cos((90.0 - obj_altitude_deg) * deg_to_rad)
        air_mass = 1.0 / (cos_z + 0.025 * math.exp(-11.0 * cos_z))
    else:
        air_mass = 40.0

    # Ozone
    extinction = 0.016

    # Rayleigh scattering
    extinction += 0.1451 * math.exp(
        -(observer_altitude_m / 1000.0) / 7.996
    )

    # Aerosol extinction to the human eye
    extinction += 0.120 * math.exp(
        -(observer_altitude_m / 1000.0) / 1.5
    )

    extinction *= air_mass

    return 2.512 ** extinction


def brightness_for_phenomenon(
    phenomenon: str,
    nd_filter: Optional[float] = None,
) -> float:
    """
    Return the JavaScript EclipseEvent brightness value for a phenomenon.

    For phenomenon="partial", nd_filter is required and is interpreted as
    optical density, e.g. ND5.0 -> nd_filter=5.0.

    For all totality phenomena, nd_filter must be None.
    """

    key = normalise_phenomenon_name(phenomenon)

    if key == "partial":
        if nd_filter is None:
            raise ValueError(
                "phenomenon='partial' requires nd_filter, for example nd_filter=5.0."
            )

        if nd_filter < 0:
            raise ValueError("nd_filter may not be negative.")

        return PARTIAL_UNFILTERED_BRIGHTNESS / (10 ** nd_filter)

    if key not in PHENOMENON_BRIGHTNESS:
        known = ", ".join(sorted(PHENOMENON_BRIGHTNESS))
        raise ValueError(
            f"Unknown phenomenon {phenomenon!r}. "
            f"Known phenomena are: {known}, or use phenomenon='partial' "
            f"with nd_filter."
        )

    if nd_filter is not None:
        raise ValueError(
            "nd_filter is only supported with phenomenon='partial'. "
            f"The phenomenon {phenomenon!r} already has a fixed empirical "
            "brightness value."
        )

    return PHENOMENON_BRIGHTNESS[key]


def calculate_exposure(
    phenomenon: str,
    sun_altitude_deg: float,
    observer_altitude_m: float,
    iso: int = 100,
    aperture: float = 8.0,
    nd_filter: Optional[float] = None
) -> float:
    """
    Calculate optimal exposure time for eclipse photography.
    
    Args:
        phenomenon: Eclipse phenomenon type (e.g., "bailys_beads", "corona_middle")
        sun_altitude_deg: Sun altitude angle in degrees (0-60)
        observer_altitude_m: Observer altitude above sea level in meters (0-3000)
        iso: ISO setting (default 100, which matches base tables)
        aperture: Aperture f-stop (default 8.0, which matches base tables)
        nd_filter: ND filter value (e.g., 5.0 for ND5.0), None if no filter
    
    Returns: 
        Exposure time in seconds
        
    Notes:
        - Base exposure tables are for ISO 100, f/8, no filter
        - ISO doubling halves exposure time
        - Each f-stop doubles/halves exposure time
        - ND filter reduces light by 10^ND factor
    """
    """
    Calculate the atmospheric-extinction-corrected exposure time in seconds.

        Exposure = fStop^2 / (ISO * Brightness)

    followed by:

        Exposure *= atmosExtinctionFactor(sunAlt, obsAlt)
                    / atmosExtinctionFactor(90.0, 0.0)
    """

    if iso <= 0:
        raise ValueError("iso must be greater than zero.")

    if aperture <= 0:
        raise ValueError("aperture must be greater than zero.")

    brightness = brightness_for_phenomenon(
        phenomenon=phenomenon,
        nd_filter=nd_filter,
    )

    if brightness <= 0:
        raise ValueError("brightness must be greater than zero.")

    exposure_s = (aperture * aperture) / (iso * brightness)

    reference_extinction = atmos_extinction_factor(90.0, 0.0)

    if reference_extinction == 0:
        raise ValueError("reference atmospheric extinction factor may not be zero.")

    extinction_correction = (
        atmos_extinction_factor(sun_altitude_deg, observer_altitude_m)
        / reference_extinction
    )

    return exposure_s * extinction_correction


def calculate_eclipse_exposures(
    eclipse_time,
    longitude: float,
    latitude: float,
    observer_altitude_m: float,
    iso: int,
    aperture: float,
    nd_filter: Optional[float] = None,
    timings: Optional[dict] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate optimal exposures for all eclipse phenomena based on location
    and camera settings.

    Args:
        eclipse_time:
            astropy.time.Time object for the eclipse date.

        longitude:
            Observer longitude in degrees.

        latitude:
            Observer latitude in degrees.

        observer_altitude_m:
            Observer altitude above sea level in metres.

        iso:
            ISO setting.

        aperture:
            Aperture f-stop.

        nd_filter:
            ND filter optical density for the partial phase,
            for example 5.0 for ND5.0. Use None if no partial-phase
            exposures should be calculated.

        timings:
            Optional dictionary with timing moments. Each timing object is
            expected to provide altitude, time_utc, and time_local.

    Returns:
        Dictionary mapping phenomenon names to calculated exposures and metadata.

        Example:
            {
                "partial_c1": {
                    "exposure": 0.00125,
                    "shutter": "1/800",
                    "sun_altitude": 45.2,
                    "time_utc": ...,
                    "time_local": ...
                },
                ...
            }
    """

    # If reference moments are required but not provided, compute them.
    if timings is None:
        if not HAS_REFERENCE_MOMENTS:
            raise ImportError("reference_moments module not available")

        timings, magnitude, eclipse_type = calculate_reference_moments(
            longitude,
            latitude,
            observer_altitude_m,
            eclipse_time,
        )

    exposures: Dict[str, Dict[str, Any]] = {}

    def add_exposure(
        name: str,
        phenomenon: str,
        moment_key: str,
        nd: Optional[float] = None,
    ) -> None:
        """
        Add one exposure entry if the requested timing moment exists.
        """

        if moment_key not in timings:
            return

        moment = timings[moment_key]
        sun_alt = moment.altitude

        exp_time = calculate_exposure(
            phenomenon=phenomenon,
            sun_altitude_deg=sun_alt,
            observer_altitude_m=observer_altitude_m,
            iso=iso,
            aperture=aperture,
            nd_filter=nd,
        )

        exposures[name] = {
            "exposure": exp_time,
            "shutter": format_shutter_speed(exp_time),
            "sun_altitude": sun_alt,
            "time_utc": moment.time_utc,
            "time_local": moment.time_local,
        }

    # Partial phases.
    #
    # The partial phases require an ND filter. If nd_filter is None, these
    # entries are skipped, which matches your original behaviour.
    if nd_filter is not None:
        add_exposure("partial_c1", "partial", "C1", nd_filter)
        add_exposure("partial_c4", "partial", "C4", nd_filter)

    # Totality phenomena.
    #
    # Only calculate these if the eclipse has C2 and C3 timings.
    if "C2" in timings and "C3" in timings:
        # Phenomena at C2, start of totality.
        add_exposure("baileys_beads_c2", "baileys_beads", "C2")
        add_exposure("chromosphere_c2", "chromosphere", "C2")
        add_exposure("diamond_ring_c2", "diamond_ring", "C2")

        # Corona and prominences at maximum eclipse.
        add_exposure("prominences", "prominences", "MAX")
        add_exposure("corona_lower", "corona_lower", "MAX")
        add_exposure("corona_inner_0.2R", "corona_inner_0.2R", "MAX")
        add_exposure("corona_inner_0.5R", "corona_inner_0.5R", "MAX")
        add_exposure("corona_middle", "corona_middle", "MAX")
        add_exposure("corona_upper_2R", "corona_upper_2R", "MAX")
        add_exposure("corona_upper_3R", "corona_upper_3R", "MAX")
        add_exposure("corona_upper_4R", "corona_upper_4R", "MAX")
        add_exposure("corona_upper_8R", "corona_upper_8R", "MAX")

        # Phenomena at C3, end of totality.
        add_exposure("baileys_beads_c3", "baileys_beads", "C3")
        add_exposure("chromosphere_c3", "chromosphere", "C3")
        add_exposure("diamond_ring_c3", "diamond_ring", "C3")

        # Earthshine at maximum eclipse.
        add_exposure("earthshine", "earthshine", "MAX")

    return exposures

def round_to_camera_shutter_speed(exposure_seconds: float) -> float:
    """
    Round exposure time to nearest realistic camera shutter speed.
    
    Camera shutter speeds typically follow 1/3 stop increments.
    Standard speeds include: 30s, 15s, 8s, 4s, 2s, 1s, 1/2, 1/4, 1/8, 1/15, 1/30,
    1/60, 1/125, 1/250, 1/500, 1/1000, 1/2000, 1/4000, 1/8000, etc.
    
    Args:
        exposure_seconds: Calculated exposure time in seconds
    
    Returns:
        Nearest realistic shutter speed in seconds
    """
    # Standard camera shutter speeds (in seconds)
    # These are the common speeds found on DSLR/mirrorless cameras
    standard_speeds = [
        # Long exposures
        30.0, 25.0, 20.0, 15.0, 13.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.2, 2.5, 2.0, 1.6, 1.3, 1.0,
        # Fractional seconds
        0.8, 0.6, 0.5, 0.4, 0.3,  # 1/1.3, 1/1.6, 1/2, 1/2.5, 1/3.2
        1/4, 1/5, 1/6, 1/8, 1/10, 1/13, 1/15, 1/20, 1/25, 1/30, 1/40, 1/50, 1/60, 1/80,
        1/100, 1/125, 1/160, 1/200, 1/250, 1/320, 1/400, 1/500, 1/640, 1/800, 1/1000,
        1/1250, 1/1600, 1/2000, 1/2500, 1/3200, 1/4000, 1/5000, 1/6400, 1/8000
    ]
    
    # Find the closest standard speed
    closest_speed = min(standard_speeds, key=lambda x: abs(x - exposure_seconds))
    return closest_speed


def format_shutter_speed(exposure_seconds: float) -> str:
    """
    Format exposure time as a human-readable shutter speed.
    Rounds to nearest realistic camera shutter speed.
    
    Args:
        exposure_seconds: Exposure time in seconds
    
    Returns:
        Formatted string (e.g., "1/250", "2s", "1/4000")
    """
    # Round to realistic camera speed first
    rounded_exposure = round_to_camera_shutter_speed(exposure_seconds)
    
    if rounded_exposure >= 1.0:
        # Long exposure - format as plain number (no 's' suffix: gphoto2 uses "4" not "4s")
        if rounded_exposure == int(rounded_exposure):
            return f"{int(rounded_exposure)}"
        else:
            return f"{rounded_exposure:.1f}"
    else:
        # Fast shutter - format as "1/X", but use decimal for denominator <= 2
        # (Canon cameras use "0.5" not "1/2" in their gphoto2 widget choices)
        denominator = round(1.0 / rounded_exposure)
        # Handle edge case where denominator is 1 (e.g., due to floating-point precision)
        if denominator == 1:
            return "1"
        if denominator == 2:
            return "0.5"
        return f"1/{denominator}"


def parse_shutter_speed(shutter_str: str) -> float:
    """
    Parse a shutter speed string and return exposure time in seconds.
    
    Args:
        shutter_str: Shutter speed string (e.g., "1/250", "2s", "30", "1/4000")
    
    Returns:
        Exposure time in seconds
    """
    shutter_str = shutter_str.strip()
    
    # Handle formats like "2s", "30s", "1.5s"
    if shutter_str.endswith('s'):
        return float(shutter_str[:-1])
    
    # Handle fraction format like "1/250"
    if '/' in shutter_str:
        parts = shutter_str.split('/')
        return float(parts[0]) / float(parts[1])
    
    # Handle plain number (assume seconds)
    return float(shutter_str)


def get_exposure_bracket(
    base_exposure: float,
    stops: int = 2,
    step: float = 1.0
) -> list:
    """
    Generate exposure bracket around a base exposure.
    
    Args:
        base_exposure: Base exposure time in seconds
        stops: Number of stops to bracket above and below base
        step: Step size in stops (e.g., 1.0 for full stops, 0.5 for half stops)
    
    Returns:
        List of exposure times in seconds, sorted from fastest to slowest
    """
    bracket = []
    current_stop = -stops
    while current_stop <= stops:
        exposure = base_exposure * (2 ** current_stop)
        bracket.append(exposure)
        current_stop += step
    
    return sorted(bracket)


def calculate_sun_altitude_at_time(
    target_time,
    eclipse_time,
    longitude: float,
    latitude: float,
    observer_altitude_m: float
) -> float:
    """
    Calculate sun altitude at a specific time.
    
    Args:
        target_time: datetime object for the time to calculate
        eclipse_time: astropy.time.Time object for the eclipse date
        longitude: Observer longitude in degrees
        latitude: Observer latitude in degrees
        observer_altitude_m: Observer altitude above sea level in meters
    
    Returns:
        Sun altitude in degrees
    """
    if not HAS_REFERENCE_MOMENTS:
        raise ImportError("reference_moments module not available")
    
    from skyfield.api import load, wgs84
    
    eph = load("de421.bsp")
    ts = load.timescale()
    earth = eph["Earth"]
    sun_ephem = eph['Sun']
    place = wgs84.latlon(latitude, longitude, observer_altitude_m)
    
    # Calculate altitude at target time
    t = ts.utc(target_time.year, target_time.month, target_time.day, 
               target_time.hour, target_time.minute, target_time.second)
    astro = (earth + place).at(t).observe(sun_ephem)
    app = astro.apparent()
    alt, az, distance = app.altaz()
    
    return alt.degrees


def calculate_eclipse_exposures(
    eclipse_time,
    longitude: float,
    latitude: float,
    observer_altitude_m: float,
    iso: int,
    aperture: float,
    nd_filter: Optional[float] = None,
    timings: Optional[dict] = None
) -> Dict[str, Dict[str, any]]:
    """
    Calculate optimal exposures for all eclipse phenomena based on location and camera settings.
    
    Args:
        eclipse_time: astropy.time.Time object for the eclipse date
        longitude: Observer longitude in degrees
        latitude: Observer latitude in degrees
        observer_altitude_m: Observer altitude above sea level in meters
        iso: ISO setting
        aperture: Aperture f-stop
        nd_filter: ND filter value (e.g., 5.0 for ND5.0), None if no filter for totality
    
    Returns:
        Dictionary mapping phenomenon names to their calculated exposures and metadata
        Example: {
            "partial_c1": {"exposure": 0.00125, "shutter": "1/800", "sun_altitude": 45.2},
            "bailys_beads_c2": {"exposure": 0.000781, "shutter": "1/1280", "sun_altitude": 45.5},
            ...
        }
    """
    # If reference moments are required but not provided, compute them.
    if timings is None:
        if not HAS_REFERENCE_MOMENTS:
            raise ImportError("reference_moments module not available")
        # Calculate reference moments to get sun altitudes at key times
        timings, magnitude, eclipse_type = calculate_reference_moments(
            longitude, latitude, observer_altitude_m, eclipse_time
        )
    
    exposures = {}
    
    # Helper to add exposure calculation
    def add_exposure(name: str, phenomenon: str, moment_key: str, nd: Optional[float] = None):
        if moment_key not in timings:
            return
        
        moment = timings[moment_key]
        sun_alt = moment.altitude
        
        # Calculate exposure
        exp_time = calculate_exposure(
            phenomenon, sun_alt, observer_altitude_m, iso, aperture, nd
        )
        
        exposures[name] = {
            "exposure": exp_time,
            "shutter": format_shutter_speed(exp_time),
            "sun_altitude": sun_alt,
            "time_utc": moment.time_utc,
            "time_local": moment.time_local
        }
    
    # Partial phases (with ND filter)
    if nd_filter:
        add_exposure("partial_c1", "partial", "C1", nd_filter)
        add_exposure("partial_c4", "partial", "C4", nd_filter)
    
    # Only calculate totality phenomena if it's a total eclipse
    if "C2" in timings and "C3" in timings:
        # Phenomena at C2 (start of totality)
        add_exposure("bailys_beads_c2", "bailys_beads", "C2")
        add_exposure("chromosphere_c2", "chromosphere", "C2")
        add_exposure("diamond_ring_c2", "diamond_ring", "C2")
        
        # Corona at mid-totality (use MAX timing)
        add_exposure("prominences", "prominences", "MAX")
        add_exposure("corona_lower", "corona_lower", "MAX")
        add_exposure("corona_inner_0.2R", "corona_inner_0.2R", "MAX")
        add_exposure("corona_inner_0.5R", "corona_inner_0.5R", "MAX")
        add_exposure("corona_middle", "corona_middle", "MAX")
        add_exposure("corona_upper", "corona_upper", "MAX")
        add_exposure("corona_outer_3R", "corona_outer_3R", "MAX")
        add_exposure("corona_outer_4R", "corona_outer_4R", "MAX")
        add_exposure("corona_outer_8R", "corona_outer_8R", "MAX")
        
        # Phenomena at C3 (end of totality)
        add_exposure("bailys_beads_c3", "bailys_beads", "C3")
        add_exposure("chromosphere_c3", "chromosphere", "C3")
        add_exposure("diamond_ring_c3", "diamond_ring", "C3")
        
        # Earthshine (if applicable)
        add_exposure("earthshine", "earthshine", "MAX")
    
    return exposures


if __name__ == "__main__":
    # Example usage / testing
    print("Eclipse Exposure Calculator")
    print("=" * 50)
    
    # Example: Baily's Beads at 45° sun angle, 1000m observer altitude
    sun_alt = 45.0
    obs_alt = 1000.0
    iso = 400
    aperture = 8.0
    
    print(f"\nConditions: Sun {sun_alt}°, Observer {obs_alt}m, ISO {iso}, f/{aperture}")
    print("-" * 50)
    
    phenomena = ["bailys_beads", "chromosphere", "prominences", "corona_middle"]
    
    for phenom in phenomena:
        exposure = calculate_exposure(phenom, sun_alt, obs_alt, iso, aperture)
        shutter = format_shutter_speed(exposure)
        print(f"{phenom:20s}: {shutter:>10s} ({exposure:.6f}s)")
    
    # Show bracket example
    print("\nExposure bracket for corona_middle (±2 stops, 1 stop intervals):")
    base = calculate_exposure("corona_middle", sun_alt, obs_alt, iso, aperture)
    bracket = get_exposure_bracket(base, stops=2, step=1.0)
    for exp in bracket:
        print(f"  {format_shutter_speed(exp)}")
    
    # Test full eclipse exposure calculation
    if HAS_REFERENCE_MOMENTS:
        print("\n" + "=" * 50)
        print("Full Eclipse Exposure Calculation Test")
        print("=" * 50)
        from astropy.time import Time
        
        eclipse_date = Time('2026-08-12')
        longitude = -3.9852
        latitude = 41.6669
        altitude = 828.0
        iso = 400
        aperture = 8.0
        nd_filter = 5.0
        
        print(f"\nEclipse: 2026-08-12")
        print(f"Location: {latitude}°N, {longitude}°E, {altitude}m")
        print(f"Camera: ISO {iso}, f/{aperture}, ND{nd_filter}")
        print("-" * 50)
        
        try:
            exposures = calculate_eclipse_exposures(
                eclipse_date, longitude, latitude, altitude, iso, aperture, nd_filter
            )
            
            for name, data in exposures.items():
                print(f"{name:25s}: {data['shutter']:>10s}  (sun alt: {data['sun_altitude']:5.1f}°)")
        except Exception as e:
            print(f"Error: {e}")
