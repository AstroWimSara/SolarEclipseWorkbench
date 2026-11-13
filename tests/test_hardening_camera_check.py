"""Hardening of the camera check: odd script values must not end the whole check."""
from solareclipseworkbench import camera_check
from solareclipseworkbench.camera_check import (
    ERROR, OK, ExposureLimits, ScriptCommand, check_settings, fit_exposure, run_active_test,
)

from test_camera_check import PROFILE_1000D, FakeCanon


def _command(iso, func="take_picture"):
    return ScriptCommand(func, "C2", "-", "00:00:05.0", "Canon EOS 1000D",
                         ["Canon EOS 1000D", "1/1000", "8", iso], "test")


def test_iso_auto_does_not_stop_the_settings_check():
    report = camera_check.TestReport()
    check_settings(FakeCanon(), [_command("Auto"), _command("100")], report)
    titles = [item.title for item in report.items]
    assert "All ISO values are available" in titles
    assert any(title.startswith("All shutter speeds") for title in titles)


def test_iso_that_is_not_a_number_fails_only_the_test_picture(monkeypatch):
    monkeypatch.setattr(camera_check, "planning_profile", lambda *a, **k: "profile")
    monkeypatch.setattr("solareclipseworkbench.camera.set_time", lambda camera: True)
    report = camera_check.TestReport()
    assert run_active_test(FakeCanon(), [_command("Auto")], report) == "profile"
    assert [(item.status, item.title) for item in report.items] == [
        (OK, "Camera clock set and verified"), (ERROR, "The test picture failed")]


def test_zero_iso_or_shutter_speed_is_left_alone():
    limits = ExposureLimits(100, 1600, 2.8, 8)
    assert fit_exposure("1/1000", 0, "8", PROFILE_1000D, limits).changes == []
    assert fit_exposure("-1/1000", 100, "8", PROFILE_1000D, limits).changes == []
    assert fit_exposure("1/1000", 100, "-8", PROFILE_1000D, limits).iso == 100
