"""
Reference moments of a solar eclipse:

    - C1: First contact;
    - C2: Second contact;
    - C3: Third contact;
    - C4: Fourth contact;
    - MAX: Maximum eclipse.
"""
import logging
import math
from datetime import datetime, timedelta

import astropy.units as u
import pytz
from astropy.coordinates import EarthLocation
from astropy.time import Time
from skyfield import almanac
from skyfield.api import load, wgs84, Topos
from skyfield.units import Angle
from timezonefinder import TimezoneFinder
from solareclipseworkbench.limb_correction import bead_reference_moments
from solareclipseworkbench.solar_eclipse import get_local_circumstances

def ut_to_hms(ut):
    hours = int(ut)
    minutes = int((ut - hours) * 60)
    seconds = ((ut - hours) * 60 - minutes) * 60
    return hours, minutes, seconds


def _ut_to_datetime(time: Time, ut: float) -> datetime:
    """ UTC datetime of a moment given in hours UT from midnight of the eclipse date.

    Near midnight UT a contact can fall on the previous or the next day (ut < 0 or ut >= 24), e.g. C1 of the
    2038-12-26 eclipse in Australia; datetime() would reject those hours.
    """
    days = math.floor(ut / 24)
    ut -= 24 * days
    if ut >= 24:    # Rounding of a tiny negative ut
        ut -= 24
        days += 1
    hours, minutes, seconds = ut_to_hms(ut)
    return datetime(time.datetime.year, time.datetime.month, time.datetime.day,
                    hours, minutes, int(seconds), int((seconds - int(seconds)) * 1_000_000)).replace(
        tzinfo=pytz.UTC) + timedelta(days=days)

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
                    # Near the date line or the poles the probe point would fall outside the valid range, which
                    # timezonefinder rejects with a ValueError: wrap the longitude and clamp the latitude.
                    probe_lng = (longitude + dlng + 180.0) % 360.0 - 180.0
                    probe_lat = max(-90.0, min(90.0, latitude + dlat))
                    tz_name = tf.timezone_at_land(lng=probe_lng, lat=probe_lat)
                    if tz_name:
                        return tz_name
    if tz_name:
        return tz_name
    # Open ocean: use the nautical time zone of this longitude rather than UTC.  With UTC, far from Greenwich the
    # "local day" searched for sunrise and sunset is not the observer's day, and sunrise could come out after
    # sunset (e.g. 160°W), so every eclipse moment would look as if the sun was down.  Note the POSIX sign
    # convention of the Etc zones: Etc/GMT+10 is UTC-10.
    offset = int(round(((longitude + 180.0) % 360.0 - 180.0) / 15.0))
    if offset == 0:
        return 'UTC'
    return f'Etc/GMT{-offset:+d}'


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

    sunrise_time = _sun_event(almanac.find_risings, observer, sun_ephem, ts, earth, loc, date, eclipse_utc,
                              midnight_sun=local_midnight)
    sunset_time = _sun_event(almanac.find_settings, observer, sun_ephem, ts, earth, loc, date, eclipse_utc,
                             midnight_sun=local_midnight + timedelta(days=1))
    timings = {}
    alt, az, apparent_alt = __calculate_alt_az(ts, earth, sun_ephem, loc, sunrise_time)
    sunrise = ReferenceMomentInfo(sunrise_time, az, alt.degrees, timezone, apparent_alt.degrees)
    timings['sunrise'] = sunrise

    alt, az, apparent_alt = __calculate_alt_az(ts, earth, sun_ephem, loc, sunset_time)
    sunset = ReferenceMomentInfo(sunset_time, az, alt.degrees, timezone, apparent_alt.degrees)
    timings['sunset'] = sunset

    first_contact_alt, first_contact_az, first_contact_app = calculate_alt_az(earth, loc, result['ut_first_contact'], sun_ephem, time, ts)
    last_contact_alt, last_contact_az, last_contact_app = calculate_alt_az(earth, loc, result['ut_last_contact'], sun_ephem, time, ts)

    # Normalize altitudes to numeric degrees for comparison
    res_h_val = getattr(result['h'], 'degrees', result['h'])
    first_alt_val = getattr(first_contact_alt, 'degrees', first_contact_alt)
    last_alt_val = getattr(last_contact_alt, 'degrees', last_contact_alt)

    # Check if altitude at one of the moments is > 0.0
    if res_h_val > 0.0 or first_alt_val > 0.0 or last_alt_val > 0.0:
        c1 = ReferenceMomentInfo(_ut_to_datetime(time, result['ut_first_contact']),
                                                     first_contact_az, first_contact_alt.degrees, timezone, first_contact_app.degrees)
        timings["C1"] = c1

        if result['ut_second_contact'] != result['ut_third_contact']:
            second_contact_alt, second_contact_az, second_contact_app = calculate_alt_az(earth, loc, result['ut_second_contact'], sun_ephem,
                                                                   time, ts)
            c2 = ReferenceMomentInfo(_ut_to_datetime(time, result['ut_second_contact']),
                                     second_contact_az, second_contact_alt.degrees, timezone, second_contact_app.degrees)
            timings["C2"] = c2

        max_contact_alt, max_contact_az, max_contact_app = calculate_alt_az(earth, loc, result['ut_maximum'], sun_ephem,
                                                               time, ts)
        maximum = ReferenceMomentInfo(_ut_to_datetime(time, result['ut_maximum']),
                                 max_contact_az, max_contact_alt.degrees, timezone, max_contact_app.degrees)
        timings["MAX"] = maximum

        if result['ut_second_contact'] != result['ut_third_contact']:
            third_contact_alt, third_contact_az, third_contact_app = calculate_alt_az(earth, loc, result['ut_third_contact'], sun_ephem,
                                                                   time, ts)
            c3 = ReferenceMomentInfo(_ut_to_datetime(time, result['ut_third_contact']),
                                     third_contact_az, third_contact_alt.degrees, timezone, third_contact_app.degrees)
            timings["C3"] = c3

            timings["duration"] = timedelta(hours=(result['ut_third_contact'] - result['ut_second_contact']))
            mean_duration = timings["duration"]

            # Limb-corrected contacts and the bead windows around them, so a
            # burst can be scheduled on the diamond ring rather than on a
            # nominal contact.  Silently absent when the limb blob is not
            # installed; the mean-limb C2 and C3 above are always there.
            try:
                bead_moments = bead_reference_moments(
                    f"{time.datetime.year:04d}-{time.datetime.month:02d}-{time.datetime.day:02d}",
                    location.lat.value, location.lon.value, location.height.value)
            except Exception as exc:
                logging.warning("Could not compute the lunar limb corrections, "
                                "falling back to mean-limb contacts: %s", exc)
                bead_moments = {}

            # The corrected contacts take over the C2 and C3 names, and the
            # mean-limb ones keep theirs with _MEAN, so an existing script
            # benefits without being rewritten.
            for contact in ("C2", "C3"):
                if contact in bead_moments and contact in timings:
                    timings[f"{contact}_MEAN"] = timings[contact]

            for name, moment in bead_moments.items():
                if name.endswith("_STATUS"):
                    timings[name] = moment
                    continue
                near_c2 = "C2" in name
                azimuth = second_contact_az if near_c2 else third_contact_az
                altitude = second_contact_alt if near_c2 else third_contact_alt
                timings[name] = ReferenceMomentInfo(moment, azimuth, altitude.degrees, timezone)

            # Totality follows the contacts it is measured between.
            if "C2" in timings and "C3" in timings:
                timings["duration"] = timings["C3"].time_utc - timings["C2"].time_utc
                timings["duration_mean"] = mean_duration

        c4 = ReferenceMomentInfo(_ut_to_datetime(time, result['ut_last_contact']),
                                                     last_contact_az, last_contact_alt.degrees, timezone, last_contact_app.degrees)
        timings["C4"] = c4

        return timings, result['mag'], result['type']
    else:
        return timings, 0, 'No eclipse'


