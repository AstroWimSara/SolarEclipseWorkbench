"""A Sony banner the user closed must stay closed during scheduled `sync_cameras` refreshes (Issue #187).

Pressing `Camera(s)` is the user asking to see the camera state again, so that refresh shows it again.
"""

from types import SimpleNamespace

import pytest

from solareclipseworkbench import gui
from solareclipseworkbench.gui import BannerNotification, CameraOverviewTableModel


class FakeSony:
    vendor = "Sony"
    name = "ILCE-7M4"

    def start_background_downloader(self):
        pass

    def stop_background_downloader(self):
        pass


@pytest.fixture
def model(monkeypatch):
    # Card-only with JPEG: always produces a banner line, without touching a real camera
    monkeypatch.setattr(gui, "get_sony_save_destination", lambda cam: "card")
    monkeypatch.setattr(gui, "get_sony_image_quality", lambda cam: "JPEG")

    model = CameraOverviewTableModel()
    model.view = SimpleNamespace(camera_banner=BannerNotification(), camera_overview=None)
    return model


def refresh(model, user_requested):
    """ Apply camera data as `update_camera_overview(user_requested)` would once its worker finished. """
    model._user_requested = user_requested
    model._pending_camera_map = {"ILCE-7M4": FakeSony()}
    model._on_data_ready([["ILCE-7M4", "50%", "10", "20"]])


def test_banner_is_shown_for_a_sony_with_bad_settings(model):
    refresh(model, user_requested=True)

    assert not model.view.camera_banner.isHidden()


def test_closed_banner_stays_closed_on_sync_cameras(model):
    banner = model.view.camera_banner
    refresh(model, user_requested=True)
    banner.close_btn.click()

    refresh(model, user_requested=False)

    assert banner.isHidden()


def test_camera_button_shows_a_closed_banner_again(model):
    banner = model.view.camera_banner
    refresh(model, user_requested=True)
    banner.close_btn.click()
    refresh(model, user_requested=False)

    refresh(model, user_requested=True)

    assert not banner.isHidden()


def test_sync_cameras_still_shows_a_banner_that_was_never_closed(model):
    refresh(model, user_requested=False)

    assert not model.view.camera_banner.isHidden()


def test_user_request_is_not_lost_when_sync_cameras_runs_before_the_data_arrives(model, monkeypatch):
    # Keep the worker from probing real cameras; only the flag bookkeeping matters here
    monkeypatch.setattr(gui.threading, "Thread", lambda *a, **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(gui.QTimer, "singleShot", lambda *a, **kw: None)
    banner = model.view.camera_banner
    refresh(model, user_requested=True)
    banner.close_btn.click()

    model.update_camera_overview(user_requested=True)
    model.update_camera_overview(user_requested=False)
    model._pending_camera_map = {"ILCE-7M4": FakeSony()}
    model._on_data_ready([["ILCE-7M4", "50%", "10", "20"]])

    assert not banner.isHidden()
