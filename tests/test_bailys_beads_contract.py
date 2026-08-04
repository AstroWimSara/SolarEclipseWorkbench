"""Public timing semantics that scripts and the UI rely on."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from solareclipseworkbench import limb_correction
from solareclipseworkbench.limb_correction import BeadWindow, bead_reference_moments, bead_window


def test_unsolved_window_never_looks_like_a_solved_edge(monkeypatch, caplog):
    monkeypatch.setattr(limb_correction, "lit_arc_degrees", lambda *_args: 0.0)

    result = bead_window(
        lambda _when: {}, 1.0, True, np.array([0.0]), np.array([0.0]),
        step_hours=0.1 / 3600.0, limit_hours=0.2 / 3600.0,
    )

    assert result.solved is False
    assert result.search_limit_seconds == pytest.approx(0.2)
    assert "no schedulable bead-window edge" in caplog.text


def test_window_records_the_last_sample_inside_the_capture_criterion(monkeypatch):
    arcs = iter([0.0, 0.0, 21.0])
    monkeypatch.setattr(limb_correction, "lit_arc_degrees", lambda *_args: next(arcs))

    result = bead_window(
        lambda _when: {}, 1.0, True, np.array([0.0]), np.array([0.0]),
        max_arc_deg=20.0, step_hours=0.1 / 3600.0, limit_hours=1.0 / 3600.0,
    )

    assert result.solved is True
    assert result.end == 1.0
    assert result.duration_seconds == pytest.approx(0.2)


@pytest.mark.parametrize("threshold", [-0.1, 360.0])
def test_window_rejects_an_impossible_arc_threshold(threshold):
    with pytest.raises(ValueError, match="max_arc_deg"):
        bead_window(
            lambda _when: {}, 1.0, True, np.array([0.0]), np.array([0.0]),
            max_arc_deg=threshold,
        )


def test_public_contacts_keep_the_published_sheet_point_convention(monkeypatch):
    base = datetime(2026, 8, 12, tzinfo=timezone.utc)

    class FakeSolution:
        c2 = 1.0
        c3 = 4.0
        c2_point = 1.5
        c3_point = 3.5
        c2_limb = 2.0
        c3_limb = 3.0
        windows = {
            "C2": BeadWindow(1.8, 2.0, True, 20.0, 60.0),
            "C3": BeadWindow(3.0, 3.2, False, 20.0, 60.0),
        }

        @staticmethod
        def to_utc(hours):
            return base + timedelta(hours=hours)

    monkeypatch.setattr(limb_correction, "solve_limb", lambda *_args, **_kwargs: FakeSolution())
    limb_correction.set_enabled(True)

    moments = bead_reference_moments("2026-08-12", 0.0, 0.0, 0.0)

    assert moments["C2"] == base + timedelta(hours=1.5)
    assert moments["C3"] == base + timedelta(hours=3.5)
    assert moments["BEADS_C2_STATUS"] == "solved"
    assert moments["BEADS_C3_STATUS"] == "unresolved"
    assert "BEADS_C3_START" not in moments
    assert "BEADS_C3_END" not in moments
