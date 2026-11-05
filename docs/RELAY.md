# USB relay shutter trigger

A USB relay board can fire a camera through its wired remote-release jack.  The relay closes the
same contacts as a cable release.  There is no USB in the path to the shutter, so a held contact
lets the camera shoot at the full rate of its own drive mode.  Over USB, many bodies shoot only a
few frames per second, and some cannot shoot a burst at all.

Use the relay for the bursts around C2 and C3.  The camera commands (`take_picture`,
`take_bracket`, ...) can still set the exposure over USB between the bursts.

## Contents

- [What you need](#what-you-need)
- [The release cable](#the-release-cable)
- [Wiring](#wiring)
- [Connecting the relay](#connecting-the-relay)
- [Script commands](#script-commands)
- [Drive mode](#drive-mode)
- [A Fujifilm body on the SDK](#a-fujifilm-body-on-the-sdk)
- [Measured on a Fujifilm X-T4](#measured-on-a-fujifilm-x-t4)
- [Fault finding](#fault-finding)

## What you need

- A USB relay board from the table below, with at least one channel.  Two channels let you
  control the half press (S1) and the full press (S2) separately.
- A release cable for your camera, cut open, or a plug for its remote jack.
- A multimeter, to identify the wires.

| Board                                                    | Backend     | Notes                                                                                                                  |
|----------------------------------------------------------|-------------|------------------------------------------------------------------------------------------------------------------------|
| LCUS-1, LCUS-2 and similar boards with a CH340 chip      | `lcus`      | These boards send no answer.  Find the port with a test fire.                                                          |
| DSD TECH SH-UR01A, SH-UR04A (CP2102 chip)                | `dsd`       | AT commands at 9600 baud.  The board answers `OK`, so the scan identifies it.                                          |
| Numato Lab USB relay boards                              | `numato`    |                                                                                                                        |
| dcttech HID boards ("USBRelay1/2/4", USB id 16c0:05df)   | `hid`       | Install the `hid` extra (`pip install "solareclipseworkbench[hid]"`).  On Linux, a udev rule must give access to the hidraw device. |
| No hardware                                              | `simulated` | To rehearse a script.  It is never selected automatically.                                                             |

`auto` tries the boards that the scan finds, in this order, and uses the first one that opens.

Other packages can add a board type through the entry-point group
`solareclipseworkbench.relay_backends`.  A backend only closes and opens one contact.

## The release cable

A wired release has three lines:

| Line   | Function                                 |
|--------|------------------------------------------|
| S1     | Half press: wakes the camera (and focuses, if AF is on) |
| S2     | Full press: releases the shutter         |
| Ground | Common return for S1 and S2              |

Which plug contact carries which line depends on the camera.  The colours of the wires in a cable
are not standard.  Two vendors can sell the same cable with different colours.  **Measure every
cable with a meter before you connect it.**  Do this again for a spare cable.

Example: on the 2.5 mm jack of a Fujifilm X-T4, the tip is S2, the ring is S1 and the sleeve is
ground.  On one RR-100-compatible cable, the wires were:

| Wire           | Plug contact | Line   |
|----------------|--------------|--------|
| white          | tip          | S2     |
| red            | ring         | S1     |
| both greens    | sleeve       | ground |

The two green wires are the same net.  Twist them into one ferrule.  This cable has three
separate nets, so both relay channels can be used.  A plug that joins tip and ring gives only
two nets: use one channel then.

Solder or crimp the wires with care.  A bad joint on S2 gives this fault: the camera wakes on
S1, but it never releases.

## Wiring

Always use the **normally open** (NO) terminals.  On normally closed terminals, the shutter is held
down while the relay has no power.  An unplugged USB cable then fires the camera and keeps it
firing.

**One channel:** connect S1 and S2 together to NO of one channel, and ground to COM.  A closed
contact is a full press.  This is the default in the relay panel (S2 on channel 1).

**Two channels:** connect S1 to NO of one channel, S2 to NO of a second channel, and ground to
both COM terminals.  This gives:

- A settle on S1 before each frame, so a sleeping camera wakes first.
- `relay_arm`: S1 stays closed, so the release lag is shorter (see the measurements below).
- A burst pulsed at a fixed interval, with a known number of frames.

## Connecting the relay

**GUI:** click the **Relay** button in the toolbar.

1. Click **Scan**.  The port list shows each USB serial port and what answers there.  A DSD TECH
   board shows ✓.  LCUS and Numato boards send no answer, so they show `?`.  HID boards need no
   port.
2. Select the board type, or keep `auto`.
3. Set the S2 channel.  For two-channel wiring, select **Half press (S1) on its own channel** and
   set the S1 channel.
4. Click **Connect**.
5. Put the lens cap on, and click **Test fire**.  The camera must take one frame.

**Release contacts** opens every contact at once.  The panel saves its settings for the next start.

**Command line:** `sew` opens a relay only when `--relay` is given:

```
python -m solareclipseworkbench.sew -d 2024-04-08 -lon -104.63525 -lat 24.01491 -alt 1877.3 -s script.txt \
    --relay /dev/ttyUSB0 --relay-backend lcus --relay-s2 2 --relay-s1 1
```

`--relay auto` tries every USB serial port.  Do not use `auto` when a GPS receiver or another
serial device is connected.

**Bench console:** `sew_hardware` is for building and testing a trigger.  Connect the board without
the camera first:

```
sew_hardware
sew> scan                 what the computer can see
sew> relay connect        open the board
sew> relay idle           every contact must stay open (measure NO to COM)
sew> relay pulse 1 0.5    listen for the click of channel 1
sew> relay walk           pulse each channel, to find which channel is which
sew> relay wiring 2 1     S2 on channel 2, S1 on channel 1
sew> relay timing         latency from the computer to the contact
```

Then connect the camera, lens cap on, and use `relay shoot` and `relay burst`.
`sew_hardware --simulate` runs the console with no hardware.

The relay contacts open when the program stops, also after Ctrl-C.  A crash cannot open them, and
the board then keeps a contact closed.  For that reason a new connection always opens every
contact first.

## Script commands

The relay commands use the same time format as the camera commands:

| Command         | Arguments                          | Effect                                                                 |
|-----------------|------------------------------------|------------------------------------------------------------------------|
| `relay_shoot`   | none                               | One frame                                                              |
| `relay_burst`   | duration [s], optional interval [s] | Hold S2 for the duration.  With an interval and two channels: hold S1, pulse S2 |
| `relay_bulb`    | exposure [s]                       | Hold the shutter open.  The camera must be set to B                    |
| `relay_arm`     | none                               | Close S1 and keep it closed                                            |
| `relay_release` | none                               | Open every contact                                                     |

```
relay_arm, C2, -, 00:00:08.0, "Wake the camera"
relay_burst, C2, -, 00:00:05.0, 4.5, "Diamond ring and Baily's beads"
relay_release, C2, +, 00:00:01.0, "Release S1"
relay_burst, C3, -, 00:00:01.0, 2, 0.25, "Eight frames, 0.25 s apart"
relay_shoot, C3, +, 00:00:10.0, "One frame"
```

- The relay is found when the command fires, not when the script is loaded.  You can connect the
  relay after you load the script.  If no relay is connected when the command fires, the command
  fails and the log says so.
- A wrong duration or interval is reported when the script is loaded.
- Only one relay command runs at a time.  A relay command that must wait more than 1.5 s for the
  previous one is skipped, the same as a camera command.  When the script is loaded, relay
  commands that overlap are reported.
- `relay_release` never waits.  It opens the contacts also while another relay command runs.
- The relay does not know which camera it is connected to.  The load-time check therefore does not
  see a camera command and a relay command that use the same camera at the same time.  Keep them
  apart in the script.
- Do not keep S1 armed while a camera command changes the exposure of the same camera.  With S1
  held, a camera can refuse the change.  Put `relay_release` before such a command.

## Drive mode

The drive mode of the camera decides what a held contact does:

- In S (single), a held contact gives one frame.
- In CH or CL, a held contact gives a burst for as long as it is held.
- With AE bracketing on, one pulse runs the complete bracket, also after the contact opens.  A
  held contact does not start a second bracket.

## A Fujifilm body on the SDK

A Fujifilm X body can be on the relay and on the Fujifilm SDK at the same time.
The relay then fires every frame of the camera commands, and the SDK only sets
the exposure.  See [Fujifilm X cameras](FUJI.md#fire-the-body-through-a-relay).

The SDK queues a PC transfer of each frame on the body, also of a relay frame.
When the Fuji body is the only one connected, the relay commands work on that
queue and on the exposure:

- `relay_burst` deletes the queued transfers while the release is held.
  Without this, the body stops after 32 frames.  When a camera command still
  uses the body, the burst fires at once and does not delete the transfers.
- `relay_arm` and `relay_shoot` first send the exposure settings that a busy
  body refused, but only while S1 is open.  This adds at most 0.8 s.

## Measured on a Fujifilm X-T4

These values come from bench tests in August 2026, with a dcttech 2-channel HID board and a DSD
TECH SH-UR04A.  Other bodies are different.  Measure your own camera before you use these numbers
in a script.

**Latency, from the command to the shutter opening** (photographed against a millisecond clock):

| Path                                      | Latency       |
|-------------------------------------------|---------------|
| S1 armed with `relay_arm`, S2 closes      | 43 to 48 ms   |
| S2 alone, S1 not used                     | about 130 ms  |
| `relay_shoot` with two channels (S1 settle of 120 ms, then S2) | about 170 ms |

The relay itself adds little: a contact change on the HID board took 2.2 ms (mean) and 3.6 ms
(maximum).  The pulse width did not change the latency.  For a burst that must start exactly at a
moment, arm S1 a few seconds before and schedule the burst that much earlier than the latency.

**Pulse length:** a 40 ms pulse on S2 fired every time, in a sweep from 40 to 400 ms.  On
`relay_shoot` the pulse is 40 ms.  A 30 ms tap fired at least one frame in every one of 18 test
sequences.  At 1/30 s and faster, a tap sometimes gave two frames.  At 1/8 s and slower it never
did.

## Fault finding

| Symptom                                           | Cause to check first                                                     |
|---------------------------------------------------|--------------------------------------------------------------------------|
| The camera wakes, but never releases              | The S2 wire or its joint.  Measure from the plug to the relay terminal.  |
| Every relay command reports success, but nothing fires | The software cannot see a broken wire.  Use the bench console and a meter. |
| One frame instead of a burst                      | The drive mode is single (S).                                            |
| `cannot open relay ... exclusively lock port`     | Another program, or the GUI, holds the port.  On macOS, a port stays locked for a short time after it is closed.  The DSD TECH backend tries again for 5 s. |
| `nothing answering AT commands`                   | The port is not a DSD TECH board.  Scan again: port names can change when a cable is plugged in again. |
| HID board: `unable to open device`                | Linux: add a udev rule for the hidraw device.  macOS: connect the board directly, not through a hub. |
| The camera fires when the USB cable is unplugged  | The wires are on the NC terminals.  Move them to NO.                     |
