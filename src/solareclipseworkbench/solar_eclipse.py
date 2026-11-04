# Based on Greg Miller gmiller@gregmiller.net 2023 https://www.celestialprogramming.com/
# Functions for computing solar eclipses.
# Algorithms from various sources including:
# - A Manual of Spherical and Practical Astronomy - Chauvenet 1863
# - The Mathematical Theory of Eclipses According to Chauvenet's Transformation of Bessel's Method - Buchanan 1904
# - Explanatory Supplement to the Astronomical Ephemeris 1961
# - Explanatory Supplement to the Astronomical Almanac 1992
# - Elements of Solar Eclipses - Meeus 1989
# - Prediction and Analysis of Solar Eclipse Circumstances - Williams 1971

import math
import csv
import os
from datetime import datetime

from astropy.time import Time
from astropy.utils.iers import conf

from solareclipseworkbench.besselian_element_generator import BesselianElementGenerator

rad = math.pi / 180
max_iterations = 20

def solve_quadrant(sin, cos):
    """
    Determines the angle (in radians) from the given sine and cosine values, resolving the correct quadrant.

    Parameters:
        sin (float): Sine of the angle.
        cos (float): Cosine of the angle.

    Returns:
        float: Angle in radians, correctly placed in the appropriate quadrant.

    Description:
        This function computes the angle corresponding to the provided sine and cosine values, ensuring the result is in the correct quadrant. It is useful for trigonometric calculations where both sine and cosine are known, and quadrant ambiguity must be resolved.
    """
    if sin >= 0 and cos >= 0:
        return math.asin(sin)
    if sin < 0 <= cos:
        return math.asin(sin)
    if sin < 0 and cos < 0:
        return -math.acos(cos)
    if sin >= 0 > cos:
        return math.acos(cos)


def get_element_coeffs(date=None):
    """
    Reads basic information for solar eclipses from `eclipse_besselian.csv`, calculated the Besselian Elements and returns the coefficients for the eclipse closest to the specified date.

    Parameters:
        date (str or datetime, optional): Date of the eclipse (format: 'YYYY-MM-DD'). If None, returns the next upcoming eclipse coefficients.

    Returns:
        dict: Dictionary containing Besselian element coefficients and related parameters for the selected eclipse, including:
            - 'jd': Julian date of the eclipse.
            - 'Δt': Delta T (difference between Terrestrial Time and Universal Time).
            - 'T0': Reference time (in hours).
            - 'X0', 'X1', 'X2', 'X3': Coefficients for the X coordinate of the shadow axis.
            - 'Y0', 'Y1', 'Y2', 'Y3': Coefficients for the Y coordinate of the shadow axis.
            - 'd0', 'd1', 'd2': Coefficients for the declination of the shadow axis.
            - 'L10', 'L11', 'L12': Coefficients for the penumbral radius.
            - 'L20', 'L21', 'L22': Coefficients for the umbral radius.
            - 'M0', 'M1', 'M2': Coefficients for the Greenwich Hour Angle.
            - 'tanf1', 'tanf2': Tangents of auxiliary angles for penumbral and umbral radii.
            - 'type': Type of eclipse.

    Description:
        This function loads eclipse data from `eclipse_besselian.csv`, selects the eclipse closest to the given date (or the next upcoming eclipse if no date is provided), and returns a dictionary of Besselian element coefficients. It also reads Delta T values from `deltat.csv` for the corresponding year.
    """
    csv_path = os.path.join(os.path.dirname(__file__), 'eclipse_besselian.csv')
    eclipses = []
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            eclipse_date = datetime(int(row['year']), int(row['month']), int(row['day']))
            row['eclipse_date'] = eclipse_date
            eclipses.append(row)
    if not eclipses:
        return None
    if date is None:
        now = datetime.now()
        # Find the next upcoming eclipse
        eclipses = [e for e in eclipses if e['eclipse_date'] >= now]
        if not eclipses:
            eclipse = sorted(eclipses, key=lambda e: e['eclipse_date'])[-1]
        else:
            eclipse = sorted(eclipses, key=lambda e: e['eclipse_date'])[0]
    else:
        if isinstance(date, str):
            date_obj = datetime.strptime(date, '%Y-%m-%d')
        else:
            date_obj = date
        # Find the closest eclipse to the given date
        eclipse = min(eclipses, key=lambda e: abs((e['eclipse_date'] - date_obj).total_seconds()))
    # Convert all numeric fields to float if possible
    coeffs = {}
    for k, v in eclipse.items():
        if k == 'eclipse_date':
            continue
        try:
            coeffs[k] = float(v)
        except (ValueError, TypeError):
            coeffs[k] = v

    # Calculate the Besselian elements
    # Prefer `td_ge` (HH:MM:SS) from the CSV; fall back to numeric `t0` if not present.
    hours = 0
    if 'td_ge' in coeffs and isinstance(coeffs['td_ge'], str) and coeffs['td_ge'].strip():
        try:
            time_parts = coeffs['td_ge'].split(':')
            hours, minutes, seconds = map(int, time_parts)
            if minutes >= 30:
                hours += 1
        except Exception:
            # If parsing fails, fall back to t0
            hours = int(float(coeffs.get('t0', 0)))
    else:
        # `t0` may be present as numeric (float) or string; coerce to float then int
        try:
            hours = int(float(coeffs.get('t0', 0)))
        except Exception:
            hours = 0

    time_str = f"{int(coeffs['year']):04d}-{int(coeffs['month']):02d}-{int(coeffs['day']):02d} {hours:02d}:00:00"

    t = Time(time_str, scale='utc')
    # Need to take the closed hour from the besselian elements CSV file to get the correct results.
    jd_tdb = t.jd
    try:
        bess = BesselianElementGenerator.get_elements(jd_tdb)
    except Exception:
        # Fall back to using values from the CSV if the ephemeris can't be loaded
        def getc(key, alt=None):
            v = coeffs.get(key, alt)
            try:
                return float(v)
            except Exception:
                return 0.0

        bess = {
            'x': [getc('x0'), getc('x1'), getc('x2'), getc('x3')],
            'y': [getc('y0'), getc('y1'), getc('y2'), getc('y3')],
            'd': [getc('d0'), getc('d1'), getc('d2')],
            'mu': [getc('mu0'), getc('mu1'), getc('mu2')],
            'l1': [getc('l10'), getc('l11'), getc('l12')],
            'l2': [getc('l20'), getc('l21'), getc('l22')],
            'tanf1': getc('tan_f1', coeffs.get('tanf1', 0.0)),
            'tanf2': getc('tan_f2', coeffs.get('tanf2', 0.0)),
        }

    elements = {'jd': coeffs['julian_date'], 'Δt': coeffs['dt'], 'T0': coeffs['t0'], 'X0': bess['x'][0], 'X1': bess['x'][1], 'X2': bess['x'][2], 'X3': bess['x'][3],
                'Y0': bess['y'][0], 'Y1': bess['y'][1], 'Y2': bess['y'][2], 'Y3': bess['y'][3], 'd0': bess['d'][0], 'd1': bess['d'][1], 'd2': bess['d'][2],
                'L10': bess['l1'][0], 'L11': bess['l1'][1], 'L12': bess['l1'][2], 'L20': bess['l2'][0], 'L21': bess['l2'][1], 'L22': bess['l2'][2],
                'M0': bess['mu'][0], 'M1': bess['mu'][1], 'M2': bess['mu'][2], 'tanf1': bess['tanf1'], 'tanf2': bess['tanf2'], 'type': coeffs['eclipse_type']}

    # elements = {'jd': coeffs['julian_date'], 'Δt': coeffs['dt'], 'T0': coeffs['t0'], 'X0': coeffs['x0'], 'X1': coeffs['x1'], 'X2': coeffs['x2'], 'X3': coeffs['x3'],
    #             'Y0': coeffs['y0'], 'Y1': coeffs['y1'], 'Y2': coeffs['y2'], 'Y3': coeffs['y3'], 'd0': coeffs['d0'], 'd1': coeffs['d1'], 'd2': coeffs['d2'],
    #             'L10': coeffs['l10'], 'L11': coeffs['l11'], 'L12': coeffs['l12'], 'L20': coeffs['l20'], 'L21': coeffs['l21'], 'L22': coeffs['l22'],
    #             'M0': coeffs['mu0'], 'M1': coeffs['mu1'], 'M2': coeffs['mu2'], 'tanf1': coeffs['tan_f1'], 'tanf2': coeffs['tan_f2'], 'type': coeffs['eclipse_type']}

    # Read delta t from the deltat.csv file
    delta_t_path = os.path.join(os.path.dirname(__file__), 'deltat.csv')

    with open(delta_t_path, newline='') as dt_file:
        dt_reader = csv.DictReader(dt_file)
        for dt_row in dt_reader:
            if int(dt_row['year']) == int(coeffs['year']):
                elements['Δt'] = float(dt_row['deltat'])
                break
        else:
            # If no year found, use the last known value
            dt_file.seek(0)  # Reset file pointer to the beginning
            for dt_row in dt_reader:
                if dt_row['deltat'] != 'deltat':
                    elements['Δt'] = float(dt_row['deltat'])
                    break

    # Compute Delta T using Astropy/IERS (new method)
    old_dt = elements.get('Δt')
    # Allow degraded IERS accuracy (use predictions if necessary)
    try:
        conf.iers_degraded_accuracy = 'warn'
    except Exception:
        pass

    new_dt = None
    try:
        # `t` was created earlier as the UTC Time for the eclipse hour
        tt_jd = t.tt.jd
        ut1_jd = t.ut1.jd
        new_dt = (tt_jd - ut1_jd) * 86400.0
    except Exception:
        # If UT1/TT calculation fails (no IERS data or offline), leave new_dt as None
        new_dt = None

    return elements



