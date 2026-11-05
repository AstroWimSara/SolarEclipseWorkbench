"""Draining the volatile buffer of a Fuji body.

Every frame shot with an SDK session open holds one of 32 slots until it is
drained, and a full buffer stops the body until its battery is removed.  The
drain works from the count the body reports, so a wrong count is not seen until
the buffer is full.
"""

import time
from unittest.mock import MagicMock

import pytest

from fujixsdk import camera as camera_mod
from fujixsdk._constants import ERRCODE_BUSY, IMAGEFORMAT_NONE, IMAGEFORMAT_RAW
from fujixsdk._errors import BusyError
from fujixsdk.camera import Camera


def _camera(captured, formats=None):
    """A camera whose buffer reports `captured` images pending."""
    cam = Camera.__new__(Camera)              # bypass the SDK-dependent __init__
    cam._closed = True                        # nothing to close down at collection
    cam.get_buffer_capacity = MagicMock(return_value=(captured, 32))
    cam.delete_image = MagicMock()
    info = MagicMock(format=IMAGEFORMAT_RAW, data_size=1024)
    cam.read_image_info = MagicMock(
        side_effect=formats if formats is not None else lambda: info)
    return cam


def test_everything_the_buffer_reports_is_drained():
    # Measured on an X-T4: filling to 30/32 and draining, the number deleted
    # matched the number reported every round (31/31, 31/31, 30/30, 31/31,
    # 30/30).  One pass is enough because nothing arrives late.
    cam = _camera(13)

    assert cam.drain_buffer() == 13
    assert cam.get_buffer_capacity.call_count == 1


def test_a_buffer_that_reads_empty_costs_nothing():
    cam = _camera(0)

    assert cam.drain_buffer() == 0
    cam.delete_image.assert_not_called()


def test_a_pass_that_stops_early_says_so(caplog):
    # Draining fewer than the buffer reported means images are still queued, and
    # the next bracket inherits them: worth a warning, not a silent shortfall.
    none_at_third = [MagicMock(format=IMAGEFORMAT_RAW, data_size=1024)] * 2 + \
                    [MagicMock(format=IMAGEFORMAT_NONE, data_size=0)]
    cam = _camera(13, formats=none_at_third)

    with caplog.at_level('WARNING', logger=camera_mod.log.name):
        assert cam.drain_buffer() == 2

    assert 'the rest go with the next drain' in caplog.text


def test_a_busy_read_is_waited_out_and_the_image_still_drained():
    cam = _camera(1)
    cam.read_image_info.side_effect = [BusyError(ERRCODE_BUSY, 'Camera is busy'),
                                       MagicMock(format=IMAGEFORMAT_RAW, data_size=1024)]

    assert cam.drain_buffer() == 1
    cam.delete_image.assert_called_once()


def test_nothing_is_deleted_or_counted_on_a_read_that_never_clears(monkeypatch):
    # Deleting blind on a busy read would inflate the drain figure with images
    # that may never have existed, and that figure is the only evidence of how
    # many frames one release really queues.
    monkeypatch.setattr(camera_mod, 'DRAIN_BUDGET_S', 0.02)
    monkeypatch.setattr(camera_mod, 'DRAIN_BUSY_BACKOFF_S', 0.005)
    cam = _camera(13)
    cam.read_image_info.side_effect = BusyError(ERRCODE_BUSY, 'Camera is busy')

    assert cam.drain_buffer() == 0
    cam.delete_image.assert_not_called()


def test_a_delete_refused_while_busy_is_retried_not_abandoned(monkeypatch):
    # The read already confirmed an image is there, so the slot has to come back
    # or the body stops dead when the buffer fills.
    monkeypatch.setattr(camera_mod, 'DRAIN_BUSY_BACKOFF_S', 0.001)
    cam = _camera(1)
    cam.delete_image.side_effect = [BusyError(ERRCODE_BUSY, 'Camera is busy'), None]

    assert cam.drain_buffer() == 1
    assert cam.delete_image.call_count == 2


def test_draining_stays_inside_its_budget_however_much_the_body_holds(monkeypatch):
    # A drain runs between shots: a body that will not let go must not hold the
    # schedule for as long as it likes.
    monkeypatch.setattr(camera_mod, 'DRAIN_BUDGET_S', 0.02)
    monkeypatch.setattr(camera_mod, 'DRAIN_BUSY_BACKOFF_S', 0.005)
    cam = _camera(32)
    cam.delete_image.side_effect = BusyError(ERRCODE_BUSY, 'Camera is busy')

    started = time.monotonic()
    cam.drain_buffer()

    assert time.monotonic() - started < 0.5
