"""
Physical constants shared across the package.

Keep values in SI units (meters) to avoid ambiguity.
"""
# Default solar radius in meters: 959.95" at 1 au (Quaglia et al. 2021).  The
# radius actually used for the contact times can be changed by the user; read
# it with solareclipseworkbench.solar_radius.get_radius_m(), which also explains
# why this value is the default.
SUN_RADIUS = SOLAR_RADIUS = 696221300

# Moon radius in meters
MOON_RADIUS = LUNAR_RADIUS = 1_737.4 * 1_000

# Earth radius in meters
EARTH_RADIUS = 6.3781e6
