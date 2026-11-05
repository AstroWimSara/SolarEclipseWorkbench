"""Fujifilm X series cameras, driven through the Fujifilm Shooting SDK.

libgphoto2 has no tethered control of the X series, so these bodies use the
native SDK through the ``fujixsdk`` bindings instead.  :class:`FujiCamera` is a
:class:`~solareclipseworkbench.camera.BaseCamera`, so a Fuji body appears in the
camera dict beside the gphoto2 cameras and takes the same script commands.

The SDK libraries are not part of this project: Fujifilm distributes them under
its own licence.  :func:`find_fuji_sdk_path` finds them, and
:func:`maybe_reexec_for_fuji_sdk` puts them on the library path at start-up.

Every frame is released over the SDK, one at a time.  The body must therefore be
on single-frame drive (S): on CH the SDK release is refused.  A take_burst is a
run of single frames, at the rate the SDK can release them.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional, Sequence

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.camera import BaseCamera, CameraError, SdkDetection, register_sdk_backend

# The bindings import without the SDK libraries, which are only loaded when a
# camera is opened.  The import itself can fail when the package is missing.
try:
    import fujixsdk
    from fujixsdk import (
        Camera as SDKCamera,
        CameraIssue,
        EclipseShooter,
        ensure_ld_library_path,
        validate_for_eclipse,
    )
    from fujixsdk import recovery as sdk_recovery
    from fujixsdk._constants import (
        AE_MODE_NAMES,
        FOCUS_MODE_NAMES,
        ITEM_MEDIASLOT1 as SDK_ITEM_MEDIASLOT1,
        ITEM_MEDIASLOT2 as SDK_ITEM_MEDIASLOT2,
        POWERCAPACITY_PERCENT,
        SDK_FOCUS_MANUAL,
        SHUTTER_SPEED_NAMES,
    )
    from fujixsdk._errors import BusyError, CommunicationError
    FUJIXSDK_AVAILABLE = True
    FUJIXSDK_IMPORT_ERROR = None
except ImportError as _exc:
    FUJIXSDK_AVAILABLE = False
    FUJIXSDK_IMPORT_ERROR = str(_exc)
    SHUTTER_SPEED_NAMES = {}
    POWERCAPACITY_PERCENT = {}

    class BusyError(Exception):
        """Stand-in so the retry helpers below import without the bindings."""

    class CommunicationError(Exception):
        """Stand-in for the lost-session error, for the same reason."""


# ======================================================================
# Timing
# ======================================================================

# For about a second after a frame the body refuses exposure changes with
# 0x1006 while it writes to the card.  The busy clears by itself.
BUSY_BACKOFF_S = 0.3

# Every retry loop is bounded by a deadline rather than by a count of attempts:
# a frame at the previous exposure still records the eclipse, a frame taken
# after its moment records nothing.  This is the budget for all the settings of
# one configure together.
EXPOSURE_BUDGET_S = 1.5

# A frame is not finished when the release returns: the shutter stays open for
# the exposure, and then the body writes the frame.  The body refuses the next
# setting until then, so the budget of the next configure is extended to cover
# the frame still in progress.  This is how long the body needs after the
# shutter closes.
FRAME_WRITE_S = 1.5

# However long the body needs, the wait is capped here, so that a script that
# asks for something impossible cannot stop the schedule.
MAX_EXPOSURE_WAIT_S = 8.0

# A lost session reports itself once per setting per frame.  Rebuilding it on
# every one would spend the eclipse reconnecting, so one attempt per this long.
RECOVERY_INTERVAL_S = 10.0


def _through_busy(action, what: str, deadline: float, recover=None):
    """Run a camera call, waiting out the 0x1006 the body raises while it writes.

    ``deadline`` is a :func:`time.monotonic` instant past which the call is
    abandoned, so the wait never delays the next scheduled frame.  Only busy is
    retried: waiting cannot make an unsupported value supported.
    """
    while True:
        try:
            return action()
        except CommunicationError:
            # The session is gone (0x2001), not busy.  Every call on the dead
            # handle fails, and a frame taken after it is at whatever exposure
            # the body was last set to.  One rebuild, then one more try.
            if recover is None or not recover():
                raise
            logging.warning('%s: the camera session was rebuilt; retrying', what)
            return action()
        except BusyError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # The exact code and what the body says is blocking it: 0x1006
                # while live view runs is a different fault from 0x1006 with a
                # frame still being written, and "busy" alone cannot tell them apart.
                logging.warning('%s: body still busy at its deadline (%s%s); '
                                'moving on rather than delaying the next frame',
                                what, exc, _busy_detail(recover))
                raise
            logging.debug('%s: body busy (%s), %.1fs of budget left', what, exc, remaining)
            time.sleep(min(BUSY_BACKOFF_S, remaining))


def _busy_detail(recover) -> str:
    """What the body says is blocking it, for the log.  Never raises."""
    camera = getattr(recover, '__self__', None)
    sdk_cam = getattr(camera, '_sdk_cam', None)
    if sdk_cam is None:
        return ''
    try:
        return ', blocked by %s' % sdk_recovery.read_blockers(sdk_cam).describe()
    except Exception:
        return ''


# ======================================================================
# Shutter speed, aperture and ISO (script value -> SDK value)
# ======================================================================

#: The fastest speed asked of the body.  Every X body reaches 1/8000 with its
#: mechanical shutter.  Faster speeds need the electronic shutter, which is a
#: setting on the body: on the mechanical shutter they are refused.
FASTEST_SHUTTER_S = 1.0 / 8000

#: The slowest speed asked of the body: the longest in the scripts' speed list.
SLOWEST_SHUTTER_S = 30.0

#: The speeds a body is known to accept, in seconds, by model.  The SDK's speed
#: table holds the scales of every model at once: a half-stop series (1/45,
#: 1/90, 1/180, 1/350, 1/750, ...) sits between the third-stop one.  An X-T4
#: refuses every one of those half-stop speeds with 0x2003, and then takes the
#: frame at the previous exposure.  Each speed below was written to an X-T4,
#: read back and confirmed.  A model that is not listed uses the SDK table.
MEASURED_SPEEDS_S = {
    'X-T4': (
        0.00003125, 0.0000390625, 0.00005, 0.0000625, 0.000078125, 0.0001,
        0.000125, 0.00015625, 0.0002, 0.00025, 0.0003125, 0.0004, 0.0005,
        0.000625, 0.0008, 0.001, 0.00125, 0.0015625, 0.002, 0.0025, 0.003125,
        0.004, 0.005, 0.00625, 0.008, 0.01, 0.0125, 0.016666667, 0.02, 0.025,
        0.033333333, 0.04, 0.05, 0.066666667, 0.076923077, 0.1, 0.125,
        0.166666667, 0.2, 0.25, 0.333333333, 0.4, 0.5, 0.625, 0.769230769,
        1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0,
    ),
}

# The camera's speeds are 1/3 EV apart, so a value closer than 1/6 EV to a speed
# is that speed written a different way.  Further away, it is a value the body
# does not have.
_SPEED_MATCH_TOLERANCE = 2.0 ** (1.0 / 6.0)


def _speed_name_seconds(name: str) -> Optional[float]:
    """Seconds for a shutter speed as the SDK table or a script writes it.

    Covers '1/2000"', '1/2000', '1.6"', '0.5' and '4min'.
    """
    clean = str(name).strip().rstrip('"').strip()
    try:
        if clean.endswith("min"):
            return float(clean[:-3]) * 60.0
        if "/" in clean:
            num, _, den = clean.partition("/")
            return float(num) / float(den)
        return float(clean)
    except (ValueError, ZeroDivisionError):
        return None


def _sdk_speeds() -> list[tuple[float, int]]:
    """(seconds, SDK value) for every speed in the SDK table, shortest first."""
    return sorted(
        (secs, val)
        for val, name in SHUTTER_SPEED_NAMES.items()
        if val > 0 and (secs := _speed_name_seconds(name)) is not None
    )


def _close(a: float, b: float) -> bool:
    """Whether two exposures are the same speed written to more decimal places."""
    return abs(math.log(a / b)) < 0.01


def _accepted_grid(measured: Optional[Sequence[float]] = None) -> list[tuple[float, int]]:
    """(seconds, SDK value) for the speeds this body takes, within the limits.

    Inside the range of ``measured``, only the measured speeds are kept.  Outside
    it there is no measurement, and the SDK table is used.
    """
    grid = [pair for pair in _sdk_speeds()
            if FASTEST_SHUTTER_S / 1.01 <= pair[0] <= SLOWEST_SHUTTER_S * 1.01]
    if not measured:
        return grid
    low, high = min(measured), max(measured)
    kept = []
    for secs, value in grid:
        if secs < low or secs > high:
            kept.append((secs, value))
            continue
        nearest = min(measured, key=lambda s: abs(math.log(s / secs)))
        if _close(nearest, secs):
            kept.append((secs, value))
    return kept or grid


def snap_to_scale(seconds: float, measured: Optional[Sequence[float]] = None) -> Optional[int]:
    """The SDK value of the speed nearest to ``seconds`` that the body takes.

    The exposure is first clamped to FASTEST_SHUTTER_S and SLOWEST_SHUTTER_S, so
    an exposure past either end is taken at the end of the scale.
    """
    grid = _accepted_grid(measured)
    if not grid or seconds is None or seconds <= 0:
        return None
    wanted = min(max(seconds, FASTEST_SHUTTER_S), SLOWEST_SHUTTER_S)
    return min(grid, key=lambda pair: abs(math.log(pair[0] / wanted)))[1]


def _parse_shutter_speed(speed_str: str, measured: Optional[Sequence[float]] = None) -> Optional[int]:
    """Map a script shutter speed to an SDK value, or None when the body has no such speed.

    The same exposure has several spellings: the SDK table calls half a second
    '1/2"', a script can call it '0.5'.  The match is therefore made on
    duration.  A speed past the end of the scale is clamped, with a warning.
    """
    wanted = _speed_name_seconds(speed_str)
    if wanted is None or wanted <= 0:
        return None
    if wanted < FASTEST_SHUTTER_S / 1.01:
        logging.warning('Shutter speed %s is faster than 1/%d; using that instead',
                        speed_str, round(1 / FASTEST_SHUTTER_S))
        wanted = FASTEST_SHUTTER_S
    elif wanted > SLOWEST_SHUTTER_S * 1.01:
        logging.warning('Shutter speed %s is longer than %g"; using that instead',
                        speed_str, SLOWEST_SHUTTER_S)
        wanted = SLOWEST_SHUTTER_S

    grid = _accepted_grid(measured)
    if not grid:
        return None
    secs, val = min(grid, key=lambda pair: abs(math.log(pair[0] / wanted)))
    ratio = max(secs, wanted) / min(secs, wanted)
    if ratio > _SPEED_MATCH_TOLERANCE:
        return None
    if ratio > 1.01:
        logging.warning("Shutter speed %s is not on this camera's scale; using %s instead",
                        speed_str, SHUTTER_SPEED_NAMES.get(val, val))
    return val


def _script_speed(value: int) -> str:
    """A shutter speed from the SDK table, as a script writes it: '1/2000' or '1.6'."""
    return str(SHUTTER_SPEED_NAMES.get(value, value)).rstrip('"').strip()


def _distinct(speeds) -> list:
    """Drop speeds that repeat one already in the list.

    Clamping at the end of the scale turns every exposure past it into the same
    speed.  Each repeat costs a buffer slot, a card write and about a second, and
    gives a frame identical to one already taken.
    """
    kept, seen, asked = [], set(), 0
    for speed in speeds:
        asked += 1
        if speed in seen:
            continue
        seen.add(speed)
        kept.append(speed)
    if asked != len(kept):
        logging.warning('Bracket: %d of %d frames are past the end of the shutter speed '
                        'scale and would be identical; taking %d', asked - len(kept), asked, len(kept))
    return kept


def _parse_aperture(aperture_str) -> Optional[int]:
    """Map a script aperture (e.g. "5.6") to the SDK value (f-number x 100)."""
    try:
        return int(round(float(str(aperture_str)) * 100))
    except (ValueError, TypeError):
        return None


def _parse_iso(iso_val) -> Optional[int]:
    """Map a script ISO (int or string) to the SDK value."""
    try:
        return int(iso_val)
    except (ValueError, TypeError):
        return None


# ======================================================================
# gphoto2-style stubs
# ======================================================================

class _FujiWidgetStub:
    """The get_value()/set_value() and choices part of a gphoto2 config widget."""

    def __init__(self, name: str, value: Any, choices: Sequence[str] = ()):
        self._name = name
        self._value = value
        self._choices = list(choices)

    def get_value(self):
        return self._value

    def set_value(self, v: Any):
        self._value = v

    def count_choices(self) -> int:
        return len(self._choices)

    def get_choice(self, index: int) -> str:
        return self._choices[index]


class _FujiConfigStub:
    """The get_child_by_name() part of a gphoto2 config.

    Maps the widget names the status helpers in camera.py and the camera check
    read (battery level, focus mode, shooting mode, ...) to values read from the
    body over the SDK.  The shutter speed and ISO widgets also carry the values
    the body takes, as choices.
    """

    def __init__(self, fuji_camera: FujiCamera):
        self._cam = fuji_camera

    def get_child_by_name(self, name: str) -> _FujiWidgetStub:
        name_lower = name.lower()
        sdk_cam = self._cam._sdk_cam

        if name_lower == 'batterylevel':
            # The body reports a coarse state, not a percentage, and some SDK
            # modules (the X-T4's) do not implement the battery API at all.
            # camera.py reads a percentage, as gphoto2 gives it, so a state is
            # given as its approximate percentage.  A state without one (mains
            # power, charging) is given by name.  The level is that of the body.
            try:
                info = sdk_cam.get_battery_info()
            except Exception:
                return _FujiWidgetStub(name, "Unknown")
            percent = POWERCAPACITY_PERCENT.get(info.body)
            return _FujiWidgetStub(name, f"{percent}%" if percent is not None else info.describe())

        if name_lower == 'focusmode':
            try:
                fm = sdk_cam.get_focus_mode()
                if fm == SDK_FOCUS_MANUAL:
                    return _FujiWidgetStub(name, "Manual")
                return _FujiWidgetStub(name, FOCUS_MODE_NAMES.get(fm, f"0x{fm:04X}"))
            except Exception:
                return _FujiWidgetStub(name, "Unknown")

        if name_lower in ('autoexposuremodedial', 'expprogram'):
            try:
                ae = sdk_cam.get_ae_mode()
                return _FujiWidgetStub(name, AE_MODE_NAMES.get(ae, f"0x{ae:04X}"))
            except Exception:
                return _FujiWidgetStub(name, "Unknown")

        if name_lower == 'shutterspeed':
            try:
                speed, _ = sdk_cam.get_shutter_speed()
                value = SHUTTER_SPEED_NAMES.get(speed, str(speed))
            except Exception:
                value = ""
            return _FujiWidgetStub(name, value, self._cam.offered_speeds())

        if name_lower == 'iso':
            try:
                value = str(sdk_cam.get_iso())
            except Exception:
                value = ""
            return _FujiWidgetStub(name, value, self._cam.offered_isos())

        if name_lower in ('aperture', 'f-number'):
            # No choices: the SDK lists the apertures per zoom position, and
            # that call is not used.
            try:
                return _FujiWidgetStub(name, f"{sdk_cam.get_aperture() / 100:.1f}")
            except Exception:
                return _FujiWidgetStub(name, "")

        return _FujiWidgetStub(name, '')


class _FujiStorageEntry:
    """A gphoto2 storage info entry: free and total space in kB."""

    def __init__(self, free_kb: float, capacity_kb: float):
        self.freekbytes = free_kb
        self.capacitykbytes = capacity_kb


# ======================================================================
# FujiCamera
# ======================================================================

class FujiCamera(BaseCamera):
    """A Fujifilm X body opened through the Shooting SDK.

    camera.py applies the exposure with :meth:`apply_settings`, and shoots with
    :meth:`capture`, :meth:`shoot_burst` and :meth:`shoot_ladder`.  The
    gphoto2-style ``get_config`` and ``get_storageinfo`` stubs let the status
    helpers in camera.py (battery, focus mode, free space) read the body.
    """

    vendor = 'Fuji'

    def __init__(self, sdk_cam: SDKCamera, name: str, sdk_path: str,
                 device_name: str = "ENUM:0", model: str = ""):
        super().__init__(name=name)
        self._sdk_cam = sdk_cam
        self._sdk_path = sdk_path
        self._device_name = device_name
        self._measured = MEASURED_SPEEDS_S.get(model)
        self._shooter: Optional[EclipseShooter] = None
        # The SDK is not thread-safe, so every call holds the camera's one lock.
        # An RLock, so a public method can call another.
        self._lock = self._usb_lock
        self._connected = True
        # The ISO and shutter speed this session last wrote; see configure().
        self._applied_iso: Optional[int] = None
        self._applied_speed: Optional[int] = None
        # Settings a busy body refused, latest value per key.  They are sent
        # again with the next configure.
        self._pending: dict = {}
        self._requested: dict = {}
        # When the frame in progress is written and the body takes settings again.
        self._frame_busy_until: float = 0.0
        self._last_recovery: float = 0.0
        self._clock_reported = False

    # --- BaseCamera ---------------------------------------------------

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        try:
            if self._sdk_cam is not None:
                self._sdk_cam.close()
        except Exception:
            pass
        self._connected = False

    def exit(self):
        self.disconnect()

    def configure(self, budget_s: Optional[float] = None, **kwargs: Any) -> None:
        """Apply camera settings over the SDK.

        Keyword arguments:
            shutter_speed: str (e.g. "1/2000")
            aperture: str (e.g. "5.6"), or "-" for a telescope with no aperture
            iso: int or str (e.g. 100)

        Raises:
            CameraError: if a setting could not be applied, naming every one
                that failed.

        A setting that fails without a message is worse than one that fails
        with one: the next frame is then taken at the previous exposure and looks
        normal until the images are reviewed.  Each failure is collected, the
        other settings are still tried, and all failures are reported together.

        A refused setting stays in ``self._pending`` and is sent again with the
        next configure, so a write that a busy body refused is applied on the
        next frame.  A key this call asks for replaces the pending one.

        The settings share one deadline: ``EXPOSURE_BUDGET_S``, extended until
        the frame in progress is written.  ``budget_s`` replaces that deadline.
        """
        self._requested = {k: v for k, v in kwargs.items() if v is not None}
        pending = self._pending
        wanted = {**pending, **self._requested}
        failures: list = []

        def _apply_aperture(raw, deadline: float) -> bool:
            value = _parse_aperture(raw)
            if value is None:
                failures.append(f"aperture={raw!r} is not a value this camera understands")
                return False
            try:
                _through_busy(lambda: self._sdk.set_aperture(value), f'{self.name}: set aperture',
                              deadline, self.recover_session)
                return True
            except Exception as exc:
                failures.append(f"aperture={raw!r} rejected by the camera ({exc})")
                return False

        def _apply_iso(raw, deadline: float) -> bool:
            # A script holds one ISO for a whole phase, so it is only written
            # when it differs from the one this session last wrote.  The
            # remembered value is cleared when a write fails or the session is
            # rebuilt, so a skip is never based on a value the body may not have.
            value = _parse_iso(raw)
            if value is None:
                failures.append(f"ISO={raw!r} is not a value this camera understands")
                return False
            if value == self._applied_iso:
                return True
            try:
                _through_busy(lambda: self._sdk.set_iso(value), f'{self.name}: set ISO {raw}',
                              deadline, self.recover_session)
                self._applied_iso = value
                return True
            except Exception as exc:
                self._applied_iso = None
                failures.append(f"ISO={raw!r} rejected by the camera ({exc})")
                return False

        def _apply_speed(raw, deadline: float) -> bool:
            # Skipped when it is the speed already set.  The body refuses the
            # write with 0x1006 for about a second while it writes the previous
            # frame, so a series of singles at one exposure would otherwise
            # wait about 1.7 s per frame to write a value the body already has.
            value = _parse_shutter_speed(str(raw), self._measured)
            if value is None:
                failures.append(f"shutter speed={raw!r} is not a value this camera understands")
                return False
            if value == self._applied_speed:
                return True
            try:
                _through_busy(lambda: self._sdk.set_shutter_speed(value),
                              f'{self.name}: set shutter speed {raw}', deadline, self.recover_session)
                self._applied_speed = value
                return True
            except Exception as exc:
                self._applied_speed = None
                failures.append(f"shutter speed={raw!r} rejected by the camera ({exc})")
                return False

        with self._lock:
            # The deadline starts after the lock is taken, so a caller that
            # waited for the lock still gets its full budget.
            started = time.monotonic()
            if budget_s is not None:
                deadline = started + budget_s
            else:
                deadline = min(max(started + EXPOSURE_BUDGET_S, self._frame_busy_until),
                               started + MAX_EXPOSURE_WAIT_S)

            if wanted.get('iso') is not None:
                if _apply_iso(wanted['iso'], deadline):
                    pending.pop('iso', None)
                else:
                    pending['iso'] = wanted['iso']

            # A telescope has no electronic aperture: a script gives "-", and the
            # setting is skipped rather than failing on every frame.
            if wanted.get('aperture') not in (None, '', '-'):
                if _apply_aperture(wanted['aperture'], deadline):
                    pending.pop('aperture', None)
                else:
                    pending['aperture'] = wanted['aperture']

            if wanted.get('shutter_speed') is not None:
                if _apply_speed(wanted['shutter_speed'], deadline):
                    pending.pop('shutter_speed', None)
                else:
                    pending['shutter_speed'] = wanted['shutter_speed']

            elapsed = time.monotonic() - started
            allowed = deadline - started

        if elapsed > allowed:
            logging.warning('%s: applying settings took %.1fs (allowed %.1fs)', self.name, elapsed, allowed)

        if failures:
            raise CameraError(f"{self.name}: could not apply " + "; ".join(failures))

    def capture(self):
        """Release the shutter once.

        When the release fails with anything but busy, the session is rebuilt,
        the last exposure is applied again, and the release is tried once more.
        """
        with self._lock:
            try:
                released = self.shooter.shoot_fast()
            except Exception as first_err:
                logging.warning('%s: release failed (%s), reconnecting', self.name, first_err)
                if not self._reconnect():
                    raise
                # A new session does not know what the old one set, so the
                # exposure is applied again before the frame.
                if self._requested:
                    try:
                        self.configure(**self._requested)
                    except Exception as exc:
                        hardware_problems.report(
                            self.name,
                            'Exposure could not be restored after reconnect; '
                            'this frame may be at the wrong exposure',
                            detail=str(exc),
                        )
                released = self.shooter.shoot_fast()
            if not released:
                raise CameraError(f"{self.name}: the camera did not release the shutter")
            self._note_frame_fired()

    # --- Hooks called by camera.py ------------------------------------

    def apply_settings(self, camera_settings) -> None:
        """Apply the exposure of a script command before it shoots.

        The frame is taken even when a setting failed: a frame at the wrong
        exposure is better than no frame.  The failure goes to the problems
        list, because the image looks normal until it is reviewed.
        """
        try:
            self.configure(shutter_speed=camera_settings.shutter_speed,
                           aperture=camera_settings.aperture,
                           iso=camera_settings.iso)
        except CameraError as exc:
            hardware_problems.report(
                self.name,
                'Exposure settings were not applied; frames may be at the wrong exposure',
                detail=str(exc),
            )

    def shoot_burst(self, seconds: float) -> int:
        """Release single frames, one after the other, for ``seconds``.

        The SDK cannot start the body's own continuous drive, so this is the
        fastest the SDK releases frames.  At least one frame is taken.

        Returns the number of frames taken.
        """
        deadline = time.monotonic() + max(0.0, seconds)
        taken = 0
        with self._lock:
            while True:
                if not self.shooter.shoot_fast():
                    break
                taken += 1
                if time.monotonic() >= deadline:
                    break
            self._note_frame_fired()
        logging.info('%s: take_burst took %d frame(s) in %.1f s', self.name, taken, seconds)
        return taken

    def shoot_ladder(self, exposures_s: Sequence[float], drop_repeats: bool = True) -> int:
        """One frame per exposure, in the order given, the speed set between frames.

        Each exposure is put on the nearest speed the body takes.  With
        ``drop_repeats``, a speed that is already in the ladder is not taken
        again (see :func:`_distinct`).  An HDR sequence passes False, because it
        repeats its speeds on purpose.

        Returns the number of frames taken.  A ladder that is cut short goes to
        the problems list, because the images cannot show it.
        """
        speeds = [snap_to_scale(s, self._measured) for s in exposures_s]
        if any(s is None for s in speeds):
            raise CameraError(f"{self.name}: no shutter speed for the exposures {list(exposures_s)}")
        if drop_repeats:
            speeds = _distinct(speeds)
        logging.info('%s: %d frame(s): %s', self.name, len(speeds), self.describe_speeds(speeds))
        with self._lock:
            taken = self.shooter.bracket_no_download(speeds)
            # The shooter writes the speeds itself, so the speed configure
            # remembers is no longer known.  The next configure writes it again.
            self._applied_speed = None
            self._note_frame_fired()
        if taken != len(speeds):
            hardware_problems.report(
                self.name,
                'Bracket was cut short; the exposure ladder is incomplete',
                detail=f'asked for {len(speeds)} frame(s), took {taken}',
            )
        return taken

    def sync_clock(self) -> bool:
        """Report that the clock of this body cannot be set from the computer.

        The model headers of the Shooting SDK list a SetDateTime API code, but
        the public headers declare no entry point and XAPI exports none.  The
        frames therefore carry the time of the body's own clock.  Reported once
        per session.

        Returns False: the clock was not set.
        """
        if not self._clock_reported:
            self._clock_reported = True
            hardware_problems.report(
                self.name,
                'Camera clock cannot be set from the computer: set it on the body by hand',
                detail='the Fujifilm Shooting SDK has no date/time call, so frame '
                       'timestamps follow the camera clock, not this computer',
                severity='warning',
            )
        return False

    # --- Session ------------------------------------------------------

    @property
    def shooter(self) -> EclipseShooter:
        if self._shooter is None:
            self._shooter = EclipseShooter(self._sdk)
        return self._shooter

    @property
    def _sdk(self):
        """The SDK handle, or a CameraError when the session is gone.

        After a failed reconnect ``_sdk_cam`` is None, so that no call can reach
        a closed handle.
        """
        if self._sdk_cam is None:
            raise CameraError(f"{self.name}: the camera connection is gone - power-cycle the "
                              f"body and detect it again")
        return self._sdk_cam

    def recover_session(self) -> bool:
        """Rebuild the USB session after it was lost, and say whether that worked.

        0x2001 means the handle is dead: every later call on it fails, and each
        frame is taken at whatever speed the body was last set to.  Rate limited
        by RECOVERY_INTERVAL_S, because the failure comes once per setting per frame.
        """
        now = time.monotonic()
        if now - self._last_recovery < RECOVERY_INTERVAL_S:
            return False
        self._last_recovery = now

        logging.warning('%s: the camera session was lost; rebuilding it', self.name)
        if not self._reconnect():
            hardware_problems.report(
                self.name,
                'The camera connection was lost and could not be rebuilt',
                detail='frames from here on will be at whatever the body is set to',
            )
            return False
        hardware_problems.report(
            self.name, 'The camera connection was lost and rebuilt',
            detail='check the frames around this moment for the wrong exposure',
            severity='warning',
        )
        return True

    def _reconnect(self) -> bool:
        """Close and reopen the SDK session."""
        try:
            if self._sdk_cam is not None:
                self._sdk_cam.close()
        except Exception:
            pass
        try:
            self._sdk_cam = SDKCamera(self._sdk_path, self._device_name)
            self._shooter = None
            # A new session does not know what the old one wrote.
            self._applied_iso = None
            self._applied_speed = None
            logging.info('%s: reconnected', self.name)
            return True
        except Exception as e:
            # The old handle is closed, and a call into it can crash the
            # process.  With None, every later call raises a CameraError that
            # says what is wrong, and the rest of the script still runs.
            self._sdk_cam = None
            logging.error('%s: reconnect failed: %s', self.name, e)
            return False

    def _note_frame_fired(self) -> None:
        """Record when the body takes settings again after the frame just released.

        The exposure is the last speed applied.  When it is not known, only the
        write time is used.
        """
        exposure_s = (self._applied_speed or 0) / 1_000_000.0
        self._frame_busy_until = time.monotonic() + exposure_s + FRAME_WRITE_S

    # --- gphoto2-style stubs ------------------------------------------

    def get_config(self) -> _FujiConfigStub:
        return _FujiConfigStub(self)

    def set_config(self, config) -> None:
        pass

    def get_storageinfo(self) -> list:
        """Free and total space per card, or an empty list when the body does not say.

        The status helpers in camera.py read an empty list as "unknown".
        """
        entries = []
        for slot in (SDK_ITEM_MEDIASLOT1, SDK_ITEM_MEDIASLOT2):
            try:
                capacity = self._sdk.get_media_capacity(slot)
            except Exception:
                continue
            free_kb = capacity.free_bytes / 1024.0
            total_kb = capacity.card_size / 1024.0 if capacity.card_size else free_kb
            entries.append(_FujiStorageEntry(free_kb, total_kb))
        return entries

    # --- Fuji-specific ------------------------------------------------

    def validate(self) -> list[CameraIssue]:
        return validate_for_eclipse(self._sdk)

    def offered_speeds(self) -> list[str]:
        """The shutter speeds this body takes, as a script writes them, shortest first.

        These are the speeds of :func:`_accepted_grid`, so a speed the body is
        known to refuse is not in the list.  When the body gives its own list,
        only the speeds in both lists are kept.  The X-T4 gives an empty list.
        """
        try:
            listed = {value for value in self._sdk.get_supported_shutter_speeds() if value > 0}
        except Exception:
            listed = set()
        return [_script_speed(value) for _, value in _accepted_grid(self._measured)
                if not listed or value in listed]

    def offered_isos(self) -> list[str]:
        """The fixed ISO values the body lists, lowest first.  The auto values are left out."""
        try:
            return [str(value) for value in sorted(set(self._sdk.get_supported_iso())) if value > 0]
        except Exception:
            return []

    def describe_speeds(self, speeds: Sequence[int]) -> str:
        """The shutter speeds of a list of SDK values, as text."""
        return ', '.join(str(SHUTTER_SPEED_NAMES.get(s, s)).rstrip('"') for s in speeds)


# ======================================================================
# Library path at start-up
# ======================================================================

def _reexec_process() -> None:
    """Restart the process, so that the dynamic linker reads the new LD_LIBRARY_PATH.

    The linker reads LD_LIBRARY_PATH only once, when the process starts.
    """
    logging.info('LD_LIBRARY_PATH updated for the Fujifilm SDK, restarting the process')
    main_spec = getattr(sys.modules.get('__main__'), '__spec__', None)
    if main_spec and main_spec.name:
        args = [sys.executable, '-m', main_spec.name] + sys.argv[1:]
    else:
        args = [sys.executable] + sys.argv
    os.execvp(sys.executable, args)


def ensure_fuji_library_path() -> bool:
    """Add the SDK libraries to LD_LIBRARY_PATH when they are not on it.

    Returns True when the environment changed, so the process must restart for
    the dynamic linker to use it.
    """
    if not FUJIXSDK_AVAILABLE:
        return False
    sdk_path = find_fuji_sdk_path()
    if not sdk_path:
        return False
    try:
        # True when the path was already complete, False when it was changed.
        return not ensure_ld_library_path(sdk_path)
    except Exception:
        logging.debug('Could not set the library path for the Fujifilm SDK', exc_info=True)
        return False


def maybe_reexec_for_fuji_sdk() -> None:
    """Call once at start-up, before the GUI or any session state is made.

    When the SDK libraries had to be added to LD_LIBRARY_PATH, the process
    restarts now.  A restart later, during camera detection, would lose the
    settings the user had not saved.
    """
    if ensure_fuji_library_path():
        _reexec_process()


# ======================================================================
# Detection
# ======================================================================

def _reset_mac_camera_stack() -> None:
    """Stop the macOS camera daemons, so that they start again with a clean state.

    Only a last resort: on macOS these daemons carry the SDK's connection to the
    camera, and must normally be left alone.  A stale session in them makes
    detection find no camera, or a handle on which every call fails with 0x2001.
    launchd starts them again when they are needed.
    """
    if platform.system() != "Darwin":
        return
    try:
        subprocess.run(["killall", "-9", "ptpcamerad", "mscamerad-xpc"], capture_output=True, timeout=5)
        logging.info("Reset the macOS camera daemons; they start again when needed")
    except Exception:
        logging.debug("Camera daemon reset failed", exc_info=True)


def _preload_mac_transport(sdk_path: str) -> None:
    """Load the SDK's PTP transport libraries before XAPI looks for them.

    FTLPTP.dylib has the install name /usr/local/lib/FTLPTP.dylib, where it is
    usually not installed.  When it is loaded by full path first, XAPI's own
    dlopen finds the loaded image.
    """
    if platform.system() != "Darwin":
        return
    for hit in sorted(Path(sdk_path).rglob("FTLPTP.dylib")):
        for name in ("FTLPTP.dylib", "FTLPTPIP.dylib"):
            candidate = hit.parent / name
            if candidate.exists():
                try:
                    ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
                    logging.debug("Preloaded %s", candidate)
                except OSError:
                    logging.debug("Could not preload %s", candidate, exc_info=True)
        return


def _report_validation_issues(camera: FujiCamera) -> None:
    """Run the pre-flight check of the body settings, and report what is wrong.

    At detection, so that a body left in AF, on JPEG or with exposure
    compensation set is found during set-up and not after the eclipse.
    """
    try:
        issues = camera.validate()
    except Exception:
        logging.debug('Fuji validation failed for %s', camera.name, exc_info=True)
        return

    for issue in issues or []:
        # "info" issues state a fact (e.g. a setting the SDK cannot read), and
        # stay in the log.
        if issue.severity == 'info':
            logging.info('%s: %s is %s (%s)', camera.name, issue.setting, issue.current, issue.message)
            continue
        hardware_problems.report(
            camera.name,
            '%s: needs %s, is %s' % (issue.setting, issue.expected, issue.current),
            detail=issue.message,
            severity=issue.severity,
        )


class FujiDetection(NamedTuple):
    """The bodies the SDK opened, and how many it saw.

    A body can be seen and still fail to open.  gphoto2 must stay away from
    both, see :func:`detect_for_workbench`.
    """

    cameras: dict
    bodies_seen: int


def detect_fuji(sdk_path: str) -> FujiDetection:
    """Find the Fuji bodies on the bus through the SDK, and open each one.

    Detection is tried three times.  A body that was just switched on often
    needs a few seconds before the SDK sees it, so the second try only waits.
    The third try first resets the macOS camera daemons.
    """
    if not FUJIXSDK_AVAILABLE:
        logging.error("The fujixsdk bindings cannot be imported (%s); no Fuji camera is detected",
                      FUJIXSDK_IMPORT_ERROR)
        return FujiDetection({}, 0)

    _preload_mac_transport(sdk_path)

    cameras = []
    reset_at = None
    for attempt in range(3):
        if attempt == 1:
            time.sleep(4.0)
        elif attempt == 2:
            _reset_mac_camera_stack()
            reset_at = time.monotonic()
            time.sleep(3.0)
        try:
            # Names only.  Reading the product name opens a session and closes
            # it again; it is read below from the session that is kept.
            cameras = SDKCamera.detect(sdk_path, with_info=False)
            logging.info('Fuji SDK detect attempt %d found %d camera(s)', attempt + 1, len(cameras))
            if cameras:
                break
        except fujixsdk.LDPathError:
            # maybe_reexec_for_fuji_sdk() at start-up normally sets the path
            # before this point.
            _reexec_process()
        except Exception as e:
            logging.debug('Fuji SDK detect attempt %d failed: %s', attempt + 1, e)
        time.sleep(2)

    if not cameras:
        logging.info('The Fuji SDK found no cameras')
        return FujiDetection({}, 0)

    # After a daemon reset, an open that starts too early does not fail fast:
    # it waits for a 15 s handshake and then fails.  The daemons need about 10 s.
    if reset_at is not None:
        settle = 10.0 - (time.monotonic() - reset_at)
        if settle > 0:
            logging.info('Waiting %.0f s for the camera daemons to start before opening', settle)
            time.sleep(settle)

    result = {}
    for info in cameras:
        name = f"Fuji Camera ({info.device_name})"
        try:
            sdk_cam = SDKCamera(sdk_path, info.device_name)
            model = ""
            try:
                model = sdk_cam.device_info.product or ""
            except Exception:
                logging.debug('Could not read the product name of %s', info.device_name, exc_info=True)
            if model:
                # The name gphoto2 gives a Fuji body, so a script can use either.
                name = f"Fuji Fujifilm {model}"
            fuji_cam = FujiCamera(sdk_cam, name, sdk_path, info.device_name, model=model)
            result[name] = fuji_cam
            logging.info('Detected Fuji camera: %s (device=%s)', name, info.device_name)
            _report_validation_issues(fuji_cam)
        except Exception as e:
            logging.warning('Could not open Fuji camera %s: %s', info.device_name, e)
            hardware_problems.report('Fuji SDK', f'Found {name} but could not open it', detail=str(e))

    return FujiDetection(result, len(cameras))


def detect_for_workbench() -> SdkDetection:
    """The SDK backend that camera.get_camera_dict calls before gphoto2.

    When the SDK is installed, gphoto2 is kept away from every Fuji body, also
    from one the SDK did not see or could not open.  gphoto2 cannot drive an X
    body tethered, and when it claims the USB device the SDK cannot open the
    body again until it is switched off and on.
    """
    sdk_path = find_fuji_sdk_path()
    if not sdk_path:
        logging.debug('Fujifilm SDK not found, no Fuji detection')
        return SdkDetection({}, ())
    logging.debug('Fujifilm SDK at %s', sdk_path)
    detection = detect_fuji(sdk_path)
    if not detection.bodies_seen:
        logging.info('Any Fuji body on the bus is left to the Fujifilm SDK: gphoto2 cannot shoot '
                     'it tethered, and its claim would lock the SDK out')
    return SdkDetection(detection.cameras, ('fuji',))


register_sdk_backend(detect_for_workbench)


# ======================================================================
# Where the SDK is
# ======================================================================

def _sdk_marker() -> str:
    """The name of the SDK's main library on this platform."""
    system = platform.system()
    if system == "Darwin":
        return "XAPI.bundle"
    if system == "Windows":
        return "XAPI.dll"
    return "XAPI.so"