def get_elements(e, t, phi, lam, height):
    """
    Computes the Besselian elements and intermediate values for a solar eclipse at a given time and geographic location.

    Parameters:
        e (dict): Dictionary containing Besselian element coefficients for the eclipse.
        t (float): Time offset (in hours) from the reference time T0.
        phi (float): Geographic latitude in degrees.
        lam (float): Geographic longitude in degrees (negative for east longitude).
        height (float): Observer's elevation above sea level in meters.

    Returns:
        dict: Dictionary containing computed Besselian elements and intermediate values, including:
            - 'X', 'Y': Rectangular coordinates of the shadow axis.
            - 'd': Declination of the shadow axis (degrees).
            - 'M': Greenwich Hour Angle of the shadow axis (degrees).
            - 'Xp', 'Yp', 'Mp': Derivatives of X, Y, and M with respect to time.
            - 'L1', 'L2': Penumbral and umbral radii.
            - 'tanf1', 'tanf2': Tangents of auxiliary angles for penumbral and umbral radii.
            - 'H': Local hour angle (degrees).
            - 'u1', 'rho_sin_phip', 'rho_cos_phip': Auxiliary values for geodetic calculations.
            - 'xi', 'eta', 'zeta': Shadow axis coordinates in the observer's local frame.
            - 'xi_p', 'eta_p': Time derivatives of xi and eta.
            - 'L1p', 'L2p': Corrected penumbral and umbral radii.
            - 'u', 'v': Projected shadow axis coordinates.
            - 'a', 'b': Projected derivatives.
            - 'n': Magnitude of the shadow axis velocity vector.

    Description:
        This function calculates the Besselian elements and related intermediate values for a solar eclipse at a specified time and location. These values are used in further calculations of eclipse circumstances, such as contact times and local geometry.
    """
    # Meeus - Elements of Solar Eclipses
    o = {'X': e['X0'] + e['X1'] * t + e['X2'] * t * t + e['X3'] * t * t * t,
         'Y': e['Y0'] + e['Y1'] * t + e['Y2'] * t * t + e['Y3'] * t * t * t,
         'd': e['d0'] + e['d1'] * t + e['d2'] * t * t, 'M': e['M0'] + e['M1'] * t,
         'Xp': e['X1'] + 2 * e['X2'] * t + 3 * e['X3'] * t * t, 'Yp': e['Y1'] + 2 * e['Y2'] * t + 3 * e['Y3'] * t * t,
         'Mp': e['M1'], 'L1': e['L10'] + e['L11'] * t + e['L12'] * t * t,
         'L2': e['L20'] + e['L21'] * t + e['L22'] * t * t, 'tanf1': e['tanf1'], 'tanf2': e['tanf2']}

    o['H'] = o['M'] - lam - 0.00417807 * e['Δt']

    o['u1'] = math.atan(0.99664719 * math.tan(phi * rad)) / rad
    o['rho_sin_phip'] = 0.99664719 * math.sin(o['u1'] * rad) + height / 6378140 * math.sin(phi * rad)
    o['rho_cos_phip'] = math.cos(o['u1'] * rad) + height / 6378140 * math.cos(phi * rad)

    o['xi'] = o['rho_cos_phip'] * math.sin(o['H'] * rad)
    o['eta'] = o['rho_sin_phip'] * math.cos(o['d'] * rad) - o['rho_cos_phip'] * math.cos(o['H'] * rad) * math.sin(o['d'] * rad)
    o['zeta'] = o['rho_sin_phip'] * math.sin(o['d'] * rad) + o['rho_cos_phip'] * math.cos(o['H'] * rad) * math.cos(o['d'] * rad)
    o['xi_p'] = 0.01745329 * e['M1'] * o['rho_cos_phip'] * math.cos(o['H'] * rad)
    o['eta_p'] = 0.01745329 * (e['M1'] * o['xi'] * math.sin(o['d'] * rad) - o['zeta'] * e['d1'])
    o['L1p'] = o['L1'] - o['zeta'] * e['tanf1']
    o['L2p'] = o['L2'] - o['zeta'] * e['tanf2']

    o['u'] = o['X'] - o['xi']
    o['v'] = o['Y'] - o['eta']
    o['a'] = o['Xp'] - o['xi_p']
    o['b'] = o['Yp'] - o['eta_p']
    o['n'] = math.sqrt(o['a'] * o['a'] + o['b'] * o['b'])

    return o


