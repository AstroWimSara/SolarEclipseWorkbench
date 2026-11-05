"""Calibrating the mount against the live view: how guide pulses move the sun in the frame."""
import math
import threading
import time

import pytest

from solareclipseworkbench.centring import Calibration, CalibrationError, Calibrator, measure
from solareclipseworkbench.indi_simulator import SimulatedIndiServer
from solareclipseworkbench.mount import Mount
from solareclipseworkbench.sun_simulator import SimulatedSunCamera


class FakeMount:
    """Just a pointing that guide pulses move, at ``rate`` arcseconds per second.

    ``scale`` per direction changes how far a pulse goes (backlash: less), and
    ``axes`` sends a direction's pulses to another axis (a broken setup).
    """

    def __init__(self, ra_h=10.0, dec_deg=15.0, rate=150.0, scale=None, axes=None, moves=True, fast=None):
        self.ra_h, self.dec_deg = ra_h, dec_deg
        self.rate = rate
        self.scale = scale or {}
        self.axes = axes or {}
        self.moves = moves
        self.pulses = []
        #: Speed of the "Centering" slew rate in arcseconds per second, or None for a mount without slew rates
        self.fast = fast
        self.slew_rate = "1x"
        self.motions = []           # (direction, seconds) of the moves at a slew rate
        self._moving = {}           # direction → (time.monotonic() it started, rate)

    def slew_rates(self):
        return [("1x", "Guide"), ("2x", "Centering"), ("3x", "Find")] if self.fast else []

    def set_slew_rate(self, rate):
        self.slew_rate = rate

    def nudge_start(self, direction):
        self._moving[direction] = (time.monotonic(), self.slew_rate)

    def nudge_stop(self, direction):
        started = self._moving.pop(direction, None)
        if started is None:
            return
        seconds = time.monotonic() - started[0]
        self.motions.append((direction, seconds))
        speed = {"1x": 15.0, "2x": self.fast, "3x": self.fast * 8}[started[1]]
        self._shift(direction, speed * seconds)

    def position(self):
        return self.ra_h, self.dec_deg

    def guide(self, direction, milliseconds):
        self.pulses.append((direction, milliseconds))
        if not self.moves:
            return
        self._shift(direction, self.rate * milliseconds / 1000 * self.scale.get(direction, 1.0))

    def _shift(self, direction, arcsec):
        axis = self.axes.get(direction, direction)
        sign = 1 if axis in ("N", "E") else -1
        if axis in ("N", "S"):
            self.dec_deg += sign * arcsec / 3600
        else:
            self.ra_h += sign * arcsec / 3600 / 15 / math.cos(math.radians(self.dec_deg))


def calibrate(mount, frames, **kwargs):
    """Calibrate without waiting: the fake mount moves at once."""
    kwargs.setdefault("wait_for_pulses", not isinstance(mount, FakeMount))
    return Calibrator(mount, frames, settle_s=0.0, find_timeout=2.0, **kwargs).run()


def move_sun_to(calibration, mount, camera, target):
    x, y = camera.sun_in_frame()
    for direction, ms in calibration.pulses_for(target[0] - x, target[1] - y).items():
        mount.guide(direction, ms)
    return camera.sun_in_frame()


# ------------------------------------------------------------- orientations


@pytest.mark.parametrize("rotation", [0, 90, 200, 333])
@pytest.mark.parametrize("mirrored", [False, True])
def test_the_calibration_finds_how_the_axes_lie_in_the_frame(rotation, mirrored):
    mount = FakeMount()
    camera = SimulatedSunCamera(mount, rotation_deg=rotation, mirrored=mirrored, seed=rotation)
    calibration = calibrate(mount, camera)

    assert calibration.mirrored == mirrored
    if not mirrored:
        assert calibration.angle_deg == pytest.approx(rotation, abs=2)
    assert calibration.skew_deg < 3
    # 150″/s at 16″/px
    assert calibration.pixels_per_second() == pytest.approx((150 / 16, 150 / 16), rel=0.05)
    assert calibration.radius == pytest.approx(60, rel=0.02)
    assert calibration.frame_size == (1000, 667)
    assert calibration.warnings == []

    # The pulses it computes bring the sun where it should be
    target = (430.0, 380.0)
    x, y = move_sun_to(calibration, mount, camera, target)
    assert math.hypot(x - target[0], y - target[1]) < 1.0


