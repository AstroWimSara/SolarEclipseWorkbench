"""Keeping the sun centred from the GUI: simulated mount, virtual camera, calibrate and centre in the Mount window.

The virtual camera's live view shows the simulated sun where the simulated
mount points (sun_simulator.simulated_live_view_jpeg), so the whole chain runs:
Live View window → LiveFrames → Calibrator / Centrer → INDI → simulated mount.
"""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import gui
from solareclipseworkbench.camera import VirtualCamera
from solareclipseworkbench.centring import CENTRED, CORRECTING, Calibration
from solareclipseworkbench.hardware_registry import register_hardware
from solareclipseworkbench.indi_simulator import SimulatedIndiServer
from solareclipseworkbench.mount import Mount
from solareclipseworkbench.sun_simulator import _LIVE_VIEW_CAMERAS, simulated_live_view_jpeg


def _until(condition, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.05)
    return condition()


@pytest.fixture
def controller(tmp_path, monkeypatch):
    _app = QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(gui.SolarEclipseController, "set_reference_moments", lambda self: None)
    ctrl = gui.SolarEclipseController(gui.SolarEclipseModel(), gui.SolarEclipseView(), is_simulator=True,
                                      low_cpu_mode=False)
    yield ctrl
    ctrl.stop_centring()
    if ctrl._live_view_window is not None:
        ctrl._live_view_window.close()
    for timer in (ctrl.time_display_timer, ctrl._problem_timer, ctrl.visualization_timer):
        timer.stop()
    ctrl.view.deleteLater()


@pytest.fixture
def mount(controller):
    """A simulated mount with a fast guide rate, so a calibration takes seconds."""
    server = SimulatedIndiServer(guide_rate=20)
    mount = Mount.open(f"127.0.0.1:{server.port}")
    mount._simulator = server               # closed with the mount; makes the virtual camera show the sun
    mount.track_solar()
    controller.mount = mount
    register_hardware("mount", mount)
    _LIVE_VIEW_CAMERAS.clear()
    yield mount
    register_hardware("mount", None)
    controller.mount = None
    mount.close()


def test_the_virtual_camera_shows_the_simulated_sun(mount):
    from io import BytesIO

    from PIL import Image

    jpeg = VirtualCamera().capture_preview()
    assert jpeg == jpeg and Image.open(BytesIO(jpeg)).size == (960, 640)
    register_hardware("mount", None)
    assert simulated_live_view_jpeg() is None                       # no simulated mount: the old test pattern
    assert Image.open(BytesIO(VirtualCamera().capture_preview())).size == (640, 480)


def test_centring_needs_a_mount_a_live_view_and_a_calibration(controller, mount):
    assert "live view" in controller.start_centring()
    controller._show_live_view(VirtualCamera())
    assert _until(lambda: controller.live_view_frame_size() is not None, 10)
    assert "Calibrate" in controller.start_centring()
    controller.mount_calibration = Calibration(north=(0.0, -0.01), east=(0.01, 0.0), frame_size=(640, 480),
                                               radius=60, camera="VirtualCamera")
    assert "Calibrate again" in controller.start_centring()        # made on other frames


def test_calibrate_and_keep_the_sun_centred_from_the_mount_window(controller, mount, monkeypatch):
    monkeypatch.setattr(gui.QMessageBox, "question", lambda *args: gui.QMessageBox.StandardButton.Yes)
    messages = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *args: messages.append(args[2]))

    controller._show_live_view(VirtualCamera())
    assert _until(lambda: controller.live_view_frame_size() == (960, 640), 10)
    popup = gui.MountPopup(controller)
    try:
        assert popup.centring_checkbox.isEnabled() is False          # not calibrated yet

        popup.calibrate()
        assert popup.calibrate_button.text() == "Stop calibrating"
        assert _until(lambda: popup._calibrator is None, 90), popup.calibration_label.text()
        assert messages == []
        calibration = controller.mount_calibration
        assert calibration is not None and calibration.frame_size == (960, 640)
        assert calibration.camera == "VirtualCamera"
        assert calibration.mount == "Telescope Simulator (simulated by sew)"
        assert abs(calibration.angle_deg - 20) < 3                   # the simulated camera is turned 20°
        assert gui.SolarEclipseController._load_mount_calibration() == calibration     # kept in the settings

        popup.centring_checkbox.setChecked(True)
        assert controller.centrer is not None and controller.centrer.running
        controller.centrer.interval_s = 1.0         # look every second instead of every 15 s
        # The simulated sun starts 35 px off the middle: it is brought back
        assert _until(lambda: controller.centring_status().state == CENTRED, 90), \
            controller.centring_status().message
        assert controller.centring_status().corrections >= 1
        overlay = controller._centring_overlay()
        assert overlay["sun"] is not None and overlay["target"] == (479.5, 319.5)
        assert overlay["state"] == CENTRED
        assert "Centring" in controller._phone_mount_state()["centring"]

        # Pushed off again (as a mount drifts), it comes back
        mount.guide("E", 1500)
        assert _until(lambda: controller.centring_status().state == CORRECTING, 60)
        assert _until(lambda: controller.centring_status().state == CENTRED, 90)

        popup.centring_checkbox.setChecked(False)
        assert controller.centrer is None
    finally:
        popup.close()


