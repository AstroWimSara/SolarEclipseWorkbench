"""The bead window gets a fast clock near the contacts, and only there."""

import datetime
import time
from types import SimpleNamespace

from solareclipseworkbench.gui import SolarEclipseController

C2 = datetime.datetime(2026, 8, 12, 18, 29, 13, tzinfo=datetime.timezone.utc)
C3 = C2 + datetime.timedelta(seconds=103)


class FakeBeadsWindow:
    def __init__(self, visible=True):
        self.visible = visible
        self.times = []

    def isVisible(self):
        return self.visible

    def set_current_time(self, moment_utc):
        self.times.append(moment_utc)


def _controller(reference_now, window, ticked_seconds_ago=0.0):
    model = SimpleNamespace(c2_info=SimpleNamespace(time_utc=C2), c3_info=SimpleNamespace(time_utc=C3))
    return SimpleNamespace(model=model, _beads_window=window,
                           _beads_clock=(reference_now, time.monotonic() - ticked_seconds_ago))


def test_near_a_contact_the_window_gets_an_extrapolated_time():
    window = FakeBeadsWindow()
    controller = _controller(C2 - datetime.timedelta(seconds=5), window, ticked_seconds_ago=0.6)

    SolarEclipseController._animate_beads(controller)

    assert len(window.times) == 1
    gained = (window.times[0] - (C2 - datetime.timedelta(seconds=5))).total_seconds()
    assert 0.6 <= gained < 1.0


def test_far_from_the_contacts_nothing_is_redrawn():
    window = FakeBeadsWindow()
    controller = _controller(C2 - datetime.timedelta(minutes=10), window)

    SolarEclipseController._animate_beads(controller)

    assert window.times == []


def test_a_hidden_window_is_not_redrawn():
    window = FakeBeadsWindow(visible=False)
    controller = _controller(C3, window)

    SolarEclipseController._animate_beads(controller)

    assert window.times == []


def test_before_the_first_tick_nothing_happens():
    window = FakeBeadsWindow()
    controller = _controller(C2, window)
    controller._beads_clock = None

    SolarEclipseController._animate_beads(controller)

    assert window.times == []
