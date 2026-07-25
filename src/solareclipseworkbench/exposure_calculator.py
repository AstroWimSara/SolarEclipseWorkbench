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

from typing import Dict, Tuple, Optional
import math


# Import solar eclipse workbench components for sun position calculation
try:
    from solareclipseworkbench.reference_moments import calculate_reference_moments
    HAS_REFERENCE_MOMENTS = True
except ImportError:
    HAS_REFERENCE_MOMENTS = False


# Exposure lookup tables: [sun_angle][observer_altitude] -> shutter_speed_seconds
# Base settings: ISO 100, f/8
# Sun angles: 0°, 5°, 10°, 15°, 30°, 45°, 60°
# Observer altitudes: 0m, 1000m, 2000m, 3000m

PARTIAL_PHASE_ND_5_0 = {
    0: {0: 30.0, 1000: 2.0, 2000: 1/3, 3000: 1/8},
    5: {0: 1/80, 1000: 1/160, 2000: 1/200, 3000: 1/320},
    10: {0: 1/250, 1000: 1/320, 2000: 1/500, 3000: 1/500},
    15: {0: 1/400, 1000: 1/500, 2000: 1/640, 3000: 1/640},
    30: {0: 1/640, 1000: 1/640, 2000: 1/800, 3000: 1/800},
    45: {0: 1/640, 1000: 1/800, 2000: 1/800, 3000: 1/800},
    60: {0: 1/800, 1000: 1/800, 2000: 1/800, 3000: 1/800}
}

PARTIAL_PHASE_ND_4_0 = {
    0: {0: 4.0, 1000: 1/5, 2000: 1/25, 3000: 1/60},
    5: {0: 1/640, 1000: 1/1250, 2000: 1/1600, 3000: 1/2500},
    10: {0: 1/2000, 1000: 1/2500, 2000: 1/4000, 3000: 1/4000},
    15: {0: 1/3200, 1000: 1/4000, 2000: 1/5000, 3000: 1/5000},
    30: {0: 1/5000, 1000: 1/5000, 2000: 1/6400, 3000: 1/6400},
    45: {0: 1/6400, 1000: 1/6400, 2000: 1/6400, 3000: 1/6400},
    60: {0: 1/6400, 1000: 1/6400, 2000: 1/6400, 3000: 1/6400}
}

BAILYS_BEADS = {
    0: {0: 4.0, 1000: 1/5, 2000: 1/25, 3000: 1/60},
    5: {0: 1/640, 1000: 1/1250, 2000: 1/1600, 3000: 1/2500},
    10: {0: 1/2000, 1000: 1/2500, 2000: 1/4000, 3000: 1/4000},
    15: {0: 1/3200, 1000: 1/4000, 2000: 1/5000, 3000: 1/5000},
    30: {0: 1/5000, 1000: 1/5000, 2000: 1/6400, 3000: 1/6400},
    45: {0: 1/6400, 1000: 1/6400, 2000: 1/6400, 3000: 1/6400},
    60: {0: 1/6400, 1000: 1/6400, 2000: 1/6400, 3000: 1/6400}
}

CHROMOSPHERE = {
    0: {0: 8.0, 1000: 1/2, 2000: 1/13, 3000: 1/30},
    5: {0: 1/320, 1000: 1/640, 2000: 1/800, 3000: 1/1250},
    10: {0: 1/1000, 1000: 1/1250, 2000: 1/2000, 3000: 1/2000},
    15: {0: 1/1600, 1000: 1/2000, 2000: 1/2500, 3000: 1/2500},
    30: {0: 1/2500, 1000: 1/250, 2000: 1/3200, 3000: 1/3200},
    45: {0: 1/3200, 1000: 1/3200, 2000: 1/3200, 3000: 1/3200},
    60: {0: 1/3200, 1000: 1/3200, 2000: 1/3200, 3000: 1/3200}
}

PROMINENCES = {
    0: {0: 15.0, 1000: 1.0, 2000: 1/6, 3000: 1/15},
    5: {0: 1/160, 1000: 1/320, 2000: 1/400, 3000: 1/640},
    10: {0: 1/500, 1000: 1/640, 2000: 1/1000, 3000: 1/1000},
    15: {0: 1/800, 1000: 1/1000, 2000: 1/1250, 3000: 1/1250},
    30: {0: 1/1250, 1000: 1/1250, 2000: 1/1600, 3000: 1/1600},
    45: {0: 1/1250, 1000: 1/1600, 2000: 1/1600, 3000: 1/1600},
    60: {0: 1/1600, 1000: 1/1600, 2000: 1/1600, 3000: 1/1600}
}

