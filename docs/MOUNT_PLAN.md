# INDI mount control — implementation plan

Issue #75, narrowed to **mount control only**.  Astro cameras are out of scope;
the DSLRs stay on gphoto2.  Goal: keep the sun in the field of view during a run.

The integration follows the pattern of the USB relay trigger
(`relay_trigger.py` + simulated backend, `hardware_registry.register_hardware`,
`HARDWARE_COMMANDS` script commands, `RelayPopup` in `gui.py`,
`hardware_console.py`, `docs/RELAY.md`).

## Decisions

- Talk to an INDI server (default `localhost:7624`) with a small **pure-Python
  INDI client** (XML over TCP), not the compiled `pyindi-client`, so the
  Windows (WSL), macOS and Linux installers stay simple.
- The INDI server can run locally, in WSL on Windows (mount cable shared with
  usbipd-win like the USB GPS), or on another machine (e.g. a Raspberry Pi at
  the mount).  Wi-Fi/Ethernet mounts need no USB at all.
- **Never GOTO.**  The mount is pointed at the sun by hand, behind a solar
  filter.  `sew` only tracks, nudges and parks.
- `sew` **sends the observer location and time** (GPS time when available) to
  the mount on connect (`GEOGRAPHIC_COORD`, `TIME_UTC`).
- Mount problems are reported through `hardware_problems`; they never stop a run.
- **Script commands are part of step 1.**

## Step 1 — Mount connection and script commands  *(done, branch `feat/indi-mount-control`)*

Built as planned, plus: under WSL a shared mount cable is attached before connecting to a local
server; the simulator (`indi_simulator.py`) is a real INDI server on localhost, used by the tests and
by the `simulated` address.  Not yet tested against a real `indiserver` / mount.

- `indi_client.py`: INDI XML client; reader thread keeps a property cache;
  `getProperties`, `newSwitchVector`, `newNumberVector`, `newTextVector`;
  waits for the property state (Ok/Busy/Alert).
- `mount.py`: `Mount` class (`connect`, `send_site`, `track_solar`,
  `stop_tracking`, `guide`, `nudge_start`/`nudge_stop`, `abort`, `park`,
  `unpark`, `position`, `describe`) on the standard properties
  `CONNECTION`, `GEOGRAPHIC_COORD`, `TIME_UTC`, `TELESCOPE_TRACK_MODE`
  (`TRACK_SOLAR`), `TELESCOPE_TRACK_STATE`, `TELESCOPE_TIMED_GUIDE_NS/WE`,
  `TELESCOPE_MOTION_NS/WE`, `TELESCOPE_ABORT_MOTION`, `TELESCOPE_PARK`,
  `EQUATORIAL_EOD_COORD`.  `SimulatedMount` for tests and simulation mode.
- Script commands (kind `mount` in `HARDWARE_COMMANDS`): `mount_track`,
  `mount_stop`, `mount_park` (later `mount_center`), checked at load time.
- `MountPopup` + toolbar button: host, port, device (from the server's device
  list), Connect / Track solar / Stop / Park, status line; settings in
  `QSettings` under `mount/*`.
- `sew --mount host[:port]` on the command line; `mount` subcommand in
  `sew_hardware`.
- Tests against a fake INDI server; optional manual test with
  `indi_simulator_telescope`.  `docs/MOUNT.md`, README, changelog.

## Step 2 — Manual nudge  *(done)*

Built as `mount.Nudger` (a thread per mount, holds that must be renewed, so a lost
release stops the mount within `HOLD_S` = 0.6 s; 1.0 s from the phone) and
`mount_ui.MountNudgePanel` (in the `Live View` and `Mount` windows).  Rates come
from the driver's `TELESCOPE_SLEW_RATE` with their labels.  Also, on request: the
`Simulated mount` check box (ticked in simulation mode), and the simulated mount
starts at the sun and moves (sky drift, nudges, pulses, park).

- N/S/E/W buttons in the `Live View` window, guiding while held (motion
  start/stop at guide rate) and a guide-rate selector.
- The same on the phone dashboard (`ACTION_MOUNT_*`, validated and queued like
  the live-view actions).

## Starting the INDI server  *(done)*

`indi_server.py`: the mounts of INDI's driver lists (drivers.xml and the third-party
lists next to it, in /usr/share/indi, /usr/local/share/indi, the KStars app on macOS,
$INDIPREFIX); `IndiServer` starts `indiserver -v -p <port> -u /tmp/indiserver-sew-<port>
<driver>` (output to a log), waits for the port, uses a server that already runs and
leaves it alone, stops its own on disconnect and at exit.  The model is chosen in the
`Mount` window (it cannot be detected: generic USB-serial chips, or Wi-Fi).  The mount
port can be a serial port, `host:port` (Wi-Fi: CONNECTION_MODE TCP + DEVICE_ADDRESS), or
empty (DEVICE_AUTO_SEARCH on).  Console: `mount drivers`, `mount start`, `mount sun [goto]`
(goto only for simulators).

Tested against INDI 1.9.9's `indi_simulator_telescope`: two differences from sew's
simulator found and fixed (TELESCOPE_TRACK_STATE and TELESCOPE_MOTION_* stay Busy while
tracking/moving; a second indiserver needs its own -u socket).  INDI's simulator starts at
the pole (point it at the sun first) and moves south for "north".

