"""
Phone GPS capture server for Solar Eclipse Workbench.

Starts a self-signed HTTPS server that serves a browser-based GPS page.
The page uses the browser's Geolocation API and submits coordinates via
a plain HTML form GET request (immune to SSL/CORS blocking on self-signed
certificates).

Typical usage
-------------
::

    server = WebGpsServer(port=8765)
    server.start()
    print("Open:", server.lan_url, "or", server.local_url)
    fix = server.wait_for_fix(timeout=300)
    server.stop()
    if fix:
        print(fix["lat"], fix["lon"])

Integration with Qt
-------------------
Use ``PhoneGpsWorker(QThread)`` — it emits ``server_started(str, str)`` with
(lan_url, localhost_url) when the server is ready, and ``location_received(dict)``
with keys ``lat``, ``lon``, ``alt``, ``accuracy`` when coordinates arrive.
"""

from __future__ import annotations

import http.server
import os
import socket
import ssl
import subprocess
import tempfile
import threading
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_WEB_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GPS Location</title>
  <style>
    body { font-family: sans-serif; max-width: 500px; margin: 2em auto; padding: 1em;
           background: #111; color: #eee; }
    h1 { color: #4af; text-align: center; }
    #status { font-size: 1em; margin: .8em 0; padding: .6em; border-radius: 6px;
               background: #222; min-height: 2em; }
    #coords { background: #1a1a2e; border-radius: 8px; padding: 1em; margin: 1em 0;
               font-family: monospace; font-size: .95em; display: none; }
    button { background: #4af; color: #000; border: none; padding: .6em 1.4em;
              font-size: 1em; border-radius: 6px; cursor: pointer; margin: .3em; }
    button.sec { background: #555; color: #eee; }
    .ok { color: #4f4; } .err { color: #f66; } .warn { color: #fa4; }
    hr { border-color: #333; margin: 1.5em 0; }
    label { display: block; margin: .5em 0 .2em; font-size: .9em; color: #aaa; }
    input[type=number], input[type=text] {
      background: #222; border: 1px solid #555; color: #eee;
      padding: .4em; border-radius: 4px; width: 100%; box-sizing: border-box;
      font-size: 1em; margin-bottom: .3em; }
    #manual { background: #1a2a1a; border-radius: 8px; padding: 1em; margin: 1em 0; }
    .note { font-size: .8em; color: #888; }
  </style>
</head>
<body>
  <h1>Solar Eclipse Workbench</h1>
  <p style="text-align:center;color:#aaa">GPS Location Capture</p>

  <div id="status">Ready.</div>
  <div id="coords"></div>

  <button onclick="getLocation()">&#x1F4CD; Get My Location</button>
  <button onclick="watchLocation()" class="sec">&#x1F504; Watch</button>
  <button onclick="stopWatch()" class="sec">&#x23F9; Stop</button>

  <hr>

  <div id="manual">
    <b>Manual / form entry</b> (works even when GPS fails):
    <form method="GET" action="/location" target="_self">
      <label>Latitude (decimal, e.g. 50.832156)</label>
      <input type="text" name="lat" id="mlat" placeholder="50.832156" required>
      <label>Longitude (decimal, e.g. 4.864231)</label>
      <input type="text" name="lon" id="mlon" placeholder="4.864231" required>
      <label>Altitude in metres (optional)</label>
      <input type="text" name="alt" id="malt" placeholder="38.0">
      <input type="hidden" name="accuracy" value="">
      <br>
      <button type="submit">&#x2714; Send location</button>
    </form>
    <p class="note">This submits via a regular browser form — no SSL issues.</p>
  </div>

  <script>
    let watchId = null;
    const opts = { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 };

    function setStatus(msg, cls) {
      const el = document.getElementById('status');
      el.innerHTML = msg;
      el.className = cls || '';
    }

    function showCoords(pos) {
      const c = pos.coords;
      document.getElementById('coords').style.display = 'block';
      document.getElementById('coords').innerHTML =
        '<b>Lat:</b> ' + c.latitude.toFixed(6) + '&deg;<br>' +
        '<b>Lon:</b> ' + c.longitude.toFixed(6) + '&deg;<br>' +
        '<b>Alt:</b> ' + (c.altitude !== null ? c.altitude.toFixed(1) + ' m' : 'n/a') + '<br>' +
        '<b>Accuracy:</b> &plusmn;' + c.accuracy.toFixed(0) + ' m';
      document.getElementById('mlat').value = c.latitude.toFixed(8);
      document.getElementById('mlon').value = c.longitude.toFixed(8);
      if (c.altitude !== null) document.getElementById('malt').value = c.altitude.toFixed(1);
      document.querySelector('input[name=accuracy]').value = c.accuracy.toFixed(1);
      setStatus('Fix received &mdash; submitting&hellip;', 'warn');
      document.querySelector('form').submit();
    }

    function showError(err) {
      const msgs = {
        1: 'Permission denied &mdash; please allow location in your browser.',
        2: 'Position unavailable &mdash; no GPS or network location on this device.',
        3: 'Timed out. Try again or use manual entry below.'
      };
      setStatus('&#10007; ' + (msgs[err.code] || err.message) +
        '<br><small style="color:#aaa">Use the manual entry form below as fallback.</small>', 'err');
    }

    function getLocation() {
      if (!navigator.geolocation) {
        setStatus('&#10007; Geolocation not supported. Use manual entry.', 'err'); return;
      }
      stopWatch();
      setStatus('Requesting location&hellip; (may take up to 30s)', 'warn');
      navigator.geolocation.getCurrentPosition(showCoords, showError, opts);
    }

    function watchLocation() {
      if (!navigator.geolocation) {
        setStatus('&#10007; Geolocation not supported. Use manual entry.', 'err'); return;
      }
      stopWatch();
      setStatus('Watching location&hellip;', 'warn');
      watchId = navigator.geolocation.watchPosition(showCoords, showError, opts);
    }

    function stopWatch() {
      if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
    }
  </script>
</body>
</html>
"""

_WEB_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Done</title>
<style>body{{font-family:sans-serif;max-width:400px;margin:3em auto;padding:1em;
background:#111;color:#eee;text-align:center;}} h1{{color:#4f4;}} p{{color:#aaa;}}</style>
</head>
<body>
<h1>&#10003; Location received!</h1>
<p>The coordinates have been sent to Solar Eclipse Workbench.</p>
<p>You can close this page.</p>
<p style="font-family:monospace;background:#222;padding:.5em;border-radius:6px">
  {lat}&deg; N &nbsp; {lon}&deg; E
</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# Core server class
# ---------------------------------------------------------------------------

class WebGpsServer:
    """Self-signed HTTPS server that captures GPS coordinates from a phone browser.

    Parameters
    ----------
    port:
        TCP port to listen on (default 8765).
    on_fix:
        Optional callback called from the server thread when coordinates are
        received.  Receives a dict with keys ``lat``, ``lon``, ``alt``,
        ``accuracy``.
    on_started:
        Optional callback called when the server is listening.  Receives
        ``(lan_url, localhost_url)`` as strings.
    """

    def __init__(
        self,
        port: int = 8765,
        on_fix: Optional[Callable[[dict], None]] = None,
        on_started: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.port = port
        self._on_fix = on_fix
        self._on_started = on_started

        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._tmpdir: Optional[str] = None
        self._cert_file: Optional[str] = None
        self._key_file: Optional[str] = None

        self._received: dict = {}
        self._event = threading.Event()

        self.lan_url: str = ""
        self.local_url: str = ""
        self.proto: str = "https"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Generate a certificate, start the server in a background thread, and
        call *on_started* with the two URLs."""
        lan_ip = _lan_ip()
        self._tmpdir = tempfile.mkdtemp()
        self._cert_file = os.path.join(self._tmpdir, "cert.pem")
        self._key_file = os.path.join(self._tmpdir, "key.pem")

        https_ok = False
        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048",
                    "-keyout", self._key_file, "-out", self._cert_file,
                    "-days", "1", "-nodes",
                    "-subj", f"/CN={lan_ip}",
                    "-addext", f"subjectAltName=IP:{lan_ip},IP:127.0.0.1,DNS:localhost",
                ],
                check=True,
                capture_output=True,
            )
            https_ok = True
        except Exception as exc:
            print(f"Warning: could not generate HTTPS certificate ({exc}). "
                  "Falling back to HTTP (geolocation may not work on mobile).")

        self.proto = "https" if https_ok else "http"
        self.lan_url = f"{self.proto}://{lan_ip}:{self.port}"
        self.local_url = f"{self.proto}://localhost:{self.port}"

        html_bytes = _WEB_HTML.encode()
        received = self._received
        event = self._event
        on_fix = self._on_fix

        class _Handler(http.server.BaseHTTPRequestHandler):
            # The server handles one request at a time: a client that connects
            # and then sends nothing (port scanner, stalled TLS handshake) must
            # not block the phone that is trying to send its location.
            timeout = 15

            def log_message(self, fmt, *args):  # silence default access log
                pass

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.end_headers()

            def do_GET(self):
                from urllib.parse import urlparse
                parsed = urlparse(self.path)

                if parsed.path == "/location":
                    try:
                        lat, lon, alt, acc = parse_location_query(parsed.query)

                        received.update({"lat": lat, "lon": lon, "alt": alt, "accuracy": acc})
                        event.set()
                        if on_fix:
                            on_fix(dict(received))

                        success = _WEB_SUCCESS_HTML.format(
                            lat=f"{lat:.6f}", lon=f"{lon:.6f}"
                        ).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(success)))
                        self.end_headers()
                        self.wfile.write(success)
                    except Exception as exc:
                        err = f"Error: {exc}".encode()
                        self.send_response(400)
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Length", str(len(err)))
                        self.end_headers()
                        self.wfile.write(err)
                    return

                # Serve the main GPS page
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)

        self._server = http.server.HTTPServer(("0.0.0.0", self.port), _Handler)

        if https_ok:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self._cert_file, self._key_file)
            # Handshake lazily, on the first read in the handler, where the
            # handler timeout applies, rather than unbounded inside accept().
            self._server.socket = ctx.wrap_socket(
                self._server.socket, server_side=True, do_handshake_on_connect=False
            )

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        if self._on_started:
            self._on_started(self.lan_url, self.local_url)

    def wait_for_fix(self, timeout: Optional[float] = 300.0) -> Optional[dict]:
        """Block until coordinates arrive or *timeout* seconds elapse.

        Pass ``timeout=None`` to wait indefinitely.
        Returns a dict with ``lat``, ``lon``, ``alt``, ``accuracy``, or
        ``None`` on timeout.
        """
        if self._event.wait(timeout):
            return dict(self._received)
        return None

    def stop(self) -> None:
        """Shut down the server and clean up temporary certificate files."""
        if self._server:
            # shutdown() waits for serve_forever() to return, so it would block
            # forever when start() failed before the serving thread was started.
            if self._thread is not None and self._thread.is_alive():
                self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._cleanup()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        for path in (self._cert_file, self._key_file):
            try:
                if path:
                    os.unlink(path)
            except OSError:
                pass
        try:
            if self._tmpdir:
                os.rmdir(self._tmpdir)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def parse_location_query(query: str) -> tuple:
    """Return ``(lat, lon, alt, accuracy)`` from the query string of a /location request.

    ``alt`` and ``accuracy`` are ``None`` when absent or empty.  Raises ``ValueError``
    for a missing, non-numeric, non-finite or out-of-range latitude/longitude, so that
    a typo in the manual form (or a stray request on the network) never becomes the
    observer location.
    """
    import math
    from urllib.parse import parse_qs

    params = parse_qs(query)

    def _number(name: str, required: bool):
        value = params.get(name, [""])[0].strip()
        if not value:
            if required:
                raise ValueError(f"{name} is missing")
            return None
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} must be a finite number")
        return number

    lat = _number("lat", True)
    lon = _number("lon", True)
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} is outside -90..90")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} is outside -180..180")
    return lat, lon, _number("alt", False), _number("accuracy", False)


