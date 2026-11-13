"""Regression tests for the hardening of the GPS modules (USB NMEA reader, phone GPS server)."""
import http.server
import threading
from datetime import datetime, timezone

import pynmea2
import pytest

from solareclipseworkbench import phone_gps, usb_gps


def _nmea(body: str) -> str:
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


# ------------------------------------------------------------------ USB GPS

def test_position_from_sentence_signs_hemispheres():
    msg = pynmea2.parse(_nmea("GPRMC,120000.00,A,3330.000,S,07030.000,W,0.0,0.0,130826,,,A"))
    lat, lon = usb_gps.position_from_sentence(msg)
    assert lat == pytest.approx(-33.5)
    assert lon == pytest.approx(-70.5)


@pytest.mark.parametrize("body", [
    "GPRMC,120000.00,A,,,,,0.0,0.0,130826,,,A",                  # empty position: pynmea2 says 0.0
    "GPRMC,120000.00,A,5030.000,,00430.000,E,0.0,0.0,130826,,,A",  # no hemisphere: pynmea2 says 0.0
    "GPRMC,120000.00,A,50x30,N,00430.000,E,0.0,0.0,130826,,,A",    # garbled: pynmea2 raises
])
def test_position_from_sentence_rejects_bad_fields(body):
    assert usb_gps.position_from_sentence(pynmea2.parse(_nmea(body))) is None


class _FakeSerial:
    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def reset_input_buffer(self):
        pass

    def readline(self):
        return (self._lines.pop(0) + "\r\n").encode() if self._lines else b""

    def close(self):
        self.closed = True


def _run_worker(monkeypatch, lines, fix_timeout=2.0):
    import serial
    fake = _FakeSerial(lines)
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: fake)
    monkeypatch.setattr(usb_gps, "check_serial_permission", lambda: True)
    worker = usb_gps.get_usb_gps_worker_class()(device="/dev/fake", fix_timeout=fix_timeout)
    fixes, errors = [], []
    worker.location_received.connect(fixes.append)
    worker.error.connect(errors.append)
    worker.run()            # on this thread: the signals are delivered directly
    return fixes, errors, fake


def test_usb_worker_survives_rmc_without_date(monkeypatch):
    """An RMC with a valid flag but an empty date made msg.datetime raise TypeError, which ended the thread."""
    lines = [_nmea("GPRMC,120000.00,A,5030.000,N,00430.000,E,0.0,0.0,,,,A")]
    lines += [_nmea(f"GPRMC,1200{s:02d}.00,A,5030.000,N,00430.000,E,0.0,0.0,130826,,,A") for s in range(1, 7)]
    fixes, errors, fake = _run_worker(monkeypatch, lines)
    assert not errors
    assert len(fixes) == 1
    assert fixes[0]["lat"] == pytest.approx(50.5)
    assert fixes[0]["lon"] == pytest.approx(4.5)
    assert fixes[0]["gps_time"] == datetime(2026, 8, 13, 12, 0, 5, tzinfo=timezone.utc)
    assert fake.closed


def test_usb_worker_ignores_fix_without_position(monkeypatch):
    """A GGA with a fix but empty position fields must not become the location 0, 0."""
    lines = [_nmea("GPGGA,120000.00,,,,,1,04,1.0,100.0,M,0.0,M,,")]
    lines += [_nmea(f"GPRMC,1200{s:02d}.00,A,,,,,0.0,0.0,130826,,,A") for s in range(1, 7)]
    fixes, errors, _ = _run_worker(monkeypatch, lines, fix_timeout=0.5)
    assert not fixes
    assert errors and "timeout" in errors[0]


def test_usb_worker_reports_unexpected_error(monkeypatch):
    class _Broken(_FakeSerial):
        def readline(self):
            raise RuntimeError("boom")

    import serial
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: _Broken([]))
    monkeypatch.setattr(usb_gps, "check_serial_permission", lambda: True)
    worker = usb_gps.get_usb_gps_worker_class()(device="/dev/fake", fix_timeout=2.0)
    errors = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors and "boom" in errors[0]


# ---------------------------------------------------------------- phone GPS

def test_parse_location_query_valid():
    assert phone_gps.parse_location_query("lat=50.5&lon=-4.25&alt=&accuracy=12") == (50.5, -4.25, None, 12.0)


@pytest.mark.parametrize("query", [
    "lat=nan&lon=4", "lat=50&lon=inf", "lat=91&lon=4", "lat=50&lon=-181", "lon=4", "lat=abc&lon=4",
    "lat=50&lon=4&alt=nan",
])
def test_parse_location_query_rejects(query):
    with pytest.raises(ValueError):
        phone_gps.parse_location_query(query)


def test_web_gps_server_stop_does_not_hang_when_never_served():
    """start() failing after the HTTP server was made (e.g. a bad certificate) left stop() in shutdown() for ever."""
    server = phone_gps.WebGpsServer(port=0)
    server._server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    stopper = threading.Thread(target=server.stop, daemon=True)
    stopper.start()
    stopper.join(3)
    assert not stopper.is_alive()


def test_phone_worker_stopped_before_it_runs_ends():
    worker = phone_gps.get_phone_gps_worker_class()(port=0)
    worker.stop_server()
    runner = threading.Thread(target=worker.run, daemon=True)
    runner.start()
    runner.join(3)
    assert not runner.is_alive()
