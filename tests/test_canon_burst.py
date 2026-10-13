"""Canon take_burst across libgphoto2 versions (Issue #131).

libgphoto2 2.5.34 (python-gphoto2 2.6.4) renamed the ``eosremoterelease``
choices, and bodies such as the EOS R10 do not offer a plain "Continuous"
drive mode.  Both used to fail silently because gp_camera_set_config returns
an error code instead of raising.
"""
import threading
import types

import gphoto2 as gp
import pytest

from solareclipseworkbench import camera as cam

REMOTE_RELEASE_2_5_33 = ["None", "Press Half", "Press Full", "Release Half", "Release Full", "Immediate",
                         "Press 1", "Press 2", "Press 3", "Release 1", "Release 2", "Release 3"]
REMOTE_RELEASE_2_5_34 = ["None", "Press Half AF", "Press Full AF", "Press Half MF", "Press Full MF",
                         "Release Half", "Release Full", "Release"]
DRIVEMODE_R10 = ["Single", "Continuous high speed", "Continuous low speed",
                 "Super high speed continuous shooting", "Timer 10 sec", "Timer 2 sec", "Continuous timer"]


class _Widget:
    def __init__(self, name, choices, value="None"):
        self.name = name
        self.choices = choices
        self.value = value


class _FakeCanon:
    """Records the eosremoterelease/drivemode values pushed with each set_config."""

    def __init__(self, release_choices, drive_choices, valid_release=None, valid_drive=None):
        self.widgets = {
            "eosremoterelease": _Widget("eosremoterelease", release_choices),
            "drivemode": _Widget("drivemode", drive_choices, "Single"),
        }
        # Values libgphoto2 + camera accept; anything else makes set_config fail.
        self.valid = {
            "eosremoterelease": set(valid_release if valid_release is not None else release_choices),
            "drivemode": set(valid_drive if valid_drive is not None else drive_choices),
        }
        self.pushed = []

    def set_config(self):
        for name, widget in self.widgets.items():
            if widget.value not in self.valid[name] and widget.value not in ("None", "Single"):
                return gp.GP_ERROR_NOT_SUPPORTED
        self.pushed.append({n: w.value for n, w in self.widgets.items()})
        return gp.GP_OK


@pytest.fixture
def fake_gp(monkeypatch):
    fake = types.SimpleNamespace(
        check_result=gp.check_result,
        gp_widget_count_choices=lambda w: (gp.GP_OK, len(w.choices)),
        gp_widget_get_choice=lambda w, i: (gp.GP_OK, w.choices[i]),
        gp_widget_get_child_by_name=lambda config, name: (gp.GP_OK, config.widgets[name]),
        gp_widget_set_value=lambda w, v: setattr(w, "value", v) or gp.GP_OK,
    )
    monkeypatch.setattr(cam, "gp", fake)
    return fake


def _run_burst(monkeypatch, canon, duration=2):
    camera = types.SimpleNamespace(vendor="Canon", name="Canon EOS R10", _camera=object(),
                                   _usb_lock=threading.RLock())
    monkeypatch.setattr(cam, "__adapt_camera_settings", lambda c, s: (object(), canon))
    monkeypatch.setattr(cam, "_set_gp_config", lambda c, config, ctx: config.set_config())
    monkeypatch.setattr(cam, "_wait_for_capture_complete", lambda *a, **k: None)
    monkeypatch.setattr(cam, "_drain_camera_events", lambda *a, **k: None)
    monkeypatch.setattr(cam.time, "sleep", lambda s: None)
    single_shots = []
    monkeypatch.setattr(cam, "take_picture", lambda c, s: single_shots.append(s))
    cam.take_burst(camera, object(), duration)
    return single_shots


@pytest.mark.parametrize("choices, expected", [
    (REMOTE_RELEASE_2_5_33, ("Press Full", "Release Full")),
    (REMOTE_RELEASE_2_5_34, ("Press Full MF", "Release")),
])
def test_remote_release_values_match_libgphoto2_version(fake_gp, choices, expected):
    assert cam._canon_remote_release_values(_Widget("eosremoterelease", choices)) == expected


@pytest.mark.parametrize("choices, expected", [
    (["Single", "Continuous", "Timer 10 sec"], "Continuous"),
    (DRIVEMODE_R10, "Continuous high speed"),
    (["Single", "Super high speed continuous shooting"], "Super high speed continuous shooting"),
    (["Single", "Continuous timer", "Silent LS continuous"], "Silent LS continuous"),
    (["Single", "Timer 2 sec", "Continuous timer"], None),
    ([], None),
])
def test_find_continuous_drivemode(fake_gp, choices, expected):
    assert cam._find_canon_continuous_drivemode(_Widget("drivemode", choices)) == expected


@pytest.mark.parametrize("release_choices, press, release", [
    (REMOTE_RELEASE_2_5_33, "Press Full", "Release Full"),
    (REMOTE_RELEASE_2_5_34, "Press Full MF", "Release"),
])
def test_burst_holds_shutter_in_continuous_mode(fake_gp, monkeypatch, release_choices, press, release):
    canon = _FakeCanon(release_choices, DRIVEMODE_R10)

    single_shots = _run_burst(monkeypatch, canon)

    assert single_shots == []
    assert [p["eosremoterelease"] for p in canon.pushed] == ["None", press, release]
    assert all(p["drivemode"] == "Continuous high speed" for p in canon.pushed)


def test_burst_falls_back_to_single_shots_when_press_is_rejected(fake_gp, monkeypatch):
    canon = _FakeCanon(REMOTE_RELEASE_2_5_34, DRIVEMODE_R10, valid_release=[])

    single_shots = _run_burst(monkeypatch, canon, duration=3)

    assert len(single_shots) == 3