def get_local_circumstances(phi, lam, height, date = None):
    """
    Computes the local circumstances of a solar eclipse for a given geographic location and date.

    Parameters:
        phi (float): Geographic latitude in degrees.
        lam (float): Geographic longitude in degrees.
        height (float): Observer's elevation above sea level in meters.
        date (str or datetime, optional): Date of the eclipse (format: 'YYYY-MM-DD'). If None, uses the next upcoming eclipse.

    Returns:
        dict: Dictionary containing:
            - 'jd' (float): Julian date of the eclipse.
            - 't' (float): Time offset from reference time T0 (in hours).
            - 'type' (str): Type of eclipse at the location.
            - 'UT' (float): Universal Time of maximum eclipse (in hours).
            - 'mag' (float): Eclipse magnitude at the location.
            - 'ut_maximum' (float): Universal Time of maximum eclipse (in hours).
            - 'ut_first_contact' (float): Universal Time of first contact (in hours).
            - 'ut_second_contact' (float): Universal Time of second contact (in hours).
            - 'ut_third_contact' (float): Universal Time of third contact (in hours).
            - 'ut_last_contact' (float): Universal Time of last contact (in hours).
            - 'h' (float): Altitude of the Sun at maximum eclipse (in degrees).
            - 'm' (float): Minimum separation between shadow axis and observer (in units of Earth's radius).
            - 'elements' (dict): Computed Besselian elements and intermediate values.

    Description:
        This function iteratively calculates the contact times, magnitude, and other local circumstances of a solar eclipse for a specified location and date using Besselian elements. It refines the timing for each contact and determines the type of eclipse visible at the location.
    """
    # Meeus - Elements of Solar Eclipses
    e = get_element_coeffs(date)
    lam = -lam

    t = 0
    tau_m = 10000
    iterations = 0
    o = None
    while abs(tau_m) > 0.00001 and iterations < max_iterations:
        o = get_elements(e, t, phi, lam, height)
        tau_m = - (o['u'] * o['a'] + o['v'] * o['b']) / (o['n'] * o['n'])
        t = t + tau_m
        iterations += 1

    m = math.sqrt(o['u'] * o['u'] + o['v'] * o['v'])
    g = (o['L1p'] - m) / (o['L1p'] + o['L2p'])

    sinh = math.sin(o['d'] * rad) * math.sin(phi * rad) + math.cos(o['d'] * rad) * math.cos(phi * rad) * math.cos(o['H'] * rad)
    h = math.asin(sinh) / rad

    s = (o['a'] * o['v'] - o['u'] * o['b']) / (o['n'] * o['L1p'])
    tau = o['L1p'] / o['n'] * math.sqrt(max(0, 1 - s * s))

    first_contact = t - tau
    last_contact = t + tau

    for _ in range(10):
        fco = get_elements(e, first_contact, phi, lam, height)
        s = (fco['a'] * fco['v'] - fco['u'] * fco['b']) / (fco['n'] * fco['L1p'])
        tau_f = - (fco['u'] * fco['a'] + fco['v'] * fco['b']) / (fco['n'] * fco['n']) - fco['L1p'] / fco['n'] * math.sqrt(max(0, 1 - s * s))
        first_contact = first_contact + tau_f

    for _ in range(10):
        fco = get_elements(e, last_contact, phi, lam, height)
        s = (fco['a'] * fco['v'] - fco['u'] * fco['b']) / (fco['n'] * fco['L1p'])
        tau_f = - (fco['u'] * fco['a'] + fco['v'] * fco['b']) / (fco['n'] * fco['n']) + fco['L1p'] / fco['n'] * math.sqrt(max(0, 1 - s * s))
        last_contact = last_contact + tau_f

    # Interior contacts
    s = (o['a'] * o['v'] - o['u'] * o['b']) / (o['n'] * o['L2p'])
    tau = o['L2p'] / o['n'] * math.sqrt(max(0, 1 - s * s))

    third_contact = t - tau
    second_contact = t + tau

    for _ in range(10):
        fco = get_elements(e, third_contact, phi, lam, height)
        s = (fco['a'] * fco['v'] - fco['u'] * fco['b']) / (fco['n'] * fco['L2p'])
        tau_f = - (fco['u'] * fco['a'] + fco['v'] * fco['b']) / (fco['n'] * fco['n']) - fco['L2p'] / fco['n'] * math.sqrt(max(0, 1 - s * s))
        third_contact = third_contact + tau_f

    for _ in range(10):
        fco = get_elements(e, second_contact, phi, lam, height)
        s = (fco['a'] * fco['v'] - fco['u'] * fco['b']) / (fco['n'] * fco['L2p'])
        tau_f = - (fco['u'] * fco['a'] + fco['v'] * fco['b']) / (fco['n'] * fco['n']) + fco['L2p'] / fco['n'] * math.sqrt(max(0, 1 - s * s))
        second_contact = second_contact + tau_f

    ut_first_contact = e['T0'] + first_contact - e['Δt'] / 60 / 60
    ut_second_contact = e['T0'] + second_contact - e['Δt'] / 60 / 60
    ut_third_contact = e['T0'] + third_contact - e['Δt'] / 60 / 60
    ut_last_contact = e['T0'] + last_contact - e['Δt'] / 60 / 60
    ut_maximum = e['T0'] + t - e['Δt'] / 60 / 60

    ut = e['T0'] + t

    eclipse_type = e['type']

    if int((ut_first_contact - ut_maximum) * 10000) == 0 and int((ut_maximum - ut_last_contact) * 10000) == 0:
        eclipse_type = "No eclipse"
    elif int((ut_second_contact - ut_third_contact) * 10000) == 0:
        eclipse_type = "Partial"
    elif eclipse_type == "A":
        eclipse_type = "Annular"
        # Switch ut_third_contact and ut_second_contact for annular eclipse
        ut_second_contact, ut_third_contact = ut_third_contact, ut_second_contact
    else:
        # Total eclipse
        eclipse_type = "Total"

    return {
        'jd': e['jd'], 't': t, 'type': eclipse_type, 'UT': ut, 'mag': g,
        'ut_maximum': ut_maximum,
        'ut_first_contact': ut_first_contact,
        'ut_second_contact': ut_second_contact,
        'ut_third_contact': ut_third_contact,
        'ut_last_contact': ut_last_contact,
        'h': h, 'm': m, 'elements': o
    }


