"""Phone dashboard: a small local web page to follow and steer a run from a phone.

The page shows the countdown to the contacts, the next scheduled commands, the
status of the cameras and the live view with its histogram and loupe, and has the +/-1 EV, reset and abort
controls of the main window.  The live view frames are those of the Live View
window on the laptop (``set_frame``): the dashboard never reads the camera, so it
adds no USB traffic and follows the pause around totality.  It is meant for when the laptop is under a sunshade or away from the
telescope.

The server runs on a background thread and never touches Qt.  The main window
hands it a snapshot of the state once a second (``set_state``), and the controls
on the phone are passed to ``on_action``, which the main window queues and carries
out on its own UI thread.

Anyone who can reach the laptop on the network could abort the run, so every
request must carry the random key that is in the URL (and in the QR code).  The
page is served over plain HTTP: it needs no secure context (unlike the phone GPS
page), and so the phone shows no certificate warning.

Usage (without Qt)::

    server = DashboardServer(on_action=lambda action, data: print(action, data))
    server.start()
    print(server.lan_url)
    server.set_state({...})
    ...
    server.stop()
"""

from __future__ import annotations

import hmac
import http.server
import json
import logging
import secrets
import threading
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from solareclipseworkbench.phone_gps import _lan_ip

LOGGER = logging.getLogger("SEW")

DEFAULT_PORT = 8766
# Ports tried after DEFAULT_PORT when it is taken (8765 is the phone GPS page)
_PORT_ATTEMPTS = 10

# Actions the page can send
ACTION_EV_UP = "ev_up"
ACTION_EV_DOWN = "ev_down"
ACTION_EV_RESET = "ev_reset"
ACTION_ABORT = "abort"
# A tap on the live view: "x" and "y" from 0 to 1 on the preview; moves the loupe (the zoom centre)
ACTION_LIVE_POINT = "live_point"
# Show the live view of another camera: "camera" is its name, or "" to close live view
ACTION_LIVE_CAMERA = "live_camera"
ACTIONS = (ACTION_EV_UP, ACTION_EV_DOWN, ACTION_EV_RESET, ACTION_ABORT, ACTION_LIVE_POINT, ACTION_LIVE_CAMERA)

