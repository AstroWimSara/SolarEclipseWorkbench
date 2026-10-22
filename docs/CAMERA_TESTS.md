# Testing your camera with Solar Eclipse Workbench

Brackets, HDR sequences and shot timing in Solar Eclipse Workbench (SEW) depend on how each camera body behaves over USB. They have been tested on a Canon EOS 80D and a Canon EOS R. Nikon and Sony bodies have not been tested this way yet. If you photograph eclipses with a Nikon or a Sony, an hour of testing at home helps you and every other user of that camera.

This guide tells you how to run the tests and what to send back. The test scripts are in [`docs/camera_tests/`](camera_tests/), one folder per brand.

## What you need

- Your camera, connected over USB, with a charged battery (or a mains adapter) and an empty card with room for about 300 pictures.
- Solar Eclipse Workbench, the same version you plan to use at the eclipse.
- `gphoto2` on the command line, to read the camera's settings (`sudo apt install gphoto2` on Ubuntu, `brew install gphoto2` on macOS).
- `exiftool`, to read the exposure of each picture (`sudo apt install libimage-exiftool-perl`, `brew install exiftool`).
- About an hour. Nothing has to be pointed at the sky: a lens cap is fine, as the tests only look at what the camera did, not at the pictures.

## Camera settings

Set these before you start, and keep them for all tests unless a script says otherwise:

