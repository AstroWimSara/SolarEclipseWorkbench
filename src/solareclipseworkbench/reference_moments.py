"""
Reference moments of a solar eclipse:

    - C1: First contact;
    - C2: Second contact;
    - C3: Third contact;
    - C4: Fourth contact;
    - MAX: Maximum eclipse.
"""
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import astronomy
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astronomy import SearchLocalSolarEclipse
import astropy.units as u
from skyfield import almanac
from skyfield.api import load, wgs84, Topos
from skyfield.units import Angle
import yaml
from timezonefinder import TimezoneFinder


class ReferenceMomentInfo:

    def __init__(self, time_utc: datetime, azimuth: Angle, altitude: float, timezone: pytz.timezone):
        """ Keep information for the reference moments.

        Args:
            - time_utc: Time of the reference moment [UTC]
            - time_local: Local time of the reference moment.
            - azimuth: Azimuth of the sun at this time.
            - altitude: Altitude of the sun at this time.
        """

        self.time_utc = time_utc
        self.time_local = self.time_utc.astimezone(timezone)

        self.azimuth = azimuth.degrees
        self.altitude = altitude


def read_reference_moments(
        filename="/Users/sara/private/solareclipseworkbench/softwareDevelopment/solareclipseworkbench/config/reference_moments.yaml") -> dict:
    """ Read the reference moments of the solar eclipse from the given file.

    The reference moments of a solar eclipse are the following:

        - C1: First contact;
        - C2: Second contact;
        - C3: Third contact;
        - C4: Fourth contact;
        - MAX: Maximum eclipse.

    In the file, they are specified in the format dd/MM/yyyy HH:mm:ss.S (local time).

    Args:
        - filename: Filename of the YAML file in which the reference moments are listed

    Returns: Dictionary with the reference moments of the solar eclipse, as datetime objects.
    """

    reference_moments = yaml.safe_load(Path(filename).read_text())["reference_moments"]

    for (key, value) in reference_moments.items():
        reference_moments[key] = datetime.strptime(value, "%d/%m/%Y %H:%M:%S.%f")

    return reference_moments