# Largest request body accepted for an action
_MAX_BODY = 1024


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>SEW dashboard</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --line:#30363d; --fg:#e6edf3; --dim:#8b949e;
          --accent:#f0b429; --ok:#3fb950; --warn:#d29922; --bad:#f85149; }
  * { box-sizing:border-box; }
  [hidden] { display:none !important; }
  body { margin:0; padding:12px 16px 24px; background:var(--bg); color:var(--fg);
         font-family:system-ui,-apple-system,sans-serif; font-size:16px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--dim);
       margin:18px 0 6px; font-weight:600; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
  #status { display:flex; justify-content:space-between; align-items:center; font-size:14px; color:var(--dim); }
  #conn.ok { color:var(--ok); } #conn.bad { color:var(--bad); font-weight:700; }
  #next { text-align:center; padding:14px 8px; }
  #nextName { font-size:18px; color:var(--dim); }
  #nextCount { font-size:56px; font-weight:700; font-variant-numeric:tabular-nums; line-height:1.1;
               color:var(--accent); }
  table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
  td { padding:5px 4px; border-bottom:1px solid var(--line); vertical-align:top; }
  tr:last-child td { border-bottom:none; }
  td.t { text-align:right; white-space:nowrap; }
  td.c { color:var(--accent); white-space:nowrap; text-align:right; font-weight:600; }
  .past td { color:var(--dim); }
  .small { font-size:13px; color:var(--dim); }
  .row { display:flex; gap:8px; }
  button { flex:1; font-size:20px; font-weight:700; padding:16px 0; border-radius:10px;
           border:1px solid var(--line); background:#21262d; color:var(--fg); }
  button:disabled { opacity:.35; }
  button:active:not(:disabled) { background:#30363d; }
  #ev { text-align:center; font-size:22px; font-weight:700; margin:4px 0 10px; }
  #ev.on { color:#f0883e; }
  #abort { background:#5a1d1d; border-color:var(--bad); color:#fff; margin-top:14px; width:100%; }
  #liveBox { position:relative; text-align:center; }
  #live { width:100%; height:auto; display:block; border-radius:6px; background:#000; }
  #live.old { opacity:.4; }
  #liveNote { font-size:14px; color:var(--dim); padding:4px 0; }
  #liveHead { display:flex; justify-content:space-between; align-items:baseline; }
  #liveHead .toggles { display:flex; gap:10px; }
  #tools { display:flex; gap:10px; align-items:flex-start; margin-top:8px; }
  #histBox { flex:1; min-width:0; }
  #hist { width:100%; height:80px; display:block; background:#14141a; border-radius:6px; }
  #histText { display:flex; justify-content:space-between; font-size:13px; color:var(--dim); margin-top:2px; }
  #histText .bad { color:var(--bad); font-weight:700; }
  #loupeBox { width:140px; flex:none; text-align:center; }
  #loupe { width:140px; height:140px; image-rendering:pixelated; display:block; background:#000; border-radius:6px; }
  #loupeText { font-size:13px; margin-top:2px; }
  #camRow { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
  #camRow label { font-size:14px; color:var(--dim); }
  #camSel { flex:1; min-width:0; font-size:16px; padding:8px; border-radius:8px; background:#21262d;
            color:var(--fg); border:1px solid var(--line); }
  #liveHead label { font-size:13px; color:var(--dim); text-transform:none; letter-spacing:0; font-weight:400; }
  #msg { min-height:1.3em; text-align:center; font-size:14px; margin-top:8px; color:var(--warn); }
</style>
</head>
<body>
<div id="status"><span id="clock">--:--:--</span><span id="conn">connecting&hellip;</span></div>

<div class="panel" id="next" style="margin-top:8px">
  <div id="nextName">&nbsp;</div>
  <div id="nextCount">--:--</div>
  <div class="small" id="runState">&nbsp;</div>
</div>

<h2>Contacts</h2>
<div class="panel"><table id="moments"></table></div>

<h2>Next commands</h2>
<div class="panel"><table id="jobs"></table><div class="small" id="jobsMore"></div></div>

<h2>Exposure</h2>
<div class="panel">
  <div id="ev">as scripted</div>
  <div class="row">
    <button id="evDown" onclick="act('ev_down')">&minus;1 EV</button>
    <button id="evReset" onclick="act('ev_reset')">Reset</button>
    <button id="evUp" onclick="act('ev_up')">+1 EV</button>
  </div>
  <button id="abort" onclick="abortRun()">Abort run</button>
  <div id="msg"></div>
</div>

<h2 id="liveHead"><span>Live view</span><span class="toggles">
  <label><input type="checkbox" id="liveOn" onchange="liveToggled()"> show</label>
  <label><input type="checkbox" id="histOn" onchange="liveToggled()"> histogram</label>
  <label><input type="checkbox" id="loupeOn" onchange="liveToggled()"> loupe</label></span></h2>
<div class="panel" id="liveBox">
  <div id="camRow"><label for="camSel">Camera</label>
    <select id="camSel" onchange="pickCamera()"></select></div>
  <img id="live" alt="" hidden onclick="livePoint(event)">
  <div id="liveNote">&nbsp;</div>
  <div id="tools" hidden>
    <div id="histBox"><canvas id="hist"></canvas><div id="histText"></div></div>
    <div id="loupeBox"><img id="loupe" alt=""><div id="loupeText"></div></div>
  </div>
</div>

<h2>Cameras</h2>
<div class="panel"><table id="cameras"></table></div>

<script>
const KEY = new URLSearchParams(location.search).get('k') || '';
let state = null, receivedAt = 0, lastOk = 0, liveShown = -1, loupeShown = -1, histShown = -1;
const liveOn = document.getElementById('liveOn'), histOn = document.getElementById('histOn'),
      loupeOn = document.getElementById('loupeOn');
const TOGGLES = [[liveOn, 'sewLive'], [histOn, 'sewHist'], [loupeOn, 'sewLoupe']];
for (const [box, name] of TOGGLES) {
  try { box.checked = localStorage.getItem(name) !== 'off'; } catch (err) { box.checked = true; }
}
function liveToggled() {
  for (const [box, name] of TOGGLES) {
    try { localStorage.setItem(name, box.checked ? 'on' : 'off'); } catch (err) {}
  }
  liveShown = loupeShown = histShown = -1; renderLive();
}

// The choice made on the phone wins over the state until the laptop has had time to switch
let camPicked = null, camPickedAt = 0;
function pickCamera() {
  const sel = document.getElementById('camSel');
  camPicked = sel.value; camPickedAt = performance.now();
  liveShown = loupeShown = histShown = -1;
  act('live_camera', {camera: sel.value}, sel.value ? 'Switching to ' + sel.value + '\u2026' : 'Live view off.');
}

function renderCameras() {
  const sel = document.getElementById('camSel');
  const names = state.live_cameras || [];
  const options = [''].concat(names);
  const key = options.join('\\n');
  if (sel.dataset.key !== key) {
    sel.innerHTML = options.map(n => '<option value="' + esc(n) + '">' + (n ? esc(n) : 'Off') + '</option>').join('');
    sel.dataset.key = key;
  }
  if (camPicked !== null && performance.now() - camPickedAt < 4000) sel.value = camPicked;
  else { camPicked = null; sel.value = state.live_camera || ''; }
  const stale = !lastOk || (performance.now() - lastOk) > 5000;
  sel.disabled = stale || !state.live_switch || !names.length;
  document.getElementById('camRow').title = state.live_switch ? '' :
    'Live view is paused around totality: the camera cannot be changed now';
}

function livePoint(ev) {
  const img = ev.currentTarget, r = img.getBoundingClientRect();
  if (!r.width || !r.height) return;
  const x = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width));
  const y = Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height));
  act('live_point', {x, y}, 'Loupe moved.');
}

