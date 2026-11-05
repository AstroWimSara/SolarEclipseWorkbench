"""Get a busy body back to a state where it will take commands.

"Camera is busy" is not one condition.  The body reports it for a half-pressed
shutter, an exposure in progress, a running live view and an untransferred
image alike, and the remedy differs for each: stopping a live view is free and
instant, while firing a shot to flush the pipeline costs a shutter actuation
and cannot clear a live view at all.  A body still streaming live view from a
crashed process looks like dead hardware when these are treated as one thing.

So this asks first.  XSDK_GetErrorDetails names the blockers in a bitmask, and
the remedies here are ordered by what they cost: read, then stop, then cancel,
then drain, then force, and only last fire a shot.  Each step is skipped when
the body does not report the thing it fixes.

Used on session open, before live view starts, and when a scheduled command
comes back busy.
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import NamedTuple

from . import _constants as C
from ._errors import XSDKError

log = logging.getLogger(__name__)

#: What XSDK_GetErrorDetails reports, from HEADERS/XAPI.H.  The bit values are
#: the SDK's; the names are what they mean to somebody reading a log at 3am.
BLOCKERS: tuple[tuple[int, str], ...] = (
    (0x0001, "the shutter is half pressed"),
    (0x0002, "AE lock is held"),
    (0x0004, "AF lock is held"),
    (0x0008, "instant AF is running"),
    (0x0010, "AF-ON is held"),
    (0x0020, "an exposure is in progress"),
    (0x0040, "the self timer is counting down"),
    (0x0080, "the camera is recording"),
    (0x0100, "live view is running"),
    (0x0200, "an image is waiting to be transferred"),
)

BLOCKER_S1 = 0x0001
BLOCKER_SHOOTING = 0x0020
BLOCKER_LIVEVIEW = 0x0100
BLOCKER_UNTRANSFERRED = 0x0200

#: Forces the body back to shooting standby, from HEADERS/XAPI.H.
FORCE_SHOOT_STANDBY = 0x0001

#: How long a flush shot needs before its frames can be drained.
_FLUSH_SETTLE_S = 0.5


class Blockers(NamedTuple):
    """What the body says is stopping it, and whether it would say."""

    bits: int
    readable: bool

    def __contains__(self, bit: int) -> bool:
        # An unreadable mask must not read as "nothing is wrong": every remedy
        # would then be skipped, which is worse than trying them all.
        return bool(self.bits & bit) if self.readable else True

    def describe(self) -> str:
        if not self.readable:
            return "the body would not say"
        names = [name for bit, name in BLOCKERS if self.bits & bit]
        if not names:
            return "nothing"
        return ", ".join(names)


def read_blockers(camera) -> Blockers:
    """Ask the body what is blocking it.  Never raises."""
    val = ctypes.c_long()
    try:
        rc = camera._lib_inst.XSDK_GetErrorDetails(camera._handle, ctypes.byref(val))
    except Exception:
        log.debug("Could not read the error details", exc_info=True)
        return Blockers(0, readable=False)
    if rc != C.COMPLETE:
        return Blockers(0, readable=False)
    return Blockers(val.value, readable=True)


def read_last_error(camera) -> str:
    """The body's own account of what last went wrong, as api/err codes.

    XSDK_GetErrorNumber reports which API failed and with what, which is the
    detail that turns "camera is busy" in a log into something diagnosable a
    day later.  Never raises: this is only ever called to explain a failure and
    must not become one.
    """
    api, err = ctypes.c_long(), ctypes.c_long()
    try:
        rc = camera._lib_inst.XSDK_GetErrorNumber(
            camera._handle, ctypes.byref(api), ctypes.byref(err))
    except Exception:
        return "error number unreadable"
    if rc != C.COMPLETE:
        return "error number unreadable (rc=%d)" % rc
    return "api=0x%04x err=0x%04x" % (api.value, err.value)


def _priority_taken(camera, mode: int) -> bool:
    """Try to take priority.  True when the body granted it.

    A refusal is logged with its return code and the body's own error number:
    0x1006 while live view runs is a different problem from 0x1006 with an
    image pending, and a log that says only "busy" cannot tell them apart
    afterwards.
    """
    rc = camera._lib_inst.XSDK_SetPriorityMode(camera._handle, ctypes.c_long(mode))
    if rc != C.COMPLETE:
        log.debug("SetPriorityMode(%d) refused: rc=0x%04x, %s, blocked by %s",
                  mode, rc & 0xFFFF, read_last_error(camera),
                  read_blockers(camera).describe())
    return rc == C.COMPLETE


def _release(camera, mode: int) -> None:
    shot_opt = ctypes.c_long(1)
    af_status = ctypes.c_long()
    camera._lib_inst.XSDK_Release(
        camera._handle, ctypes.c_long(mode),
        ctypes.byref(shot_opt), ctypes.byref(af_status))


def unblock(camera, priority: int = C.PRIORITY_CAMERA,
            allow_shot: bool = True, why: str = "") -> bool:
    """Clear what is stopping the body and take the given priority.

    Returns True when the body granted priority.  Steps are ordered by cost and
    skipped when the body does not report the condition they fix, so a healthy
    camera passes through in one call and one round trip.

    allow_shot=False forbids the flush shot.  Pass it during an eclipse, where
    an unplanned actuation is a lost frame and a mirror slap at the wrong
    moment; pass it wherever the caller would rather fail than surprise
    somebody with a shutter firing.
    """
    where = f" ({why})" if why else ""
    blockers = read_blockers(camera)

    # Nothing to clear and priority already ours: the common case, and it must
    # stay cheap because this runs on every recovery path.
    if _priority_taken(camera, priority):
        if blockers.readable and blockers.bits:
            log.debug("Priority taken%s with %s outstanding", where,
                      blockers.describe())
        return True

    log.info("The camera is busy%s: %s (%s)", where, blockers.describe(),
             read_last_error(camera))

    # 1. Live view.  Free, instant, and the one a crashed process leaves behind.
    #    A body in live view refuses priority in both directions while
    #    answering every read normally, which reads as dead hardware.
    if BLOCKER_LIVEVIEW in blockers:
        try:
            camera.stop_live_view()
            log.info("Stopped a live view left running%s", where)
        except XSDKError:
            log.debug("No live view to stop%s", where, exc_info=True)
        if _priority_taken(camera, priority):
            return True

    # 2. A held contact, physical or from a release that never completed.
    if BLOCKER_S1 in blockers:
        _release(camera, C.RELEASE_CANCEL)
        if _priority_taken(camera, priority):
            return True

    # 3. Frames the body is still holding.
    if BLOCKER_UNTRANSFERRED in blockers:
        try:
            camera.drain_buffer()
        except XSDKError:
            log.debug("Could not drain the buffer%s", where, exc_info=True)
        if _priority_taken(camera, priority):
            return True

    # 4. Playback or a menu.  Costs nothing but a mode change.
    try:
        rc = camera._lib_inst.XSDK_SetForceMode(
            camera._handle, ctypes.c_long(FORCE_SHOOT_STANDBY))
        if rc == C.COMPLETE:
            log.info("Forced the body back to shooting standby%s", where)
    except Exception:
        log.debug("Could not force shooting standby%s", where, exc_info=True)
    if _priority_taken(camera, priority):
        return True

    if not allow_shot:
        log.warning("The camera is still busy%s: %s (%s), and a flush shot is "
                    "not allowed here", where,
                    read_blockers(camera).describe(), read_last_error(camera))
        return False

    # 5. Last resort: fire a shot to flush a stuck pipeline.  This actuates the
    #    shutter, so it is last and it is announced.
    log.warning("Firing a flush shot to clear the pipeline%s - the shutter "
                "will fire once", where)
    _release(camera, C.RELEASE_S1ON)
    time.sleep(0.15)
    _release(camera, C.RELEASE_S2_S1OFF)
    time.sleep(_FLUSH_SETTLE_S)

    for _ in range(20):
        try:
            camera.drain_buffer()
        except XSDKError:
            log.debug("Could not drain after the flush shot", exc_info=True)
        if _priority_taken(camera, priority):
            log.info("Priority taken after the flush shot%s", where)
            return True
        time.sleep(0.5)

    log.error("The camera is still busy%s after every remedy: %s (%s).  "
              "Power-cycle the body - take the battery out - and detect it "
              "again", where, read_blockers(camera).describe(),
              read_last_error(camera))
    return False
