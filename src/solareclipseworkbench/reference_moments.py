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


def calculate_reference_moments(longitude: float, latitude: float, altitude: float, date: str) -> dict:
    """ Calculate the reference moments of the solar eclipse and return as a dictionary.

    The reference moments of a solar eclipse are the following:

        - C1: First contact;
        - C2: Second contact;
        - C3: Third contact;
        - C4: Fourth contact;
        - MAX: Maximum eclipse.

    Args:
        - longitude: Longitude at which the solar eclipse will be observed [degrees]
        - latitude: Latitude at which the solar eclipse will be observed [degrees]
        - altitude: Altitude at which the solar eclipse will be observed [m]
        - date: Date at which the solar eclipse will be observed [dd/MM/yyyy]

    Returns: Dictionary with the reference moments of the solar eclipse, as datetime objects.
    """

    # TODO
    raise NotImplementedError
