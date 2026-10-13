"""
Reference moments of a solar eclipse:

    - C1: First contact;
    - C2: Second contact;
    - C3: Third contact;
    - C4: Fourth contact;
    - MAX: Maximum eclipse.
"""
from datetime import datetime, timedelta

import astropy.units as u
import pytz
from astropy.coordinates import EarthLocation
from astropy.time import Time
from skyfield import almanac
from skyfield.api import load, wgs84, Topos
from skyfield.units import Angle
from timezonefinder import TimezoneFinder
from solareclipseworkbench.solar_eclipse import get_local_circumstances

def ut_to_hms(ut):
    hours = int(ut)
    minutes = int((ut - hours) * 60)
    seconds = ((ut - hours) * 60 - minutes) * 60
    return hours, minutes, seconds

class ReferenceMomentInfo:

    def __init__(self, time_utc: datetime, azimuth: Angle, altitude: float, timezone: pytz.timezone,
                 apparent_altitude: float = None):
        """ Keep information for the reference moments.

        Args:
            - time_utc: Time of the reference moment [UTC]
            - time_local: Local time of the reference moment.
            - azimuth: Azimuth of the sun at this time.
            - altitude: Geometric altitude of the sun's centre at this time (no refraction), used for exposures.
            - apparent_altitude: Altitude of the sun's centre as seen, i.e. with atmospheric refraction.  This is
              what is displayed.  At sunrise and sunset it is about -0.27°: the upper limb touches the horizon.
        """

        self.time_utc = time_utc
        self.time_local = self.time_utc.astimezone(timezone)

        self.azimuth = azimuth.degrees
        self.altitude = altitude
        self.apparent_altitude = altitude if apparent_altitude is None else apparent_altitude


def _find_timezone(longitude: float, latitude: float) -> str:
    """Return the best timezone name for the given coordinates.

    For land locations, timezone_at_land() gives a direct result.
    For sea/ocean locations it returns None, so nearby land points are
    scanned in expanding steps until a land timezone is found.
    Falls back to 'UTC' only if no land timezone can be determined.
    """
    tf = TimezoneFinder()
    tz_name = tf.timezone_at_land(lng=longitude, lat=latitude)
    if tz_name is None:
        for step in [0.5, 1.0, 2.0, 3.0, 5.0]:
            for dlat in [-step, 0, step]:
                for dlng in [-step, 0, step]:
                    if dlat == 0 and dlng == 0:
                        continue
                    tz_name = tf.timezone_at_land(lng=longitude + dlng, lat=latitude + dlat)
                    if tz_name:
                        return tz_name
    return tz_name or 'UTC'