def compute_central_lat_lon_for_time(e, utc):
    """
    Computes the central latitude and longitude of the eclipse shadow at a specific Universal Time (UTC) using Besselian elements.

    Parameters:
        e (dict): Dictionary containing Besselian element coefficients for the eclipse.
        utc (float): Universal Time (in hours) for which to compute the central coordinates.

    Returns:
        dict: Dictionary containing:
            - 'lat' (float): Central latitude in degrees.
            - 'lon' (float): Central longitude in degrees.
            - 'magnitude' (float): Eclipse magnitude parameter.
            - 'duration' (float): Duration of the eclipse at this point (seconds).
            - 'width' (float): Width of the eclipse path at this point (km).

    Description:
        This function calculates the geographic coordinates (latitude and longitude) of the center of the eclipse shadow for a given UTC, along with the magnitude, duration, and path width. It uses Besselian elements to determine the position and geometry of the shadow on Earth's surface.
    """
    t = utc - e['T0']
    x = e['X0'] + e['X1'] * t + e['X2'] * t * t + e['X3'] * t * t * t
    y = e['Y0'] + e['Y1'] * t + e['Y2'] * t * t + e['Y3'] * t * t * t
    d = e['d0'] + e['d1'] * t + e['d2'] * t * t
    m = e['M0'] + e['M1'] * t
    l1 = e['L10'] + e['L11'] * t + e['L12'] * t * t
    l2 = e['L20'] + e['L21'] * t + e['L22'] * t * t
    xp = e['X1'] + 2 * e['X2'] * t + 3 * e['X3'] * t * t
    yp = e['Y1'] + 2 * e['Y2'] * t + 3 * e['Y3'] * t * t

    omega = 1 / math.sqrt(1 - 0.006694385 * math.cos(d * rad) * math.cos(d * rad))
    p = e['M1'] / 57.2957795
    # Meeus: b and c are the components of the shadow's velocity relative to the ground, while capital B is the
    # height of the central point above the fundamental plane.  They must be kept apart, otherwise the duration
    # and the path width come out wrong.
    b = yp - p * x * math.sin(d * rad)
    c = xp + p * y * math.sin(d * rad)
    y1 = omega * y
    b1 = omega * math.sin(d * rad)
    b2 = 0.99664719 * omega * math.cos(d * rad)
    capital_b = math.sqrt(max(0, 1 - x * x - y1 * y1))
    phi1 = math.asin(capital_b * b1 + y1 * b2)
    sin_h = max(-1.0, min(1.0, x / math.cos(phi1)))
    cos_h = max(-1.0, min(1.0, (capital_b * b2 - y1 * b1) / math.cos(phi1)))
    h = solve_quadrant(sin_h, cos_h) / rad
    phi = math.atan(1.00336409 * math.tan(phi1)) / rad
    lam = m - h - 0.00417807 * e['Δt']
    l1p = l1 - capital_b * e['tanf1']
    l2p = l2 - capital_b * e['tanf2']
    a = c - p * capital_b * math.cos(d * rad)
    n = math.sqrt(a * a + b * b)
    duration = 7200 * l2p / n
    k2 = capital_b * capital_b + ((x * a + y * b) * (x * a + y * b)) / (n * n)
    k = math.sqrt(k2)
    width = 12756 * abs(l2p) / k
    magnitude = (l1p - l2p) / (l1p + l2p)
    return {'lat': phi, 'lon': -lam, 'magnitude': magnitude, 'duration': duration, 'width': width}


