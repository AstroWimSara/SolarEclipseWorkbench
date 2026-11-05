"""Battery, media and shutter count, called the way the SDK documents them.

All three passed the wrong number of arguments and had never once returned a
real answer.  The reference manual gives each signature exactly; these pin
what is sent, since a wrong count is refused by the body rather than caught
here - and an over-claimed count reads off the stack.
"""

import ctypes

import pytest

from fujixsdk import _constants as C
from fujixsdk.camera import BatteryInfo, Camera, MediaCapacity, ShutterCount


class _RecordingBody:
    """Answers GetProp by filling every out-pointer with a known number."""

    def __init__(self):
        self.seen = []
        self._lib_inst = self
        self._handle = ctypes.c_void_p()

    def XSDK_GetProp(self, handle, code, param, *args):
        self.seen.append((code.value, param.value, len(args)))
        for index, arg in enumerate(args, start=1):
            if hasattr(arg, "_obj"):
                arg._obj.value = index * 10
        return C.COMPLETE

    def _check(self, rc):
        if rc != C.COMPLETE:
            raise AssertionError("unexpected rc %r" % rc)

    def get_prop(self, api_code, api_param=None, *args):
        return Camera.get_prop(self, api_code, api_param, *args)


def _body():
    return _RecordingBody()


def test_battery_sends_six_out_parameters():
    # XSDK_GetProp(h, code, param, plBodyBatteryInfo, plGripBatteryInfo,
    #              plGripBattery2Info, plBodyBatteryRatio, plGripBatteryRatio,
    #              plGripBattery2Ratio) - three were sent.
    body = _body()

    result = Camera.get_battery_info(body)

    code, param, nargs = body.seen[-1]
    assert code == C.API_CODE_CheckBatteryInfo
    assert nargs == 6, "the body refuses any other count"
    assert param == 6, "the parameter must match the arguments sent"
    assert isinstance(result, BatteryInfo)


def test_media_capacity_sends_the_slot_then_four_out_parameters():
    # The slot is an input and comes first; it was never sent at all.
    body = _body()

    result = Camera.get_media_capacity(body, C.ITEM_MEDIASLOT2)

    code, param, nargs = body.seen[-1]
    assert code == C.API_CODE_GetMediaCapacity
    assert nargs == 5
    assert param == 5
    assert isinstance(result, MediaCapacity)


def test_media_status_asks_about_a_slot():
    body = _body()

    Camera.get_media_status(body, C.ITEM_MEDIASLOT2)

    code, param, nargs = body.seen[-1]
    assert code == C.API_CODE_GetMediaStatus
    assert nargs == 2, "the slot was never passed, so this never answered"
    assert param == 2


def test_shutter_count_returns_all_three_counters():
    body = _body()

    result = Camera.get_shutter_count(body)

    code, param, nargs = body.seen[-1]
    assert code == C.API_CODE_GetShutterCount
    assert nargs == 3
    assert param == 3
    assert isinstance(result, ShutterCount)
    assert result.current == 10 and result.total == 20 and result.exchanges == 30


def test_the_dial_status_refuses_rather_than_returning_a_number():
    # Four arguments on the X-T4 and the reference does not document them, so
    # it cannot be wired.  Refusing is better than returning an uninitialised long.
    with pytest.raises(NotImplementedError):
        Camera.get_command_dial_status(_body())


def test_a_low_battery_is_recognised_as_low():
    flat = BatteryInfo(body=C.POWERCAPACITY_PREEND, grip=0, grip2=0,
                       body_ratio=0, grip_ratio=0, grip2_ratio=0)
    good = BatteryInfo(body=C.POWERCAPACITY_100, grip=0, grip2=0,
                       body_ratio=100, grip_ratio=0, grip2_ratio=0)

    assert flat.is_low and "nearly flat" in flat.describe()
    assert not good.is_low


def test_a_card_that_cannot_take_a_frame_is_flagged():
    # The pre-flight question that matters: a write-protected or full card
    # takes nothing at all, which is not a thing to learn at second contact.
    for status in (C.MEDIASTATUS_WRITEPROTECTED, C.MEDIASTATUS_FULL,
                   C.MEDIASTATUS_NOCARD):
        assert status in C.MEDIASTATUS_CANNOT_WRITE
    assert C.MEDIASTATUS_OK not in C.MEDIASTATUS_CANNOT_WRITE


def test_free_space_is_computed_from_sectors():
    capacity = MediaCapacity(blank_frames=940, remaining_sectors=1000,
                             sector_size=512, card_size=64 * 1000 ** 3)

    assert capacity.free_bytes == 512_000
    assert "940 frames" in capacity.describe()