CORONA_LOWER = {
    0: {0: 60.0, 1000: 4.0, 2000: 1/1.3, 3000: 1/5},
    5: {0: 1/40, 1000: 1/80, 2000: 1/125, 3000: 1/160},
    10: {0: 1/125, 1000: 1/160, 2000: 1/250, 3000: 1/250},
    15: {0: 1/200, 1000: 1/250, 2000: 1/320, 3000: 1/320},
    30: {0: 1/320, 1000: 1/320, 2000: 1/400, 3000: 1/400},
    45: {0: 1/320, 1000: 1/400, 2000: 1/400, 3000: 1/400},
    60: {0: 1/400, 1000: 1/400, 2000: 1/400, 3000: 1/400}
}

CORONA_INNER_02R = {
    0: {0: 480.0, 1000: 30.0, 2000: 6.0, 3000: 2.0},
    5: {0: 1/5, 1000: 1/10, 2000: 1/15, 3000: 1/20},
    10: {0: 1/15, 1000: 1/25, 2000: 1/30, 3000: 1/30},
    15: {0: 1/25, 1000: 1/30, 2000: 1/40, 3000: 1/40},
    30: {0: 1/40, 1000: 1/40, 2000: 1/50, 3000: 1/50},
    45: {0: 1/40, 1000: 1/50, 2000: 1/50, 3000: 1/50},
    60: {0: 1/50, 1000: 1/50, 2000: 1/50, 3000: 1/50}
}

CORONA_INNER_05R = {
    0: {0: 960.0, 1000: 60.0, 2000: 11.0, 3000: 4.0},
    5: {0: 1/2, 1000: 1/5, 2000: 1/8, 3000: 1/10},
    10: {0: 1/8, 1000: 1/13, 2000: 1/15, 3000: 1/15},
    15: {0: 1/13, 1000: 1/15, 2000: 1/20, 3000: 1/20},
    30: {0: 1/20, 1000: 1/25, 2000: 1/25, 3000: 1/25},
    45: {0: 1/25, 1000: 1/25, 2000: 1/25, 3000: 1/25},
    60: {0: 1/25, 1000: 1/25, 2000: 1/25, 3000: 1/25}
}

CORONA_MIDDLE = {
    0: {0: 3900.0, 1000: 240.0, 2000: 46.0, 3000: 16.0},
    5: {0: 2.0, 1000: 1.0, 2000: 1/1.6, 3000: 1/2.5},
    10: {0: 1/2, 1000: 1/3, 2000: 1/4, 3000: 1/5},
    15: {0: 1/3, 1000: 1/4, 2000: 1/5, 3000: 1/6},
    30: {0: 1/5, 1000: 1/6, 2000: 1/6, 3000: 1/6},
    45: {0: 1/6, 1000: 1/6, 2000: 1/6, 3000: 1/6},
    60: {0: 1/6, 1000: 1/6, 2000: 1/6, 3000: 1/6}
}

CORONA_UPPER = {
    0: {0: 7800.0, 1000: 480.0, 2000: 120.0, 3000: 32.0},
    5: {0: 4.0, 1000: 2.0, 2000: 1.0, 3000: 1/1.3},
    10: {0: 1.0, 1000: 1/1.3, 2000: 1/1.6, 3000: 1/2},
    15: {0: 1/1.6, 1000: 1/2, 2000: 1/2.5, 3000: 1/2.5},
    30: {0: 1/2.5, 1000: 1/3, 2000: 1/4, 3000: 1/4},
    45: {0: 1/3, 1000: 1/4, 2000: 1/4, 3000: 1/4},
    60: {0: 1/4, 1000: 1/4, 2000: 1/4, 3000: 1/4}
}

CORONA_OUTER_3R = {
    0: {0: 15540.0, 1000: 960.0, 2000: 180.0, 3000: 60.0},
    5: {0: 7.0, 1000: 4.0, 2000: 2.0, 3000: 2.0},
    10: {0: 2.0, 1000: 1.0, 2000: 1.0, 3000: 1.0},
    15: {0: 1.0, 1000: 1.0, 2000: 1.0, 3000: 1/1.3},
    30: {0: 1/1.3, 1000: 1/1.3, 2000: 1/1.6, 3000: 1/1.6},
    45: {0: 1/1.3, 1000: 1/1.6, 2000: 1/1.6, 3000: 1/1.6},
    60: {0: 1/1.6, 1000: 1/1.6, 2000: 1/1.6, 3000: 1/1.6}
}

CORONA_OUTER_4R = {
    0: {0: 31080.0, 1000: 1920.0, 2000: 360.0, 3000: 120.0},
    5: {0: 14.0, 1000: 7.0, 2000: 5.0, 3000: 3.0},
    10: {0: 4.0, 1000: 3.0, 2000: 2.0, 3000: 2.0},
    15: {0: 3.0, 1000: 2.0, 2000: 2.0, 3000: 2.0},
    30: {0: 2.0, 1000: 1.0, 2000: 1.0, 3000: 1.0},
    45: {0: 1.0, 1000: 1.0, 2000: 1.0, 3000: 1.0},
    60: {0: 1.0, 1000: 1.0, 2000: 1.0, 3000: 1.0}
}

