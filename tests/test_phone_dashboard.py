"""Phone dashboard: the local web page that shows the run and has the +/-1 EV and abort controls."""

import json
import os
import queue
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from solareclipseworkbench.camera import (EXPOSURE_COMPENSATION_STEP_EV, get_exposure_compensation,
                                          set_exposure_compensation)
from solareclipseworkbench.phone_dashboard import (ACTION_ABORT, ACTION_EV_DOWN, ACTION_EV_RESET, ACTION_EV_UP,
                                                   ACTION_LIVE_CAMERA, ACTION_LIVE_POINT,
                                                   DashboardServer)


@pytest.fixture
def server():
    received = []
    srv = DashboardServer(port=18766, on_action=lambda action, data: received.append(action))
    srv.received = received
    srv.start()
    yield srv
    srv.stop()


def _base(srv):
    return f"http://127.0.0.1:{srv.port}"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


def _post(url, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


def test_page_and_state_need_the_key(server):
    for path in ("/", "/state", "/?k=wrong", "/state?k=wrong"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(_base(server) + path)
        assert exc.value.code == 403

    status, page = _get(f"{_base(server)}/?k={server.key}")
    assert status == 200
    assert b"Abort run" in page


def test_state_is_the_last_one_set(server):
    server.set_state({"ev": 2, "jobs": [{"command": "take_picture"}]})
    status, body = _get(f"{_base(server)}/state?k={server.key}")
    assert status == 200
    assert json.loads(body) == {"ev": 2, "jobs": [{"command": "take_picture"}]}


def test_actions_are_passed_on(server):
    for action in (ACTION_EV_UP, ACTION_EV_DOWN, ACTION_EV_RESET, ACTION_ABORT):
        assert _post(f"{_base(server)}/action?k={server.key}", {"action": action}) == 200
    assert server.received == [ACTION_EV_UP, ACTION_EV_DOWN, ACTION_EV_RESET, ACTION_ABORT]


def test_unknown_or_unauthorised_actions_are_refused(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{_base(server)}/action?k={server.key}", {"action": "rm -rf"})
    assert exc.value.code == 400

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{_base(server)}/action?k=wrong", {"action": ACTION_ABORT})
    assert exc.value.code == 403

    assert server.received == []


def test_live_view_frame_is_served_with_the_key(server):
    url = f"{_base(server)}/live.jpg?k={server.key}"
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(url)
    assert exc.value.code == 404

    server.set_frame(b"\xff\xd8jpeg", 3)
    assert _get(url) == (200, b"\xff\xd8jpeg")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{_base(server)}/live.jpg?k=wrong")
    assert exc.value.code == 403

    server.set_frame(None)
    with pytest.raises(urllib.error.HTTPError):
        _get(url)


def test_loupe_is_served_with_its_frame(server):
    url = f"{_base(server)}/loupe.png?k={server.key}"
    server.set_frame(b"\xff\xd8jpeg", 4, b"\x89PNG")
    assert _get(url) == (200, b"\x89PNG")
    # No frame, no loupe
    server.set_frame(None, 0, b"\x89PNG")
    with pytest.raises(urllib.error.HTTPError):
        _get(url)


def test_a_tap_on_the_live_view_needs_a_point_on_it():
    received = []
    srv = DashboardServer(on_action=lambda action, data: received.append(data))
    body = lambda **d: json.dumps({"action": ACTION_LIVE_POINT, **d}).encode()
    assert srv._handle_action(body(x=0.25, y=1)) == 200
    assert received == [{"action": ACTION_LIVE_POINT, "x": 0.25, "y": 1.0}]
    for bad in (body(), body(x=0.5), body(x="a", y=0.5), body(x=1.5, y=0.5), body(x=0.5, y=-0.1)):
        assert srv._handle_action(bad) == 400
    assert len(received) == 1


def test_next_free_port_is_used(server):
    other = DashboardServer(port=server.port)
    other.start()
    try:
        assert other.port != server.port
        assert other.lan_url.endswith(f":{other.port}/?k={other.key}")
    finally:
        other.stop()


def test_url_carries_the_key():
    srv = DashboardServer()
    assert len(srv.key) >= 12
    assert DashboardServer().key != srv.key


# The controller side: the actions are carried out on the UI thread

def _controller(running=True):
    from solareclipseworkbench.gui import SolarEclipseController

    calls = []
    ctrl = SimpleNamespace(
        _phone_actions=queue.Queue(),
        scheduler=SimpleNamespace(running=running),
        _shutdown_scheduler=lambda: calls.append("shutdown"),
        update_time=lambda: calls.append("update_time"),
        calls=calls,
    )
    ctrl._apply_exposure_compensation = lambda ev: set_exposure_compensation(ev)
    ctrl.handle = lambda: SolarEclipseController._handle_phone_actions(ctrl)
    return ctrl


@pytest.fixture(autouse=True)
def _no_compensation():
    set_exposure_compensation(0)
    yield
    set_exposure_compensation(0)


def test_ev_controls_change_the_compensation():
    ctrl = _controller()
    for action in (ACTION_EV_UP, ACTION_EV_UP, ACTION_EV_DOWN):
        ctrl._phone_actions.put((action, {}))
    ctrl.handle()
    assert get_exposure_compensation() == EXPOSURE_COMPENSATION_STEP_EV
    assert ctrl.calls == ["update_time"]

    ctrl._phone_actions.put((ACTION_EV_RESET, {}))
    ctrl.handle()
    assert get_exposure_compensation() == 0


def test_abort_stops_a_running_scheduler_only():
    ctrl = _controller(running=True)
    ctrl._phone_actions.put((ACTION_ABORT, {}))
    ctrl.handle()
    assert "shutdown" in ctrl.calls

    ctrl = _controller(running=False)
    ctrl._phone_actions.put((ACTION_ABORT, {}))
    ctrl.handle()
    assert "shutdown" not in ctrl.calls


# End to end through the main window: the state reaches the page, and the controls reach the scheduler

@pytest.fixture
def controller(tmp_path, monkeypatch):
    import sys
    from PyQt6.QtWidgets import QApplication
    from solareclipseworkbench import gui

    _app = QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(gui.SolarEclipseController, "set_reference_moments", lambda self: None)
    ctrl = gui.SolarEclipseController(gui.SolarEclipseModel(), gui.SolarEclipseView(), is_simulator=False,
                                      low_cpu_mode=False)
    yield ctrl
    ctrl._stop_phone_dashboard()
    for timer in (ctrl.time_display_timer, ctrl._problem_timer, ctrl.visualization_timer):
        timer.stop()
    if ctrl.scheduler is not None and ctrl.scheduler.running:
        ctrl.scheduler.shutdown(wait=False)
    ctrl.view.deleteLater()


def test_dashboard_shows_the_jobs_and_aborts_the_run(controller):
    from datetime import datetime, timedelta, timezone

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger

    from solareclipseworkbench.camera import CameraSettings, take_picture
    from solareclipseworkbench.gui import JobsTableModel

    scheduler = BackgroundScheduler(timezone=timezone.utc)
    scheduler.add_job(take_picture, trigger=DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(hours=1)),
                      args=[object(), CameraSettings("VirtualCamera", "1/1000", "8", 200)], name="Partial phase")
    scheduler.start(paused=True)
    controller.model.longitude, controller.model.latitude = 4.7, 50.9
    controller.scheduler = scheduler
    controller.jobs_model = JobsTableModel(scheduler, controller)

    controller._open_phone_dashboard()
    server = controller._phone_dashboard
    assert server is not None and server.running

    _, body = _get(f"http://127.0.0.1:{server.port}/state?k={server.key}")
    state = json.loads(body)
    assert state["running"] is True
    assert state["jobs_remaining"] == 1
    assert state["jobs"][0]["description"] == "Partial phase"
    assert 3500 < state["jobs"][0]["seconds"] <= 3600
    assert state["live"] is None

    _post(f"http://127.0.0.1:{server.port}/action?k={server.key}", {"action": ACTION_EV_UP})
    controller._handle_phone_actions()
    assert get_exposure_compensation() == EXPOSURE_COMPENSATION_STEP_EV
    assert "1/500" in controller.jobs_model._data.iloc[0]["Command"]

    _post(f"http://127.0.0.1:{server.port}/action?k={server.key}", {"action": ACTION_ABORT})
    controller._handle_phone_actions()
    assert not scheduler.running
    _, body = _get(f"http://127.0.0.1:{server.port}/state?k={server.key}")
    state = json.loads(body)
    assert state["running"] is False and state["jobs"] == []

    controller._stop_phone_dashboard()
    assert controller._phone_dashboard is None and not server.running


def test_dashboard_shows_the_frames_of_the_live_view_window(controller):
    class _LiveView:
        _camera = SimpleNamespace(name="VirtualCamera")
        share_with_phone = False

        def isVisible(self):
            return True

        def phone_frame(self):
            return b"\xff\xd8frame", 7, 0.5

        def phone_tools(self):
            return {"histogram": {"bins": [1.0, 0.5], "clipped": 0.0, "black": 90.0, "clipped_from": 250},
                    "loupe": {"score": 12.5, "share": 1.0, "x": 0.5, "y": 0.5}}, b"\x89PNG"

        def set_zoom_centre_from_phone(self, x, y):
            self.points.append((x, y))

        def phone_status(self):
            return "paused"

        def set_totality_paused(self, paused):
            pass

    window = _LiveView()
    window.points = []
    controller._live_view_window = window
    controller._open_phone_dashboard()
    server = controller._phone_dashboard

    state = json.loads(_get(f"http://127.0.0.1:{server.port}/state?k={server.key}")[1])
    assert window.share_with_phone
    assert state["live"]["camera"] == "VirtualCamera" and state["live"]["status"] == "paused"
    assert state["live"]["frame"] == 7 and state["live"]["age"] == 0.5
    assert state["live"]["histogram"]["black"] == 90.0 and state["live"]["loupe"]["score"] == 12.5
    assert _get(f"http://127.0.0.1:{server.port}/live.jpg?k={server.key}") == (200, b"\xff\xd8frame")
    assert _get(f"http://127.0.0.1:{server.port}/loupe.png?k={server.key}") == (200, b"\x89PNG")

    _post(f"http://127.0.0.1:{server.port}/action?k={server.key}", {"action": ACTION_LIVE_POINT, "x": 0.2, "y": 0.7})
    controller._handle_phone_actions()
    assert window.points == [(0.2, 0.7)]

    controller._stop_phone_dashboard()
    assert not window.share_with_phone
    controller._live_view_window = None


def test_a_camera_for_live_view_must_be_a_name():
    received = []
    srv = DashboardServer(on_action=lambda action, data: received.append(data))
    body = lambda **d: json.dumps({"action": ACTION_LIVE_CAMERA, **d}).encode()
    assert srv._handle_action(body(camera="Canon EOS R5")) == 200
    assert srv._handle_action(body(camera="")) == 200
    for bad in (body(), body(camera=3), body(camera="x" * 201)):
        assert srv._handle_action(bad) == 400
    assert received == [{"action": ACTION_LIVE_CAMERA, "camera": "Canon EOS R5"},
                        {"action": ACTION_LIVE_CAMERA, "camera": ""}]


@pytest.fixture
def two_cameras(controller, monkeypatch):
    """Two virtual cameras, and a LiveViewWindow that touches no camera."""
    from solareclipseworkbench import gui
    from solareclipseworkbench.camera import VirtualCamera

    class _Window:
        opened = []

        def __init__(self, camera, parent=None):
            self._camera = camera
            self.visible = False
            self.paused = None
            self.share_with_phone = False
            _Window.opened.append(self)

        def set_totality_paused(self, paused):
            self.paused = paused

        def show(self):
            self.visible = True

        def isVisible(self):
            return self.visible

        def close(self):
            self.visible = False

        def phone_frame(self):
            return None, 0, None

        def phone_tools(self):
            return {}, None

        def phone_status(self):
            return "paused" if self.paused else "active"

    monkeypatch.setattr(gui, "LiveViewWindow", _Window)
    first, second = VirtualCamera(), VirtualCamera()
    first.name, second.name = "Canon EOS R5", "Nikon Z8"
    controller.model.camera_overview.camera_overview_dict = {"Canon EOS R5": first, "Nikon Z8": second}
    return controller, _Window


def _contacts(controller, c2_in_s):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    c2, c3 = now + timedelta(seconds=c2_in_s), now + timedelta(seconds=c2_in_s + 120)
    controller.model.c2_info = SimpleNamespace(time_utc=c2, time_local=c2)
    controller.model.c3_info = SimpleNamespace(time_utc=c3, time_local=c3)
    return now


def test_the_phone_picks_the_camera_for_live_view(two_cameras):
    controller, window_class = two_cameras
    controller._reference_now = _contacts(controller, 3600)
    controller._open_phone_dashboard()

    state = controller._phone_dashboard_state(controller._reference_now)
    assert state["live_cameras"] == ["Canon EOS R5", "Nikon Z8"]
    assert state["live_camera"] == "" and state["live_switch"] is True

    controller._switch_live_view_from_phone("Nikon Z8")
    first = controller._live_view_window
    assert first._camera.name == "Nikon Z8" and first.visible and first.share_with_phone
    assert controller._phone_dashboard_state(controller._reference_now)["live_camera"] == "Nikon Z8"

    controller._switch_live_view_from_phone("Canon EOS R5")
    assert not first.visible
    assert controller._live_view_window._camera.name == "Canon EOS R5"

    # An unknown camera changes nothing; "" closes live view
    controller._switch_live_view_from_phone("Sony A1")
    assert controller._live_view_window._camera.name == "Canon EOS R5"
    controller._switch_live_view_from_phone("")
    assert controller._live_view_window is None
    assert len(window_class.opened) == 2


def test_the_camera_is_not_changed_around_totality(two_cameras):
    controller, window_class = two_cameras
    controller._reference_now = _contacts(controller, 60)
    controller._switch_live_view_from_phone("Canon EOS R5")
    assert controller._live_view_window is not None and controller._live_view_window.paused is False

    controller._reference_now = _contacts(controller, 10)   # within 15 s of C2
    controller._open_phone_dashboard()
    assert controller._phone_dashboard_state(controller._reference_now)["live_switch"] is False
    controller._switch_live_view_from_phone("Nikon Z8")
    controller._switch_live_view_from_phone("")
    assert controller._live_view_window._camera.name == "Canon EOS R5"
    assert controller._live_view_window.visible
    assert len(window_class.opened) == 1


def test_a_live_view_opened_around_totality_starts_paused(two_cameras):
    controller, _ = two_cameras
    controller._reference_now = _contacts(controller, -30)  # in totality
    controller._show_live_view(controller.model.camera_overview.camera_overview_dict["Nikon Z8"])
    assert controller._live_view_window.paused is True