- Mode dial on **M** (manual exposure), and **manual focus** (otherwise the camera may refuse to shoot with the lens cap on).
- **Auto power off** disabled, or at least 30 minutes.
- Exposure steps of **1/3 EV**. Some scripts ask you to switch to 1/2 EV.
- **Nikon:** the release mode dial or button on a **Continuous** mode. SEW cannot change it on bodies with a physical dial, and bursts and brackets need it.
- **Sony:** the PC Remote settings as described in the README section [Sony PC Remote settings discussion](../README.md#sony-pc-remote-settings-discussion). Start with the Save Destination at **PC+Camera**. Some scripts are run a second time at **PC**.

## Step 1: Prepare the scripts

1. Download the folder for your brand: [`nikon`](camera_tests/nikon/) or [`sony`](camera_tests/sony/). There is also a [`canon`](camera_tests/canon/) folder, for other Canon bodies.
2. Start SEW and press `Camera(s)`. Note the camera name exactly as the camera table shows it, e.g. `Nikon Z 8` or `Sony ILCE-7M3`.
3. In every script, replace `MY_CAMERA` with that name. Use Find and Replace in a text editor, or in the folder on Linux or macOS:

   ```bash
   sed -i 's/MY_CAMERA/Nikon Z 8/' *.txt          # Linux
   sed -i '' 's/MY_CAMERA/Nikon Z 8/' *.txt       # macOS
   ```

Each line of a script has a description that starts with its number (e.g. `1-2`) and says what to expect. You see it in the jobs table and in the log.

## Step 2: Read the camera's settings

Close SEW (only one program can use the camera at a time), connect the camera and run:

```bash
gphoto2 --summary > summary.txt
gphoto2 --list-all-config > config_third.txt
```

On a Nikon, switch to 1/2 EV steps and run `gphoto2 --list-all-config > config_half.txt` too. Then switch back to 1/3 EV.

On a Sony, check `gphoto2 --get-config shutterspeed`: does it list speeds in 1/3 EV steps (…, 1/100, 1/125, 1/160, …)? Then switch the camera to 0.5EV steps and run it again. Note whether the list changes. SEW expects a Sony at 0.3EV steps, and the wizard warns otherwise.

## Step 3: Test Camera in the wizard

Start `sew_wizard`, go to the equipment page, select or add your camera and press `Test Camera...` with the full test. Take a screenshot of the report. It lists the brackets the camera takes itself, which the scripts below rely on.

## Step 4: Run the test scripts

Start SEW in simulation mode:

```bash
sew -s
```

For each script:

1. Set the camera as the table below says.
2. Press `Camera(s)`.
3. Press the simulation button and set the start given at the top of the script, e.g. **C2** and **-2 minutes** for `Simulation start: C2 - 0:02:00`.
4. Load the script. It starts right away. Watch the jobs table, and the camera.
5. When the last command has run, stop the schedule and note anything the log cannot show (a warning dialog, the camera showing an error, a frame that did not fire).

Running each script in its own SEW session gives each run its own log file, which makes the results easier to read. It is not required.

### Nikon

| Script | Exposure steps | Other settings | What it checks |
|---|---|---|---|
| `1_brackets.txt` | 1/3 EV | Continuous | Brackets `"1 3"` and `"2/3 5"`, a frame count the camera may not offer (`"1 9"`), a step it does not offer (`"1/2 3"`), single pictures after a bracket |
| `2_half_ev.txt` | **1/2 EV** | Continuous | The camera's bracketing at 1/2 EV, a 1/3 EV step on a 1/2 EV camera, a 1/3 EV shutter speed (1/320) rounded, HDR 1 EV apart |
| `3_hdr.txt` | 1/3 EV | any | HDR round trip (9 frames) and one way (5 frames) |
| `4_timing.txt` | 1/3 EV | Continuous | Identical commands send no settings, changed settings are applied, the shutter dial is put back (turn it at `4-6`), a burst of 5 frames, the time to change drive mode |
| `5_prepare.txt` | 1/3 EV | Continuous | `prepare_camera` before a burst and a bracket |
| `6_bad_brackets.txt` | any | any | Only load it: a `Script problems` dialog should appear at once |

### Sony

| Script | Exposure steps | Other settings | What it checks |
|---|---|---|---|
| `1_brackets.txt` | 0.3EV | **PC+Camera**, then again at **PC** | Brackets matching a continuous bracketing mode (`"1 3"`, `"1 5"`), one without (`"1 7"`, taken in software), an old script with a mode name, a single picture after a bracket |
| `2_hdr.txt` | 0.3EV | PC+Camera (and PC if you can) | HDR round trip, one way taken as a camera bracket (4 stops), one way without a matching mode (3 stops) |
| `3_timing.txt` | 0.3EV | PC+Camera | Identical brackets send no settings, changed settings, the dial test (turn it at `3-6`), a burst, the time to change drive mode and the time a bracket keeps the camera busy |
| `4_prepare.txt` | 0.3EV | PC+Camera | `prepare_camera` before a burst and a bracket: the shots after it should start soon after the command |
| `5_bad_brackets.txt` | any | any | Only load it: a `Script problems` dialog should appear at once |

Sony bodies are slow to change drive mode (about 4 s) and, in software brackets, to change the shutter speed, so the Sony scripts leave more time between commands. If SEW reports when you load a script that a command "will probably be skipped", note it, and run the script anyway.

### Canon

Canon users can run the scripts in the [`canon`](camera_tests/canon/) folder: `1_aeb_menu5.txt` with `Number of bracketed shots` at 5, `2_aeb_menu3.txt` at 3, `3_half_ev.txt` at 1/2 EV increments with 3, and the others at 1/3 EV with 5. The results of the EOS 80D and EOS R are in [BRACKETING_CHECKS.md](BRACKETING_CHECKS.md).

## Step 5: A script from the wizard

The last test is a real eclipse script. In `sew_wizard`, generate a script for your camera with **Bracket each corona exposure**, **earthshine** and the **HDR** option on (choose **One way**). Then:

1. Press `Verify with Camera...` and take a screenshot of the report.
2. Load the script in `sew -s` with the simulation starting about 1 minute before C2, and let it run until the totality part has finished.

When the script is loaded, there should be no "will probably be skipped" warnings. During the run, no commands should be dropped. On a Sony, the script should have `Prepare for C2 diamond ring` and `Prepare for C3 beads` lines if it has bursts at C2 and C3.

## Step 6: Send the results

Collect these files in one folder:

- `summary.txt`, `config_third.txt` (and `config_half.txt`)
- the screenshots of `Test Camera...` and `Verify with Camera...`
- the log files of the runs from `~/.SolarEclipseWorkbench/logs/` (`sew-*.log` and `sew_wizard-*.log`, named by date and time in UTC)
- the exposure data of the pictures. In the folder with the pictures, run:

  ```bash
  exiftool -FileName -ExposureTime -FNumber -ISO -AEBBracketValue -DateTimeOriginal -SubSecTimeOriginal *.NEF > exif.txt
  ```

  Use `*.ARW` for a Sony and `*.CR2` or `*.CR3` for a Canon.
- the script the wizard generated
- a short `notes.txt`: the camera model and firmware, which script you ran with which settings, and anything you saw that the log does not show

Then open an issue or a discussion on [GitHub](https://github.com/AstroWimSara/SolarEclipseWorkbench) titled with your camera model, e.g. "Camera test: Nikon Z 8", and attach the folder as a zip file. The logs contain the location you set in SEW. Remove it if you do not want to share it.

## What the results are compared with

Each test script line says what to expect. The full list of checks, with the results so far, is in [BRACKETING_CHECKS.md](BRACKETING_CHECKS.md). Some things learned on the Canons that may also apply to your camera:

- The timing of each shot is in the log: `take_bracket released the shutter at 18:29:30.912 UTC: 0.25 s after its scheduled time`. On the Canons it was 0.1 to 0.45 s.
- The camera's own bracketing may shoot the frames in a different order from what you expect (0, −, + or −, 0, +). That is fine. What matters is that all frames are there with the right exposures.
- A frame missing from a bracket or a burst, a single picture that became a burst, or a command that fired seconds late are the results that matter most. Please describe them in your notes even if you are not sure what caused them.
