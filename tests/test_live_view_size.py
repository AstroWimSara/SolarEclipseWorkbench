import threading
from unittest.mock import patch

import gphoto2

from solareclipseworkbench.camera import get_live_view_sizes, set_live_view_size, LIVE_VIEW_SIZE_WIDGET


class _FakeWidget:
    def __init__(self, value, choices):
        self.value = value
        self.choices = choices

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class _FakeCamera:
    def __init__(self):
        self._camera = object()
        self._usb_lock = threading.RLock()
        self.name = "Canon EOS R"


def _patched(widget, set_error=None):
    def set_single_config(target, name, w, context):
        assert name == LIVE_VIEW_SIZE_WIDGET
        if set_error:
            raise set_error
        return 0

    return [
        patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()),
        patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x),
        patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config", return_value=widget),
        patch("solareclipseworkbench.camera.gp.gp_camera_set_single_config", side_effect=set_single_config),
        patch("solareclipseworkbench.camera._widget_choices", return_value=widget.choices),
    ]


def _run(patches, func, *args):
    for p in patches:
        p.start()
    try:
        return func(*args)
    finally:
        for p in patches:
            p.stop()


def test_sizes_are_read_from_the_camera():
    widget = _FakeWidget("Medium", ["Large", "Medium", "Small"])
    assert _run(_patched(widget), get_live_view_sizes, _FakeCamera()) == ("Medium", ["Large", "Medium", "Small"])


def test_camera_without_live_view_size_returns_none():
    camera = _FakeCamera()
    with patch("solareclipseworkbench.camera.gp.gp_context_new", return_value=object()), \
         patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda x: x), \
         patch("solareclipseworkbench.camera.gp.gp_camera_get_single_config",
               side_effect=gphoto2.GPhoto2Error(-2)):
        assert get_live_view_sizes(camera) is None
    # The USB lock is released again
    assert camera._usb_lock.acquire(blocking=False)


def test_virtual_camera_has_no_live_view_size():
    class _NoGphoto:
        pass

    assert get_live_view_sizes(_NoGphoto()) is None
    assert set_live_view_size(_NoGphoto(), "Large") is False


def test_size_is_set_on_the_camera():
    widget = _FakeWidget("Medium", ["Large", "Medium", "Small"])
    assert _run(_patched(widget), set_live_view_size, _FakeCamera(), "Large") is True
    assert widget.value == "Large"


def test_refused_size_returns_false():
    widget = _FakeWidget("Medium", ["Large", "Medium", "Small"])
    assert _run(_patched(widget, gphoto2.GPhoto2Error(-1)), set_live_view_size, _FakeCamera(), "Large") is False


def test_busy_camera_is_not_waited_for_forever():
    camera = _FakeCamera()
    held = threading.Event()
    done = threading.Event()

    def hold():
        with camera._usb_lock:
            held.set()
            done.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(1)
    try:
        with patch("solareclipseworkbench.camera._LIVE_VIEW_SIZE_LOCK_WAIT_S", 0.05):
            assert get_live_view_sizes(camera) is None
            assert set_live_view_size(camera, "Large") is False
    finally:
        done.set()
        t.join()


def test_a_size_the_camera_does_not_offer_starts_at_the_camera_default():
    # An EOS 80D reports 'val 0' next to Large, Medium and Small, and does not accept it back
    from solareclipseworkbench.gui import CAMERA_DEFAULT_SIZE, live_view_size_items

    items, selected = live_view_size_items("val 0", ["Large", "Medium", "Small"])
    assert items == [CAMERA_DEFAULT_SIZE, "Large", "Medium", "Small"]
    assert selected == CAMERA_DEFAULT_SIZE


def test_a_size_the_camera_offers_is_selected():
    from solareclipseworkbench.gui import live_view_size_items

    assert live_view_size_items("Medium", ["Large", "Medium", "Small"]) == (["Large", "Medium", "Small"], "Medium")
