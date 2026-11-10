"""Shared test settings."""
import pytest

from solareclipseworkbench.mount import Mount


@pytest.fixture(autouse=True)
def quick_tracking_check(monkeypatch):
    """Check that tracking holds for 0.3 s instead of 1.5 s, so tracking tests stay fast.

    Still well above the 50 ms after which the simulator drops tracking (track_drops).
    """
    monkeypatch.setattr(Mount, "TRACK_SETTLE_S", 0.3)
