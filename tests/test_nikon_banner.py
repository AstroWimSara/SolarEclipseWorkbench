"""Nikon cameras with a release-mode dial need it set to Continuous for take_burst / take_bracket, which the app
cannot do for them, so the banner reminds the user (Issue #160).  take_hdr takes single frames, so it needs no reminder.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from solareclipseworkbench import gui, take_bracket, take_burst, take_hdr, take_picture
from solareclipseworkbench.gui import BannerNotification, CameraOverviewTableModel
from solareclipseworkbench.utils import get_continuous_mode_commands


class FakeNikon:
    vendor = "Nikon"
    name = "Nikon DSC D610"


class FakeSony:
    vendor = "Sony"
    name = "ILCE-7M4"

    def start_background_downloader(self):
        pass

    def stop_background_downloader(self):
        pass


@pytest.fixture
def model(monkeypatch):
    # Card-only with JPEG: always produces a Sony banner line, without touching a real camera
    monkeypatch.setattr(gui, "get_sony_save_destination", lambda cam: "card")
    monkeypatch.setattr(gui, "get_sony_image_quality", lambda cam: "JPEG")

    model = CameraOverviewTableModel()
    model.view = SimpleNamespace(camera_banner=BannerNotification(), camera_overview=None)
    return model


def refresh(model, cameras, user_requested=True):
    """ Apply camera data as `update_camera_overview(user_requested)` would once its worker finished. """
    model._user_requested = user_requested
    model._pending_camera_map = cameras
    model._on_data_ready([[name, "50%", "10", "20"] for name in cameras])


def banner_text(model):
    return model.view.camera_banner.label.text()


def test_nikon_gets_a_reminder_before_a_script_is_loaded(model):
    refresh(model, {"Nikon DSC D610": FakeNikon()})

    assert not model.view.camera_banner.isHidden()
    assert "Nikon DSC D610" in banner_text(model)
    assert "Continuous" in banner_text(model)


def test_reminder_names_the_commands_the_script_uses(model):
    refresh(model, {"Nikon DSC D610": FakeNikon()})

    model.set_continuous_mode_commands({"Nikon DSC D610": {"take_bracket", "take_burst"}})

    assert not model.view.camera_banner.isHidden()
    assert "take_bracket, take_burst" in banner_text(model)


def test_no_reminder_when_the_script_only_takes_single_pictures(model):
    refresh(model, {"Nikon DSC D610": FakeNikon()})

    model.set_continuous_mode_commands({})

    assert model.view.camera_banner.isHidden()


def test_reminder_only_for_the_nikon_the_script_drives_in_continuous_mode(model):
    refresh(model, {"Nikon DSC D610": FakeNikon(), "Nikon Z8": SimpleNamespace(vendor="Nikon", name="Nikon Z8")})

    model.set_continuous_mode_commands({"Nikon Z8": {"take_bracket"}})

    assert "Nikon Z8" in banner_text(model)
    assert "D610" not in banner_text(model)


def test_no_reminder_for_other_brands(model):
    refresh(model, {"Canon EOS R10": SimpleNamespace(vendor="Canon", name="Canon EOS R10")})

    assert model.view.camera_banner.isHidden()


def test_sony_and_nikon_share_one_banner(model):
    refresh(model, {"ILCE-7M4": FakeSony(), "Nikon DSC D610": FakeNikon()})

    assert "ILCE-7M4" in banner_text(model)
    assert "Nikon DSC D610" in banner_text(model)


def test_loading_a_script_shows_a_closed_banner_again_when_its_text_changes(model):
    banner = model.view.camera_banner
    refresh(model, {"Nikon DSC D610": FakeNikon()})
    banner.close_btn.click()

    model.set_continuous_mode_commands({"Nikon DSC D610": {"take_burst"}})

    assert not banner.isHidden()


def test_closed_reminder_stays_closed_on_sync_cameras(model):
    banner = model.view.camera_banner
    refresh(model, {"Nikon DSC D610": FakeNikon()})
    model.set_continuous_mode_commands({"Nikon DSC D610": {"take_burst"}})
    banner.close_btn.click()

    refresh(model, {"Nikon DSC D610": FakeNikon()}, user_requested=False)

    assert banner.isHidden()


def test_stopping_the_script_goes_back_to_the_general_reminder(model):
    refresh(model, {"Nikon DSC D610": FakeNikon()})
    model.set_continuous_mode_commands({})

    model.set_continuous_mode_commands(None)

    assert not model.view.camera_banner.isHidden()


def test_get_continuous_mode_commands_reads_the_scheduled_jobs():
    nikon, sony = FakeNikon(), FakeSony()
    # Same body under its model name and an alias
    cameras = {"Nikon DSC D610": nikon, "Left": nikon, "ILCE-7M4": sony}
    later = datetime.now(pytz.utc) + timedelta(hours=1)

    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    try:
        scheduler.add_job(take_burst, "date", run_date=later, args=[nikon, None, 3.0])
        scheduler.add_job(take_bracket, "date", run_date=later, args=[nikon, None, "0.7 5"])
        scheduler.add_job(take_picture, "date", run_date=later, args=[sony, None])
        scheduler.add_job(take_hdr, "date", run_date=later, args=[sony, None, 4])

        result = get_continuous_mode_commands(scheduler, cameras)
    finally:
        scheduler.shutdown(wait=False)

    # take_hdr takes single frames, so it does not need a continuous release mode
    assert result == {"Nikon DSC D610": {"take_burst", "take_bracket"},
                      "Left": {"take_burst", "take_bracket"}}