def test_no_correction_around_totality(controller, mount, monkeypatch):
    controller._show_live_view(VirtualCamera())
    assert _until(lambda: controller.live_view_frame_size() == (960, 640), 10)
    controller.mount_calibration = Calibration(north=(0.0, -0.05), east=(0.05, 0.0), frame_size=(960, 640),
                                               radius=60, camera="VirtualCamera", mount=mount.identity)
    monkeypatch.setattr(controller, "_live_view_paused_at", lambda now: True)
    assert controller.start_centring() is None
    assert _until(lambda: controller.centring_status().state == "paused", 10)


# ------------------------------------------------- the eclipse in simulation


def test_the_simulated_camera_shows_the_eclipse_of_the_simulated_time(mount, monkeypatch):
    """With the simulated time 10 min before C2 the live view shows that crescent; in totality, the corona."""
    import io

    import numpy as np
    from PIL import Image

    from solareclipseworkbench import sun_simulator
    from solareclipseworkbench.sun_finder import find_sun

    def frame():
        return np.asarray(Image.open(io.BytesIO(simulated_live_view_jpeg())).convert("RGB"))

    monkeypatch.setattr(sun_simulator, "ECLIPSE_CLOCK", lambda: (-600.0, -708.0))
    partial = frame()
    fix = find_sun(partial, radius_hint=60)
    assert fix is not None and fix.bright_fraction < 0.9            # a crescent, not the full disk
    assert (fix.x, fix.y) == pytest.approx((479.5 + 12, 319.5 - 8), abs=1.0)   # where the mount points

    monkeypatch.setattr(sun_simulator, "ECLIPSE_CLOCK", lambda: (40.0, -68.0))
    assert find_sun(frame(), radius_hint=60) is None                  # totality: the corona

    monkeypatch.setattr(sun_simulator, "ECLIPSE_CLOCK", None)         # no time known: a crescent anyway
    assert find_sun(frame(), radius_hint=60) is not None


def test_the_images_follow_the_phase_by_c2_then_by_c3():
    from solareclipseworkbench.sun_simulator import EclipseImages

    images = EclipseImages()
    assert images.pick(-600, -708)["phase"] == "partial"
    assert images.pick(-600, -708)["from_c2"] == pytest.approx(-600, abs=60)
    assert images.pick(30, -78)["phase"] == "totality"
    assert images.pick(300, 192)["from_c3"] == pytest.approx(192, abs=60)   # after C3, by C3
    assert images.pick(None, None)["phase"] == "partial"


def test_the_controller_gives_the_simulated_time_of_the_eclipse(controller):
    assert controller._eclipse_clock() is None                        # no contacts known


def test_a_calibration_of_another_mount_is_not_used(controller, mount):
    """INDI's telescope simulator has the same name as sew's, but mirrors the frame: its calibration
    would push the sun further out (a calibration saved before the mount was recorded neither)."""
    controller._show_live_view(VirtualCamera())
    assert _until(lambda: controller.live_view_frame_size() == (960, 640), 10)
    for other in ("Telescope Simulator", ""):
        controller.mount_calibration = Calibration(north=(0.0, 0.05), east=(0.05, 0.0), frame_size=(960, 640),
                                                   radius=60, camera="VirtualCamera", mount=other)
        problem = controller.start_centring()
        assert problem is not None and "Calibrate again" in problem and "simulated by sew" in problem
        assert controller.centrer is None
