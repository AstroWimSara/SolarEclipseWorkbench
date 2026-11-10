"""The wizard aims the Baily's beads bursts at the bead windows.

With the lunar limb profile the reference moments include each Baily's beads
window, and a burst at a fixed C2-4 s can miss most of it.  The bursts are still
written relative to C2 and C3, so the script keeps working without the profile.
Whatever the timing, a generated script must load without warnings: no command
waiting for the camera, and no false "written for a longer totality".
"""

import copy
import csv
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from astropy.time import Time

from solareclipseworkbench import hardware_problems, limb_correction
from solareclipseworkbench.camera_check import CameraProfile
from solareclipseworkbench.command_timing import (BEADS_WINDOW_MARGIN_S, CONTACT_BURST_S, burst_lead_s,
                                                  burst_shooting_s, vendor_from_name)
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.utils import schedule_commands
from solareclipseworkbench.wizard import SummaryPage

# On the 2026 centre line, where the correction is worth whole seconds
LON, LAT, ALT = -4.5289, 42.0095, 740.0

needs_limb_profile = pytest.mark.skipif(
    limb_correction.load_default_limb(download=False) is None,
    reason=f"lunar limb profile not installed ({limb_correction.band_file()})")


@pytest.fixture(scope="module")
def moments():
    limb_correction.set_enabled(True)
    result, _, _ = calculate_reference_moments(LON, LAT, ALT, Time("2026-08-12"))
    return result


def _script(camera_name, profile=None, **extra_fields):
    fields = {
        'eclipse_name': '2026 Spain', 'eclipse_date': 'August 12, 2026', 'eclipse_type': 'Total',
        'location': 'Spain', 'latitude': str(LAT), 'longitude': str(LON), 'altitude': str(ALT),
        'camera_name': camera_name, 'focal_length': 600, 'aperture_min': 5.6, 'aperture_max': 32,
        'preferred_iso': 400, 'iso_min': 100, 'iso_max': 6400, 'filter_value': '5.0',
        'c1_c4': True, 'equispaced': True, 'seconds_value': 60,
        'diamond': True, 'bailys': True, 'corona': True, 'chromosphere': True, 'prominences': True,
        'sync_enabled': False, 'voice_enabled': False,
    }
    fields.update(extra_fields)
    wizard = MagicMock()
    wizard.field.side_effect = fields.get
    wizard.camera_profiles = {camera_name: profile} if profile is not None else {}
    page = SummaryPage()
    page.wizard = lambda: wizard
    return page._generate_script()


def _command(script, description):
    """(seconds after the reference, reference, burst parameter) of the line with this description."""
    for line in script.split('\n'):
        if line.startswith('take_') and line.rstrip().endswith(f'"{description}"'):
            fields = next(csv.reader([line], skipinitialspace=True))
            h, m, s = fields[3].split(':')
            seconds = (int(h) * 60 + int(m)) * 60 + float(s)
            return (seconds if fields[2] == '+' else -seconds), fields[1], fields
    raise AssertionError(f'no "{description}" in the script')


@needs_limb_profile
@pytest.mark.parametrize("camera_name", ["Canon EOS R5", "Nikon Z8", "Sony ILCE-7RM3A"])
def test_the_beads_bursts_hold_the_last_and_the_first_bead(moments, camera_name):
    """The C2 burst ends just after BEADS_C2_END, the C3 burst starts just before BEADS_C3_START."""
    script = _script(camera_name)
    vendor = vendor_from_name(camera_name)
    margin = timedelta(seconds=BEADS_WINDOW_MARGIN_S)

    at, reference, fields = _command(script, "C2 beads")
    assert reference == "C2"
    shooting = burst_shooting_s(vendor, float(fields[-2]))
    shooting_end = moments["C2"].time_utc + timedelta(seconds=at + burst_lead_s(vendor) + shooting)
    assert abs((shooting_end - (moments["BEADS_C2_END"].time_utc + margin)).total_seconds()) <= 0.1, script

    at, reference, fields = _command(script, "C3 beads")
    assert reference == "C3"
    shooting_start = moments["C3"].time_utc + timedelta(seconds=at + burst_lead_s(vendor))
    assert abs((shooting_start - (moments["BEADS_C3_START"].time_utc - margin)).total_seconds()) <= 0.1, script

    for contact in ("C2", "C3"):
        assert f"# Baily's beads window ({contact}): " in script


