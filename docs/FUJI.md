# Fujifilm X cameras

Solar Eclipse Workbench controls Fujifilm X bodies through the Fujifilm Shooting
SDK.  libgphoto2 cannot control an X body tethered, so these bodies do not use
gphoto2.  The SDK was tested with an X-T4.

## What works

| Script command | On a Fuji body |
|---|---|
| `take_picture` | One frame at the shutter speed, ISO and aperture of the command. |
| `take_bracket` | One frame per exposure of the bracket, darkest first.  The shutter speed is set over USB between the frames. |
| `take_hdr` | As `take_bracket`, with the exposures of the HDR sequence. |
| `take_burst` | Single frames, one after the other, for the number of seconds of the command (see below). |
| `prepare_camera` | Sets the exposure, as for the other brands. |
| `sync_cameras` | Cannot set the camera clock (see below). |

The exposure compensation of the main window applies to Fuji bodies as to the
other brands.

## Limits

- **Bursts are slow.**  The SDK releases one frame at a time, and it cannot start
  the body's own continuous drive.  On an X-T4 this gives about 0.5 to 1.8 frames
  per second.  A fast burst at C2 and C3 needs a release cable on the remote
  socket of the body.  That is not part of this release.
- **The drive dial must be on S.**  With the dial on CH, the body refuses the SDK
  release (error 0x1008), and every frame of the script is lost.  The SDK
  cannot read the dial: it reports "stills" for S, CL and CH.
- **The camera clock cannot be set from the computer.**  The SDK has no date and
  time call.  Set the clock on the body by hand.  Each run log has the time at
  which each command released the shutter, in UTC.
- **No live view.**  The live view window is for gphoto2 cameras only.
- **No camera test in the wizard.**  `Test Camera...` and `Verify with
  Camera...` read gphoto2 settings, and do not support a Fuji body yet.
- **Shutter speeds from 1/8000 to 30 s.**  A faster speed needs the electronic
  shutter, which is a setting on the body.  An exposure past either end is taken
  at the end of the scale.

## Install the SDK

Fujifilm distributes the SDK under its own licence.  It is not part of Solar
Eclipse Workbench.

1. Get the Fujifilm X Series Camera Control SDK from Fujifilm.
2. Unpack it.  The folder has a name such as `SDK13410`.
3. Put that folder in one of these places:
   - `~/fujixsdk/`
   - `~/FujiSDK/`
   - `/opt/fujixsdk/`
   - `/usr/local/lib/fujixsdk/`
   - `SDK/` in the source checkout of Solar Eclipse Workbench

   Or set the environment variable `FUJI_SDK_PATH` to the SDK folder.

The workbench finds the SDK by its main library: `XAPI.so` on Linux,
`XAPI.bundle` on macOS and `XAPI.dll` on Windows.

On Linux, the SDK libraries must be on `LD_LIBRARY_PATH`.  The GUI, the wizard
and a command-line run add them, and restart once at start-up.  You do not have to
set the path yourself.  On NixOS the SDK also needs `libstdc++` and `libusb`,
which the workbench looks for in the Nix store.

On macOS, do not stop `ptpcamerad`.  The SDK talks to the camera through it.

## Set up the body

The workbench checks the body when it is detected.  Each setting that costs
frames is reported in the GUI.  Some settings cannot be read over USB.  Check
them on the body.

| Setting | Value | Why |
|---|---|---|
| Connection Setting → PC Connection Mode | **USB Tethering Shooting Auto** | The SDK does not find the body in another mode. |
| Shutter speed dial | **T** | The SDK sets the shutter speed.  At a number, the dial wins. |
| ISO dial | **C** | The SDK sets the ISO.  On A, the ISO is automatic. |
| Aperture ring of a lens | **a number** | On A the body is in aperture priority, not manual.  A telescope has no ring. |
| Exposure compensation dial | **0** | It applies on top of the exposure of the script. |
| Drive dial | **S** | On CH the SDK cannot release the shutter. |
| Focus mode switch | **M** | In S or C, the SDK release can fail, and frames are dropped or late. |
| AF/MF Setting → AF+MF, PRE-AF | **OFF** | AF+MF starts autofocus on each release, also in M. |
| Image Quality | **RAW** (no JPEG) | A JPEG beside each RAW took the rate from 1.85 to 0.61 frames per second on an X-T4. |
| Long Exposure NR | **OFF** | It takes a dark frame after each long exposure, which doubles its time. |
| Shoot Without Lens | **ON** on a telescope | Without it, the body does not release on a telescope. |
| Auto Power Off | **OFF** | The body must stay on for the whole script. |

The camera appears in the workbench as `Fuji Fujifilm <model>`, for example
`Fuji Fujifilm X-T4`.  Use that name in the script.

## The transfer buffer

The SDK keeps a PC transfer of every frame in a buffer of 32 frames on the body,
also when the frame is on the card.  When that buffer is full, the body stops
until its battery is removed.  The workbench deletes the queued transfers before
the buffer is full.  The frames on the card are not touched.
