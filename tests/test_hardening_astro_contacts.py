"""Regression tests for eclipses and places at the edges of the astronomical code.

- Greatest eclipse at 23:30 TD or later: the element generator was asked for hour "24:00:00" and crashed.
- Contacts before 0h or after 24h UT: building their datetime crashed ("minute must be in 0..59").
- Ocean near the date line: the timezone search probed longitudes beyond ±180° and crashed.
- Open ocean far from Greenwich: the UTC fallback timezone put sunrise after sunset.
- Midnight sun: sunrise and sunset were both the moment of lowest sun, so the eclipse looked after sunset.
"""
import csv
import os
from datetime import datetime, timedelta, timezone

import pytz
import pytest
from astropy.time import Time

from solareclipseworkbench import solar_eclipse
from solareclipseworkbench.reference_moments import (_find_timezone, _ut_to_datetime, calculate_reference_moments,
                                                     ut_to_hms)


def _catalogue_row(date):
    path = os.path.join(os.path.dirname(solar_eclipse.__file__), "eclipse_besselian.csv")
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}" == date:
                return row
    raise LookupError(date)


@pytest.mark.parametrize("date", ["2012-05-20", "2045-02-16"])
def test_greatest_eclipse_just_before_midnight(date):
    elements = solar_eclipse.get_element_coeffs(date)
    # Catalogue t0 = 0 means 00:00 of the next day: on the catalogue date that is hour 24
    assert elements["T0"] == 24

    row = _catalogue_row(date)
    h, m, s = map(int, row["td_ge"].split(":"))
    circumstances = solar_eclipse.get_local_circumstances(float(row["lat_dd_ge"]), float(row["lng_dd_ge"]), 0, date)
    expected_ut = h + m / 60 + s / 3600 - elements["Δt"] / 3600
    # On the catalogue date, not a day early (and within the Δt difference with the catalogue)
    assert abs(circumstances["ut_maximum"] - expected_ut) < 2 / 60


def test_ut_to_datetime_wraps_to_neighbouring_days():
    day = Time("2038-12-26")
    assert _ut_to_datetime(day, -0.5) == datetime(2038, 12, 25, 23, 30, tzinfo=timezone.utc)
    assert _ut_to_datetime(day, 24.25) == datetime(2038, 12, 27, 0, 15, tzinfo=timezone.utc)
    assert _ut_to_datetime(day, -1e-17).date() in (datetime(2038, 12, 25).date(), datetime(2038, 12, 26).date())


def test_ut_to_datetime_unchanged_within_the_day():
    day = Time("2026-08-12")
    for ut in (0.0, 1.2345678, 17.3388888, 23.9999):
        h, m, s = ut_to_hms(ut)
        old = datetime(2026, 8, 12, h, m, int(s), int((s - int(s)) * 1_000_000)).replace(tzinfo=pytz.UTC)
        assert _ut_to_datetime(day, ut) == old


@pytest.mark.parametrize("longitude, latitude", [(179.9, -10.0), (-179.9, 60.0), (180.0, 0.0), (0.0, 89.9)])
def test_timezone_search_near_date_line_and_poles(longitude, latitude):
    pytz.timezone(_find_timezone(longitude, latitude))


def test_ocean_timezone_follows_longitude():
    name = _find_timezone(-160.0, -25.0)
    assert pytz.timezone(name).utcoffset(datetime(2045, 2, 16)) == timedelta(hours=-11)


def test_contacts_across_midnight_utc():
    # Tasmania, 2038-12-26: C1 is on 25 December UTC
    timings, _, _ = calculate_reference_moments(147.0, -42.0, 0, Time("2038-12-26"))
    assert timings["C1"].time_utc.date() == datetime(2038, 12, 25).date()
    assert timings["sunrise"].time_utc < timings["C1"].time_utc < timings["MAX"].time_utc \
        < timings["C4"].time_utc < timings["sunset"].time_utc


def test_sunrise_before_sunset_in_the_open_ocean():
    # 2045-02-16, mid-Pacific: the C4 contact is on 17 February UTC
    timings, _, _ = calculate_reference_moments(-160.0, -25.0, 0, Time("2045-02-16"))
    assert timings["sunrise"].time_utc < timings["MAX"].time_utc < timings["sunset"].time_utc
    assert timings["C4"].time_utc.date() == datetime(2045, 2, 17).date()


def test_midnight_sun_keeps_the_eclipse_in_daylight():
    # 80°N on 2026-08-12: the Sun does not set
    timings, _, eclipse_type = calculate_reference_moments(-20.0, 80.0, 0, Time("2026-08-12"))
    assert "C1" in timings and "C4" in timings
    assert timings["sunrise"].time_utc <= timings["C1"].time_utc
    assert timings["C4"].time_utc <= timings["sunset"].time_utc