# Bracketed corona with earthshine and HDR pictures in between: on a Sony every
# change between a bracket and a single picture costs extra time.
ALL_TOTALITY_SHOTS = {
    'corona_bracket': True, 'bracket_step': '1', 'bracket_frames': 5,
    'earthshine': True, 'hdr_burst': True, 'hdr_stops': 4, 'hdr_start_auto': True, 'hdr_iso_auto': True,
}


@needs_limb_profile
@pytest.mark.parametrize("extra_fields", [{}, ALL_TOTALITY_SHOTS], ids=["default", "bracketed"])
@pytest.mark.parametrize("camera_name", ["Canon EOS R5", "Nikon Z8", "Sony ILCE-7RM3A"])
def test_a_generated_script_loads_without_warnings(moments, camera_name, extra_fields, tmp_path):
    path = tmp_path / "script.txt"
    script = _script(camera_name, **extra_fields)
    if extra_fields:
        assert "take_bracket" in script and "Earthshine" in script and "take_hdr" in script
    path.write_text(script)
    _assert_loads_without_warnings(moments, camera_name, path)


def _assert_loads_without_warnings(moments, camera_name, path):
    # Move the eclipse into the future, so the scheduler keeps every job
    shift = datetime.now(timezone.utc) + timedelta(hours=3) - moments["C2"].time_utc
    future = {}
    for name, value in moments.items():
        if hasattr(value, "time_utc"):
            value = copy.copy(value)
            value.time_utc = value.time_utc + shift
        future[name] = value

    hardware_problems.drain()
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    try:
        unknown = schedule_commands(str(path), scheduler, future, {camera_name: object()}, None, None, None)
    finally:
        scheduler.shutdown(wait=False)

    assert unknown == {}
    assert [str(problem) for problem in hardware_problems.drain()] == []


def test_without_bead_windows_the_bursts_keep_their_fixed_offsets(monkeypatch):
    monkeypatch.setattr(limb_correction, "_enabled", False)

    script = _script("Canon EOS R5")

    assert _command(script, "C2 beads")[:2] == (-4.0, "C2")
    assert _command(script, "C3 beads")[:2] == (1.0, "C3")
    assert "Baily's beads window" not in script


# Full camera tests: a Z 8 with a CFexpress card, and a Canon and a Sony that
# keep up with a 5 s burst.
TESTED = {
    "Nikon Z8": CameraProfile("Nikon Z8", "Nikon", picture_overhead_s=1.0, burst_overhead_s=0.6, burst_fps=20.0,
                              burst_max_s=5.0, full_test=True),
    "Canon EOS R5": CameraProfile("Canon EOS R5", "Canon", picture_overhead_s=1.0, burst_overhead_s=3.0,
                                  burst_busy_per_s=1.2, burst_max_s=5.0, full_test=True),
    "Sony ILCE-7RM3A": CameraProfile("Sony ILCE-7RM3A", "Sony", picture_overhead_s=1.0, burst_overhead_s=3.0,
                                     burst_busy_per_s=1.0, burst_max_s=5.0, full_test=True),
}


@needs_limb_profile
@pytest.mark.parametrize("camera_name", list(TESTED))
def test_a_tested_camera_covers_the_bead_windows_and_its_script_loads_without_warnings(moments, camera_name,
                                                                                       tmp_path):
    profile = TESTED[camera_name]
    script = _script(camera_name, profile=profile)
    vendor = vendor_from_name(camera_name)
    timing = profile.timing_profile()
    assert "# timing: " + camera_name in script

    for contact in ("C2", "C3"):
        at, _, fields = _command(script, f"{contact} beads")
        window = (moments[f"BEADS_{contact}_END"].time_utc - moments[f"BEADS_{contact}_START"].time_utc)
        shooting = burst_shooting_s(vendor, float(fields[-2]), timing)
        # Longer than the standard burst, up to the window plus its margins
        assert CONTACT_BURST_S < shooting <= window.total_seconds() + 1.0 + 0.06, script
    _, _, diamond = _command(script, "C2 diamond ring")
    assert burst_shooting_s(vendor, float(diamond[-2]), timing) == pytest.approx(CONTACT_BURST_S)

    path = tmp_path / "script.txt"
    path.write_text(script)
    _assert_loads_without_warnings(moments, camera_name, path)