def compute_extremes(e, t0):
    """
    Computes the geographic and geometric circumstances at a specific time offset for a solar eclipse using Besselian elements.

    Parameters:
        e (dict): Dictionary containing Besselian element coefficients for the eclipse.
        t0 (float): Time offset (in hours) from the reference time T0.

    Returns:
        dict: Dictionary containing computed values at the given time, including:
            - 't': Time offset used for calculation.
            - 'X', 'Y': Rectangular coordinates of the shadow axis.
            - 'd': Declination of the shadow axis (degrees).
            - 'M': Greenwich Hour Angle of the shadow axis (degrees).
            - 'L1', 'L2': Penumbral and umbral radii.
            - 'Xp', 'Yp': Derivatives of X and Y with respect to time.
            - 'omega': Auxiliary value for Earth's oblateness.
            - 'p': Derivative of M with respect to time (radians/hour).
            - 'b', 'c': Auxiliary values for path geometry.
            - 'y1', 'b1', 'b2': Intermediate values for latitude calculations.
            - 'B': Auxiliary value for path geometry.
            - 'Phi1', 'Phi': Geodetic latitude (degrees).
            - 'H': Local hour angle (degrees).
            - 'lam': Longitude (degrees).
            - 'L1p', 'L2p': Corrected penumbral and umbral radii.
            - 'a', 'n': Path geometry values.
            - 'duration': Duration of eclipse at this point (seconds).
            - 'sinh', 'h': Altitude of the Sun (degrees).
            - 'K2', 'K': Path width geometry.
            - 'width': Width of the eclipse path (km).
            - 'A': Magnitude parameter.

    Description:
        This function calculates the detailed circumstances (location, geometry, and timing) of the eclipse shadow at a given time offset using Besselian elements.
        It is typically used to determine the properties of the eclipse at extreme points, such as the beginning or end of the path.
    """
    t = t0
    r = {'t': t, 'X': e['X0'] + e['X1'] * t + e['X2'] * t * t + e['X3'] * t * t * t,
         'Y': e['Y0'] + e['Y1'] * t + e['Y2'] * t * t + e['Y3'] * t * t * t,
         'd': e['d0'] + e['d1'] * t + e['d2'] * t * t, 'M': e['M0'] + e['M1'] * t,
         'L1': e['L10'] + e['L11'] * t + e['L12'] * t * t, 'L2': e['L20'] + e['L21'] * t + e['L22'] * t * t,
         'Xp': e['X1'] + 2 * e['X2'] * t + 3 * e['X3'] * t * t, 'Yp': e['Y1'] + 2 * e['Y2'] * t + 3 * e['Y3'] * t * t}
    r['omega'] = 1 / math.sqrt(1 - 0.006694385 * math.cos(r['d'] * rad) * math.cos(r['d'] * rad))
    r['p'] = e['M1'] / 57.2957795
    r['b'] = r['Yp'] - r['p'] * r['X'] * math.sin(r['d'] * rad)
    r['c'] = r['Xp'] + r['p'] * r['Y'] * math.sin(r['d'] * rad)
    r['y1'] = r['omega'] * r['Y']
    r['b1'] = r['omega'] * math.sin(r['d'] * rad)
    r['b2'] = 0.99664719 * r['omega'] * math.cos(r['d'] * rad)
    temp = 1 - r['X'] * r['X'] - r['y1'] * r['y1']
    if temp < 0:
        temp = 0
    r['B'] = math.sqrt(temp)
    r['Phi1'] = math.asin(r['B'] * r['b1'] + r['y1'] * r['b2'])
    sin_h = r['X'] / math.cos(r['Phi1'])
    cos_h = (r['B'] * r['b2'] - r['y1'] * r['b1']) / math.cos(r['Phi1'])
    r['H'] = solve_quadrant(sin_h, cos_h) / rad
    r['Phi'] = math.atan(1.00336409 * math.tan(r['Phi1'])) / rad
    r['lam'] = -(r['M'] - r['H'] - 0.00417807 * e['Δt'])
    r['L1p'] = r['L1'] - r['B'] * e['tanf1']
    r['L2p'] = r['L2'] - r['B'] * e['tanf2']
    r['a'] = r['c'] - r['p'] * r['B'] * math.cos(r['d'] * rad)
    r['n'] = math.sqrt(r['a'] * r['a'] + r['b'] * r['b'])
    r['duration'] = 7200 * r['L2p'] / r['n']
    r['sinh'] = math.sin(r['d'] * rad) * math.sin(r['Phi'] * rad) + math.cos(r['d'] * rad) * math.cos(r['Phi'] * rad) * math.cos(r['H'] * rad)
    r['h'] = math.asin(r['sinh']) / rad
    r['K2'] = r['B'] * r['B'] + ((r['X'] * r['a'] + r['Y'] * r['b']) * (r['X'] * r['a'] + r['Y'] * r['b'])) / (r['n'] * r['n'])
    r['K'] = math.sqrt(r['K2'])
    r['width'] = 12756 * abs(r['L2p']) / r['K']
    r['A'] = (r['L1p'] - r['L2p']) / (r['L1p'] + r['L2p'])
    return r


def compute_estimate(e):
    """
    Computes initial estimates for the contact times of a solar eclipse using Besselian elements.

    Parameters:
        e (dict): Dictionary of Besselian elements and coefficients for the eclipse.

    Returns:
        dict: Dictionary containing 'tau1' and 'tau2', which are initial time estimates (in hours) for the start and end of the eclipse.

    Description:
        This function calculates rough estimates for the contact times (tau1 and tau2) of a solar eclipse using the provided Besselian elements. These estimates are useful as starting points for more precise iterative calculations of eclipse circumstances.
    """
    omega = 1 / math.sqrt(1 - 0.006694385 * math.cos(e['d0'] * rad) * math.cos(e['d0'] * rad))
    u = e['X0']
    a = e['X1']
    v = omega * e['Y0']
    b = omega * e['Y1']
    n = math.sqrt(a * a + b * b)
    s = (a * v - u * b) / n
    tau = -(u * a + v * b) / (n * n)
    tau1 = tau - math.sqrt(1 - s * s) / n
    tau2 = tau + math.sqrt(1 - s * s) / n
    return {'tau1': tau1, 'tau2': tau2}


