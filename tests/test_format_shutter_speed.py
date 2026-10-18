"""format_shutter_speed writes each exposure as the camera shutter speed nearest to it.

The speeds between 1/4 s and 1 s used to be written as "1/X" with a whole X, so
0.8 s came out as "1" and 0.4 s and 0.6 s as "0.5": up to 1/3 stop off in the
scripts the wizard writes.
"""
import pytest

from solareclipseworkbench.exposure_calculator import format_shutter_speed, parse_shutter_speed


@pytest.mark.parametrize("seconds, expected", [
    (1 / 8000, "1/8000"),
    (1 / 250, "1/250"),
    (1 / 4, "1/4"),
    (0.3, "1/3"),
    (1 / 3, "1/3"),
    (0.4, "0.4"),
    (0.5, "0.5"),
    (0.6, "0.6"),
    (0.7, "0.6"),
    (0.8, "0.8"),
    (1.0, "1"),
    (1.3, "1.3"),
    (2.5, "2.5"),
    (30, "30"),
])
def test_format_shutter_speed(seconds, expected):
    assert format_shutter_speed(seconds) == expected


@pytest.mark.parametrize("seconds", [0.4, 0.5, 0.6, 0.8])
def test_speeds_below_one_second_keep_their_value(seconds):
    assert parse_shutter_speed(format_shutter_speed(seconds)) == pytest.approx(seconds)