function drawHistogram(h) {
  const c = document.getElementById('hist'), dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, ht = c.clientHeight;
  if (!w) return;
  c.width = w * dpr; c.height = ht * dpr;
  const g = c.getContext('2d'); g.scale(dpr, dpr);
  g.fillStyle = '#14141a'; g.fillRect(0, 0, w, ht);
  const n = h.bins.length, bw = w / n;
  // The clipped range in red, so the disc touching it shows
  const clipX = h.clipped_from / 256 * w;
  for (let i = 0; i < n; i++) {
    const x = i * bw;
    g.fillStyle = x >= clipX ? '#f85149' : '#d2d2dc';
    const bar = h.bins[i] * (ht - 4);
    g.fillRect(x, ht - bar, Math.max(1, bw - 0.5), bar);
  }
  const t = document.getElementById('histText');
  t.innerHTML = '<span class="' + (h.clipped > 0.05 ? 'bad' : '') + '">clipped ' + h.clipped.toFixed(2) +
    '%</span><span>black ' + h.black.toFixed(1) + '%</span>';
}

function renderLive() {
  const img = document.getElementById('live'), note = document.getElementById('liveNote');
  const live = state && state.live;
  const tools = document.getElementById('tools');
  if (state) renderCameras();
  if (!live) {
    img.hidden = true; tools.hidden = true; liveShown = loupeShown = histShown = -1;
    const names = (state && state.live_cameras) || [];
    note.textContent = !names.length ? 'No camera for live view: detect the cameras on the laptop.'
      : (state.live_switch ? 'Live view is off: pick a camera.' : 'Live view is paused around totality.');
    return;
  }
  renderTools(live);
  if (!liveOn.checked) { img.hidden = true; img.removeAttribute('src'); note.textContent = live.camera; return; }
  if (live.frame && live.frame !== liveShown) {
    liveShown = live.frame;
    img.src = 'live.jpg?k=' + encodeURIComponent(KEY) + '&f=' + live.frame;
  }
  img.hidden = !live.frame;
  const age = live.age == null ? null : live.age + elapsed();
  const old = age == null || age > 5 || live.status !== 'active';
  img.className = old ? 'old' : '';
  let text = live.camera;
  if (live.status === 'paused') text += ' \u00b7 paused around totality (the script has the USB); the camera cannot be changed';
  else if (live.status === 'disabled') text += ' \u00b7 disabled on the laptop';
  else if (!live.frame) text += ' \u00b7 waiting for the first frame';
  if (age != null && age > 5) text += ' \u00b7 last frame ' + fmt(age) + ' ago';
  if (loupeOn.checked && live.loupe && live.status === 'active') text += ' \u00b7 tap to move the loupe';
  note.textContent = text;
}

