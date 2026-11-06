"""Nudging the mount (N/S/E/W while a button is held), the simulated mount moving, and the nudge controls."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.hardware_registry import register_hardware
from solareclipseworkbench.indi_simulator import GUIDE_RATE, SimulatedIndiServer
from solareclipseworkbench.mount import Mount, MountError
from solareclipseworkbench.mount_ui import MountNudgePanel, format_position
from solareclipseworkbench.observer import Observer
from solareclipseworkbench.phone_dashboard import (ACTION_MOUNT_HOLD, ACTION_MOUNT_RELEASE, ACTION_MOUNT_STOP,
                                                   DashboardServer)


def _until(condition, timeout=2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hardware_problems.clear()
    register_hardware("mount", None)
    yield
    hardware_problems.clear()
    register_hardware("mount", None)


@pytest.fixture
def server():
    server = SimulatedIndiServer()
    yield server
    server.close()


@pytest.fixture
def mount(server):
    mount = Mount.open(f"127.0.0.1:{server.port}")
    yield mount
    mount.close()


@pytest.fixture
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _motion(server):
    ns, we = server.values("TELESCOPE_MOTION_NS"), server.values("TELESCOPE_MOTION_WE")
    return sorted(name for name, on in {**ns, **we}.items() if on)


# ------------------------------------------------------------------ slew rates


def test_the_slew_rates_have_their_labels(mount):
    assert mount.slew_rates() == [("1x", "Guide"), ("2x", "Centering"), ("3x", "Find"), ("4x", "Max")]
    assert mount.slew_rate == "1x"
    mount.set_slew_rate("3x")
    assert mount.slew_rate == "3x"
    with pytest.raises(MountError, match="no slew rate"):
        mount.set_slew_rate("warp")


# ---------------------------------------------------------------------- nudger


def test_a_held_nudge_moves_until_released(server, mount):
    nudger = mount.nudger
    nudger.hold("N", rate="2x")
    assert _until(lambda: _motion(server) == ["MOTION_NORTH"])
    assert mount.slew_rate == "2x"
    for _ in range(4):          # renewed while the button is held
        nudger.hold("N")
        time.sleep(0.2)
    assert _motion(server) == ["MOTION_NORTH"]
    nudger.release("N")
    assert _until(lambda: _motion(server) == [])
    assert nudger.moving == []


def test_a_nudge_that_is_not_renewed_stops_by_itself(server, mount):
    mount.nudger.hold("E", hold_s=0.3)
    assert _until(lambda: _motion(server) == ["MOTION_EAST"])
    assert _until(lambda: _motion(server) == [], timeout=1.0)


def test_the_opposite_direction_replaces_the_first_and_axes_are_independent(server, mount):
    nudger = mount.nudger
    nudger.hold("N")
    nudger.hold("E")
    assert _until(lambda: _motion(server) == ["MOTION_EAST", "MOTION_NORTH"])
    nudger.hold("S")
    assert _until(lambda: _motion(server) == ["MOTION_EAST", "MOTION_SOUTH"])
    nudger.release("N")         # not the direction that is moving: nothing changes
    time.sleep(0.1)
    assert _motion(server) == ["MOTION_EAST", "MOTION_SOUTH"]
    nudger.release()
    assert _until(lambda: _motion(server) == [])


def test_abort_stops_the_nudge_and_the_mount(server, mount):
    mount.nudger.hold("W")
    assert _until(lambda: _motion(server) == ["MOTION_WEST"])
    mount.nudger.abort()
    assert _until(lambda: ("TELESCOPE_ABORT_MOTION", {"ABORT": True}) in server.received)
    assert _until(lambda: _motion(server) == [])


def test_closing_the_mount_stops_a_nudge(server):
    mount = Mount.open(f"127.0.0.1:{server.port}")
    mount.nudger.hold("S", hold_s=10)
    assert _until(lambda: _motion(server) == ["MOTION_SOUTH"])
    mount.close()
    assert _motion(server) == []


def test_a_failing_nudge_is_reported_once_and_not_retried():
    server = SimulatedIndiServer(refuse={"TELESCOPE_MOTION_NS"})
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        for _ in range(5):
            mount.nudger.hold("N")
            time.sleep(0.05)
        assert _until(lambda: mount.nudger.last_error != "")
        problems = hardware_problems.peek()
        assert len(problems) == 1 and problems[0].source == "Mount"
        mount.close()
    finally:
        server.close()


def test_a_bad_direction_is_refused(mount):
    with pytest.raises(MountError):
        mount.nudger.hold("up")


# ------------------------------------------------------------ simulated motion


def test_the_simulated_mount_moves_with_nudges_pulses_and_park(server, mount):
    mount.track_solar()
    ra, dec = mount.position()
    mount.guide("N", 2000)
    assert _until(lambda: mount.position()[1] > dec)
    assert (mount.position()[1] - dec) * 3600 == pytest.approx(GUIDE_RATE * 15 * 2, abs=0.01)

    mount.set_slew_rate("3x")
    dec = mount.position()[1]
    mount.nudger.hold("S", hold_s=0.5)
    assert _until(lambda: mount.position()[1] < dec - 0.05)

    mount.park()
    assert _until(lambda: mount.position()[1] == 90.0)


def test_a_simulated_mount_that_does_not_track_drifts_with_the_sky(server, mount):
    ra = mount.position()[0]
    assert _until(lambda: mount.position()[0] != ra, timeout=2.5)


def test_positions_read_as_ra_and_dec():
    assert format_position((14.5, -15.5)) == "RA 14h30m00s  Dec −15°30′00″"
    assert format_position(None) == ""


# ----------------------------------------------------------------- the panel


def test_the_panel_hides_without_a_mount_and_nudges_with_one(app, server, mount):
    panel = MountNudgePanel(hide_when_absent=True)
    panel.show()
    panel.refresh()
    assert not panel.isVisible()

    register_hardware("mount", mount)
    panel.refresh()
    assert panel.isVisible()
    assert panel.rate_combo.count() == 4 and panel.rate() == "1x"
    assert panel.position_label.text().startswith("RA ")

    panel.rate_combo.setCurrentIndex(1)
    panel.buttons["N"].pressed.emit()
    assert _until(lambda: _motion(server) == ["MOTION_NORTH"])
    assert _until(lambda: mount.slew_rate == "2x")
    # Longer than one hold: the panel renews it while the button stays down
    assert not _until(lambda: _motion(server) != ["MOTION_NORTH"], timeout=0.8)
    panel.buttons["N"].released.emit()
    assert _until(lambda: _motion(server) == [])

    # The chosen rate is kept for the next time
    other = MountNudgePanel()
    assert other.rate() == "2x"
    other.deleteLater()
    panel.deleteLater()


def test_hiding_the_panel_releases_a_held_button(app, server, mount):
    register_hardware("mount", mount)
    panel = MountNudgePanel()
    panel.show()
    panel.buttons["W"].pressed.emit()
    assert _until(lambda: _motion(server) == ["MOTION_WEST"])
    panel.hide()
    assert _until(lambda: _motion(server) == [])
    panel.deleteLater()


# ----------------------------------------------------------------- the phone


def test_phone_mount_actions_are_checked():
    received = []
    srv = DashboardServer(on_action=lambda action, data: received.append(data))

    def body(**d):
        return json.dumps(d).encode()

    assert srv._handle_action(body(action=ACTION_MOUNT_HOLD, direction="n", rate="2x")) == 200
    assert srv._handle_action(body(action=ACTION_MOUNT_RELEASE, direction="N", rate="2x")) == 200
    assert srv._handle_action(body(action=ACTION_MOUNT_STOP)) == 200
    assert received == [{"action": ACTION_MOUNT_HOLD, "direction": "N", "rate": "2x"},
                        {"action": ACTION_MOUNT_RELEASE, "direction": "N"},
                        {"action": ACTION_MOUNT_STOP}]
    for bad in (body(action=ACTION_MOUNT_HOLD), body(action=ACTION_MOUNT_HOLD, direction="up"),
                body(action=ACTION_MOUNT_HOLD, direction=1), body(action=ACTION_MOUNT_HOLD, direction="N", rate=3),
                body(action=ACTION_MOUNT_HOLD, direction="N", rate="x" * 41)):
        assert srv._handle_action(bad) == 400


@pytest.fixture
def controller(app, monkeypatch):
    from solareclipseworkbench import gui

    monkeypatch.setattr(gui.SolarEclipseController, "set_reference_moments", lambda self: None)
    ctrl = gui.SolarEclipseController(gui.SolarEclipseModel(), gui.SolarEclipseView(), is_simulator=False,
                                      low_cpu_mode=False)
    yield ctrl
    for timer in (ctrl.time_display_timer, ctrl._problem_timer, ctrl.visualization_timer):
        timer.stop()
    ctrl.view.deleteLater()


def test_the_phone_nudges_and_stops_the_mount(controller, server, mount):
    assert controller._phone_mount_state() is None
    controller.mount = mount

    state = controller._phone_mount_state()
    assert state["connected"] and state["rates"][0] == ["1x", "Guide"] and state["rate"] == "1x"
    assert state["position"].startswith("RA ")

    controller._phone_actions.put((ACTION_MOUNT_HOLD, {"direction": "E", "rate": "4x"}))
    controller._handle_phone_actions()
    assert _until(lambda: _motion(server) == ["MOTION_EAST"])
    assert _until(lambda: mount.slew_rate == "4x")
    controller._phone_actions.put((ACTION_MOUNT_RELEASE, {"direction": "E"}))
    controller._handle_phone_actions()
    assert _until(lambda: _motion(server) == [])

    controller._phone_actions.put((ACTION_MOUNT_STOP, {}))
    controller._handle_phone_actions()
    assert _until(lambda: ("TELESCOPE_ABORT_MOTION", {"ABORT": True}) in server.received)
    controller.mount = None


# --------------------------------------------------------- the Mount window


def test_the_simulated_mount_is_one_tick_away(app, monkeypatch):
    from solareclipseworkbench import gui

    class Controller(Observer):
        is_simulator = True
        mount = None
        mount_calibration = None
        centrer = None
        _live_view_window = None

        def stop_centring(self):
            pass

        def stop_indi_server(self):
            pass

        def update(self, changed_object):
            pass

        def do(self, actions):
            pass

        def send_site_to_mount(self):
            return self.mount.send_site(40.4, -3.7, 650)

    controller = Controller()
    popup = gui.MountPopup(controller)
    try:
        # Ticked by itself in simulation mode, and the server fields are not needed then
        assert popup.simulated_checkbox.isChecked()
        assert not popup.address.isEnabled()
        popup.connect_or_disconnect()
        assert controller.mount is not None and "simulated" in controller.mount.describe()
        assert popup.nudge_panel.isEnabled() and popup.nudge_panel.buttons["N"].isEnabled()
        popup.connect_or_disconnect()
        assert controller.mount is None
    finally:
        if controller.mount is not None:
            controller.mount.close()
        popup.close()
