from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from solareclipseworkbench.usb_gps import estimate_time_offset


def _noop():
    pass


def test_estimate_time_offset_picks_sample_with_smallest_latency():
    t0 = datetime(2026, 8, 12, 18, 0, 0, tzinfo=timezone.utc)
    computer_clock_error = timedelta(seconds=10)  # computer is 10 s slow
    latencies = [timedelta(seconds=s) for s in (0.4, 0.12, 0.3, 0.9)]
    samples = [(t0 + timedelta(seconds=i), t0 + timedelta(seconds=i) - computer_clock_error + latency)
               for i, latency in enumerate(latencies)]

    assert estimate_time_offset(samples) == computer_clock_error - timedelta(seconds=0.12)


def test_estimate_time_offset_ignores_stale_buffered_sentence():
    t0 = datetime(2026, 8, 12, 18, 0, 0, tzinfo=timezone.utc)
    # First sentence was buffered for 3 s before being read; the others are fresh.
    samples = [(t0, t0 + timedelta(seconds=3.1)),
               (t0 + timedelta(seconds=3), t0 + timedelta(seconds=3.1)),
               (t0 + timedelta(seconds=4), t0 + timedelta(seconds=4.1))]

    assert estimate_time_offset(samples) == timedelta(seconds=-0.1)


def test_estimate_time_offset_requires_samples():
    with pytest.raises(ValueError):
        estimate_time_offset([])


def test_jobs_table_shows_gps_corrected_times():
    from solareclipseworkbench.gui import JobsTableModel, JobsTableColumnNames

    gps_time_offset = timedelta(seconds=10)  # GPS is 10 s ahead of the computer
    gps_now = datetime.now(timezone.utc) + gps_time_offset
    true_execution_time = gps_now.replace(microsecond=0) + timedelta(hours=1)

    scheduler = BackgroundScheduler(timezone=timezone.utc)
    # Scheduled on the computer clock, as schedule_command() does
    scheduler.add_job(_noop, trigger=DateTrigger(run_date=true_execution_time - gps_time_offset),
                      name="C2 shot")
    scheduler.start(paused=True)
    try:
        controller = SimpleNamespace(
            view=SimpleNamespace(time_format="24 hours"),
            model=SimpleNamespace(longitude=4.7, latitude=50.9, gps_time_offset=gps_time_offset),
        )
        model = JobsTableModel(scheduler, controller)
    finally:
        scheduler.shutdown(wait=False)

    assert model.execution_times_utc_as_datetime == [true_execution_time]

    countdown = model._data.loc[0, JobsTableColumnNames.COUNTDOWN.value]
    minutes, seconds = (int(part) for part in countdown.split(":"))
    # About an hour to go on the GPS clock, not 10 s less
    assert minutes * 60 + seconds >= 3595
