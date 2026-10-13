from astropy.time import Time

from solareclipseworkbench.reference_moments import calculate_reference_moments


def _assert_sunrise_sunset_on_eclipse_day(timings):
    eclipse_day = timings["MAX"].time_local.date()
    assert timings["sunrise"].time_local.date() == eclipse_day
    assert timings["sunset"].time_local.date() == eclipse_day
    assert timings["sunrise"].time_utc < timings["MAX"].time_utc < timings["sunset"].time_utc


def test_sunrise_sunset_far_east():
    # Sydney, UTC+10: a fixed UTC search window used to return the next morning's sunrise.
    timings, _, _ = calculate_reference_moments(151.21, -33.87, 50, Time("2028-07-22"))
    _assert_sunrise_sunset_on_eclipse_day(timings)


def test_sunrise_sunset_far_west():
    # Mazatlán, UTC-7: local sunset falls on the next UTC day.
    timings, _, _ = calculate_reference_moments(-106.41, 23.25, 10, Time("2024-04-08"))
    _assert_sunrise_sunset_on_eclipse_day(timings)


def test_sunset_is_standard_upper_limb_definition():
    # Sunset is when the refracted upper limb touches the horizon, i.e. the geometric altitude of the sun's centre
    # is about -0.833° (34' refraction + 16' semi-diameter), as in almanacs, NOAA and Stellarium.
    timings, _, _ = calculate_reference_moments(-3.9852, 41.6669, 828, Time("2026-08-12"))
    assert abs(timings["sunset"].altitude + 0.8333) < 0.01
    assert abs(timings["sunrise"].altitude + 0.8333) < 0.01
    # The displayed (refracted) altitude of the centre is then about minus the semi-diameter.
    assert -0.35 < timings["sunset"].apparent_altitude < -0.2
