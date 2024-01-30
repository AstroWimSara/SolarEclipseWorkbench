"""
Reference moments of a solar eclipse:

    - C1: First contact;
    - C2: Second contact;
    - C3: Third contact;
    - C4: Fourth contact;
    - MAX: Maximum eclipse.
"""
from datetime import datetime
from pathlib import Path

import pytz
from astropy.coordinates import EarthLocation
from astropy.time import Time
import numpy as np
import astropy.units as u
from astropy import coordinates, constants
from sunpy.coordinates import sun
from astropy.coordinates import solar_system_ephemeris
from skyfield import almanac
from skyfield.api import load, wgs84, Topos
from skyfield.units import Angle
import scipy
import yaml
from timezonefinder import TimezoneFinder

class ReferenceMomentInfo:

    def __init__(self, time_utc: datetime, azimuth: Angle, altitude: Angle, timezone: pytz.timezone):
        """ Keep information for the reference moments.

        Args:
            - time_utc: Time of the reference moment [UTC]
            - azimuth: Azimuth of the sun at this time.
            - altitude: Altitude of the sun at this time.
            - timezone: Timezone for the local time
        """

        self.time_utc = time_utc
        self.time_local = self.time_utc.astimezone(timezone)

        self.azimuth = azimuth.degrees
        self.altitude = altitude.degrees


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


def calculate_reference_moments(longitude: float, latitude: float, altitude: float, time: Time) -> dict:
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

    time_start = __calc_time_start(
        location=location,
        time_search_start=time,
        time_search_stop=time + 1 * u.day,
    )

    eph = load("de421.bsp")
    ts = load.timescale()

    earth = eph["Earth"]
    sunc = eph['Sun']

    place = wgs84.latlon(location.lat.value, location.lon.value, location.height.value)
    loc = Topos(location.lat.value, location.lon.value, elevation_m=location.height.value)
    observer = eph['Earth'] + place

    date = ts.utc(time.datetime.year, time.datetime.month, time.datetime.day, 4)

    sunrise, y = almanac.find_risings(observer, sunc, date, date + 1)
    sunset, y = almanac.find_settings(observer, sunc, date, date + 1)
    timings = {}
    alt, az = __calculate_alt_az(ts, earth, sunc, loc, sunrise.utc_datetime()[0])
    sunrise = ReferenceMomentInfo(sunrise.utc_datetime()[0], az, alt, timezone)
    timings['sunrise'] = sunrise

    alt, az = __calculate_alt_az(ts, earth, sunc, loc, sunset.utc_datetime()[0])
    sunset = ReferenceMomentInfo(sunset.utc_datetime()[0], az, alt, timezone)
    timings['sunset'] = sunset

    if time_start is None or time_start > sunset.time_utc:
        return timings, 0

    # Define an array of observation times centered around the time of interest
    times = time_start + np.concatenate([np.arange(-200, 14400) * u.s])
    # Create an observer coordinate for the time array
    observer = location.get_itrs(times)

    # Calculate the eclipse amounts using a JPL ephemeris
    with solar_system_ephemeris.set('de432s'):
        amount = sun.eclipse_amount(observer)
        amount_minimum = sun.eclipse_amount(observer, moon_radius='minimum')

    # Calculate the start/end points of partial/total solar eclipse
    partial = np.flatnonzero(amount > 0)

    if len(partial) > 0:
        start_partial, end_partial = times[partial[[0, -1]]]
        alt, az = __calculate_alt_az(ts, earth, sunc, loc, start_partial.datetime)
        c1 = ReferenceMomentInfo(start_partial.datetime.replace(tzinfo=pytz.UTC), az, alt, timezone)
        timings["C1"] = c1

        total = np.flatnonzero(amount_minimum == 1)
        if len(total) > 0:
            start_total, end_total = times[total[[0, -1]]]
            alt, az = __calculate_alt_az(ts, earth, sunc, loc, start_total.datetime)
            c2 = ReferenceMomentInfo(start_total.datetime.replace(tzinfo=pytz.UTC), az, alt, timezone)
            timings["C2"] = c2

            max_time = Time((start_total.unix + end_total.unix) / 2, format="unix").datetime
            alt, az = __calculate_alt_az(ts, earth, sunc, loc, max_time)
            max = ReferenceMomentInfo(max_time.replace(tzinfo=pytz.UTC), az, alt, timezone)
            timings["MAX"] = max

            alt, az = __calculate_alt_az(ts, earth, sunc, loc, end_total.datetime)
            c3 = ReferenceMomentInfo(end_total.datetime.replace(tzinfo=pytz.UTC), az, alt, timezone)
            timings["C3"] = c3

            timings["duration"] = (end_total - start_total).datetime
            max_time = (start_total.unix + end_total.unix) / 2
        else:
            max_time = Time((start_partial.unix + end_partial.unix) / 2, format="unix")
            alt, az = __calculate_alt_az(ts, earth, sunc, loc, max_time.datetime)
            max = ReferenceMomentInfo(max_time.datetime.replace(tzinfo=pytz.UTC), az, alt, timezone)
            timings["MAX"] = max

        max_loc = location.get_itrs(Time(max_time, format="unix"))
        magnitude = sun.eclipse_amount(max_loc).value / 100

        alt, az = __calculate_alt_az(ts, earth, sunc, loc, end_partial.datetime)
        c4 = ReferenceMomentInfo(end_partial.datetime.replace(tzinfo=pytz.UTC), az, alt, timezone)
        timings["C4"] = c4

    return timings, magnitude

