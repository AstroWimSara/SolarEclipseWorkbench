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

from astropy.coordinates import EarthLocation
from astropy.time import Time
import numpy as np
import astropy.units as u
from astropy import coordinates, constants
from sunpy.coordinates import sun
from astropy.coordinates import solar_system_ephemeris
import scipy
import yaml


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


def calculate_reference_moments(location: EarthLocation, time: Time) -> dict:
    """ Calculate the reference moments of the solar eclipse and return as a dictionary.

    The reference moments of a solar eclipse are the following:

        - C1: First contact;
        - C2: Second contact;
        - C3: Third contact;
        - C4: Fourth contact;
        - MAX: Maximum eclipse.

    Args:
        - location: Location of the observer (longitude [°], latitude [°], elevation [m])
        - time: Date of the eclipse [yyyy-mm-dd]

    Returns: Dictionary with the reference moments of the solar eclipse, as datetime objects.
    """

    time_start = __calc_time_start(
        location=location,
        time_search_start=time,
        time_search_stop=time + 1,
    )

    if time_start is None:
        return {}

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
    timings = {}
    if len(partial) > 0:
        start_partial, end_partial = times[partial[[0, -1]]]
        timings["C1"] = start_partial.isot

        total = np.flatnonzero(amount_minimum == 1)
        if len(total) > 0:
            start_total, end_total = times[total[[0, -1]]]
            timings["C2"] = start_total.isot
            timings["MAX"] = Time((start_total.unix + end_total.unix) / 2, format="unix").isot
            timings["C3"] = end_total.isot
        timings["C4"] = end_partial.isot

    return timings

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
    location = EarthLocation(lat=24.01491 * u.deg, lon=-104.63525 * u.deg, height=1877.3 * u.m)
    eclipse_date = Time('2024-04-08')
    print (calculate_reference_moments(location, eclipse_date))

if __name__ == "__main__":
    main()
