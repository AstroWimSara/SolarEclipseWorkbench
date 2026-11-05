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

**Track sun** unparks the mount when it is parked, and lets it track at the solar rate.  Not every
driver has a solar rate; the mount then tracks at the sidereal rate, and the sun drifts about 2.5′
an hour across the field of view.  **Stop tracking** stops it, **Park** parks it (after a
confirmation) and **Abort** stops every motion at once.

**Disconnect** and closing Solar Eclipse Workbench only close the connection to the INDI server: the
driver stays connected and the mount keeps tracking.

The window saves the address, the mount and the port for the next start.

## Nudge the mount

While a mount is connected, the `Mount` window and the `Live View` window have a row of nudge
buttons: **◀ W**, **▲ N**, **▼ S** and **E ▶** move the mount for as long as the button is held,
at the speed chosen next to them (the slew rates of the driver, e.g. Guide, Centering, Find, Max;
the slowest is the default, and the choice is kept).  **Stop** stops every motion at once (a park
as well); tracking goes on.  The position of the mount is shown next to the buttons.

The directions are those of the sky.  The picture in live view can be turned or mirrored by the
optics, so a button can move the sun another way in the picture: try each button once while
framing.

The phone dashboard has the same buttons, the speed and the position in its `Mount` panel.

A held button keeps telling Solar Eclipse Workbench to move, several times a second.  When that
stops — the button is released, the window closes, or the phone loses the network — the mount
stops by itself within a second, so a lost button release never leaves the mount running.

## Simulated mount

Tick **Simulated mount** in the `Mount` window and click **Connect** to try the mount controls, the
nudges, the phone dashboard and scripts with `mount_*` commands without a mount or an INDI server.
In simulation mode (`sew --sim`) it is ticked already.  The simulated mount starts pointed at the
sun.  Without tracking, its position drifts with the sky; it follows the nudges at the chosen speed,
the guide pulses and a park, so the position next to the nudge buttons shows what it does.

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
sew> mount connect localhost          connect, and show what the mount reports
sew> mount site 40.42 -3.70 650       send a location and the time
sew> mount track                      track at the solar rate
sew> mount guide N 1000               a one-second guide pulse to the north
sew> mount stop
sew> mount disconnect                 the mount keeps tracking
```

`sew_hardware --simulate` uses the built-in simulated mount.