CORONA_OUTER_8R = {
    0: {0: 77700.0, 1000: 4800.0, 2000: 900.0, 3000: 300.0},
    5: {0: 36.0, 1000: 18.0, 2000: 11.0, 3000: 9.0},
    10: {0: 11.0, 1000: 7.0, 2000: 6.0, 3000: 5.0},
    15: {0: 7.0, 1000: 5.0, 2000: 4.0, 3000: 4.0},
    30: {0: 4.0, 1000: 4.0, 2000: 3.0, 3000: 3.0},
    45: {0: 4.0, 1000: 3.0, 2000: 3.0, 3000: 3.0},
    60: {0: 3.0, 1000: 3.0, 2000: 3.0, 3000: 3.0}
}

DIAMOND_RING = {
    0: {0: 180.0, 1000: 12.0, 2000: 2, 3000: 1/1.3},
    5: {0: 1/13, 1000: 1/25, 2000: 1/40, 3000: 1/50},
    10: {0: 1/40, 1000: 1/60, 2000: 1/80, 3000: 1/80},
    15: {0: 1/60, 1000: 1/80, 2000: 1/100, 3000: 1/100},
    30: {0: 1/100, 1000: 1/100, 2000: 1/125, 3000: 1/125},
    45: {0: 1/125, 1000: 1/125, 2000: 1/125, 3000: 1/125},
    60: {0: 1/125, 1000: 1/125, 2000: 1/125, 3000: 1/125}
}

EARTHSHINE = {
    0: {0: 172680.0, 1000: 10740.0, 2000: 2040.0, 3000: 720.0},  # 2878m, 179m, 34m, 12m
    5: {0: 60.0, 1000: 39.0, 2000: 25.0, 3000: 19.0},
    10: {0: 24.0, 1000: 16.0, 2000: 13.0, 3000: 11.0},
    15: {0: 15.0, 1000: 11.0, 2000: 10.0, 3000: 9.0},
    30: {0: 9.0, 1000: 8.0, 2000: 7.0, 3000: 7.0},
    45: {0: 8.0, 1000: 7.0, 2000: 7.0, 3000: 7.0},
    60: {0: 7.0, 1000: 7.0, 2000: 7.0, 3000: 6.0}
}


# Phenomenon name mapping
EXPOSURE_TABLES = {
    "partial_nd5": PARTIAL_PHASE_ND_5_0,
    "partial_nd4": PARTIAL_PHASE_ND_4_0,
    "bailys_beads": BAILYS_BEADS,
    "chromosphere": CHROMOSPHERE,
    "prominences": PROMINENCES,
    "corona_lower": CORONA_LOWER,
    "corona_inner_0.2R": CORONA_INNER_02R,
    "corona_inner_0.5R": CORONA_INNER_05R,
    "corona_middle": CORONA_MIDDLE,
    "corona_upper": CORONA_UPPER,
    "corona_outer_3R": CORONA_OUTER_3R,
    "corona_outer_4R": CORONA_OUTER_4R,
    "corona_outer_8R": CORONA_OUTER_8R,
    "diamond_ring": DIAMOND_RING,
    "earthshine": EARTHSHINE
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
    # Select appropriate table based on phenomenon and filter
    if phenomenon.startswith("partial") and nd_filter:
        if nd_filter >= 4.5:
            table_key = "partial_nd5"
        else:
            table_key = "partial_nd4"
    else:
        table_key = phenomenon
    
    if table_key not in EXPOSURE_TABLES:
        raise ValueError(f"Unknown phenomenon: {phenomenon}")
    
    lookup_table = EXPOSURE_TABLES[table_key]
    
    # Get base exposure (ISO 100, f/8)
    base_exposure = _interpolate_2d(sun_altitude_deg, observer_altitude_m, lookup_table)
    
    # Adjust for ISO (ISO doubling = exposure halving)
    iso_factor = 100.0 / iso
    
    # Adjust for aperture (each stop = 2x light)
    # f/8 is base, so f/5.6 (one stop wider) = 2x light = 0.5x exposure
    # f/11 (one stop narrower) = 0.5x light = 2x exposure
    # Aperture area ∝ 1/f²
    aperture_factor = (aperture / 8.0) ** 2
    
    # Adjust for ND filter (if not already in base table)
    nd_factor = 1.0
    if nd_filter and not phenomenon.startswith("partial"):
        nd_factor = 10 ** (-nd_filter)
    
    # Calculate final exposure
    exposure = base_exposure * iso_factor * aperture_factor * nd_factor
    
    return exposure


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
