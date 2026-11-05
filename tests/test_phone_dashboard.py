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
        ctrl._phone_actions.put(action)
    ctrl.handle()
    assert get_exposure_compensation() == EXPOSURE_COMPENSATION_STEP_EV
    assert ctrl.calls == ["update_time"]

    ctrl._phone_actions.put(ACTION_EV_RESET)
    ctrl.handle()
    assert get_exposure_compensation() == 0


def test_abort_stops_a_running_scheduler_only():
    ctrl = _controller(running=True)
    ctrl._phone_actions.put(ACTION_ABORT)
    ctrl.handle()
    assert "shutdown" in ctrl.calls

    ctrl = _controller(running=False)
    ctrl._phone_actions.put(ACTION_ABORT)
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