def calculate_alt_az(earth, loc, reference_moment, sun_ephem, time, ts):
    # Convert the first contact time to a datetime object
    first_contact_datetime = _ut_to_datetime(time, reference_moment)
    return __calculate_alt_az(ts, earth, sun_ephem, loc, first_contact_datetime)


def __calculate_alt_az(ts, earth, sun_ephem, loc, timing):
    """ Return the geometric altitude, the azimuth and the apparent (refracted) altitude of the sun. """
    astro = (earth + loc).at(ts.from_datetime(timing)).observe(sun_ephem)
    app = astro.apparent()

    alt, az, distance = app.altaz()
    apparent_alt, _, _ = app.altaz(temperature_C=10.0, pressure_mbar='standard')
    return alt, az, apparent_alt


def _sun_event(finder, observer, sun_ephem, ts, earth, loc, date, eclipse_utc, midnight_sun):
    """ UTC datetime of the sunrise or sunset (``finder``) on the local day that starts at ``date``.

    Far north or south the Sun may not cross the horizon that day.  Skyfield then returns the moment it comes
    closest to the horizon, flagged as not a real rising/setting.  In polar day (midnight sun) that moment would
    make the whole eclipse look as if it happened after sunset, so the day boundary ``midnight_sun`` is returned
    instead: the Sun is up all day.  In polar night the closest approach is kept, as before.
    """
    times, real = finder(observer, sun_ephem, date, date + 1)
    index = 0
    if len(times) == 0:
        # The event drifts just across the window edge (DST change, high latitude): look half a day further.
        times, real = finder(observer, sun_ephem, date + (-0.5), date + 1.5)
        if len(times) == 0:
            return midnight_sun.astimezone(pytz.UTC)
        moments = times.utc_datetime()
        index = min(range(len(moments)), key=lambda k: abs((moments[k] - eclipse_utc).total_seconds()))
    moment = times.utc_datetime()[index]
    if not real[index]:
        alt, _, _ = __calculate_alt_az(ts, earth, sun_ephem, loc, moment)
        # Skyfield's horizon for the Sun: upper limb on the refracted horizon
        if alt.degrees > -0.8333:
            return midnight_sun.astimezone(pytz.UTC)
    return moment


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
