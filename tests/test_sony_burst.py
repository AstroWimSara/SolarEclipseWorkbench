from unittest.mock import patch

from solareclipseworkbench.camera import CameraSettings, take_burst


class _DummyLock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


class _SonyCamera:
    def __init__(self):
        self.vendor = "Sony"
        self.name = "Sony Test"
        self._camera = object()
        self._usb_lock = _DummyLock()

    def capture(self, *args, **kwargs):
        raise AssertionError("fallback capture should not be used in this regression test")


def test_take_burst_holds_the_bulb_instead_of_triggering_each_frame():
    """Sony bursts are driven by holding the bulb, not by N trigger_capture calls.

    Once the bulb is held the camera firmware decides the frame rate, so the old
    per-frame trigger loop (and its per-frame CAPTURE_COMPLETE wait) must not run.
    """
    camera = _SonyCamera()
    settings = CameraSettings("Sony Test", "1/2000", "5.6", 100)

    with patch("solareclipseworkbench.camera.__adapt_camera_settings", return_value=(object(), object())), \
         patch("solareclipseworkbench.camera.gp.check_result", side_effect=lambda value: value), \
         patch("solareclipseworkbench.camera.gp.gp_widget_get_child_by_name", return_value=object()), \
         patch("solareclipseworkbench.camera.gp.gp_widget_set_value") as set_value, \
         patch("solareclipseworkbench.camera.gp.gp_camera_trigger_capture") as trigger_capture, \
         patch("solareclipseworkbench.camera.gp.gp_camera_get_config", return_value=object()), \
         patch("solareclipseworkbench.camera._find_capturemode_choice", return_value="Continuous Shooting"), \
         patch("solareclipseworkbench.camera._set_gp_config"), \
         patch("solareclipseworkbench.camera._drain_camera_events") as drain_events, \
         patch("solareclipseworkbench.camera._wait_for_capture_complete") as wait_for_capture_complete:
        take_burst(camera, settings, 0)

    values_set = [call.args[1] for call in set_value.call_args_list]
    assert values_set == ["Continuous Shooting", 1, 0]
    trigger_capture.assert_not_called()
    wait_for_capture_complete.assert_not_called()
    assert drain_events.call_count == 2