def __calculate_alt_az(ts, earth, sunc, loc, timing):
    astro = (earth + loc).at(ts.utc(timing.year, timing.month, timing.day, timing.hour, timing.minute, timing.second)).observe(sunc)
    app = astro.apparent()

    alt, az, distance = app.altaz()
    return alt, az

def __calc_time_start(location: EarthLocation, time_search_start: Time, time_search_stop: Time) -> Time:
    """ Calculate the start time of the eclipse.

    Args:
        - location: Location of the observer (Longitude, Latitude, Elevation).
        - time_search_start: First day to start the search for an eclipse
        - time_search_stop: End day of the search for an eclipse

    Returns: Date and time of the start of the eclipse
    """

    solar_system_ephemeris.set("de432s")

    # If we're only looking for a partial eclipse, we can accept a coarser search grid
    step = 1 * u.hr
    
    # Define a grid of times to search for eclipses
    time = Time(np.arange(time_search_start, time_search_stop, step=step))

    # Find the times that are during an eclipse
    mask_eclipse = __distance_contact(location=location, time=time) < 0

    # Find the index of the first time that an eclipse is occuring
    index_start = np.argmax(mask_eclipse)
    if index_start > 0:
        # Search around that time to find when the eclipse actually starts
        time_eclipse_start = scipy.optimize.root_scalar(
            f=lambda t: __distance_contact(location, Time(t, format="unix")).value,
            bracket=[time[index_start - 1].unix, time[index_start].unix],
        ).root
        time_eclipse_start = Time(time_eclipse_start, format="unix")

        return Time(time_eclipse_start.isot)
    else:
        return None

def __distance_contact(location: EarthLocation, time: Time) -> u.Quantity:
    """ Calculate the distance between the sun and the moon

    Args:
        - location: Location of the observer (Longitude, Latitude, Elevation).
        - time: Time to use to calculate the distance between the sun and the moon

    Returns: Distance between sun and moon (in degrees)
    """

    radius_sun = constants.R_sun
    radius_moon = 1737.4 * u.km

    coordinate_sun = coordinates.get_sun(time)
    coordinate_moon = coordinates.get_body("moon", time)

    frame_local = coordinates.AltAz(obstime=time, location=location)

    alt_az_sun = coordinate_sun.transform_to(frame_local)
    alt_az_moon = coordinate_moon.transform_to(frame_local)

    angular_radius_sun = np.arctan2(radius_sun, alt_az_sun.distance).to(u.deg)
    angular_radius_moon = np.arctan2(radius_moon, alt_az_moon.distance).to(u.deg)

    separation_max = angular_radius_moon + angular_radius_sun

    return (alt_az_moon.separation(alt_az_sun).deg * u.deg) - separation_max


def main():
    # Example
    eclipse_date = Time('2024-04-08')
    timings, magnitude = calculate_reference_moments(-104.63525, 24.01491, 1877.3, eclipse_date)
    print ("Magnitude: ", magnitude)
    print ("")
    print("{:<10} {:<25} {:<25} {:<25} {:<25}".format("Moment", "UTC", "Local time", "Azimuth", "Altitude"))
    print ("------------------------------------------------------------------------------------------------------------")
    for key, value in timings.items():
        if value.__class__ == ReferenceMomentInfo:
             print("{:<10} {:<25} {:<25} {:<25} {:<25}".format(key, value.time_utc.strftime("%m/%d/%Y %H:%M:%S"), value.time_local.strftime("%m/%d/%Y %H:%M:%S"), value.azimuth, value.altitude))
        else:
             print("{:<10} {:<25}".format(key, str(value)))


if __name__ == "__main__":
    main()