def calculate_reference_moments(longitude: float, latitude: float, altitude: float, time: Time) -> (dict, int, str):
    """ Calculate the reference moments of the solar eclipse and return as a dictionary.

    The reference moments of a solar eclipse are the following:

        - sunrise: Moment of sun rise;
        - C1: First contact;
        - C2: Second contact;
        - C3: Third contact;
        - C4: Fourth contact;
        - MAX: Maximum eclipse;
        - sunset: Moment of sun set.

    Args:
        - longitude: Longitude of the location [degrees]
        - latitude: Latitude of the location [degrees]
        - altitude: Altitude of the location [m]
        - time: Date of the eclipse [yyyy-mm-dd]

    Returns: Dictionary with the reference moments of the solar eclipse, as datetime objects.
    """
    tf = TimezoneFinder()
    timezone = pytz.timezone(tf.timezone_at(lng=longitude, lat=latitude))

    location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=altitude * u.m)

    astronomy_time = astronomy.Time.Parse(time.isot + 'Z')
    observer = astronomy.Observer(latitude, longitude)
    start_time = astronomy_time

    eclipse = SearchLocalSolarEclipse(start_time, observer)

    eph = load("de421.bsp")
    ts = load.timescale()

    earth = eph["Earth"]
    sun_ephem = eph['Sun']

    place = wgs84.latlon(location.lat.value, location.lon.value, location.height.value)
    loc = Topos(location.lat.value, location.lon.value, elevation_m=location.height.value)
    observer = eph['Earth'] + place

    date = ts.utc(time.datetime.year, time.datetime.month, time.datetime.day, 4)

    sunrise, y = almanac.find_risings(observer, sun_ephem, date, date + 1)
    sunset, y = almanac.find_settings(observer, sun_ephem, date, date + 1)
    timings = {}
    alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, sunrise.utc_datetime()[0])
    sunrise = ReferenceMomentInfo(sunrise.utc_datetime()[0], az, alt.degrees, timezone)
    timings['sunrise'] = sunrise

    alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, sunset.utc_datetime()[0])
    sunset = ReferenceMomentInfo(sunset.utc_datetime()[0], az, alt.degrees, timezone)
    timings['sunset'] = sunset

    if str(eclipse.partial_begin.time)[:10] != str(time)[:10]:
        return timings, 0, 'No eclipse'

    # Check if altitude at one of the moments is > 0.0
    if eclipse.peak.altitude > 0.0 or eclipse.start_partial.altitude > 0.0 or eclipse.end_partial > 0.0:
        alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, eclipse.partial_begin.time.Utc())
        c1 = ReferenceMomentInfo(eclipse.partial_begin.time.Utc().replace(tzinfo=pytz.UTC), az,
                                 eclipse.partial_begin.altitude, timezone)
        timings["C1"] = c1

        if eclipse.total_begin is not None:
            alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, eclipse.total_begin.time.Utc())
            c2 = ReferenceMomentInfo(eclipse.total_begin.time.Utc().replace(tzinfo=pytz.UTC), az,
                                     eclipse.total_begin.altitude, timezone)
            timings["C2"] = c2

        alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, eclipse.peak.time.Utc())
        max_eclipse = ReferenceMomentInfo(eclipse.peak.time.Utc().replace(tzinfo=pytz.UTC), az, eclipse.peak.altitude,
                                          timezone)
        timings["MAX"] = max_eclipse

        if eclipse.total_end is not None:
            alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, eclipse.total_end.time.Utc())
            c3 = ReferenceMomentInfo(eclipse.total_end.time.Utc().replace(tzinfo=pytz.UTC), az,
                                     eclipse.total_end.altitude, timezone)
            timings["C3"] = c3
            timings["duration"] = eclipse.total_end.time.Utc() - eclipse.total_begin.time.Utc()

        alt, az = __calculate_alt_az(ts, earth, sun_ephem, loc, eclipse.partial_end.time.Utc())
        c4 = ReferenceMomentInfo(eclipse.partial_end.time.Utc().replace(tzinfo=pytz.UTC), az,
                                 eclipse.partial_end.altitude, timezone)
        timings["C4"] = c4

        return timings, eclipse.obscuration, eclipse.kind.name
    else:
        return timings, 0, 'No eclipse'


def __calculate_alt_az(ts, earth, sun_ephem, loc, timing):
    astro = (earth + loc).at(
        ts.utc(timing.year, timing.month, timing.day, timing.hour, timing.minute, timing.second)).observe(sun_ephem)
    app = astro.apparent()

    alt, az, distance = app.altaz()
    return alt, az


def main():
    eclipse_date = Time('2024-04-08')
    # eclipse_date = Time('2024-10-02')
    timings, magnitude, eclipse_type = calculate_reference_moments(-104.63525, 24.01491, 1877.3, eclipse_date)
    # timings, magnitude, type = calculate_reference_moments(-75.18647, -47.29000, 1877.3, eclipse_date)
    print("Type: ", eclipse_type)
    print("Magnitude: ", magnitude)
    print("")
    print("{:<10} {:<25} {:<25} {:<25} {:<25}".format("Moment", "UTC", "Local time", "Azimuth", "Altitude"))
    print(
        "------------------------------------------------------------------------------------------------------------")
    for key, value in timings.items():
        if value.__class__ == ReferenceMomentInfo:
            print("{:<10} {:<25} {:<25} {:<25} {:<25}".format(key, value.time_utc.strftime("%m/%d/%Y %H:%M:%S"),
                                                              value.time_local.strftime("%m/%d/%Y %H:%M:%S"),
                                                              value.azimuth, value.altitude))
        else:
            print("{:<10} {:<25}".format(key, str(value)))


if __name__ == "__main__":
    main()
