"""XSDK_SetProp and XSDK_GetProp take an api_param, and it is not free-form.

The SDK's own headers list one required number per API per model.  A wrong
number makes the body answer 0x1002 "Invalid parameter": the focus mode cannot
be read and the live view size cannot be set.
"""

import ctypes
import inspect

from fujixsdk import _constants as C
from fujixsdk import _library
from fujixsdk.camera import _resolve_param


def test_the_live_view_numbers_match_the_vendor_sample():
    # SAMPLES/Windows/LiveView/live_view_control.py passes 1 for the size and
    # the quality and 0 for the start.
    assert C.api_param(C.API_CODE_SetLiveViewImageSize) == 1
    assert C.api_param(C.API_CODE_SetLiveViewImageQuality) == 1
    assert C.api_param(C.API_CODE_StartLiveView) == 0
    assert C.api_param(C.API_CODE_StopLiveView) == 0


def test_the_focus_mode_and_image_quality_reads_send_their_param():
    assert C.api_param(C.API_CODE_GetFocusMode) == 1
    assert C.api_param(C.API_CODE_GetImageQuality) == 1


def test_an_unknown_api_falls_back_to_zero():
    # Where the wrapper already was, so an API missing from the table is no
    # worse off than before.
    assert C.api_param(0xDEAD) == 0


def test_an_omitted_param_is_the_number_of_arguments():
    value = ctypes.c_long(1)
    param, args = _resolve_param(C.API_CODE_SetLiveViewImageSize, None, (value,))

    assert param == 1
    assert args == (value,)


def test_the_count_describes_the_stack_not_the_header():
    # CheckBatteryInfo wants six arguments and the wrapper passes three.
    # Sending 6 does not fail - it reads three words of whatever is on the
    # stack, which is a segmentation fault rather than an error code.
    param, args = _resolve_param(C.API_CODE_CheckBatteryInfo, None, (1, 2, 3))

    assert param == 3, "promised the SDK more arguments than exist"
    assert args == (1, 2, 3)


def test_no_argument_call_sends_zero():
    param, args = _resolve_param(C.API_CODE_StartLiveView, None, ())

    assert param == 0
    assert args == ()


def test_a_value_passed_where_the_param_used_to_go_is_not_mistaken_for_one():
    # The param was positional and mandatory, so an old-style caller's first
    # variadic argument lands in its slot.  Treating a ctypes value as a
    # parameter number would send garbage to the body.
    value = ctypes.c_long(3)
    param, args = _resolve_param(C.API_CODE_SetLiveViewImageSize, value, ())

    assert param == 1, "counted the value as a parameter number"
    assert args == (value,)


def test_an_explicit_param_still_wins():
    param, args = _resolve_param(C.API_CODE_SetLiveViewImageSize, 7, ())

    assert param == 7
    assert args == ()


def test_the_live_view_sizes_are_the_sizes_the_body_makes():
    # Named XGA/VGA/QVGA with resolutions to match, none of which the body
    # produces.  The numbers were always right; only the description was not.
    assert C.LIVEVIEW_SIZE_L == 0x0001
    assert C.LIVEVIEW_SIZE_XGA == C.LIVEVIEW_SIZE_L      # old name still works
    assert C.LIVEVIEW_QUALITY_BASIC == 0x0003            # was missing entirely


def test_the_variadic_entry_points_declare_their_fixed_arguments():
    """The bug that made almost every property call fail on Apple Silicon.

    XSDK_GetProp(XSDK_HANDLE, long lAPICode, long lAPIParam, ...) is variadic.
    On arm64 macOS a variadic argument is passed on the stack while a fixed one
    goes in a register, and ctypes only knows where the variadic part starts if
    argtypes declares the fixed part.  With argtypes unset it passes everything
    as fixed, the callee reads the stack, and finds whatever was there - 0x1002
    "Invalid parameter" at best and a segmentation fault at worst.

    Asserted on the class rather than a live library so it holds with no camera
    and no SDK present.
    """
    source = inspect.getsource(_library.XAPILibrary._setup_functions)
    for name in ("XSDK_CapProp", "XSDK_SetProp", "XSDK_GetProp"):
        assert f'self._func("{name}", fixed)' in source, (
            f"{name} is variadic and must declare its three fixed arguments; "
            "leaving argtypes unset breaks the ABI on arm64 macOS")
    assert "fixed = [c_void_p, ctypes.c_long, ctypes.c_long]" in source