def _lan_ip() -> str:
    """Return the machine's LAN IP address, or 127.0.0.1 as fallback."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Optional Qt worker (only usable when PyQt6 is installed)
# ---------------------------------------------------------------------------

def _make_phone_gps_worker():
    """Return the PhoneGpsWorker QThread class, importing PyQt6 on demand."""
    from PyQt6.QtCore import QThread, pyqtSignal  # type: ignore

    class PhoneGpsWorker(QThread):
        """QThread that runs a WebGpsServer and emits Qt signals.

        Signals
        -------
        server_started(lan_url: str, local_url: str)
            Emitted once the HTTPS server is listening.
        location_received(data: dict)
            Emitted when the phone submits its location.
            Dict keys: ``lat``, ``lon``, ``alt``, ``accuracy``.
        error(message: str)
            Emitted if the server fails to start.
        """

        server_started = pyqtSignal(str, str)
        location_received = pyqtSignal(dict)
        error = pyqtSignal(str)

        def __init__(self, port: int = 8765, parent=None):
            super().__init__(parent)
            self.port = port
            self._server: Optional[WebGpsServer] = None
            self._stop_requested = threading.Event()

        def run(self) -> None:
            try:
                self._server = WebGpsServer(
                    port=self.port,
                    on_fix=lambda data: self.location_received.emit(data),
                    on_started=lambda lan, local: self.server_started.emit(lan, local),
                )
                if self._stop_requested.is_set():
                    # stop_server() came before the server existed: without this
                    # check wait_for_fix() would never return and the thread hang.
                    return
                self._server.start()
                # Block until a fix arrives or stop_server() signals the event.
                self._server.wait_for_fix(timeout=None)
            except Exception as exc:
                self.error.emit(str(exc))
            finally:
                # Always shut down on the worker thread so the main thread
                # never blocks on httpserver.shutdown().
                if self._server:
                    self._server.stop()
                    self._server = None

        def stop_server(self) -> None:
            """Signal the worker thread to stop (non-blocking, safe to call from main thread)."""
            self._stop_requested.set()
            if self._server:
                self._server._event.set()   # unblock wait_for_fix; run() calls stop()

    return PhoneGpsWorker


# Lazy attribute so the module can be imported without PyQt6 being present.
_PhoneGpsWorker = None


def get_phone_gps_worker_class():
    """Return the ``PhoneGpsWorker`` class (PyQt6 required)."""
    global _PhoneGpsWorker
    if _PhoneGpsWorker is None:
        _PhoneGpsWorker = _make_phone_gps_worker()
    return _PhoneGpsWorker
