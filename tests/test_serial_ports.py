"""Serial port enumeration differs by platform, and is easy to break from the other one.

Every test here fakes the platform, so the whole file runs anywhere.
"""

from types import SimpleNamespace
from unittest.mock import patch

import solareclipseworkbench.serial_ports as serial_ports


def _port(device, vid=0x1A86, pid=0x7523, description="USB serial", location=None):
    return SimpleNamespace(device=device, vid=vid, pid=pid, description=description, location=location)


def test_macos_prefers_the_call_up_node():
    # Opening /dev/tty.* blocks waiting for carrier detect, which a relay board
    # never asserts, so the call-up node is the only usable one.
    ports = [_port("/dev/tty.usbserial-A1"), _port("/dev/cu.usbserial-A1")]

    with patch.object(serial_ports.serial.tools.list_ports, "comports", return_value=ports), \
         patch.object(serial_ports.sys, "platform", "darwin"):
        found = [p.device for p in serial_ports.usb_serial_ports()]

    assert found == ["/dev/cu.usbserial-A1"]


def test_macos_does_not_list_the_same_adapter_twice():
    ports = [_port("/dev/cu.usbserial-A1"), _port("/dev/tty.usbserial-A1"),
             _port("/dev/cu.usbmodem14201"), _port("/dev/tty.usbmodem14201")]

    with patch.object(serial_ports.serial.tools.list_ports, "comports", return_value=ports), \
         patch.object(serial_ports.sys, "platform", "darwin"):
        found = serial_ports.usb_serial_ports()

    assert len(found) == 2


def test_ports_without_a_usb_id_are_dropped():
    # On macOS these are the built-in Bluetooth serial devices.
    ports = [_port("/dev/cu.usbserial-A1"), _port("/dev/tty.Bluetooth-Incoming-Port", vid=None)]

    with patch.object(serial_ports.serial.tools.list_ports, "comports", return_value=ports), \
         patch.object(serial_ports.sys, "platform", "darwin"):
        found = [p.device for p in serial_ports.usb_serial_ports()]

    assert found == ["/dev/cu.usbserial-A1"]


def test_linux_node_list_is_untouched():
    ports = [_port("/dev/ttyUSB0"), _port("/dev/ttyACM0")]

    with patch.object(serial_ports.serial.tools.list_ports, "comports", return_value=ports), \
         patch.object(serial_ports.sys, "platform", "linux"):
        found = [p.device for p in serial_ports.usb_serial_ports()]

    assert found == ["/dev/ttyUSB0", "/dev/ttyACM0"]


def _two_chips_four_nodes():
    return [
        _port("/dev/cu.usbserial-7", 0x10C4, 0xEA60, "", "1-1.3"),
        _port("/dev/cu.SLAB_USBtoUART8", 0x10C4, 0xEA60, "", "1-1.3"),
        _port("/dev/cu.usbserial-0001", 0x10C4, 0xEA60, "", "1-1.4"),
        _port("/dev/cu.SLAB_USBtoUART", 0x10C4, 0xEA60, "", "1-1.4"),
    ]


def test_one_adapter_behind_two_drivers_is_offered_once():
    """With both the Silicon Labs kext and Apple's CP210x driver installed, one
    chip fronts two nodes.  Cheap boards can share a serial number, so
    `location` is the only field that tells one adapter from another."""
    with patch.object(serial_ports.serial.tools.list_ports, "comports", _two_chips_four_nodes), \
         patch.object(serial_ports.sys, "platform", "darwin"):
        ports = serial_ports.usb_serial_ports()

    assert len(ports) == 2, f"one node per chip, got {[p.device for p in ports]}"
    assert {p.location for p in ports} == {"1-1.3", "1-1.4"}, \
        "both physical adapters must survive - dropping one hides the relay"


def test_a_saved_port_is_found_again_under_its_other_name():
    """A port saved under the node that is no longer offered resolves, by
    physical location, to the node that is."""
    with patch.object(serial_ports.serial.tools.list_ports, "comports", _two_chips_four_nodes), \
         patch.object(serial_ports.sys, "platform", "darwin"):
        offered = {p.device for p in serial_ports.usb_serial_ports()}
        hidden = next(p.device for p in _two_chips_four_nodes()
                      if p.location == "1-1.4" and p.device not in offered)
        resolved = serial_ports.resolve_port(hidden)

    assert resolved in offered
    assert resolved != hidden


def test_an_unknown_port_is_returned_unchanged():
    with patch.object(serial_ports.serial.tools.list_ports, "comports", _two_chips_four_nodes), \
         patch.object(serial_ports.sys, "platform", "darwin"):
        assert serial_ports.resolve_port("/dev/cu.nothing-here") == "/dev/cu.nothing-here"