def refine_estimate(e, t):
    """
    Refines the initial time estimates for the contact points of a solar eclipse using Besselian elements.

    Parameters:
        e (dict): Dictionary containing Besselian element coefficients for the eclipse.
        t (float): Initial time estimate (in hours) for the contact point.

    Returns:
        dict: Dictionary containing:
            - 'tau1' (float): Refined time estimate for the start of the eclipse (in hours).
            - 'tau2' (float): Refined time estimate for the end of the eclipse (in hours).

    Description:
        This function uses the provided Besselian elements and an initial time estimate to calculate more accurate contact times (tau1 and tau2) for the eclipse. It is typically used after obtaining rough estimates to improve the precision of eclipse timing calculations.
    """
    x = e['X0'] + e['X1'] * t + e['X2'] * t * t + e['X3'] * t * t * t
    y = e['Y0'] + e['Y1'] * t + e['Y2'] * t * t + e['Y3'] * t * t * t
    xp = e['X1'] + 2 * e['X2'] * t + 3 * e['X3'] * t * t
    yp = e['Y1'] + 2 * e['Y2'] * t + 3 * e['Y3'] * t * t
    omega = 1 / math.sqrt(1 - 0.006694385 * math.cos(e['d0'] * rad) * math.cos(e['d0'] * rad))
    u = x
    a = xp
    v = omega * y
    b = omega * yp
    n = math.sqrt(a * a + b * b)
    s = (a * v - u * b) / n
    tau = -(u * a + v * b) / (n * n)
    tau1 = tau - math.sqrt(1 - s * s) / n
    tau2 = tau + math.sqrt(1 - s * s) / n
    return {'tau1': tau1, 'tau2': tau2}


def get_extreme_points(e):
    """
    Computes the extreme (beginning and ending) points of a solar eclipse path using Besselian elements.

    Parameters:
        e (dict): Dictionary containing Besselian element coefficients for the eclipse.

    Returns:
        dict: Dictionary with two keys:
            - 'begin': Circumstances at the beginning extreme point (dict with computed values).
            - 'end': Circumstances at the ending extreme point (dict with computed values).

    Description:
        This function estimates and refines the contact times for the start and end of the eclipse using Besselian elements, then computes the geographic circumstances (such as latitude, longitude, and other parameters) for these extreme points. The results are useful for mapping the limits of the eclipse path.
    """
    est = compute_estimate(e)
    est2 = refine_estimate(e, est['tau1'])
    est3 = refine_estimate(e, est['tau2'])
    begin_circumstances = compute_extremes(e, est['tau1'] + est2['tau1'])
    end_circumstances = compute_extremes(e, est['tau2'] + est3['tau2'])
    return {'begin': begin_circumstances, 'end': end_circumstances}


def compute_rise_set_point(be, gamma):
    """
    Computes the geographic coordinates (latitude and longitude) of a rise or set point for the eclipse shadow at a given time and position angle.

    Parameters:
        be (dict): Dictionary containing Besselian elements for the eclipse at a given time.
        gamma (float): Position angle (in radians) for the rise or set point.

    Returns:
        dict: Dictionary with:
            - 'lat' (float): Latitude in degrees.
            - 'lon' (float): Longitude in degrees (normalized to [-180, 180]).

    Description:
        This function calculates the latitude and longitude of the eclipse shadow's rise or set point using the provided Besselian elements and position angle. The result is useful for mapping the boundaries of the eclipse shadow on Earth's surface.
    """
    eta = math.cos(gamma)
    xi = math.sin(gamma)
    sin_d = math.sin(be['d'] * rad)
    cos_d = math.cos(be['d'] * rad)
    cos_phi1_sin_theta = xi
    cos_phi1_cos_theta = -eta * sin_d
    theta = math.atan2(cos_phi1_sin_theta, cos_phi1_cos_theta)
    lam = -(be['H'] * rad - theta)
    sin_phi = eta * cos_d
    phi = math.asin(sin_phi)
    return {'lat': phi / rad, 'lon': lam / rad if lam <= math.pi else lam / rad - 360}

def compute_rise_set_points(be):
    """
    Computes the geographic coordinates of both rise and set points for the eclipse shadow at a given time.

    Args:
        be (dict): Dictionary containing Besselian elements for the eclipse at a given time.

    Returns:
        list: A list containing two dictionaries, each with 'lat' (latitude in degrees) and 'lon' (longitude in degrees) for the rise and set points.
    """
    m = math.atan2(be['X'], be['Y'])
    cos_gamma_m = (m * m + 1 - be['L1'] * be['L1']) / (2 * m)
    gamma_m = math.acos(cos_gamma_m)
    gamma_m2 = 2 * math.pi - gamma_m
    gamma1 = gamma_m + m
    gamma2 = gamma_m2 + m
    ll1 = compute_rise_set_point(be, gamma1)
    ll2 = compute_rise_set_point(be, gamma2)
    return [ll1, ll2]

def get_rise_set_curves():
    """
    Computes the rise and set curves for the eclipse shadow over a range of times.

    Returns:
        dict: Dictionary containing lists of geographic coordinates for the shadow's setting and rising curves, as well as the extreme northern and southern longitudes at the start and end of the eclipse.
            - 'setting': List of coordinates for the setting curve.
            - 'rising': List of coordinates for the rising curve.
            - 'nStart': Longitude of the northernmost point at the start.
            - 'sStart': Longitude of the southernmost point at the start.
            - 'nEnd': Longitude of the northernmost point at the end.
            - 'sEnd': Longitude of the southernmost point at the end.
    """
    t = -3
    e = get_element_coeffs()
    list1 = []
    list2 = []
    list3 = []
    list4 = []
    max_lat = -100
    min_lat = 100
    n_start = None
    s_start = None
    while t < .5:
        be = get_elements(e, t, 0, 0, 0)
        p = compute_rise_set_points(be)
        if not math.isnan(p[0]['lat']):
            list1.append(p[0])
            if p[0]['lat'] > max_lat:
                max_lat = p[0]['lat']
                n_start = p[0]['lon']
            if p[0]['lat'] < min_lat:
                min_lat = p[0]['lat']
                s_start = p[0]['lon']
        if not math.isnan(p[1]['lat']):
            list2.insert(0, p[1])
            if p[1]['lat'] < min_lat:
                min_lat = p[1]['lat']
                s_start = p[1]['lon']
        t += .01
    t = .5
    max_lat = -100
    min_lat = 100
    n_end = None
    s_end = None
    while t < 4:
        be = get_elements(e, t, 0, 0, 0)
        p = compute_rise_set_points(be)
        if not math.isnan(p[0]['lat']):
            list3.append(p[0])
            if p[0]['lat'] > max_lat:
                max_lat = p[0]['lat']
                n_end = p[0]['lon']
            if p[0]['lat'] < min_lat:
                min_lat = p[0]['lat']
                s_end = p[0]['lon']
        if not math.isnan(p[1]['lat']):
            list4.insert(0, p[1])
            if p[1]['lat'] > max_lat:
                max_lat = p[1]['lat']
                n_end = p[1]['lon']
            if p[1]['lat'] < min_lat:
                min_lat = p[1]['lat']
                s_end = p[1]['lon']
        t += .01
    return {'setting': list1 + list2, 'rising': list3 + list4, 'nStart': n_start, 'sStart': s_start, 'nEnd': n_end, 'sEnd': s_end}