def test_a_frame_showing_the_sky_as_it_looks_has_guiding_east_move_the_sun_right():
    mount = FakeMount()
    camera = SimulatedSunCamera(mount)          # north up, east left
    x0, _ = camera.sun_in_frame()
    mount.guide("E", 1000)
    assert camera.sun_in_frame()[0] > x0
    calibration = calibrate(mount, camera)
    assert calibration.angle_deg == pytest.approx(0, abs=2) or calibration.angle_deg == pytest.approx(360, abs=2)
    assert not calibration.mirrored


def test_calibrating_on_a_crescent():
    mount = FakeMount()
    camera = SimulatedSunCamera(mount, rotation_deg=45, moon=(0.6, 0.2))
    calibration = calibrate(mount, camera)
    assert calibration.angle_deg == pytest.approx(45, abs=3)
    target = (520.0, 300.0)
    x, y = move_sun_to(calibration, mount, camera, target)
    assert math.hypot(x - target[0], y - target[1]) < 1.0


def test_a_slow_guide_rate_needs_longer_legs():
    mount = FakeMount(rate=20)                  # about 1.2 px per second
    camera = SimulatedSunCamera(mount)
    calibration = calibrate(mount, camera)
    assert calibration.pixels_per_second() == pytest.approx((20 / 16, 20 / 16), rel=0.06)
    longest_leg = max(ms for _, ms in mount.pulses)
    assert longest_leg <= 3000                  # several pulses, none too long


def test_the_sun_is_brought_back_after_each_leg():
    mount = FakeMount()
    camera = SimulatedSunCamera(mount, rotation_deg=10)
    start = camera.sun_in_frame()
    calibrate(mount, camera)
    end = camera.sun_in_frame()
    assert math.hypot(end[0] - start[0], end[1] - start[1]) < 0.5


# ------------------------------------------------------------------ problems


def test_no_sun_in_the_frame():
    mount = FakeMount()
    camera = SimulatedSunCamera(mount, offset=(2000, 0))
    with pytest.raises(CalibrationError, match="not found"):
        Calibrator(mount, camera, settle_s=0.0, find_timeout=1.0).run()


def test_a_mount_that_does_not_move():
    mount = FakeMount(moves=False)
    camera = SimulatedSunCamera(mount)
    with pytest.raises(CalibrationError, match="did not move"):
        calibrate(mount, camera, max_leg_ms=2000)


def test_axes_that_move_the_sun_the_same_way():
    mount = FakeMount(axes={"N": "E", "S": "W"})
    camera = SimulatedSunCamera(mount)
    with pytest.raises(CalibrationError, match="same direction"):
        calibrate(mount, camera)


def test_backlash_is_reported_but_accepted():
    mount = FakeMount(scale={"S": 0.4})
    camera = SimulatedSunCamera(mount)
    calibration = calibrate(mount, camera)
    assert len(calibration.warnings) == 1 and "backlash" in calibration.warnings[0]
    assert "backlash" in calibration.describe()


def test_a_refused_guide_pulse():
    class Refusing(FakeMount):
        def guide(self, direction, milliseconds):
            raise RuntimeError("TELESCOPE_TIMED_GUIDE_WE refused")

    mount = Refusing()
    with pytest.raises(CalibrationError, match="refused a guide pulse"):
        calibrate(mount, SimulatedSunCamera(mount))


def test_a_calibration_can_be_stopped():
    mount = FakeMount(rate=5)                   # slow: the calibration takes long
    camera = SimulatedSunCamera(mount)
    calibrator = Calibrator(mount, camera, settle_s=0.0)
    errors = []

    def run():
        try:
            calibrator.run()
        except CalibrationError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    calibrator.stop()
    thread.join(5)
    assert not thread.is_alive()
    assert errors == ["stopped"]