Found in the user's first stage-1 test: with INDI's simulator, whose Centering rate moves
the sun ~110 px/s in 250 ms steps, coarse moves of 0.1 s did nothing or a whole step, the
sun bounced and the centring gave up ("calibrate again").  Fixed: a fast move is only made
when it lasts at least 1 s (an axis under 0.25 s is left to the guide pulses); shorter
corrections are guide pulses, which the driver times.  The fake test mount can now move in
steps (tick_s) to cover this.

Open for the HAZ31 (alt-az): which driver, whether guide pulses work in alt-az mode, and
whether they move in RA/Dec (then the calibration must turn with the field rotation).

## Step 3 — Automatic centring from the DSLR live view  *(done, to be tested on a real mount)*

Done: `sun_finder.find_sun()` (numpy only, ~60 ms per 1000 px frame), checked on
663 frames of the 2026-08-12 eclipse (Canon EOS R, tests/data/sun, not in git; 21 of
them with their expected answers in tests/data/sun_frames):

- Otsu threshold on the brightest channel (a low, red sun has a dark limb in
  luminance), largest bright region, RANSAC circles on its edge where the image
  gets darker outward (the moon's limb gets brighter outward: without this, thin
  crescents gave circles half on each limb), sub-pixel limb on radial profiles in
  the full frame.  Thin crescents (1-2 px wide) are searched in the full frame.
- With the radius known (`radius_hint`, ±8 %), short arcs (≥ 60°) are fitted with the
  radius held.  Without it, at least 120° of limb is needed.
- Rejected: an edge wider than 8 % of the radius (the corona fades over 8-10 px, the
  limb drops in 1-3 px of 60), a short saturated arc (beads, diamond ring glare), a
  disk with an enclosed hole.
- Result with the radius known: found from the full disk to C2 - 17 s and from
  C3 + 20 s to sunset; nothing from C2 - 12 s to C3 + 12 s (the centring pauses from
  C2 - 15 s to C3 + 15 s anyway); no wrong fix seen.  Frame-to-frame scatter on a
  tracked mount: median 0.16 px, 90 % under 0.3 px (partial phases before C2).

Done: calibration (`centring.Calibrator`, `centring.Calibration`).  Guides E then W,
N then S, each until the sun moved ~8 px (pulses of at most 3 s, the length adapted
to the speed seen), and measures the sun in two frames after each move.  Gives a
2×2 matrix (dx, dy) per (N ms, E ms), so rotation and mirroring of the frame are
handled; `pulses_for(dx, dy)` inverts it.  Refuses when the sun is not found, does
not move, or the axes are less than 60° apart; reports Dec backlash.  Saved as JSON,
valid for one frame size (and camera).  About 90 s at a guide rate of 0.5× sidereal
with a sun of 60 px.  `sun_simulator.SimulatedSunCamera` draws the sun where the
(simulated) mount points, turned and mirrored as asked, for the tests.

Done: the centring loop (`centring.Centrer`).  A look every 30 s (2 s after a
correction); offsets up to 2 px are left alone; 70 % of the offset is corrected, at
most 3 s of guiding per axis; the pulses wait for `utils.quiet_for()` (no camera or
relay command running or due within the pulse + settling + 2 s; scheduling now keeps
each job's start and busy time in `utils.JOB_BUSY`).  Paused around totality (the
caller passes the C2 − 15 s … C3 + 15 s window).  Keeps a running radius from fixes on
a long arc.  Stops itself when three corrections in a row move the sun less than 30 %
of what the calibration says they should, or when the frame size changes.  Bench
console: `mount follow`.

Done: the GUI.  The `Live View` window hands its frames to `controller.live_frames`
(no extra USB traffic; cleared when it closes).  `Mount` window: **Calibrate** (on
a thread, with progress; the calibration is kept in the settings as
`mount/calibration`) and **Keep the sun centred** (`controller.start_centring()`,
with the quiet check on the scheduler and the totality pause of the live view).
The live view draws the sun found, the target and the state; the phone shows the
state.  In simulation mode, the virtual camera's live view shows the simulated sun
where the simulated mount points (`sun_simulator.simulated_live_view_jpeg`).

Then, on request: corrections are no longer capped at 3 s — as long as the gap
between the shots allows (the whole correction before C1), in pulses of at most 3 s,
cut to one pulse per axis only when the gap is short.  The calibration also
measures a fast slew rate (the driver's centering rate), and a sun more than 10 px
off is moved most of the way at that rate first.  First centring from 35 px: 14-20 s
instead of minutes.  The simulated mount guides at 2× sidereal; the simulated
camera shows the real 2026 eclipse (77 crops, 230 KB, img/eclipse, made by
scripts/make_eclipse_images.py) in the phase of the simulated time.

Ideas for later: pick the target by clicking in the live view; hold the
calibration per camera; a `mount_centre on/off` script command.

- Sun detection: threshold, edge pixels, circle fit with a radius constraint,
  rejecting the concave lunar edge (a crescent's centroid would drift).
  Unit tests on synthetic crescents for all phases.
- Calibration once per setup: known E/W and N/S pulses, measure the shift, store
  a 2×2 pixel→axis matrix (handles rotation and mirror flips).
- Control loop: at most one small, capped correction every 30–60 s, only when
  live view runs and is not in the totality pause (C2 − 15 s … C3 + 15 s), the
  USB lock is free, and no scheduled job fires or is busy within the next few
  seconds (busy windows from `command_timing.py` / `relay_duration_s`).  Gives
  up after repeated failures.
- Target marker in the live view; centring status on the phone dashboard.