def calculate_reference_moments(longitude: float, latitude: float, altitude: float, time: Time) -> (dict, int, str):
    """ Calculate the reference moments of the solar eclipse and return as a dictionary.

    The reference moments of a solar eclipse are the following:

        - sunrise: Moment of sun rise;
        - C1: First contact;
        - C2: Second contact;
        - C3: Third contact;
        - C4: Fourth contact;
        - MAX: Maximum eclipse;
        - duration: Duration of the eclipse;
        - sunset: Moment of sun set.

    Args:
        - longitude: Longitude of the location [degrees]
        - latitude: Latitude of the location [degrees]
        - altitude: Altitude of the location [m]
        - time: Date of the eclipse [yyyy-mm-dd]

    Returns: Dictionary with the reference moments of the solar eclipse, as datetime objects.
    """
    timezone = pytz.timezone(_find_timezone(longitude, latitude))

    location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=altitude * u.m)

    # Get time as YYYY-MM-DD
    timestr = str(time).split(' ')[0]
    result = get_local_circumstances(latitude, longitude, altitude, timestr)

    eph = load("de421.bsp")
    ts = load.timescale()

    earth = eph["Earth"]
    sun_ephem = eph['Sun']

    place = wgs84.latlon(location.lat.value, location.lon.value, location.height.value)
    loc = Topos(location.lat.value, location.lon.value, elevation_m=location.height.value)
    observer = eph['Earth'] + place

    # Search sunrise/sunset over the local calendar day of the eclipse (local midnight to local midnight).  A fixed
    # UTC window picks the wrong day far from Greenwich, e.g. the next morning's sunrise in Australia.
    eclipse_utc = datetime(time.datetime.year, time.datetime.month, time.datetime.day, tzinfo=pytz.UTC) \
        + timedelta(hours=result['ut_maximum'])
    local_midnight = timezone.localize(datetime.combine(eclipse_utc.astimezone(timezone).date(), datetime.min.time()))
    date = ts.from_datetime(local_midnight)

    sunrise, y = almanac.find_risings(observer, sun_ephem, date, date + 1)
    sunset, y = almanac.find_settings(observer, sun_ephem, date, date + 1)
    timings = {}
    alt, az, apparent_alt = __calculate_alt_az(ts, earth, sun_ephem, loc, sunrise.utc_datetime()[0])
    sunrise = ReferenceMomentInfo(sunrise.utc_datetime()[0], az, alt.degrees, timezone, apparent_alt.degrees)
    timings['sunrise'] = sunrise

    alt, az, apparent_alt = __calculate_alt_az(ts, earth, sun_ephem, loc, sunset.utc_datetime()[0])
    sunset = ReferenceMomentInfo(sunset.utc_datetime()[0], az, alt.degrees, timezone, apparent_alt.degrees)
    timings['sunset'] = sunset

    first_contact_alt, first_contact_az, first_contact_app = calculate_alt_az(earth, loc, result['ut_first_contact'], sun_ephem, time, ts)
    last_contact_alt, last_contact_az, last_contact_app = calculate_alt_az(earth, loc, result['ut_last_contact'], sun_ephem, time, ts)

    # Normalize altitudes to numeric degrees for comparison
    res_h_val = getattr(result['h'], 'degrees', result['h'])
    first_alt_val = getattr(first_contact_alt, 'degrees', first_contact_alt)
    last_alt_val = getattr(last_contact_alt, 'degrees', last_contact_alt)

    # Check if altitude at one of the moments is > 0.0
    if res_h_val > 0.0 or first_alt_val > 0.0 or last_alt_val > 0.0:
        sc_h, sc_m, sc_s = ut_to_hms(result['ut_first_contact'])
        sc_microseconds = int((sc_s - int(sc_s)) * 1_000_000)

        c1 = ReferenceMomentInfo(datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                                                     sc_h, sc_m, int(sc_s), sc_microseconds).replace(tzinfo=pytz.UTC),
                                                     first_contact_az, first_contact_alt.degrees, timezone, first_contact_app.degrees)
        timings["C1"] = c1

        if result['ut_second_contact'] != result['ut_third_contact']:
            second_contact_alt, second_contact_az, second_contact_app = calculate_alt_az(earth, loc, result['ut_second_contact'], sun_ephem,
                                                                   time, ts)
            sc_h, sc_m, sc_s = ut_to_hms(result['ut_second_contact'])
            sc_microseconds = int((sc_s - int(sc_s)) * 1_000_000)

            c2 = ReferenceMomentInfo(datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                                              sc_h, sc_m, int(sc_s), sc_microseconds).replace(tzinfo=pytz.UTC),
                                     second_contact_az, second_contact_alt.degrees, timezone, second_contact_app.degrees)
            timings["C2"] = c2

        max_contact_alt, max_contact_az, max_contact_app = calculate_alt_az(earth, loc, result['ut_maximum'], sun_ephem,
                                                               time, ts)
        sc_h, sc_m, sc_s = ut_to_hms(result['ut_maximum'])
        sc_microseconds = int((sc_s - int(sc_s)) * 1_000_000)

        maximum = ReferenceMomentInfo(datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                                          sc_h, sc_m, int(sc_s), sc_microseconds).replace(tzinfo=pytz.UTC),
                                 max_contact_az, max_contact_alt.degrees, timezone, max_contact_app.degrees)
        timings["MAX"] = maximum

        if result['ut_second_contact'] != result['ut_third_contact']:
            third_contact_alt, third_contact_az, third_contact_app = calculate_alt_az(earth, loc, result['ut_third_contact'], sun_ephem,
                                                                   time, ts)
            sc_h, sc_m, sc_s = ut_to_hms(result['ut_third_contact'])
            sc_microseconds = int((sc_s - int(sc_s)) * 1_000_000)

            c3 = ReferenceMomentInfo(datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                                              sc_h, sc_m, int(sc_s), sc_microseconds).replace(tzinfo=pytz.UTC),
                                     third_contact_az, third_contact_alt.degrees, timezone, third_contact_app.degrees)
            timings["C3"] = c3

            timings["duration"] = timedelta(hours=(result['ut_third_contact'] - result['ut_second_contact']))

        sc_h, sc_m, sc_s = ut_to_hms(result['ut_last_contact'])
        sc_microseconds = int((sc_s - int(sc_s)) * 1_000_000)

        c4 = ReferenceMomentInfo(datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                                                     sc_h, sc_m, int(sc_s), sc_microseconds).replace(tzinfo=pytz.UTC),
                                                     last_contact_az, last_contact_alt.degrees, timezone, last_contact_app.degrees)
        timings["C4"] = c4

        return timings, result['mag'], result['type']
    else:
        return timings, 0, 'No eclipse'