function renderTools(live) {
  const tools = document.getElementById('tools');
  const showHist = histOn.checked && !!live.histogram, showLoupe = loupeOn.checked && !!live.loupe;
  tools.hidden = !(showHist || showLoupe);
  document.getElementById('histBox').hidden = !showHist;
  document.getElementById('loupeBox').hidden = !showLoupe;
  if (showHist && live.frame !== histShown) { histShown = live.frame; drawHistogram(live.histogram); }
  if (showLoupe && live.frame !== loupeShown) {
    loupeShown = live.frame;
    document.getElementById('loupe').src = 'loupe.png?k=' + encodeURIComponent(KEY) + '&f=' + live.frame;
    const l = live.loupe, t = document.getElementById('loupeText');
    t.textContent = l.score == null ? '' : l.score.toFixed(1) + ' \u00b7 ' + Math.round(l.share * 100) + '% of best';
    t.style.color = l.share > 0.95 ? '#3fb950' : '#f0b429';
  }
}

function fmt(s) {
  const neg = s < 0; s = Math.abs(Math.floor(s));
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
        m = Math.floor(s % 3600 / 60), sec = s % 60;
  const p = n => String(n).padStart(2, '0');
  let out = (h || d) ? p(h) + ':' + p(m) + ':' + p(sec) : p(m) + ':' + p(sec);
  if (d) out = d + 'd ' + out;
  return (neg ? '+' : '') + out;
}
function esc(t) {
  return String(t == null ? '' : t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}
function elapsed() { return (performance.now() - receivedAt) / 1000; }

function render() {
  const conn = document.getElementById('conn');
  const stale = !lastOk || (performance.now() - lastOk) > 5000;
  conn.textContent = stale ? 'NO CONNECTION' : 'live';
  conn.className = stale ? 'bad' : 'ok';
  if (!state) return;
  const e = elapsed();

  const now = new Date(Date.parse(state.now_utc) + e * 1000);
  document.getElementById('clock').textContent =
    (state.simulation ? 'SIMULATION · ' : '') + now.toISOString().substr(11, 8) + ' UTC';

  // Next contact
  const upcoming = state.moments.filter(m => m.seconds - e > 0);
  const nx = upcoming[0];
  document.getElementById('nextName').textContent = nx ? nx.name + ' in' : 'All contacts passed';
  document.getElementById('nextCount').textContent = nx ? fmt(nx.seconds - e) : '--:--';
  document.getElementById('runState').textContent = state.running
    ? state.jobs_remaining + ' command(s) to go'
    : (state.script ? 'Script stopped' : 'No script loaded');

  document.getElementById('moments').innerHTML = state.moments.map(m => {
    const s = m.seconds - e;
    return '<tr class="' + (s < 0 ? 'past' : '') + '"><td>' + esc(m.name) + '</td><td class="t">' +
      esc(m.local) + '</td><td class="c">' + (s < 0 ? '&mdash;' : fmt(s)) + '</td></tr>';
  }).join('');

  const jobs = state.jobs.filter(j => j.seconds - e > -1);
  document.getElementById('jobs').innerHTML = jobs.length ? jobs.map(j =>
    '<tr><td class="c">' + fmt(Math.max(0, j.seconds - e)) + '</td><td>' + esc(j.command) +
    (j.description ? '<div class="small">' + esc(j.description) + '</div>' : '') + '</td></tr>'
  ).join('') : '<tr><td class="small">No commands scheduled</td></tr>';
  const more = state.jobs_remaining - jobs.length;
  document.getElementById('jobsMore').textContent = more > 0 ? '+ ' + more + ' more' : '';

  const ev = document.getElementById('ev');
  ev.textContent = state.ev ? (state.ev > 0 ? '+' : '−') + Math.abs(state.ev) + ' EV for all following shots'
                            : 'as scripted';
  ev.className = state.ev ? 'on' : '';
  document.getElementById('evUp').disabled = stale || state.ev >= state.ev_max;
  document.getElementById('evDown').disabled = stale || state.ev <= -state.ev_max;
  document.getElementById('evReset').disabled = stale || !state.ev;
  document.getElementById('abort').disabled = stale || !state.running;

  document.getElementById('cameras').innerHTML = state.cameras.length ? state.cameras.map(c =>
    '<tr><td>' + esc(c.name) + '</td><td class="t">\U0001F50B ' + esc(c.battery) + '</td><td class="t">' +
    esc(c.free) + '</td></tr>'
  ).join('') : '<tr><td class="small">No cameras connected</td></tr>';

  renderLive();
}

async function poll() {
  try {
    const r = await fetch('state?k=' + encodeURIComponent(KEY), {cache: 'no-store'});
    if (r.ok) { state = await r.json(); receivedAt = performance.now(); lastOk = receivedAt; }
    else if (r.status === 403) { document.getElementById('msg').textContent = 'Wrong key: scan the QR code again.'; }
  } catch (err) { /* shown as NO CONNECTION */ }
  render();
}

async function act(action, extra, sent) {
  const msg = document.getElementById('msg');
  try {
    const r = await fetch('action?k=' + encodeURIComponent(KEY), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({action}, extra || {}))});
    msg.textContent = r.ok ? (sent || 'Sent.') : 'Refused (' + r.status + ').';
  } catch (err) { msg.textContent = 'Not sent: no connection.'; }
  setTimeout(() => { msg.textContent = ''; }, 2500);
  setTimeout(poll, 400);
}