def get_limits_by_longitude_as_list(e, north_south, g, start_lon, end_lon):
    """
    Computes eclipse limit points (latitude and longitude) for a range of longitudes, both at the equator and near the poles, for a given eclipse and direction.

    Parameters:
        e (dict): Besselian element coefficients for the eclipse.
        north_south (int): Direction indicator (`+1` for north, `-1` for south).
        g (float): Eclipse magnitude or related parameter.
        start_lon (float): Starting longitude in degrees.
        end_lon (float): Ending longitude in degrees.

    Returns:
        list: A list containing two lists:
            - First list: Eclipse limit points at the equator for each longitude.
            - Second list: Eclipse limit points near the pole for each longitude.
            - Each point is a dictionary with `'lat'` (latitude in degrees) and `'lon'` (longitude in degrees), or `None` if no valid point is found.

    Description:
        This function iterates over the specified longitude range, calculating the eclipse limit points at both the equator and near the poles for each longitude. The results are useful for mapping the geographic boundaries of the eclipse shadow.
    """
    eq_points = []
    polar_points = []
    step = 0.01
    i = start_lon
    while i <= end_lon:
        eq = get_limits_for_longitude(e, i, north_south, g, 0)
        polar = get_limits_for_longitude(e, i, north_south, g, 89.9 * (1 if e['Y0'] >= 0 else -1))
        if polar is not None and eq is not None:
            if abs(eq['lat'] - polar['lat']) < 0.1:
                eq_points.append(eq)
            else:
                eq_points.append(eq)
                polar_points.append(polar)
        else:
            eq_points.append(None)
            polar_points.append(None)
        i += step
    return [eq_points, polar_points]

def get_limits_for_longitude(e, lam, north_south, g, start_phi):
    """
    Computes the eclipse limit point (latitude and longitude) for a given longitude and direction.

    Args:
        e (dict): Dictionary containing Besselian element coefficients for the eclipse.
        lam (float): Longitude (in degrees) for which to compute the limit.
        north_south (int): Direction indicator (+1 for north, -1 for south).
        g (float): Eclipse magnitude or related parameter.
        start_phi (float): Starting latitude (in degrees) for the iterative calculation.

    Returns:
        dict or None: Dictionary with 't' (time offset), 'lat' (latitude in degrees), and 'lon' (longitude in degrees) if a valid point is found; otherwise None.
    """
    t = 0
    phi = start_phi
    i = 0
    delta_phi = 1000
    tau = 1000
    while (abs(tau) > 0.0001 or abs(delta_phi) > 0.0001) and i < 20:
        x = e['X0'] + e['X1'] * t + e['X2'] * t * t + e['X3'] * t * t * t
        y = e['Y0'] + e['Y1'] * t + e['Y2'] * t * t + e['Y3'] * t * t * t
        d = e['d0'] + e['d1'] * t + e['d2'] * t * t
        m = e['M0'] + e['M1'] * t
        xp = e['X1'] + 2 * e['X2'] * t + 3 * e['X3'] * t * t
        yp = e['Y1'] + 2 * e['Y2'] * t + 3 * e['Y3'] * t * t
        l1 = e['L10'] + e['L11'] * t + e['L12'] * t * t
        l2 = e['L20'] + e['L21'] * t + e['L22'] * t * t
        h = m + lam - 0.00417807 * e['Δt']
        height = 0
        u1 = math.atan(0.99664719 * math.tan(phi * rad)) / rad
        rho_sin_phip = 0.99664719 * math.sin(u1 * rad) + height / 6378140 * math.sin(phi * rad)
        rho_cos_phip = math.cos(u1 * rad) + height / 6378140 * math.cos(phi * rad)
        xi = rho_cos_phip * math.sin(h * rad)
        eta = rho_sin_phip * math.cos(d * rad) - rho_cos_phip * math.cos(h * rad) * math.sin(d * rad)
        zeta = rho_sin_phip * math.sin(d * rad) + rho_cos_phip * math.cos(h * rad) * math.cos(d * rad)
        xi_p = 0.01745329 * e['M1'] * rho_cos_phip * math.cos(h * rad)
        eta_p = 0.01745329 * (e['M1'] * xi * math.sin(d * rad) - zeta * e['d1'])
        l1p = l1 - zeta * e['tanf1']
        l2p = l2 - zeta * e['tanf2']
        u = x - xi
        v = y - eta
        a = xp - xi_p
        b = yp - eta_p
        n = math.sqrt(a * a + b * b)
        tau = - (u * a + v * b) / (n * n)
        w = (v * a - u * b) / n
        q = (b * math.sin(h * rad) * rho_sin_phip + a * (math.cos(h * rad) * math.sin(d * rad) * rho_sin_phip + math.cos(d * rad) * rho_cos_phip)) / (57.29578 * n)
        e = l1p - g * (l1p + l2p)
        delta_phi = (w + north_south * abs(e)) / q
        t = t + tau
        phi = phi + delta_phi
        i += 1
    if abs(tau) > 0.0001 or abs(delta_phi) > 0.0001:
        return None
    phi = (90 + phi) % 180
    if phi < 0:
        phi += 180
    phi -= 90
    return {'t': t, 'lat': phi, 'lon': lam}

