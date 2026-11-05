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

## Step 2 — Manual nudge

- N/S/E/W buttons in the `Live View` window, guiding while held (motion
  start/stop at guide rate) and a guide-rate selector.
- The same on the phone dashboard (`ACTION_MOUNT_*`, validated and queued like
  the live-view actions).

## Step 3 — Automatic centring from the DSLR live view

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