def calculate_alt_az(earth, loc, reference_moment, sun_ephem, time, ts):
    hours, minutes, seconds = ut_to_hms(reference_moment)
    # Convert the first contact time to a datetime object
    first_contact_datetime = datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                                      hours, minutes, int(seconds), int((seconds - int(seconds)) * 1_000_000)).replace(
        tzinfo=pytz.UTC)
    return __calculate_alt_az(ts, earth, sun_ephem, loc, first_contact_datetime)


def __calculate_alt_az(ts, earth, sun_ephem, loc, timing):
    """ Return the geometric altitude, the azimuth and the apparent (refracted) altitude of the sun. """
    astro = (earth + loc).at(ts.from_datetime(timing)).observe(sun_ephem)
    app = astro.apparent()

    alt, az, distance = app.altaz()
    apparent_alt, _, _ = app.altaz(temperature_C=10.0, pressure_mbar='standard')
    return alt, az, apparent_alt


def main():
    eclipse_date = Time('2026-08-12')
    # eclipse_date = Time('2005-10-03')
    # timings, magnitude, eclipse_type = calculate_reference_moments(-4.14506554482961, 40.58805075678097, 828, eclipse_date)

    timings, magnitude, eclipse_type = calculate_reference_moments(-3.9852, 41.6669, 828, eclipse_date)
    # timings, magnitude, type = calculate_reference_moments(-75.18647, -47.29000, 1877.3, eclipse_date)
    print("Type: ", eclipse_type)
    print("Magnitude: ", magnitude)
    print("")
    print("{:<10} {:<25} {:<25} {:<25} {:<25}".format("Moment", "UTC", "Local time", "Azimuth", "Apparent altitude"))
    print(
        "------------------------------------------------------------------------------------------------------------")
    for key, value in timings.items():
        if value.__class__ == ReferenceMomentInfo:
            # Also show microseconds in the UTC and local time
            print("{:<10} {:<25} {:<25} {:<25} {:<25}".format(key, value.time_utc.strftime("%m/%d/%Y %H:%M:%S.%f"),
                                                              value.time_local.strftime("%m/%d/%Y %H:%M:%S.%f"),
                                                              value.azimuth, value.apparent_altitude))
        else:
            print("{:<10} {:<25}".format(key, str(value)))


if __name__ == "__main__":
    main()