def find_fuji_sdk_path() -> Optional[str]:
    """The folder of the Fujifilm Shooting SDK, or None when it is not found.

    Looks in this order:
    1. the FUJI_SDK_PATH environment variable
    2. ~/fujixsdk, ~/FujiSDK, /opt/fujixsdk, /usr/local/lib/fujixsdk
    3. SDK/ and fujixsdk/ next to the source checkout

    In a folder, the first SDK* subfolder that holds the platform's XAPI
    library is used, else the folder itself when it holds one.
    """
    env_path = os.environ.get('FUJI_SDK_PATH')
    if env_path and Path(env_path).is_dir():
        return env_path

    checkout = Path(__file__).resolve().parent.parent.parent
    search_dirs = [
        Path.home() / "fujixsdk",
        Path.home() / "FujiSDK",
        Path("/opt/fujixsdk"),
        Path("/usr/local/lib/fujixsdk"),
        checkout / "SDK",
        checkout / "fujixsdk",
    ]

    marker = _sdk_marker()
    for base in search_dirs:
        if not base.is_dir():
            continue
        for sdk_dir in sorted(base.glob("SDK*")):
            if sdk_dir.is_dir() and any(sdk_dir.glob(f"**/{marker}")):
                return str(sdk_dir)
        if any(base.glob(f"**/{marker}")):
            return str(base)

    return None
