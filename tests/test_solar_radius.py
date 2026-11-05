"""The selectable solar radius (Issue #197)."""
import pytest
from astropy.time import Time

from solareclipseworkbench import solar_radius
from solareclipseworkbench.besselian_element_generator import BesselianElementGenerator
from solareclipseworkbench.constants import SOLAR_RADIUS
from solareclipseworkbench.reference_moments import calculate_reference_moments


@pytest.fixture(autouse=True)
def default_radius():
    solar_radius.set_radius_arcsec(solar_radius.DEFAULT_ARCSEC)
    yield
    solar_radius.set_radius_arcsec(solar_radius.DEFAULT_ARCSEC)


class FakeSettings(dict):
    def contains(self, key):
        return key in self

    def value(self, key):
        return self[key]


def test_default_is_quaglia():
    assert solar_radius.get_radius_arcsec() == 959.95
    # The default is the radius in metres sew has always used
    assert solar_radius.get_radius_m() == pytest.approx(SOLAR_RADIUS, abs=100)
    assert solar_radius.m_to_arcsec(SOLAR_RADIUS) == pytest.approx(959.95, abs=1e-4)


def test_presets_and_custom():
    assert solar_radius.preset_for(959.63) == "auwers"
    assert solar_radius.preset_for(959.95) == "quaglia"
    assert solar_radius.preset_for(959.99) is None
    assert "custom" in solar_radius.describe(959.99)
    solar_radius.set_radius_arcsec(959.99)
    assert solar_radius.get_radius_arcsec() == 959.99


@pytest.mark.parametrize("bad", [None, "abc", float("nan"), 900.0, 1000.0])
def test_implausible_radius_is_refused(bad):
    with pytest.raises(ValueError):
        solar_radius.set_radius_arcsec(bad)
    assert solar_radius.get_radius_arcsec() == solar_radius.DEFAULT_ARCSEC


def test_load_saved():
    # QSettings returns strings from an ini file
    assert solar_radius.load_saved(FakeSettings({solar_radius.SETTINGS_KEY: "959.63"})) == 959.63
    # Nothing saved, or garbage: the radius in use stays
    assert solar_radius.load_saved(FakeSettings()) == 959.63
    assert solar_radius.load_saved(FakeSettings({solar_radius.SETTINGS_KEY: "oops"})) == 959.63


def test_besselian_elements_follow_radius():
    jd = Time("2026-08-12 18:00:00", scale="utc").jd
    quaglia = BesselianElementGenerator.get_elements(jd)
    solar_radius.set_radius_arcsec(solar_radius.AUWERS_ARCSEC)
    auwers = BesselianElementGenerator.get_elements(jd)
    # A smaller Sun: smaller penumbra, larger umbra (L2 is negative for a total eclipse)
    assert auwers["l1"][0] < quaglia["l1"][0]
    assert auwers["l2"][0] < quaglia["l2"][0] < 0


def test_smaller_sun_gives_longer_totality():
    """2026-08-12 in Spain: about 1 s more totality with 959.63", around the same midpoint."""
    def contacts():
        moments, _, _ = calculate_reference_moments(-2.9294, 41.7639, 1180, Time("2026-08-12"))
        return moments["C2"].time_utc, moments["C3"].time_utc

    c2_q, c3_q = contacts()
    solar_radius.set_radius_arcsec(solar_radius.AUWERS_ARCSEC)
    c2_a, c3_a = contacts()

    gained = (c3_a - c2_a).total_seconds() - (c3_q - c2_q).total_seconds()
    assert 0.7 < gained < 1.2
    midpoint_shift = ((c2_a - c2_q) + (c3_a - c3_q)).total_seconds() / 2
    assert abs(midpoint_shift) < 0.1
