# Testing the mount control with real hardware

The mount code (`indi_client.py`, `mount.py`) is covered by tests against a simulated INDI server
that `sew` brings itself (`indi_simulator.py`).  Real drivers answer in their own way, and that is
what these tests are for.  Work through the stages in order: each one removes one unknown.

Note the result of every check (✅ / ❌ + what happened) in a copy of this file or in the issue (#75).

## What to collect when something goes wrong

- **The sew log:** `~/.SolarEclipseWorkbench/logs/sew-<time>Z.log`.  Every INDI message of the
  driver is logged as `INDI <device>: ...`, every change as `Sent to ...`, `... tracks at the ...
  rate`, and so on.
- **The INDI server output:** start the server with `-vvv` and save what it prints:
  `indiserver -vvv indi_eqmod_telescope 2>&1 | tee indiserver.log`
- **The properties of the driver:** `indi_getprop -h localhost` lists every property with its
  value.  Run it before and after the step that failed.  (`indi_getprop` and `indi_setprop` come
  with `indi-bin`.)
- For the bench console, `sew_hardware --debug` logs every XML element sent and received.

## What could differ from the simulator

These are the points where a real driver may behave differently.  Watch them in every stage.

| # | Risk | Where in the code |
|---|------|-------------------|
| R1 | Connecting takes longer than 15 s (slow serial handshake, Wi-Fi), or the driver needs `DEVICE_PORT` and a baud rate before it connects | `Mount.connect_driver` |
| R2 | The driver refuses `GEOGRAPHIC_COORD` or `TIME_UTC` (e.g. while tracking, or when the handset is the time source), or expects another time format | `Mount.send_site` |
| R3 | The driver has no `TRACK_SOLAR`, or names its modes differently | `Mount.track_solar` |
| R4 | The driver does not answer a change at all (no `set...Vector` back), so `sew` waits 5 s and reports a timeout although it worked | `IndiClient.change` |
| R5 | Unpark or park is refused, or reports `Busy` for a long time | `Mount.park`, `Mount.unpark` |
| R6 | `DRIVER_INFO.DRIVER_INTERFACE` is missing, so `Find mounts` does not see the mount | `find_mounts` |
| R7 | Under WSL the serial cable is not attached in time, or `/dev/ttyUSB0` is not accessible (no `dialout`) | `wsl_usb`, installer |
| R8 | Sexagesimal or unusual number formats in `EQUATORIAL_EOD_COORD` | `parse_number` |

## Stage 1 — Real INDI server, simulated telescope driver (no mount)

This checks the client against the real `indiserver` instead of `sew`'s own simulator.

Setup: `sudo apt install indi-bin`, then `indiserver -vvv indi_simulator_telescope`.

| Check | How | Expected |
|-------|-----|----------|
| 1.1 Find | `sew` → **Mount** → server `localhost` → **Find mounts** | `Telescope Simulator` in the list |
| 1.2 Connect | **Connect** | Status `Telescope Simulator on localhost:7624: not tracking`; "Sent to the mount: location …; time …" |
| 1.3 Location and time arrived | `indi_getprop "Telescope Simulator.GEOGRAPHIC_COORD.*" "Telescope Simulator.TIME_UTC.*"` | The location of the `Location` window (`LONG` 0–360, east positive) and the current UTC time |
| 1.4 Track | **Track sun** | Status `tracking (solar)`; `indi_getprop` shows `TELESCOPE_TRACK_MODE.TRACK_SOLAR=On` and `TELESCOPE_TRACK_STATE.TRACK_ON=On` |
| 1.5 Stop | **Stop tracking** | Status `not tracking` |
| 1.6 Park | **Park** → confirm | Status `parked` after the slew of the simulator |
| 1.7 Track from parked | **Track sun** | Unparks, then `tracking (solar)` |
| 1.8 Abort | **Park**, then **Abort** during the slew | The slew stops; no error |
| 1.9 Disconnect | **Disconnect** | `indi_getprop` still shows `CONNECTION.CONNECT=On` and `TRACK_ON=On` |
| 1.10 Reconnect | **Connect** again | Connects straight away (the driver is already connected) |
| 1.11 Server gone | Stop `indiserver` while connected | Status says the connection is lost; buttons disabled; no crash |
| 1.12 Location change | Connected, change the location in the `Location` window | The new location in `GEOGRAPHIC_COORD` |
| 1.N1 Rates | Connected, look at the speed list next to the nudge buttons (`Mount` window) | The slew rates of the driver with their names, slowest first |
| 1.N2 Nudge | Hold **▲ N** for 3 s at each speed | The position (Dec) changes while held and stops when released; faster at a faster speed |
| 1.N3 Lost release | Hold **E ▶**, and move the mouse off the button and release it outside the window; or close the window while holding | The mount stops within a second |
| 1.N4 Stop | Start a **Park** (in the `Mount` window), then click **Stop** next to the nudge buttons | The park stops; tracking is left as it was |
| 1.N5 Phone | Phone dashboard: hold the buttons of the `Mount` panel | As 1.N2; switch the phone's Wi-Fi off while holding: the mount stops within about a second |
| 1.13 Bench console | `sew_hardware --debug`, then `mount connect localhost`, `mount track`, `mount guide N 1000`, `mount status` | Same results; the XML is logged |

## Stage 2 — The real mount, indoors

Mount powered, no telescope or the telescope pointed away from any window.  Start the server with the
driver of the mount, e.g. `indiserver -vvv indi_eqmod_telescope`.

| Check | How | Expected |
|-------|-----|----------|
| 2.1 Port | Fill **Mount port** with the serial port (`ls /dev/ttyUSB* /dev/ttyACM*`) → **Connect** | Connects within 15 s (R1).  If not, note how long the driver takes in the server output |
| 2.2 Port saved | Disconnect, restart `indiserver`, connect with **Mount port** empty | Note whether the driver remembers the port (it does when its configuration was saved) |
| 2.3 Location and time | As 1.3, and on the handset or in the driver's own UI (e.g. KStars/Ekos) | Same location and time on the mount (R2).  Note any `INDI ...` message in the log |
| 2.4 Solar rate | **Track sun** | `tracking (solar)`, or the sidereal warning when the driver has no solar rate (R3).  Note which |
| 2.5 Motors | Listen/watch the RA axis after 2.4 | The RA motor runs at tracking speed |
| 2.6 Stop | **Stop tracking** | RA motor stops |
| 2.7 Response time | In the log, time between `mount_track` / button and `tracks at the … rate` | Under 1 s.  A 5 s wait followed by a timeout error means R4 |
| 2.8 Park / unpark | **Park**, wait, **Track sun** | Parks at the driver's park position; unparks and tracks again (R5) |
| 2.9 Abort | **Park**, then **Abort** after 1 s | The mount stops at once |
| 2.10 Find mounts | **Find mounts** with an empty mount name | The mount is listed (R6) |
| 2.11 Guide pulses | `sew_hardware`: `mount connect`, `mount guide N 2000`, `mount guide E 2000` | Short movements of the axes; no error |
| 2.N1 Nudge directions | At the slowest speed, hold each button for 2 s; watch the axes | N/S moves the Dec axis, E/W the RA axis, each both ways |
| 2.N2 Speeds | Hold **▲ N** for 2 s at each speed | Clearly faster at each step.  Note the speeds the driver offers |
| 2.N3 Stop latency | Hold at the fastest speed, release | The motor stops within half a second of the release (the laptop) |
| 2.N4 Lost release | As 1.N3 and 1.N5 with the real mount | The motor stops within a second |
| 2.12 Script | Simulation mode (`sew --sim`), a script with `mount_track` and `mount_park` a minute apart, mount connected | Both commands run at their time (log: `mount_track`, `mount_park`); `Mount: track the sun` in the job list |
| 2.13 Script without mount | The same script, mount not connected when `mount_track` fires | The job fails in the log; the run goes on |
| 2.14 Close sew | Close `sew` while tracking | The mount keeps tracking |

### Windows (WSL) only

| Check | How | Expected |
|-------|-----|----------|
| 2.W1 Share | Connect the mount cable, Start menu → `Share cameras with Solar Eclipse Workbench`, share it | Listed as shared |
| 2.W2 Auto-attach | Unplug and replug the cable, then **Connect** in `sew` (server `localhost`) | The cable is attached by `sew` (log: attach), the driver connects (R7) |
| 2.W3 Permissions | If 2.W2 fails with "permission denied" in the server output | `groups` in WSL must list `dialout` |

### Server on another computer (if you use one)

| Check | How | Expected |
|-------|-----|----------|
| 2.R1 | Server on e.g. a Raspberry Pi; in `sew` server `<host>` or `<host>:7624` | Same as 2.1–2.9 |
| 2.R2 | Pull the network cable / Wi-Fi off while connected | Connection lost shown; mount keeps tracking |

## Stage 3 — Outdoors, on the sun

**Solar filter on the telescope and the finder before pointing anywhere near the sun.**

| Check | How | Expected |
|-------|-----|----------|
| 3.1 Point | Polar-align as usual, point at the sun by hand, centre it in live view | — |
| 3.N1 Centre with nudges | In live view, centre the sun with the nudge buttons, on the laptop and on the phone | Note how each button moves the sun in the picture (rotation/mirror), and which speed is best for centring |
| 3.2 Track | **Track sun**; leave it for 30 min | Note how far the sun moves in the `Live View` window (crosshair on) after 10 and 30 min |
| 3.3 Sidereal comparison | If the driver has a solar rate: let it track at sidereal (e.g. with `indi_setprop`) for 30 min | The sun drifts more than in 3.2 (≈1.2′ in 30 min) — confirms the solar rate is really used |
| 3.4 Full dress rehearsal | Simulation mode with the real eclipse script, `mount_track` at the start and `mount_park` at the end, cameras connected | The mount commands do not delay any camera command (run report: no `late` or `dropped` caused around them) |

## After testing

- Fix what failed, add a test to `tests/test_mount.py` for it (the simulator can be told to refuse
  or ignore a property: `SimulatedIndiServer(refuse=..., silent=..., solar=False)`).
- Add the driver and mount that worked to the table in [Telescope mount](MOUNT.md).
