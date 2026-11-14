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

This checks the client against the real `indiserver` and INDI's own telescope simulator, instead
of `sew`'s simulator.  Most of it has been run during development (INDI 1.9.9, Ubuntu):
connecting, the slew rates, location and time, solar tracking, nudges, guide pulses, park,
abort, calibration and centring.  It found two differences from `sew`'s own simulator, both
fixed: a real driver keeps tracking and moving "Busy" (`sew` waited for it to end), and a second
`indiserver` needs its own local socket.

Setup: `sudo apt install indi-bin`.

**Things to know about INDI's telescope simulator:**

- It starts pointed at the celestial pole (or at 0h, 0°).  There, guiding east-west moves the sun
  almost nothing (the movement shrinks with the cosine of the declination): the calibration takes
  minutes and the centring needs long corrections.  Point it at the sun first: in `sew_hardware`,
  `mount sun goto` (it refuses a real mount).
- "North" moves it south (guide pulses and nudges alike), as a German mount on the other side of
  the pier does.  The calibration finds that out ("mirrored"); the nudge buttons just move that
  way.

| Check | How | Expected |
|-------|-----|----------|
| 1.1 Start the server | `sew --sim` → **Mount** → untick **Simulated mount**, tick **Start the INDI server**, model **Telescope Simulator** → **Connect** | Connects within a second or two; "(INDI server started with indi_simulator_telescope)"; `pgrep -a indiserver` shows it |
| 1.2 Location and time arrived | `indi_getprop "Telescope Simulator.GEOGRAPHIC_COORD.*" "Telescope Simulator.TIME_UTC.*"` | The location of the `Location` window (`LONG` 0–360, east positive) and the current UTC time |
| 1.3 Point at the sun | In another terminal: `sew_hardware`, `mount connect localhost`, `mount sun goto`, `quit`.  Again each time the INDI server restarts: INDI's simulator starts at the pole | "Pointed at the sun, tracking at the solar rate"; the position in the `Mount` window changes |
| 1.4 Track | **Track sun** | Status `tracking (solar)` |
| 1.5 Stop | **Stop tracking** | Status `not tracking` |
| 1.6 Park | **Park** → confirm | Status `parked` after the slew of the simulator |
| 1.7 Track from parked | **Track sun** | Unparks, then `tracking (solar)` (point at the sun again with 1.3) |
| 1.8 Abort | **Park**, then **Abort** during the slew | The slew stops; no error |
| 1.9 Disconnect | **Disconnect** | The server is stopped (`pgrep -a indiserver` shows nothing) |
| 1.10 A server that runs already | `indiserver indi_simulator_telescope` in a terminal, then **Connect** with **Start the INDI server** ticked | "(the INDI server that already ran is used)"; **Disconnect** leaves it running |
| 1.11 Server gone | Stop `indiserver` (Ctrl-C in its terminal) while connected | Status says the connection is lost; buttons disabled; no crash |
| 1.12 Location change | Connected, change the location in the `Location` window | The new location in `GEOGRAPHIC_COORD` |
| 1.13 Driver not installed | Only when the list has a model marked "(driver not installed)": choose it → **Connect**.  With Ubuntu's `indi-bin` every model is installed, so there is none: skip this check | A message that the driver is not installed, and in which package it may be |
| 1.N1 Rates | Connected, look at the speed list next to the nudge buttons | Guide, Centering, Find, Max |
| 1.N2 Nudge | Hold **▲ N** for 3 s at each speed | The position changes while held (south, see above) and stops when released; faster at a faster speed |
| 1.N3 Lost release | Hold **E ▶**, move the mouse off the button and release it outside the window; or close the window while holding | The mount stops within a second |
| 1.N4 Stop | Start a **Park**, then click **Stop** next to the nudge buttons | The park stops |
| 1.N5 Phone | Phone dashboard, `Mount` panel: hold the buttons | As 1.N2; switch the phone's Wi-Fi off while holding: the mount stops within about a second |
| 1.S1 Calibrate and centre | After 1.3, open `Live View` on the virtual camera (it shows the sun where the mount points), **Calibrate**, then **Keep the sun centred**; nudge the sun away.  Then disconnect, connect `simulated` (sew's own simulated mount) and try **Keep the sun centred** again | Calibration in about 1.5 minutes ("… mirrored …; at the 2x rate about 110 px a second").  The sun comes back in three or four guide corrections, about a minute for 30 px: this simulator's Centering rate is so fast that only offsets of more than about 110 px are moved at it first.  Never "calibrate again".  With sew's simulated mount the calibration of INDI's simulator is not used: "The calibration was made with Telescope Simulator; the mount now is Telescope Simulator (simulated by sew).  Calibrate again." |
| 1.S2 Script | Load the example script `testMount.txt` (in the `example_scripts` folder of the package: `src/solareclipseworkbench/example_scripts/` in the source), **Simulator**: C1, 3 minutes; mount connected (after 1.3), `Live View` on the virtual camera, **Keep the sun centred** on | The mount commands run at their time (`Mount: track the sun`, `Mount: park` in the job list; status `tracking (solar)`, then `parked`, then tracking again).  The pictures and brackets are taken while tracking.  During the run of pictures every 2 s (C1 − 110 s … C1 − 92 s) the centring says "waiting for a gap … between the shots" and corrects after it.  After the park the sun is gone from the live view, and the centring says "the mount is parked: the centring waits until it tracks again", without warnings.  After the second `mount_track` it looks for the sun again: "the sun is not found in the live view" once (a warning in the run report), until you point the simulator at the sun again with `mount sun goto` |
| 1.C Bench console | `sew_hardware --debug`, `mount start indi_simulator_telescope`, `mount sun goto`, `mount guide N 1000`, `mount status` | Same results; every XML element sent is logged, and every update received, except that the position and the axes, which the driver sends several times a second, are logged once every 10 s while their state stays the same |

## Stage 2 — The real mount, indoors

Mount powered, no telescope or the telescope pointed away from any window.  Start the server with the
driver of the mount, e.g. `indiserver -vvv indi_eqmod_telescope`.

Tested on 2026-11-07 with the **iOptron HAZ31** and the **iOptron v3** driver (`indi_ioptronv3_telescope`,
INDI 1.9.9), see also [Your mount: iOptron HAZ31](#your-mount-ioptron-haz31) and
[Results so far](#results-so-far).

| Check | How | Expected | Result |
|-------|-----|----------|--------|
| 2.1 Port | Fill **Mount port** with the serial port (`ls /dev/ttyUSB* /dev/ttyACM*`) → **Connect** | Connects within 15 s (R1).  If not, note how long the driver takes in the server output | ✅ |
| 2.2 Port saved | Disconnect, restart `indiserver`, connect with **Mount port** empty | Note whether the driver remembers the port (it does when its configuration was saved) | ✅ Remembered |
| 2.3 Location and time | As 1.3, and on the handset or in the driver's own UI (e.g. KStars/Ekos) | Same location and time on the mount (R2).  Note any `INDI ...` message in the log | ✅ |
| 2.4 Solar rate | **Track sun** | `tracking (solar)`, or the sidereal warning when the driver has no solar rate (R3).  Note which | ✅ Solar |
| 2.5 Motors | Listen/watch the RA axis after 2.4 | The RA motor runs at tracking speed | ✅ |
| 2.6 Stop | **Stop tracking** | RA motor stops | ✅ |
| 2.7 Response time | In the log, time between `mount_track` / button and `tracks at the … rate` | Under 1 s.  A 5 s wait followed by a timeout error means R4 | ✅ |
| 2.8 Park / unpark | **Park**, wait, **Track sun** | Parks at the driver's park position; unparks and tracks again (R5) | ✅ |
| 2.9 Abort | **Park**, then **Abort** after 1 s | The mount stops at once | ✅ |
| 2.10 Find mounts | Untick **Start the INDI server** (the button is greyed out while it is ticked), start the server yourself (`indiserver indi_ioptronv3_telescope`), empty **Mount**, then **Find mounts** | The mount is listed (R6) | ⏳ Button not found: it was greyed out because **Start the INDI server** was ticked.  To redo |
| 2.11 Guide pulses | `sew_hardware`: `mount connect`, `mount guide N 2000`, `mount guide E 2000` | No error.  The movement is too small to see by eye (2 s at 0.5× sidereal is about 15″): check it in the live view, or with the calibration (H.7) | ✅ No error ("Guide pulse N 2000 ms sent"); no movement seen (as expected, issue 3) |
| 2.N1 Nudge directions | At the slowest speed, hold each button for 2 s; watch the axes | N/S moves the Dec axis, E/W the RA axis, each both ways | ✅ N goes down, S up, E left, W right (issue 4) |
| 2.N2 Speeds | Hold **▲ N** for 2 s at each speed | Clearly faster at each step.  Note the speeds the driver offers | ✅ 1x, 2x, 8x, 16x, 64x, 128x, 256x, 512x, Max |
| 2.N3 Stop latency | Hold at the fastest speed, release | The motor stops within half a second of the release (the laptop) | ✅ |
| 2.N4 Lost release | As 1.N3 and 1.N5 with the real mount | The motor stops within a second | ✅ |
| 2.12 Script | Simulation mode (`sew --sim`), a script with `mount_track` and `mount_park` a minute apart, mount connected | Both commands run at their time (log: `mount_track`, `mount_park`); `Mount: track the sun` in the job list | ✅ |
| 2.13 Script without mount | The same script, mount not connected when `mount_track` fires | The job fails in the log; the run goes on | ✅ |
| 2.14 Close sew | Close `sew` while tracking | The mount keeps tracking | ✅ |

### Windows (WSL) only

| Check | How | Expected |
|-------|-----|----------|
| 2.W1 Share | Connect the mount cable, Start menu → `Share cameras with Solar Eclipse Workbench`, share it | Listed as shared |
| 2.W2 Auto-attach | Unplug and replug the cable, then **Connect** in `sew` (server `localhost`) | The cable is attached by `sew` (log: attach), the driver connects (R7) |
| 2.W3 Permissions | If 2.W2 fails with "permission denied" in the server output | `groups` in WSL must list `dialout` |

## Your mount: iOptron HAZ31

The HAZ31 is an **alt-azimuth** mount, which raises questions an equatorial mount does not.
iOptron says the HAZ mounts work with a third-party INDI driver on Linux and macOS.  INDI 1.9.9
(Ubuntu's `indi-bin`) has no HAZ entry in its list: try **iOptron v3**
(`indi_ioptronv3_telescope`) first; the newer INDI of the PPA (`ppa:mutlaqja/ppa`, package
`indi-full`) may list the HAZ mounts by name (`sew_hardware`, `mount drivers ioptron`).

| Check | How | Expected / to note | Result |
|-------|-----|--------------------|--------|
| H.1 Driver | `mount drivers ioptron`; then `mount start indi_ioptronv3_telescope /dev/ttyUSB0` (USB on the 8409 hand controller; `ls /dev/ttyUSB* /dev/ttyACM*`) | Connects.  If not: note the last lines of the server output (shown with the error, and in `~/.SolarEclipseWorkbench/logs/indiserver-*.log`) | ✅ Connects with iOptron v3 |
| H.2 Wi-Fi | The mount's Wi-Fi: **Mount port** `address:port` from the HAZ manual | Connects without a cable | ✅ |
| H.3 Location and time | As 1.2, and on the hand controller | Same location and time on the mount | ✅ |
| H.4 Solar rate | **Track sun** | `tracking (solar)`, or the sidereal warning.  Note which | ✅ |
| H.4b Track sun once | **Stop tracking**, then **Track sun** once; repeat three times, and once after a **Park** | Tracks after one click each time (it may take up to a few seconds).  The log shows "switched tracking off again … (try 1 of 4)" when the driver dropped it.  Note how many tries it took | ✅ Works from the first click (the log shows three tries, note 8) |
| H.5 Directions | At the slowest speed, hold each nudge button 2 s; watch the axes | **Which axis does N/S move, and which E/W: altitude/azimuth, or RA/Dec?**  Note it, and whether "N" goes up or down | N goes down, S up, E left, W right (issue 4) |
| H.5b Reverse | Tick **Reverse N/S** in the `Mount` window; hold **▲ N**, then **▼ S**.  Disconnect, connect again, and on the phone | N goes up now, S down; still ticked after connecting again, and the phone's buttons move the same way | ✅ |
| H.6 Guide pulses | `sew_hardware`: `mount guide N 2000`, `mount guide E 2000` | Do they move the mount at all in alt-az mode?  Which axis?  (Without guide pulses there is no centring.)  Too small to see by eye: check in the live view | ❌ 2026-11-14, alt-az mode: accepted by the driver ("Ok"), but the mount does not move: 90 s of guiding E or N did not change its RA/Dec (issue 5) |
| H.7 Calibrate | On the sun (filter!), roughly centred, **Calibrate** | Note the direction, mirrored or not, the px/s of guiding and of the fast rate | ❌ 2026-11-14 (Canon EOS 80D on a PhotoLine 80): failed, see issue 5 |
| H.7b Calibrate with slews | **Track sun**, wait until the status says tracking, sun roughly centred, **Calibrate** | After about 30 s of guiding E: "the mount ignores guide pulses: calibrating again with slews at the 1x rate instead"; then "slewing W at the 1x rate brought the sun back only …: trying the 2x rate", and a calibration "slewing at the 2x rate east moves the sun … (… px south, … px west)", west about a third of east.  **Track sun** and **Stop tracking** are greyed out meanwhile.  Then **Keep the sun centred**: the corrections say "slewing at the 1x rate".  If the sun is "not found", send the `no-sun-*.png` from the log folder | ✅ 2026-11-14 (log `sew-20261114-130913Z.log`): pulses found ignored, 1x and 2x did not move the sun west, calibrated at 3x (fast rate 4x).  The centring brought the sun in from 101 px and held it within 3-7 px for 18 min (looks every 30 s, now 15 s).  Behind a tree the sun was "not found" (soft edge) and the mount was left alone, as it should |
| H.8 Field rotation | **Keep the sun centred** for at least an hour (C.F1); then **Calibrate** again | **Compare the direction with H.7.**  If it turned by several degrees, the guide pulses move in RA/Dec while the sky turns in the frame: tell me, and the calibration will be turned with the sky (from the location, the time and the sun's position).  If it did not turn, alt-az corrections need nothing more | ⏳ |
| H.9 After 1-2 hours | Leave the centring on | "centred" most of the time; or after a while "… did not move the sun the way they should: calibrate again" (field rotation, see H.8) | ⏳ 18 min on 2026-11-14 (H.7b) without problems; 1-2 hours still to do |

### Results so far

From the tests above and the sew log of 2026-11-07 (`sew-20261107-143421Z.log`):

1. **Track sun needs three clicks** (2.8, H.4).  Each click sends the solar rate and `TRACK_ON`.  The
   driver answers `TRACK_ON` (Busy), then 60 ms later falls back to `TRACK_OFF` (Idle).  The third
   time it stays on, with "Slew complete, tracking..." from the driver.  That happened twice in a row
   (14:41:01 → 14:41:08 and 14:41:18 → 14:41:24).  sew logged "tracks at the solar rate" after every
   click, so it reported success while the mount did not track.  Without any command the driver
   also switches `TRACK_STATE` on and off every few seconds, which suggests the iOptron v3 driver
   misreads the HAZ31's status.  **Fixed:** **Track sun** now checks for 1.5 s that tracking stays
   on, switches it on again (up to four times), and reports an error when it still does not hold.
   To retest: H.4b.  Also try the newer INDI of the PPA for a driver made for the HAZ mounts.
2. **Find mounts** (2.10): not a bug.  The button only works with a server you start yourself; with
   **Start the INDI server** sew knows the mount already.  The check is now explicit about it.
3. **Guide pulses** (2.11, H.6): the driver accepted them (`TIMED_GUIDE_NS` Ok).  At the guide rate
   of 0.5× sidereal, 2 s is about 15″ and 5 s about 38″: too little to see on the mount.  The
   calibration (H.7) shows whether they move the sun.
4. **N moves down** (2.N1, H.5): E/W (left/right) is the azimuth and is the right way round for a
   mount facing south; N/S is the altitude, the wrong way round.  For the centring this does not
   matter (the calibration measures it).  **Fixed:** **Reverse N/S** and **Reverse E/W** in the
   `Mount` window swap the nudge buttons, kept for each mount.  To retest: H.5b.
5. **Calibration fails** (H.6, H.7; log `sew-20261114-114028Z.log`, outdoors, alt-az mode, Wi-Fi).
   Three things went wrong:
   - The HAZ31 in alt-az mode **ignores guide pulses**.  Every `TIMED_GUIDE` was answered "Ok",
     but during 90 s of guiding E and then 90 s N the mount's RA and Dec stayed within a few
     arcseconds (0.5× sidereal predicts 675″).  What the calibration measured (8 px in 90 s) was
     the sky drifting: guiding W as long moved the sun on the same way ("came back -72%").
     Slews (`TELESCOPE_MOTION`, the N/S/E/W buttons) do move it.  **Fixed:** the calibration
     checks the mount's coordinates after 20 s of guiding, and a return leg that moves the sun on
     instead of back.  When the pulses are ignored it calibrates again with timed slews at the
     slowest slew rate, and the centring then corrects with those slews.
   - **Tracking was off** during two of the runs (switched off from the `Mount` window at 11:57:10,
     on again at 12:01:03), so the sun drifted out of the frame at the sidereal rate.  **Fixed:**
     the calibration refuses a mount that does not track (tracking that is back within 5 s counts,
     for this driver's flicker), and **Track sun**, **Stop tracking** and **Park** are greyed out
     while it calibrates.
   - After the first `take_picture` of a simulation the sun finder found "nothing above the noise"
     in the live view, although the sun was still visible there.  The mount did not move (its
     coordinates stayed the same).  Not explained yet.  **Changed:** the log now gives the
     brightness of the frame with that message, and the first frame in which the calibration or
     the centring does not find the sun is saved as `no-sun-*.png` next to the log file.
   To retest: H.7b.
6. **Centring with slews does not get closer than about 8 px** (2026-11-14 13:46, log
   `sew-20261114-123919Z.log`).  The calibration fell back to slews at 1x and the coarse moves at
   2x brought the sun from 118 px to 8 px, but then every correction W at 1x did nothing, and the
   centring stopped after three ("did not move the sun the way they should").  The mount's RA
   shows why: at 1x it slews E (2× sidereal: 3.1 px/s) but not W (the RA stays the same; the
   calibration's own return leg came back -23 %).  At 2x it slews 3× sidereal E and 1× W.  The
   HAZ31 in alt-az mode seems to turn its motor at the slew rate against the ground, with the sky
   adding or taking 1× sidereal.  **Fixed:** W and S are measured on their own, corrections use
   the speed of the direction they move in, and a rate that hardly moves one way is skipped for
   the next one up (2x for the HAZ31; the fast rate is then 3x).  To retest: H.7b.

## Your mount: SkyWatcher AZ-GTi

The AZ-GTi is also an **alt-azimuth** mount (unless its firmware is switched to EQ mode), so the
questions of the HAZ31 apply too.  What is known before testing, from INDI 1.9.9 on this computer:

- **Driver**: `indi_skywatcherAltAzMount`.  In the **Mount model** list: *SkyWatcher AZ-GTi Alt-Az
  WiFi* and *SkyWatcher AZ-GTi Alt-Az Wired* (the same driver).  INDI calls the mount
  `Skywatcher Alt-Az`.  It has a solar tracking rate and takes guide pulses.  ✅ (2026-11-11)
- **Wi-Fi**: the driver talks to the mount over **UDP at 192.168.4.1, port 11880**: the address of
  the mount's own Wi-Fi network (`SynScan_xxxx`).  Join that network with the computer (it then has
  no internet), or put the mount on your own Wi-Fi with the SynScan app (station mode) and use the
  address your router gives it.  sew leaves the driver's UDP setting alone. ✅
- **Close the SynScan app** (phone, tablet) before connecting: two programs controlling one mount
  get in each other's way. ✅
- **No alignment**: the alignment made in the SynScan app is not used by the INDI driver, and sew
  never aligns or slews the mount.  The driver works out where it points from where it started
  (the AZ-GTi's home position: level, pointing north at the horizon).  For tracking in alt-az,
  that matters: an alt-az mount tracks by turning both axes at rates that depend on where it points.
- **The driver tracks, not the mount**: the driver keeps adjusting the rates of both axes.  When
  the INDI server stops (a **Disconnect** in sew stops the server that sew started), the mount
  keeps its last rates, which are only right for a while.
- **EQ mode** (on a wedge, firmware set to EQ): use the **EQMod** driver (`indi_eqmod_telescope`),
  which is not in Ubuntu's `indi-bin`: install `indi-eqmod` from the INDI PPA.  Test alt-az first.

Start in the home position: level, the telescope horizontal and pointing north, as for the
SynScan app.  Indoors, without the sun, for A.1–A.7 and A.11; outdoors, **with the solar filter on
before the telescope gets near the sun**, for the rest.

| Check | How | Expected / to note | Result |
|-------|-----|--------------------|--------|
| A.1 Connect over Wi-Fi | Computer on the `SynScan_xxxx` network.  `Mount` window: tick **Start the INDI server**, **Mount model** *SkyWatcher AZ-GTi Alt-Az WiFi*, **Mount port** `192.168.4.1:11880` → **Connect** | `Skywatcher Alt-Az … not tracking`.  If not: the last lines of the server output (with the error, and in `~/.SolarEclipseWorkbench/logs/indiserver-*.log`) | ✅ |
| A.1b Port of each model | Connect the HAZ31 (iOptron v3, its Wi-Fi address), disconnect; choose *SkyWatcher AZ-GTi Alt-Az WiFi* | **Mount port** shows `192.168.4.1:11880` (the AZ-GTi's), and the HAZ31's address again when choosing iOptron v3 | ⏳ |
| A.2 Position | Read the position in the `Mount` window right after connecting, in the home position | **Note RA/Dec.**  Pointing north at the horizon, the declination should be about 90° minus your latitude (about 39° at a latitude of 51°) | ✅ |
| A.3 Location and time | `indi_getprop "Skywatcher Alt-Az.GEOGRAPHIC_COORD.*"` and `"Skywatcher Alt-Az.TIME_UTC.*"` | Your location and the time now | ✅ `LAT`=35.0201, `LONG`=11.0040, `ELEV`=0; `UTC`=2026-11-11T11:06:40, `OFFSET`=1.  The location is the one in the `Location` window (in Tunisia), not where the mount stood: see note 6 |
| A.3b Location warning | Set the `Location` window to the eclipse site, connect a mount that has your location (the HAZ31 from its GPS) | A warning with both locations and the distance.  Connecting again: no warning (it has the location now) | ⏳ |
| A.4 Solar rate | **Track sun** | `tracking (solar)`, and both motors turn slowly.  Note it if it says sidereal | ✅ `tracking (solar)` |
| A.5 Directions | **Stop tracking**.  At the slowest speed, hold each nudge button 2 s; watch the axes | **Which axis does N/S move, and which E/W: altitude/azimuth, or RA/Dec (both axes at once)?**  Note it, and whether "N" goes up or down | ✅ N goes up.  Only one axis moves (the altitude): no **Reverse N/S** needed |
| A.6 Speeds | Hold **▲ N** for 2 s at each speed | Note the speeds the driver offers, and whether each is faster | ✅ |
| A.7 Guide pulses | `sew_hardware`, `mount connect localhost`, `mount track`, `mount guide N 2000`, `mount guide E 2000` | Do they move the mount?  Which axis?  (Without guide pulses there is no centring.) | ⏳ No errors; whether they move the mount: outdoors, with the camera (A.9) |
| A.8 Tracking alone | Outdoors: point at the sun with the nudge buttons (filter!), **Track sun**, centring off.  Watch the live view for 10 minutes | **Note how far the sun drifts, and which way.**  A few pixels a minute is the mount; the sun leaving the frame within minutes means the driver does not know where it points (A.2): tell me | ⏳ |
| A.9 Calibrate | On the sun, roughly centred, **Calibrate** | Note the direction, mirrored or not, the px/s of guiding and of the fast rate.  If it says "the mount points at the celestial pole" while it is on the sun: the driver's position is wrong (A.2): tell me | ⏳ |
| A.10 Field rotation | **Keep the sun centred** for at least an hour; then **Calibrate** again | As H.8: **compare the direction with A.9** | ⏳ |
| A.11 Park | Indoors: **Park**, then **Track sun** | Note where it parks (the home position?), and that it unparks and tracks again | ⚠️ Parks at the starting (home) position, unparks and tracks again.  But a first **Park**, while `sew_hardware` (A.7) had the mount tracking, blocked the driver for a minute (note 5) |
| A.11b Park while tracking | **Track sun**, then **Park** at once | Parks within a few seconds ("stopped tracking, to park" in the log), no "Motor not stopped"; the buttons keep working | ⏳ |
| A.12 Wi-Fi lost | While tracking on the sun: switch off the computer's Wi-Fi for 2 minutes, then on again | sew stays connected to the INDI server (it runs on this computer); it is the driver that loses the mount.  **Note what the `Mount` window and the log say** (an `INDI …` error, a status that no longer changes), whether the driver connects again by itself when the Wi-Fi is back, **whether the mount kept tracking**, and how far the sun drifted | ⏳ |
| A.13 Disconnect | While tracking on the sun: **Disconnect** (it stops the INDI server sew started), wait 10 minutes | **Note how far the sun drifted** compared with A.8.  If it drifts away quickly, sew should not stop the server of this driver while the mount tracks: tell me | ⏳ |
| A.W Wired (optional) | USB cable in the mount's hand-controller port (`ls /dev/ttyUSB*`), **Mount model** *SkyWatcher AZ-GTi Alt-Az Wired*, **Mount port** `/dev/ttyUSB0` → **Connect** | Connects.  If not: the driver starts at 9600 baud; try 115200 with `indi_setprop "Skywatcher Alt-Az.DEVICE_BAUD_RATE.115200=On"` before connecting, and note which works | — No hand controller to test with |

### Results so far (AZ-GTi and Wi-Fi)

From the tests above and the sew log of 2026-11-11 (`sew-20261111-105822Z.log`):

5. **Park while tracking blocks the AZ-GTi driver** (A.11).  `sew_hardware` switched tracking on
   at 11:11:02 (A.7).  The **Park** at 11:12:27 got "Mount error: Motor not stopped" from the
   driver, which then sent nothing for a minute and answered nothing: two **Stop tracking** and the
   nudges timed out.  At 11:13:28 it answered the park, too late.  After **Disconnect** /
   **Connect** everything worked, and a **Park** without tracking (11:14:07) parked at once.  Not
   caused by the two programs being connected: the driver cannot park while its motors run.
   **Fixed:** **Park** stops tracking first and waits until the axes stand still.  To retest: A.11b.
6. **The location sent is the one of the `Location` window** (A.3).  It was 35.02° N, 11.00° E (in
   Tunisia), and sew sent it to both mounts.  It replaced the HAZ31's own location (50°50′ N,
   4°52′ E, from its GPS).  An alt-azimuth mount turns both axes at rates computed from the
   location, so outdoors (A.8–A.10, H.7–H.9) **set the `Location` window to where the mount
   stands**, or the sun drifts away.  **Fixed:** connecting warns when the location sent is more
   than 50 km from the one the mount had.  To retest: A.3b.
7. **Mount port of the previous mount** (A.1).  The first two connects of the AZ-GTi used the
   HAZ31's Wi-Fi address (`10.10.100.254:8899`, still in **Mount port**) and timed out after 15 s.
   **Fixed:** the **Mount port** is kept for each mount model.  To retest: A.1b.
8. **iOptron v3 on Wi-Fi** (H.4b): one click of **Track sun** was enough; the log shows that
   sew needed three tries (10:59:09 → 10:59:16), as the HAZ31 did before the fix.  When the HAZ31's
   Wi-Fi was gone (11:02), the driver logged "Read Command Error: Timeout error" every 10 s while the
   `Mount` window still showed the last state: see A.12.

## Calibration (step 3) — before the GUI has it

The calibration measures how guide pulses move the sun in the live view.  Until the
`Mount` window has a button for it, test it in the bench console `sew_hardware`.

**Simulated, anywhere** (about 1.5 minutes):

```
sew_hardware --simulate
sew> mount connect
sew> mount track
sew> mount calibrate        a simulated camera, turned 25°, with the sun a few pixels off-centre
sew> mount centre           guides the sun to the middle: "Now at … +0.0, +0.0 px from the middle"
sew> mount guide E 15000    push it about 7 px off
sew> mount follow 5         a look every 5 s: "correcting … px off: guiding …" until "centred"; Ctrl-C stops
```

**Real mount and camera** — needs the sun (or see C.0), so outdoors, filter on:

| Check | How | Expected |
|-------|-----|----------|
| C.0 Indoors instead | Point at a round, evenly lit target far away (a frosted lamp globe, a white disk on a dark wall at 50+ m) so it is a disk of 50-100 px in live view | The calibration also works on that; the guide pulses move it |
| C.1 Setup | INDI server with the mount's driver; camera on USB, in a mode with live view; the sun roughly centred with the nudge buttons | — |
| C.2 Calibrate | `sew_hardware`, `mount connect localhost`, `mount track`, `mount calibrate` (or `mount calibrate EOS` to pick the camera) | Progress lines; done after ~1.5 min with the direction, mirrored or not, and the px per second of guiding.  Note them |
| C.3 Plausible | Compare with the setup | Mirrored only with a diagonal or mirror in the path.  The px/s about guide rate × 15″/s ÷ image scale (″/px) |
| C.4 Centre | Nudge the sun 5-10 px off the middle, then `mount centre` | "Now at … px from the middle" within about 1 px.  Run it again: "Already in the middle" |
| C.5 Turn the camera | Turn the camera 90° on the telescope, `mount calibrate` again | The direction changes by about 90° |
| C.6 Backlash | Read the progress lines of N/S | "came back …% of the way": below 70 % is reported as backlash.  Note the value |
| C.F1 Follow | `mount follow 10`; leave it for 10 minutes | "centred" most of the time, a correction now and then (polar alignment, periodic error).  Note how often it corrects and by how much |
| C.F2 Push off | During C.F1, nudge the sun 20-40 px off with the nudge buttons (or before starting) | It comes back in one or two corrections: a move at the fast rate, then guiding; then stays within 2 px.  Note whether the fast move overshoots |
| C.F2b Fast rate | Read the calibration line | "at the … rate … px a second": the driver's centering rate.  Without it ("guiding only"), large offsets come back slowly |
| C.F3 Wrong calibration | Calibrate, turn the camera 90°, `mount follow 10` | After three corrections: "… did not move the sun the way they should: calibrate again", and it stops |
| C.7 Problems | Cover the lens: `mount calibrate`.  Park the mount: `mount calibrate` | "the sun is not found …" / "the sun did not move …" (the second after up to 1.5 min of trying) |

### In the GUI

**Simulated** (`sew --sim`, with the virtual camera):

| Check | How | Expected |
|-------|-----|----------|
| G.1 Sun in live view | `Mount` → **Simulated mount** → **Connect**; open `Live View` on the virtual camera | A sun, a little off-centre; it moves with the nudge buttons |
| G.2 Calibrate | **Calibrate** → Yes | Progress in the `Mount` window; after ~40 s "Calibrated … towards 20° …, not mirrored …; at the 2x rate … px a second" |
| G.3 Centre | Tick **Keep the sun centred** | Live view: the target cross and "Centring: …"; the sun comes to the middle in one or two corrections (a fast move, then guiding), well within a minute |
| G.3b Phases | Run a simulation from e.g. C2 − 15 min | The live view shows the crescents of the 2026 eclipse thinning as the simulated time goes on, the corona in totality, the crescents after C3; the centring keeps the crescent on the target |
| G.4 Drift | Nudge the sun away with the buttons | It is brought back |
| G.5 Script | Load a script and run it in simulation | The centring says "waiting for a gap" before shots, and "paused around totality" from C2 − 15 s to C3 + 15 s |
| G.6 Phone | Phone dashboard, `Mount` panel | "Centring: …" after the position |
| G.7 Restart | Close and start `sew` again | The calibration is still there; **Keep the sun centred** works without calibrating again |

**Real mount and camera**: as C.1–C.F3 above, but with **Calibrate** and **Keep the sun centred**
in the `Mount` window and the `Live View` window open on the camera.  Also: **Calibrate** with the
live view closed says to open it; turning the camera to portrait (or changing the preview size)
makes **Keep the sun centred** ask for a new calibration.

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
