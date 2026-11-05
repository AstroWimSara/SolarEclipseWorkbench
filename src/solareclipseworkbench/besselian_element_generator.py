import math
from astropy.time import Time
from solareclipseworkbench.nutation import Nutation
from skyfield.api import load
from solareclipseworkbench.vec import Vec, PolynomialRegression
from solareclipseworkbench.constants import EARTH_RADIUS as earth_radius
from solareclipseworkbench import solar_radius

class BesselianElementGenerator:
    """
    Generates Besselian elements for solar eclipses using ephemeris data.
    Provides static methods to compute Besselian elements, sun/moon positions, and helper utilities.
    """
    @staticmethod
    def get_elements(jd_tdb):
        """
        Compute Besselian elements as polynomials for a given Julian date (TDB).
        Args:
            jd_tdb (float): Julian date in Barycentric Dynamical Time (TDB).
        Returns:
            dict: Polynomial coefficients for x, y, d, l1, l2, mu, and values for tanf1, tanf2.
        """
        x, y, d, l1, l2, mu, tan_f1, tan_f2 = ([] for _ in range(8))
        t = []
        for i in range(5):
            t_i = i - 2
            t.append(t_i)
            # Get sun and moon positions for each time offset
            p = BesselianElementGenerator.get_sun_and_moon_position(jd_tdb + t_i / 24.0)
            elements = BesselianElementGenerator.get_besselian_elements_from_position(
                p['sunra'], p['sundec'], p['sunR'],
                p['moonra'], p['moondec'], p['moonR'], p['jd_tdb']
            )
            x.append(elements['x'])
            y.append(elements['y'])
            d.append(elements['d'])
            l1.append(elements['l1'])
            l2.append(elements['l2'])
            mu.append(elements['mu'])
            tan_f1.append(elements['tanf1'])
            tan_f2.append(elements['tanf2'])
        # For interpolation to work, mu needs to be linear and not wrap at 360
        BesselianElementGenerator.eliminate_angle_wrap(mu)
        return {
            'x': PolynomialRegression.solve(t, x, 3),
            'y': PolynomialRegression.solve(t, y, 3),
            'd': PolynomialRegression.solve(t, d, 3),
            'l1': PolynomialRegression.solve(t, l1, 3),
            'l2': PolynomialRegression.solve(t, l2, 3),
            'mu': PolynomialRegression.solve(t, mu, 3),
            'tanf1': tan_f1[2],
            'tanf2': tan_f2[2]
        }

    @staticmethod
    def get_sun_and_moon_position(jd_tdb):
        """
        Get the apparent right ascension, declination, and distance of the Sun and Moon.
        Args:
            jd_tdb (float): Julian date in TDB.
        Returns:
            dict: Sun and Moon positions (RA, Dec in radians, distance in Earth radii).
        """
        # Load the JPL ephemeris DE440s (covers 1849-2150).
        planets = load('de440s.bsp')
        ts = load.timescale()
        # Directly use the Julian Date in TDB format
        t = ts.tdb_jd(jd_tdb)
        # Get the coordinates of the sun and moon
        earth = planets['earth']
        e = earth.at(t)
        sun = planets['sun']
        moon = planets['moon']
        sun = e.observe(sun).apparent()
        moon = e.observe(moon).apparent()
        # Convert the positions to RA, Dec, and distance
        sun_ra, sun_dec, sun_r = sun.radec('date')
        moon_ra, moon_dec, moon_r = moon.radec('date')
        # Convert RA and Dec to radians
        sun_ra = sun_ra.radians
        sun_dec = sun_dec.radians
        moon_ra = moon_ra.radians
        moon_dec = moon_dec.radians
        return {
            'jd_tdb': jd_tdb,
            'sunra': sun_ra,
            'sundec': sun_dec,
            'sunR': sun_r.au * 1.496e+8 / 6378.1,  # Convert AU to Earth radii
            'moonra': moon_ra,
            'moondec': moon_dec,
            'moonR': moon_r.au * 1.496e+8 / 6378.1
        }

    @staticmethod
    def get_besselian_elements_from_position(sun_ra, sun_dec, sun_r, moon_ra, moon_dec, moon_r, jd_tdb):
        """
        Calculate Besselian elements from the positions of the Sun and Moon.
        Args:
            sun_ra, sun_dec, sun_r: Sun's right ascension, declination (radians), and distance (Earth radii)
            moon_ra, moon_dec, moon_r: Moon's right ascension, declination (radians), and distance (Earth radii)
            jd_tdb (float): Julian date in TDB
        Returns:
            dict: Besselian elements (x, y, d, l1, l2, mu, tanf1, tanf2)
        """
        # Constants
        theta = Nutation.era_gst00b(0, jd_tdb)
        # The solar radius is the one the user selected (959.95" by default, see solar_radius.py)
        ds = solar_radius.get_radius_m() / earth_radius
        # The k value taking into account the lunar limb is 0.272281.  Without the lunar limb, it is 0.2725076.
        k = 0.272281
        rad = math.pi / 180
        # Rename variables to match equations
        alpha_p, delta_p, r_p = sun_ra, sun_dec, sun_r
        alpha, delta, r = moon_ra, moon_dec, moon_r
        # Compute Sun and Moon position vectors
        sun_pos = [
            r_p * math.cos(alpha_p) * math.cos(delta_p),
            r_p * math.sin(alpha_p) * math.cos(delta_p),
            r_p * math.sin(delta_p)
        ]
        moon_pos = [
            r * math.cos(alpha) * math.cos(delta),
            r * math.sin(alpha) * math.cos(delta),
            r * math.sin(delta)
        ]
        # Vector from Moon to Sun
        gv = Vec.sub(sun_pos, moon_pos)
        g = Vec.magnitude(gv)
        a = math.atan2(gv[1], gv[0])
        d = math.asin(gv[2] / g)
        mu = BesselianElementGenerator.range2pi(theta - a)
        # Besselian element coordinates
        x = r * math.cos(delta) * math.sin(alpha - a)
        y = r * (math.sin(delta) * math.cos(d) - math.cos(delta) * math.sin(d) * math.cos(alpha - a))
        z = r * (math.sin(delta) * math.sin(d) + math.cos(delta) * math.cos(d) * math.cos(alpha - a))
        sin_f1 = (ds + k) / g
        sin_f2 = (ds - k) / g
        c1 = z + k / sin_f1
        c2 = z - k / sin_f2
        tanf1 = math.tan(math.asin(sin_f1))
        tanf2 = math.tan(math.asin(sin_f2))
        l1 = c1 * tanf1
        l2 = c2 * tanf2
        return {
            'x': x,
            'y': y,
            'd': d / rad,  # Convert radians to degrees
            'l1': l1,
            'l2': l2,
            'mu': mu / rad,  # Convert radians to degrees
            'tanf1': tanf1,
            'tanf2': tanf2
        }

    @staticmethod
    def eliminate_angle_wrap(a):
        """
        Unwraps a list of angles in degrees to avoid discontinuities at 360/0.
        Args:
            a (list): List of angles in degrees.
        Returns:
            list: Unwrapped angles.
        """
        for i in range(len(a) - 1):
            d = a[i + 1] - a[i]
            if abs(d) > 180:
                a[i + 1] += 360 * (-math.copysign(1, d))
        return a

    @staticmethod
    def range2pi(angle):
        """
        Normalize angle to the range [0, 2*pi) radians.
        Args:
            angle (float): Angle in radians.
        Returns:
            float: Normalized angle in radians.
        """
        temp = angle % (2 * math.pi)
        if temp < 0:
            temp += 2 * math.pi
        return temp

def test_besselian_elements_aug_12_2026():
    """Test Besselian elements for the total solar eclipse of August 12, 2026."""

    # Calculate the julian date using astropy
    t = Time('2026-08-12 18:00:00', scale='utc')
    # Need to take the closed hour from the besselian elements CSV file to get the correct results.
    jd_tdb = t.jd

    try:
        elements = BesselianElementGenerator.get_elements(jd_tdb)
        print("Besselian elements for 2026-08-12:", elements)
    except Exception as e:
        print("Error computing Besselian elements:", e)

if __name__ == "__main__":
    test_besselian_elements_aug_12_2026()
