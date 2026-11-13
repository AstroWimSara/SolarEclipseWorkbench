"""The main window keeps running on bad input, bad settings and failing parts (hardening of gui.py)."""

import datetime
import logging
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from solareclipseworkbench import gui
from solareclipseworkbench.gui import (CameraOverviewTableModel, EclipsePlotWidget, SimulatorPopup,
                                       SolarEclipseController, SolarEclipseModel, SolarEclipseView)

# Before the fixture replaces it
REAL_SET_REFERENCE_MOMENTS = SolarEclipseController.set_reference_moments


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def write_settings(path, **values):
    settings = QSettings(str(path / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()


@pytest.fixture
def start(app, tmp_path, monkeypatch):
    monkeypatch.setattr(gui.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(SolarEclipseController, "set_reference_moments", lambda self: None)
    controllers = []

    def _start():
        controller = SolarEclipseController(SolarEclipseModel(), SolarEclipseView(), is_simulator=False,
                                            low_cpu_mode=True)
        controllers.append(controller)
        return controller

    yield _start
    for controller in controllers:
        for timer in (controller.time_display_timer, controller._problem_timer, controller.visualization_timer,
                      controller._beads_fast_timer):
            timer.stop()
        controller.view.deleteLater()


def wait_for(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


# Settings


def test_unreadable_settings_do_not_keep_the_application_from_starting(start, tmp_path):
    ini = tmp_path / ".SolarEclipseWorkbench.ini"
    ini.write_text("[General]\nlongitude=abc\nlatitude=50.0\naltitude=10\neclipse_date=31 Foo 2027\n"
                   "date_format=nonsense\ntime_format=also nonsense\n")

    controller = start()

    assert not controller.model.is_location_set
    assert not controller.model.is_eclipse_date_set
    assert controller.view.date_format in gui.DATE_FORMATS
    assert controller.view.time_format in gui.TIME_FORMATS
    controller.update_time()        # the clock tick works with the formats that were used instead


# Camera overview


def test_sync_cameras_from_the_scheduler_thread_updates_on_the_gui_thread(app):
    threads = []
    # Patched before the model is made: the signal is connected to it at construction
    with mock.patch.object(CameraOverviewTableModel, "update_camera_overview",
                           lambda self, user_requested=True: threads.append(threading.current_thread())):
        model = CameraOverviewTableModel()
        controller = SimpleNamespace(model=SimpleNamespace(camera_overview=model))
        worker = threading.Thread(target=gui.sync_cameras, args=(controller,))
        worker.start()
        worker.join()
        assert wait_for(lambda: threads)

    assert threads == [threading.main_thread()]


def test_no_camera_found_is_applied_and_the_polling_stops(app, monkeypatch):
    model = CameraOverviewTableModel()
    model.view = None
    model.camera_overview_dict = {"old": object()}
    model._force_camera_refresh = True
    monkeypatch.setattr(gui, "get_camera_dict", lambda **kwargs: {})
    monkeypatch.setattr(gui, "ConfigManager", lambda: SimpleNamespace(get_camera_aliases=lambda: {}))
    polls = []
    original = model._try_apply_pending
    monkeypatch.setattr(model, "_try_apply_pending", lambda worker=None: (polls.append(1), original(worker)))

    model.update_camera_overview()

    assert wait_for(lambda: model.camera_overview_dict == {})
    count = len(polls)
    wait_for(lambda: False, timeout=0.6)
    assert len(polls) == count      # no more polling once applied


def test_polling_stops_when_the_worker_ends_without_data(app):
    model = CameraOverviewTableModel()
    model._pending_data = None
    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join()

    with mock.patch.object(gui.QTimer, "singleShot") as single_shot:
        model._try_apply_pending(worker)

    single_shot.assert_not_called()


# Eclipse plot


def test_the_plot_loads_nothing_before_a_location_is_set(app, monkeypatch):
    widget = EclipsePlotWidget()
    load = mock.Mock(return_value=True)
    monkeypatch.setattr(widget, "_ensure_ephemerides_loaded", load)

    widget.plot(datetime.datetime.now(datetime.timezone.utc))

    load.assert_not_called()


def test_a_failed_ephemeris_load_is_not_retried_at_every_redraw(app, monkeypatch):
    monkeypatch.setattr(EclipsePlotWidget, "CACHED_EPHEMERIDES", None)
    monkeypatch.setattr(EclipsePlotWidget, "_load_failed_at", None)
    widget = EclipsePlotWidget()
    loads = []

    def failing_load():
        loads.append(1)
        EclipsePlotWidget._load_failed_at = time.monotonic()
        return False

    monkeypatch.setattr(widget, "_load_ephemerides", failing_load)

    assert widget._ensure_ephemerides_loaded() is False
    assert widget._ensure_ephemerides_loaded() is False

    assert len(loads) == 1


def test_no_second_load_while_one_is_running(app, monkeypatch):
    monkeypatch.setattr(EclipsePlotWidget, "CACHED_EPHEMERIDES", None)
    monkeypatch.setattr(EclipsePlotWidget, "_load_failed_at", None)
    monkeypatch.setattr(EclipsePlotWidget, "_loading", True)
    widget = EclipsePlotWidget()
    load = mock.Mock()
    monkeypatch.setattr(widget, "_load_ephemerides", load)

    assert widget._ensure_ephemerides_loaded() is False
    load.assert_not_called()


# Console silencing


def test_overlapping_quiet_periods_restore_the_console():
    stdout = sys.stdout
    first_in, second_in, first_out = threading.Event(), threading.Event(), threading.Event()

    def first():
        with gui._quiet_console():
            first_in.set()
            second_in.wait(5)
        first_out.set()

    def second():
        first_in.wait(5)
        with gui._quiet_console():
            second_in.set()
            first_out.wait(5)

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sys.stdout is stdout


# Script loading


def test_a_script_that_cannot_be_loaded_is_reported_and_its_scheduler_stopped(start, tmp_path, monkeypatch):
    controller = start()
    controller.model.reference_moments = {"C1": object()}
    script = tmp_path / "script.txt"
    script.write_bytes(b"\xff\xfe garbage")
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *args: (str(script), ""))
    started = mock.Mock()

    def observe(*args, **kwargs):
        controller.scheduler = started        # as if the scheduler had been started before the error
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    from solareclipseworkbench import utils
    monkeypatch.setattr(utils, "observe_solar_eclipse", observe)
    critical = mock.Mock()
    monkeypatch.setattr(QMessageBox, "critical", critical)

    controller.update(controller.view.file_action)

    critical.assert_called_once()
    started.shutdown.assert_called_once_with(wait=False)


# Closing


def test_closing_goes_on_when_a_device_refuses_to_close(start, monkeypatch):
    controller = start()
    monkeypatch.setattr(gui, "register_hardware", lambda *args: None)
    controller.relay_trigger = mock.Mock(**{"close.side_effect": RuntimeError("relay gone")})
    controller.scheduler = mock.Mock()
    camera = mock.Mock()
    controller.model.camera_overview.camera_overview_dict = {"cam": camera}
    popup = mock.Mock()
    controller.mount_popup = popup

    controller.update(QCloseEvent())

    controller.scheduler.shutdown.assert_called_once_with(wait=False)
    camera.exit.assert_called_once_with()
    popup.close.assert_called_once_with()
    assert controller.relay_trigger is None


# Input


def test_a_simulation_offset_that_is_not_a_number_yet_is_not_accepted(start):
    controller = start()
    popup = SimulatorPopup(controller)
    popup.offset_minutes.setText("-")

    with mock.patch.object(controller, "_apply_simulation_offset") as apply:
        popup.accept_starting_time()

    apply.assert_not_called()


# Reference moments


def test_a_new_location_recomputes_the_contact_times(start, monkeypatch):
    controller = start()
    controller.model.is_location_set = controller.model.is_eclipse_date_set = True
    recompute = mock.Mock()
    monkeypatch.setattr(controller, "set_reference_moments", recompute)

    controller._reference_moments_changed("location")

    recompute.assert_called_once_with()


def test_contact_times_are_not_recomputed_while_a_script_runs(start, monkeypatch):
    controller = start()
    controller.model.is_location_set = controller.model.is_eclipse_date_set = True
    controller.scheduler = mock.Mock(**{"get_jobs.return_value": [object()]})
    recompute = mock.Mock()
    monkeypatch.setattr(controller, "set_reference_moments", recompute)

    controller._reference_moments_changed("location")

    recompute.assert_not_called()


def test_failed_contact_times_do_not_leave_the_old_ones_in_use(start, monkeypatch):
    controller = start()
    controller.model.reference_moments = {"C1": object()}
    controller.model.c1_info = object()
    controller.view.c1_time_utc_label.setText("10:00:00.0")
    monkeypatch.setattr(gui, "limb_correction_is_enabled", lambda: False)
    monkeypatch.setattr(controller.model, "get_reference_moments", mock.Mock(side_effect=ValueError("no eclipse")))
    critical = mock.Mock()
    monkeypatch.setattr(QMessageBox, "critical", critical)

    REAL_SET_REFERENCE_MOMENTS(controller)

    critical.assert_called_once()
    assert controller.model.reference_moments is None
    assert controller.model.c1_info is None
    assert controller.view.c1_time_utc_label.text() == ""


# Clock tick


def test_a_failing_window_does_not_starve_the_rest_of_the_clock_tick(start, monkeypatch, caplog):
    controller = start()
    controller._beads_window = mock.Mock(**{"isVisible.return_value": True,
                                            "set_current_time.side_effect": RuntimeError("deleted")})
    countdown = mock.Mock()
    monkeypatch.setattr(controller, "update_jobs_countdown", countdown)

    with caplog.at_level(logging.ERROR):
        controller.update_time()
        controller.update_time()

    assert countdown.call_count == 2
    assert len([r for r in caplog.records if "Baily's beads" in r.getMessage()]) == 1


# Saved locations


def test_the_location_and_compare_sites_windows_share_their_saved_locations(start):
    controller = start()

    assert controller.config_manager() is controller.config_manager()