function abortRun() {
  if (confirm('Abort the run?\\n\\nAll commands still to come are cancelled. This cannot be undone.')) act('abort');
}

poll();
setInterval(poll, 1000);
setInterval(render, 250);
</script>
</body>
</html>
"""


class DashboardServer:
    """HTTP server for the phone dashboard.

    Args:
        - port: First TCP port to try; the next ones are tried when it is taken
        - on_action: Called on the server thread with ``(action, data)`` for every
                     accepted control (one of ``ACTIONS``).  It must return quickly
                     and must not touch Qt; queue the action instead.
        - key: Access key; a random one when not given
    """

    def __init__(self, port: int = DEFAULT_PORT, on_action: Optional[Callable[[str, dict], None]] = None,
                 key: Optional[str] = None):
        self.port = port
        self.key = key or secrets.token_urlsafe(9)
        self._on_action = on_action
        self._state_json = b"{}"
        self._frame: Optional[bytes] = None
        self._frame_id = 0
        self._loupe: Optional[bytes] = None
        self._lock = threading.Lock()
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.lan_url = ""
        self.local_url = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    def set_state(self, state: dict) -> None:
        """Replace the state the page shows; safe to call from any thread."""
        data = json.dumps(state, default=str).encode()
        with self._lock:
            self._state_json = data

    def set_frame(self, jpeg: Optional[bytes], frame_id: int = 0, loupe_png: Optional[bytes] = None) -> None:
        """Replace the live view frame (JPEG) and its loupe (PNG), or remove them with None.

        Safe to call from any thread.
        """
        with self._lock:
            self._frame = jpeg
            self._frame_id = frame_id if jpeg else 0
            self._loupe = loupe_png if jpeg else None

    def loupe(self) -> Optional[bytes]:
        with self._lock:
            return self._loupe

    def frame(self) -> Optional[bytes]:
        with self._lock:
            return self._frame

    def state_json(self) -> bytes:
        with self._lock:
            return self._state_json

    def key_ok(self, key: Optional[str]) -> bool:
        return bool(key) and hmac.compare_digest(str(key), self.key)

    def start(self) -> None:
        """Start listening on the first free port from ``port`` on, in a background thread."""
        if self._server is not None:
            return

        handler = _make_handler(self)
        last_error: Optional[OSError] = None
        for port in range(self.port, self.port + _PORT_ATTEMPTS):
            try:
                self._server = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
                self.port = port
                break
            except OSError as exc:
                last_error = exc
        if self._server is None:
            raise OSError(f"No free port for the phone dashboard from {self.port} on: {last_error}")

        self._server.daemon_threads = True
        self.lan_url = f"http://{_lan_ip()}:{self.port}/?k={self.key}"
        self.local_url = f"http://localhost:{self.port}/?k={self.key}"
        self._thread = threading.Thread(target=self._server.serve_forever, name="PhoneDashboard", daemon=True)
        self._thread.start()
        LOGGER.info("Phone dashboard started at %s", self.lan_url)

    def stop(self) -> None:
        """Stop the server; it can be started again."""
        server, self._server = self._server, None
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            LOGGER.debug("Could not stop the phone dashboard cleanly", exc_info=True)
        LOGGER.info("Phone dashboard stopped")

    def _handle_action(self, body: bytes) -> int:
        """Check an action request and pass it on; return the HTTP status."""
        try:
            data = json.loads(body.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            return 400
        if not isinstance(data, dict):
            return 400
        action = data.get("action")
        if action not in ACTIONS:
            return 400
        if action == ACTION_LIVE_POINT:
            try:
                x, y = float(data["x"]), float(data["y"])
            except (KeyError, TypeError, ValueError):
                return 400
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                return 400
            data = {"action": action, "x": x, "y": y}
        if action == ACTION_LIVE_CAMERA:
            camera = data.get("camera")
            if not isinstance(camera, str) or len(camera) > 200:
                return 400
            data = {"action": action, "camera": camera}
        if action == ACTION_LIVE_CAMERA:
            LOGGER.info("Phone dashboard: live view of %r", data["camera"] or "no camera")
        elif action == ACTION_LIVE_POINT:
            LOGGER.debug("Phone dashboard: loupe moved to %.3f, %.3f", data["x"], data["y"])
        else:
            LOGGER.info("Phone dashboard: %s", action)
        if self._on_action is not None:
            try:
                self._on_action(action, data)
            except Exception:
                LOGGER.exception("Phone dashboard action %s failed", action)
                return 500
        return 200


def _make_handler(server: DashboardServer):
    page = _DASHBOARD_HTML.encode()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # no access log: the page polls every second
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self, parsed) -> bool:
            key = parse_qs(parsed.query).get("k", [None])[0]
            if server.key_ok(key):
                return True
            self._send(403, b"Forbidden: open the URL with its key (scan the QR code in Solar Eclipse Workbench)",
                       "text/plain; charset=utf-8")
            return False

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path not in ("/", "/state", "/live.jpg", "/loupe.png"):
                self._send(404, b"Not found", "text/plain")
                return
            if not self._authorised(parsed):
                return
            if parsed.path == "/live.jpg":
                frame = server.frame()
                if frame is None:
                    self._send(404, b"No live view frame", "text/plain")
                else:
                    self._send(200, frame, "image/jpeg")
            elif parsed.path == "/loupe.png":
                loupe = server.loupe()
                if loupe is None:
                    self._send(404, b"No loupe", "text/plain")
                else:
                    self._send(200, loupe, "image/png")
            elif parsed.path == "/state":
                self._send(200, server.state_json(), "application/json")
            else:
                self._send(200, page, "text/html; charset=utf-8")

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/action":
                self._send(404, b"Not found", "text/plain")
                return
            if not self._authorised(parsed):
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > _MAX_BODY:
                self._send(400, b'{"ok":false}', "application/json")
                return
            status = server._handle_action(self.rfile.read(length))
            self._send(status, b'{"ok":true}' if status == 200 else b'{"ok":false}', "application/json")

    return _Handler