def test_progress_is_reported():
    lines = []
    mount = FakeMount()
    Calibrator(mount, SimulatedSunCamera(mount), settle_s=0.0, progress=lines.append, wait_for_pulses=False).run()
    assert lines[0] == "looking for the sun"
    assert any(line.startswith("guided N") for line in lines)
    assert lines[-1].startswith("done: ")


# ---------------------------------------------------------- the calibration


def test_a_calibration_is_saved_and_read_back():
    mount = FakeMount()
    calibration = calibrate(mount, SimulatedSunCamera(mount, rotation_deg=120, mirrored=True), camera="Canon EOS R")
    again = Calibration.from_json(calibration.to_json())
    assert again == calibration
    assert again.matches((1000, 667), "Canon EOS R")
    assert not again.matches((667, 1000), "Canon EOS R")       # turned to portrait
    assert not again.matches((1000, 667), "Nikon Z8")


def test_pulses_for_no_movement_are_none():
    calibration = Calibration(north=(0.0, -0.01), east=(0.01, 0.0), frame_size=(1000, 667), radius=60)
    assert calibration.pulses_for(0, 0) == {}
    assert calibration.pulses_for(10, 0) == {"E": pytest.approx(1000)}
    assert calibration.pulses_for(0, 10) == {"S": pytest.approx(1000)}


def test_measuring_waits_for_new_frames():
    mount = FakeMount()
    camera = SimulatedSunCamera(mount)
    x, y, fix = measure(camera, after=time.monotonic())
    assert (x, y) == pytest.approx(camera.sun_in_frame(), abs=0.3)


# ---------------------------------------------------------- with INDI


def test_the_fast_rate_is_calibrated_when_the_mount_has_slew_rates():
    mount = FakeMount(fast=1200)                # "Centering": 75 px a second at 16″/px
    camera = SimulatedSunCamera(mount, rotation_deg=50, mirrored=True)
    calibration = calibrate(mount, camera)
    assert calibration.fast_rate == "2x"
    assert mount.slew_rate == "1x"              # put back
    fast = (math.hypot(*calibration.fast_north) + math.hypot(*calibration.fast_east)) * 500
    assert fast == pytest.approx(1200 / 16, rel=0.15)
    assert "at the 2x rate" in calibration.describe()
    # Moving at the fast rate for the times it computes brings the sun where it should be, roughly
    x, y = camera.sun_in_frame()
    for direction, ms in calibration.moves_for(40, -30).items():
        mount.set_slew_rate("2x")
        mount.nudge_start(direction)
        time.sleep(ms / 1000)
        mount.nudge_stop(direction)
    x2, y2 = camera.sun_in_frame()
    assert math.hypot(x2 - x - 40, y2 - y + 30) < 6


def test_a_mount_without_slew_rates_is_calibrated_for_guiding_only():
    mount = FakeMount()
    calibration = calibrate(mount, SimulatedSunCamera(mount))
    assert not calibration.has_fast_rate


def test_an_older_calibration_without_a_fast_rate_is_read():
    old = ('{"north": [0.0, -0.01], "east": [0.01, 0.0], "frame_size": [960, 640], "radius": 60.0, '
           '"camera": "Canon EOS R", "made": 1.0, "warnings": []}')
    calibration = Calibration.from_json(old)
    assert not calibration.has_fast_rate and calibration.frame_size == (960, 640)


def test_calibrating_the_simulated_indi_mount():
    server = SimulatedIndiServer(guide_rate=20)
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        mount.track_solar()
        camera = SimulatedSunCamera(mount, rotation_deg=30, mirrored=True)
        calibration = calibrate(mount, camera)
        assert calibration.mirrored
        assert calibration.fast_rate == "2x"         # the INDI simulator names its rates as INDI does
        target = (450.0, 300.0)
        x, y = camera.sun_in_frame()
        for direction, ms in calibration.pulses_for(target[0] - x, target[1] - y).items():
            mount.guide(direction, ms)
        time.sleep(0.3)
        x, y = camera.sun_in_frame()
        assert math.hypot(x - target[0], y - target[1]) < 1.0
        mount.close()
    finally:
        server.close()