def compute_outline_point(be, q, umbra):
    """
    Computes the geographic coordinates (latitude and longitude) of a point on the outline curve of the eclipse shadow for a given position angle.

    Args:
        be (dict): Dictionary containing Besselian elements for the eclipse at a given time.
        q (float): Position angle (in degrees) for the outline curve point.
        umbra (bool): If True, computes for the umbral shadow (L2); if False, computes for the penumbral shadow (L1).

    Returns:
        dict: Dictionary with 'lat' (latitude in degrees) and 'lon' (longitude in degrees) of the computed outline point.
    """
    # The Explanatory Supplement to the Astronomical Ephemeris 1961
    e = math.sqrt(0.00672267)
    sin_d = math.sin(be['d'] * rad)
    cos_d = math.cos(be['d'] * rad)
    rho1 = math.sqrt(1 - e * e * cos_d * cos_d)
    rho2 = math.sqrt(1 - e * e * sin_d * sin_d)
    sin_d1 = sin_d / rho1
    cos_d1 = math.sqrt(1 - e * e) * cos_d / rho1
    sin_d1d2 = e * e * sin_d * cos_d / (rho1 * rho2)
    cos_d1d2 = math.sqrt(1 - e * e) / (rho1 * rho2)
    q *= rad
    sin_q = math.sin(q)
    cos_q = math.cos(q)
    tan_f = be['tanf1']
    l0 = be['L1']
    if umbra:
        l0 = be['L2']
        tan_f = be['tanf2']
    # The radius on the ground is L - zeta tan f, with zeta the height of the ground point above the fundamental
    # plane.  Iterate from the plane radius L each time; subtracting the correction cumulatively makes the shadow
    # ~30% too large.
    l = l0
    for _ in range(3):
        xi = be['X'] - l * sin_q
        eta = (be['Y'] - l * cos_q) / rho1
        zeta1 = math.sqrt(1 - xi * xi - eta * eta)
        zeta = rho2 * (zeta1 * cos_d1d2 - eta * sin_d1d2)
        l = l0 - zeta * tan_f
    xi = be['X'] - l * sin_q
    eta = (be['Y'] - l * cos_q) / rho1
    zeta1 = math.sqrt(1 - xi * xi - eta * eta)
    cos_phi1_sin_theta = xi
    cos_phi1_cos_theta = zeta1 * cos_d1 - eta * sin_d1
    theta = math.atan2(cos_phi1_sin_theta, cos_phi1_cos_theta) / rad
    lam = be['H'] - theta
    phi1 = math.asin(eta * cos_d1 + zeta1 * sin_d1)
    phi = math.atan((1 / math.sqrt(1 - e * e)) * math.tan(phi1)) / rad
    if phi > 90:
        phi -= 180
    if phi < -90:
        phi += 180
    if lam > 180:
        lam -= 360
    return {'lat': phi, 'lon': -lam}

def proper_angle(d):
    """
    Normalizes an angle to the range [0, 360) degrees.

    Args:
        d (float): Angle in degrees.

    Returns:
        float: The normalized angle in degrees, within the range [0, 360].
    """
    t = d
    if t < 0:
        t += 360
    if t >= 360:
        t -= 360
    return t

def get_solar_eclipses(number_of_eclipses=None, start_date=None):
    """
    Reads eclipse_besselian.csv and returns a list of solar eclipses.

    Args:
        number_of_eclipses (int, optional): Limits the number of returned eclipses. If None, returns all available eclipses.
        start_date (str or datetime, optional): Filters eclipses after this date (format: 'YYYY-MM-DD'). If None, includes all dates.

    Returns:
        list: A list of dictionaries, each containing information about a solar eclipse:
            - 'date': Date of the eclipse (DD/MM/YYYY).
            - 'type': Type of eclipse (e.g., Total, Annular, Partial).
            - 'magnitude': Magnitude of the eclipse (float).
            - 'duration': Duration of the eclipse in seconds (float).
            - 'saros': Saros series identifier (str).
    """
    eclipses = []
    csv_path = os.path.join(os.path.dirname(__file__), 'eclipse_besselian.csv')
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            eclipse_date = datetime(int(row['year']), int(row['month']), int(row['day']))
            if start_date:
                if isinstance(start_date, str):
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                else:
                    start_dt = start_date
                if eclipse_date < start_dt:
                    continue

            date = eclipse_date.strftime('%d/%m/%Y')

            eclipse_info = {
                'date': date,
                'type': row['eclipse_type'],
                'magnitude': float(row['magnitude']),
                'duration': float(row['duration_secs']),
                'saros': row['saros'],
            }
            eclipses.append(eclipse_info)
            if number_of_eclipses and len(eclipses) >= number_of_eclipses:
                break
    return eclipses

def get_outline_curve_q_range(be, l):
    """
    Calculates the range of position angles (Q) for the outline curve of the eclipse shadow.

    Args:
        be (dict): Dictionary containing Besselian elements for the eclipse at a given time.
        l (float): Radius parameter (typically L1 or L2) for the shadow outline.

    Returns:
        dict: Dictionary with 'start' and 'end' keys representing the starting and ending position angles (in degrees) for the outline curve.
            - 'start': Starting position angle (Q2) in degrees.
            - 'end': Ending position angle (Q1) in degrees.
    """
    msq = be['X'] * be['X'] + be['Y'] * be['Y']
    m = math.sqrt(msq)
    capital_m = math.atan2(be['X'], be['Y'])
    denom = 2 * l * m
    numer = m * m + l * l - 1
    cos_qm = numer / denom
    try:
        q1 = proper_angle((math.acos(cos_qm) + capital_m) / rad)
        q2 = proper_angle((-math.acos(cos_qm) + capital_m) / rad)
    except ValueError:
        q2 = 0
        q1 = 360
    if q1 < q2:
        q1 += 360
    return {'start': q2, 'end': q1}
