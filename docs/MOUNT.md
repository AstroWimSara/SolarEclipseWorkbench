# Telescope mount

Solar Eclipse Workbench can control the telescope mount, so it tracks the sun at the solar rate
during the run and can be parked at the end.  The mount is reached through
[INDI](https://indilib.org): an `indiserver` runs the driver of the mount, and Solar Eclipse
Workbench connects to that server over the network (on the same computer, that is `localhost`).

**The mount is never sent to a position.**  There is no GOTO: point the mount at the sun by hand,
with the solar filter on, and let Solar Eclipse Workbench track, stop and park it.

Parking does move the mount.  Before you use **Park** or `mount_park`, make sure the cables are free
and that the telescope will not sweep past the sun without a filter.

## Start the INDI server

The INDI server needs the driver of your mount.  Some common ones:

| Mount                                         | Driver                     |
|-----------------------------------------------|----------------------------|
| Sky-Watcher EQ mounts (EQMOD cable, or USB)   | `indi_eqmod_telescope`     |
| Sky-Watcher with a SynScan handset / Wi-Fi    | `indi_synscan_telescope`   |
| Celestron                                     | `indi_celestron_gps`       |
| iOptron                                       | `indi_ioptronv3_telescope` |
| LX200-compatible (Meade, 10Micron, Avalon, …) | `indi_lx200generic` and others |
| No mount, to try things                       | `indi_simulator_telescope` |

`indiserver -v <driver>` starts the server and prints what the driver does.  Leave it running in
its own terminal.

### Linux (and WSL on Windows)

On Ubuntu:

```
sudo apt install indi-bin
indiserver -v indi_eqmod_telescope
```

The drivers of some mounts come in separate packages; the INDI PPA (`ppa:mutlaqja/ppa`) has the
newest INDI and all third-party drivers (`indi-full`).  Your user must be in the `dialout` group to
open a serial port (the installer script adds you).

### Windows

Solar Eclipse Workbench runs in WSL on Windows, and so does the INDI server: install it in the
Ubuntu of WSL as above.

Most mounts connect with a USB serial cable.  Like a camera, the cable belongs to Windows until it is
shared with WSL: connect the mount, and use `Share cameras with Solar Eclipse Workbench` from the
Start menu (or `usbipd bind --busid <busid>` in an administrator PowerShell).  This only has to be
done once.  After that, Solar Eclipse Workbench attaches the cable to WSL by itself when it connects
to an INDI server on `localhost`.  The cable then shows up in WSL as `/dev/ttyUSB0` or
`/dev/ttyACM0`.

If the INDI server started before the cable was attached, connecting the mount still works: the
driver only opens the port when it connects.

### macOS

The INDI server is part of [KStars](https://kstars.kde.org) for macOS.  It is often simpler to run
it on another computer, see below.

### On another computer

The INDI server can run on any computer the laptop can reach over the network, such as a Raspberry
Pi at the mount (StellarMate and Astroberry come with INDI).  Enter its address in the **Mount**
window, e.g. `astroberry.local` or `192.168.1.20:7624`.  The mount's cable then goes into that
computer, not into the laptop, so it needs no sharing with WSL at all.  A mount with Wi-Fi or
Ethernet needs no cable either.

## Let Solar Eclipse Workbench start the INDI server

Instead of starting `indiserver` yourself, tick **Start the INDI server, for this mount** in the
`Mount` window and choose the model of the mount in **Mount model** (type part of the name to
find it).  The list is read from the driver lists of INDI on this computer; a model whose driver
is not installed is marked so.  On **Connect**, `indiserver` is started with the driver of that
model, on this computer (in WSL on Windows), and stopped again on **Disconnect** and when Solar
Eclipse Workbench closes (also when it ends on an error).  The mount keeps tracking: its own
controller does that.  An INDI server that already runs is used and left alone.

The model has to be chosen because it cannot be found out: most mounts are connected through a
USB-serial chip that other devices have as well, and a mount on Wi-Fi is not on USB at all.  It
is remembered for the next start.

**Mount port** tells the driver how to reach the mount:

- empty: the driver searches the serial ports itself (this can take half a minute).  For a mount
  model that INDI lists as Wi-Fi (e.g. *SkyWatcher AZ-GTi Alt-Az WiFi*), the driver is put in
  network mode with its own address instead (`192.168.4.1:11880` for a SkyWatcher),
- a serial port, e.g. `/dev/ttyUSB0`,
- the address of a mount on Wi-Fi, `host:port`, e.g. `192.168.4.1:11880` (SkyWatcher on its own
  Wi-Fi network) or `10.10.100.254:8899` (iOptron); see the manual of the mount.  This is needed
  for a Wi-Fi mount whose model INDI does not list as Wi-Fi, such as the iOptron mounts.

sew starts the driver under its own name (e.g. `Skywatcher Alt-Az`), not under the name of the
model as KStars/Ekos does, so the settings saved in Ekos are not used: give the address here.

The output of the server goes to `~/.SolarEclipseWorkbench/logs/indiserver-<time>Z.log`; when
the mount does not connect, the last lines are shown with the error.

## Connect the mount

1. Click **Mount** in the toolbar.  To try everything without a mount, tick **Simulated mount** and
   click **Connect**: see [Simulated mount](#simulated-mount).
2. Enter the address of the INDI server: `localhost` when it runs on this computer (or in WSL),
   otherwise `host` or `host:port`.  The port is 7624 unless you started the server with another one.
3. Click **Find mounts**, and choose the mount when the server has more than one.
4. **Mount port** is the serial port of the mount on the computer of the INDI server
   (e.g. `/dev/ttyUSB0`).  Leave it empty when the driver already has it saved.
5. Click **Connect**.

On connecting, the observing location and the time are sent to the mount.  The time is the computer
clock, corrected with the USB GPS when a GPS was used in the `Location` window.  When the location
is changed later, it is sent again.

The location sent is the one of the `Location` window, which may be the eclipse site rather than
where the mount stands now.  An alt-azimuth mount (an AZ-GTi, a HAZ mount) computes its tracking from
it, so with a wrong location the sun drifts away.  When the mount had a location more than 50 km
from the one sent (from its GPS, its hand controller or an earlier session), a warning says so on
connecting: set the `Location` window to where the mount stands.

**Track sun** unparks the mount when it is parked, and lets it track at the solar rate.  Not every
driver has a solar rate; the mount then tracks at the sidereal rate, and the sun drifts about 2.5′
an hour across the field of view.  Some drivers answer that the mount tracks and switch tracking
off again a moment later, when the mount did not take the command (the iOptron v3 driver with a
HAZ31 does it twice).  **Track sun** therefore checks that tracking stays on, switches it on again
up to four times, and says so when it still does not hold.  **Stop tracking** stops it, **Park** parks it (after a
confirmation) and **Abort** stops every motion at once.  A tracking mount stops tracking before it
parks, and the park waits until the motors stand still (up to 10 s): the AZ-GTi driver refuses to
park while they run, and then does not answer for a minute.

**Disconnect** and closing Solar Eclipse Workbench only close the connection to the INDI server: the
driver stays connected and the mount keeps tracking.

The window saves the address, the mount and the port for the next start.  The **Mount port** is
kept for each mount model: choosing another model shows the port that model was last connected with.

## Nudge the mount

While a mount is connected, the `Mount` window and the `Live View` window have a row of nudge
buttons: **◀ W**, **▲ N**, **▼ S** and **E ▶** move the mount for as long as the button is held,
at the speed chosen next to them (the slew rates of the driver, e.g. Guide, Centering, Find, Max;
the slowest is the default, and the choice is kept).  **Stop** stops every motion at once (a park
as well); tracking goes on.  The position of the mount is shown next to the buttons.

The directions are those of the sky.  The picture in live view can be turned or mirrored by the
optics, so a button can move the sun another way in the picture: try each button once while
framing.

Some mounts move the other way than the button says (an alt-azimuth mount often has N/S, the
altitude, the wrong way round).  **Reverse N/S** and **Reverse E/W** in the `Mount` window swap
those buttons, here, in the live view and on the phone.  They are kept for each mount.  They do not
change the guide pulses: the calibration for keeping the sun centred measures which way the mount
moves.

The phone dashboard has the same buttons, the speed and the position in its `Mount` panel.

A held button keeps telling Solar Eclipse Workbench to move, several times a second.  When that
stops — the button is released, the window closes, or the phone loses the network — the mount
stops by itself within a second, so a lost button release never leaves the mount running.

## Keep the sun centred

With the mount connected and the `Live View` window open on the camera that shows the sun, Solar
Eclipse Workbench can keep the sun in the middle of the frame for the whole run.

1. Click **Track sun**, and centre the sun roughly with the nudge buttons, filter on.  The
   calibration refuses a mount that does not track: the sky drifting through the frame would be
   measured instead of the mount.  **Track sun**, **Stop tracking** and **Park** are greyed out
   while it runs.
2. In the `Mount` window, click **Calibrate**.  The mount is guided east, west, north and south at
   the guide rate, then moved briefly at a fast slew rate (the driver's "Centering" rate), and the
   sun is brought back where it was each time: about 1.5 minutes at a guide rate of half the
   sidereal rate (a higher guide rate in the driver makes it faster).  This measures which way and
   how far guiding and moving fast move the sun in the live view, so a camera turned on the
   telescope and a mirrored image (a diagonal) are handled.  The calibration is kept for the next
   start; calibrate again when the camera is turned or the live-view size changes.

   Some mounts answer guide pulses and do not move: the iOptron HAZ31 in alt-az mode does that.
   After 20 seconds of guiding, the calibration checks that the mount's own coordinates moved as
   far as its guide rate says, and that guiding back brings the sun back.  When the pulses are
   ignored, it calibrates again with timed slews (as the N/S/E/W buttons move the mount), and the
   centring then corrects with those slews instead of guide pulses.  An alt-az mount does not slew
   equally fast both ways: the iOptron HAZ31 slews at 1x as fast as 2× sidereal east and does not
   move west at all, and at 2x 3× east and 1× west.  So the four directions are measured each on
   their own, and a rate that hardly moves the sun one way is skipped for the next one up.
3. Tick **Keep the sun centred**.

Every 15 seconds the sun is found in the live view: its own edge is used, so the centre stays put
while the moon covers more and more of it.  When it is more than 2 pixels off the middle, it is
guided back.  A sun more than 10 pixels off is first moved most of the way at the fast rate (a
few seconds), and guide pulses do the rest.  A correction is as long as it needs to be when no
shot is coming (before C1, the first centring takes seconds); during the run it has to fit in a
gap between the shots, or it is cut to one pulse of at most 3 seconds per axis:

- only in a gap between the scheduled shots (no camera is busy and none is due for the move and
  a few seconds more),
- not from 15 seconds before C2 to 15 seconds after C3: the mount just tracks then, as the live
  view is paused anyway,
- and it stops by itself, with the reason in the `Mount` window, when the corrections do not move
  the sun as the calibration says (calibrate again) or the live-view frames change size.

The live view shows the sun that was found (a green circle) and the target (a small cross), with
the state of the centring; the phone dashboard shows the state in its `Mount` panel.

Guide pulses are for small corrections: at half the sidereal rate, a second of guiding moves the
sun half a pixel of a sun of 60 pixels radius.  That is why a sun far off is moved at the fast
rate first.  A mount without slew rates in its driver only guides, and a sun far off then comes
back slowly: put it close with the nudge buttons first.

## Simulated mount

Tick **Simulated mount** in the `Mount` window and click **Connect** to try the mount controls, the
nudges, the phone dashboard and scripts with `mount_*` commands without a mount or an INDI server.
In simulation mode (`sew --sim`) it is ticked already.  The simulated mount starts pointed at the
sun.  Without tracking, its position drifts with the sky; it follows the nudges at the chosen speed,
the guide pulses and a park, so the position next to the nudge buttons shows what it does.
With the simulated mount connected, the live view of the virtual camera shows the sun where the
simulated mount points (turned 20° and a little off-centre), so **Calibrate** and **Keep the sun
centred** can be tried too.  The sun is the real one, from frames of the total eclipse of
12 August 2026, in the phase of the (simulated) time: the crescent of ten minutes before C2 at
C2 − 10 min, the corona in totality.  The simulated mount guides at twice the sidereal rate,
faster than a real mount, so a calibration takes well under a minute.

On the command line, use `--mount simulated`, and `sew_hardware --simulate` for the bench console.

To test against a real INDI server without a mount, use the simulator driver of INDI instead:
`indiserver indi_simulator_telescope`, and connect to `localhost`.

## Script commands

```
mount_track, C1, -, 00:10:00.0, "Track the sun"
mount_stop,  C4, +, 00:01:00.0, "Stop tracking"
mount_park,  C4, +, 00:05:00.0, "Park the mount"
```

The commands take no arguments.  The mount is looked up when a command fires, so it can be connected
after the script is loaded.  A mount command that fails (no mount connected, the server gone, the
driver refusing) is shown in the main window and logged, and the run goes on: the cameras do
not need the mount.

## Command line

`sew` (`python -m solareclipseworkbench.sew`) connects a mount only when `--mount` is given, and
sends it the location from the command line and the computer time:

```
python -m solareclipseworkbench.sew -d 2026-08-12 -lon -3.70 -lat 40.42 -alt 650 -s script.txt \
    --mount localhost --mount-device "EQMod Mount" --mount-port /dev/ttyUSB0
```

**Bench console:** `sew_hardware` can test a mount without the GUI:

```
sew_hardware
sew> mount drivers ioptron            the mount drivers INDI has, with "ioptron" in the name
sew> mount start indi_ioptronv3_telescope /dev/ttyUSB0
                                      start indiserver with that driver, and connect
sew> mount connect localhost          or: connect to a server that runs already
sew> mount sun                        where the sun is now
sew> mount sun goto                   point a simulator there (never a real mount)
sew> mount site 40.42 -3.70 650       send a location and the time
sew> mount track                      track at the solar rate
sew> mount guide N 1000               a one-second guide pulse to the north
sew> mount stop
sew> mount disconnect                 the mount keeps tracking
```

`sew_hardware --simulate` uses the built-in simulated mount.
