# Bracketing: checks on real cameras

The bracketing changes for #161 (`take_bracket` with `"<EV step> <frames>"`) and #171 (the wizard reads the camera's brackets) pass the automated tests. They have not yet been tried on a real camera. Tick off each item once it has been checked on a real body, and note the model.

To see what a camera reports for a setting, close Solar Eclipse Workbench and run `gphoto2 --get-config <name>` with the camera connected. For example, `gphoto2 --get-config aeb` lists the choices of the `aeb` setting.

## Canon

- [x] **The AEB step names match.** `gphoto2 --get-config aeb` lists values like `+/- 1/3`, `+/- 2/3`, `+/- 1`, `+/- 1 2/3`. `Test Camera...` in the wizard lists the same steps, each with 3, 5 and 7 frames.
  Model: Canon EOS 80D (2026-10-20). 1/3 EV increments: `+/- 1/3` to `+/- 3` (9 steps), 27 brackets listed. 1/2 EV increments: `+/- 1/2` to `+/- 3` (6 steps), 18 brackets listed.
- [x] **The camera may report the bracketed speed during AEB.** If so, the frame count now works. Set `Number of bracketed shots` to **5** in the camera menu and run `take_bracket … "1 5"`: 5 frames should be taken. SEW used to stop after 3 frames, because it read the shutter speed from a stale copy of the settings.
  Model: Canon EOS 80D (2026-10-20), after the fix in the next item. `"1 5"` at 1/60 gave 1/60, 1/250, 1/125, 1/30, 1/15 (0, −2, −1, +1, +2), and `"+/- 1 2/3"` gave 5 frames 1 2/3 EV apart. The frames are about 1.3 s apart: a `"1 5"` kept the camera busy 6.7 s and a `"3 5"` at 1/30 9.1 s, against 10.1 s and 12.4 s in the planning.
- [ ] **The bracket stops when the menu is set lower than the script.** Set `Number of bracketed shots` to **3** and run `"1 5"`: SEW should take 3 frames and log `AEB stopped after 3 frames instead of 5 …`.
  Model: ______ (only on a body that reports the bracketed speed). Canon EOS 80D (2026-10-21), which does not: with the menu at 3, `"1 5"` took all 5 frames, 1/60, 1/125, 1/30, 1/60, 1/125 (0, −1, +1, then a new sequence 0, −1), as expected. `"1 3"` gave 0, −1, +1.
- [x] **The camera may always report the base speed during AEB.** If it does, every bracket stops after 3 frames, the same as before these changes. Note it here so the check can be changed.
  Result: Canon EOS 80D (2026-10-20) always reports the base speed. With `Number of bracketed shots` at 5, `"1 5"` and `"+/- 1 2/3"` at 1/60 both logged `AEB stopped after 3 frames instead of 5` (`sew-20261020-191947Z.log`). After the third frame the camera still reported 1/60, where its next frame is at 1/250. `gphoto2 --get-config shutterspeed` after each of 4 AEB frames also gives 1/60 every time, so reading the speed later does not help. Fixed: a camera that reports the base speed before the second frame now takes every frame of the script. Run `1_aeb_menu5.txt` again to check this.
- [x] **A bracket with fewer frames than the menu setting still works.** Set the menu to **5** and run `"1 3"`. The 3 frames should be 0, −1, +1 EV (the camera's default bracketing order). Check the exposures in the EXIF data, and check that AEB is off afterwards.
  Result: it does not work. Canon EOS 80D (2026-10-20), menu at 5: the camera's sequence is 0, −2, −1, +1, +2 steps (EXIF `AEBBracketValue`, frames `_MG_6969`–`_MG_6983`), so `"1 3"` gave 1/60, 1/250, 1/125 (0, −2, −1). AEB was off afterwards (the next single pictures were at 1/60), and turning AEB on again starts a new sequence. The README and `Verify with Camera...` now say the menu must match the bracket, and `Verify with Camera...` warns when a script mixes frame counts.
- [x] **A step AEB does not offer falls back to software.** With the camera set to 1/2-stop increments, a `"1/3 3"` bracket should log `AEB does not offer a step of 1/3 EV, will fallback to simulated bracketing` and still take 3 frames.
  Model: Canon EOS 80D (2026-10-20), tested the other way round: at 1/3-stop increments, `"1/2 3"` at 1/60 logged `AEB does not offer a step of 1/2 EV, will fallback to simulated bracketing` and took 1/80, 1/60, 1/40. At 1/2-stop increments (2026-10-21), `"1/3 3"` logged `AEB does not offer a step of 1/3 EV, will fallback to simulated bracketing` and took 1/90, 1/60, 1/45.

## Nikon

- [ ] **The step and pattern names match.** Run `gphoto2 --get-config aebracketingstep` and `gphoto2 --get-config aebracketingpattern`. The wizard expects values like `2/3 EV` and `3 images (…)`. `Test Camera...` should list the matching brackets, without any 2-frame patterns.
  Model: ______
- [ ] **A bracket within the camera's patterns.** `"1 3"` and `"2/3 5"` should give the right number of frames with the right step. Check the release-mode dial is on Continuous; the banner should remind you.
  Model: ______
- [ ] **A frame count the camera does not offer.** For example `"1 7"` on a body with at most 5 frames. SEW should log `failed to set 'aebracketingpattern' at 7 images, chose … instead` and take that number of frames.
  Model: ______
- [ ] **A body without `bracketing` over USB.** The bracket should be taken in software, one picture per frame.
  Model: ______

## Sony

- [ ] **The mode names match.** `gphoto2 --get-config capturemode` lists modes like `Bracketing C 1.0 Steps 3 Pictures`. `Test Camera...` should list them as `"1 3"`, `"1 5"`, … (continuous modes only, not `Bracketing S`).
  Model: ______
- [ ] **A bracket that matches a mode.** `"1 3"` should select `Bracketing C 1.0 Steps 3 Pictures` (see the log), and all frames should be written, in both `PC` and `PC+Camera` save mode.
  Model: ______
- [ ] **A bracket without a matching mode.** For example `"2 5"`: SEW should log `No continuous bracketing mode for 5 frames, 2 EV apart, will fallback to simulated bracketing` and take 5 frames in software. Note how long it takes, since Sony is slow to change shutter speed.
  Model: ______
- [ ] **Old scripts with a mode name still work.** `"Bracketing C 3.0 Steps 5 Pictures"` should still be passed to the camera as is.
  Model: ______

## Software bracketing (any brand)

- [ ] **The exposures are correct.** `"1 5"` at 1/60 should give about 1/250, 1/125, 1/60, 1/30, 1/15, darkest first. Afterwards the camera should be back at 1/60.
  Canon EOS 80D (2026-10-20): `"1/2 3"` at 1/60 gave 1/80, 1/60, 1/40 (the nearest 1/3 EV speeds, darkest first), and the next bracket started at 1/60 again. A Canon at 1/3 EV takes `"1 5"` with AEB, so the 5-frame case needs a Nikon, a Sony or a Canon at 1/2 EV.
- [x] **Brackets near the camera's limits.** A bracket near the fastest or slowest shutter speed should repeat the end speed rather than fail.
  Canon EOS 80D (2026-10-20), with AEB: `"2/3 5"` at 1/6400 gave 1/6400, 1/8000, 1/8000, 1/4000, 1/2500. The camera repeats 1/8000 itself, and nothing failed. In software (2026-10-21, 1/2 EV increments): `"2/3 5"` at 1/6000 gave 1/8000, 1/8000, 1/6000, 1/4000, 1/2000, with the warning `frames are up to 0.9 EV off`. Only the fast end was tested.

## Scripts in SEW

- [x] **A bad bracket is caught when the script is loaded.** A script with `"1 4"` or `"abc"` should show a problem in the GUI when it is loaded, and that bracket should be skipped. The other commands should still be scheduled.
  Canon EOS 80D (2026-10-20): both were logged as errors when the script was loaded and were skipped, and the other commands ran. **But the dialog only appeared after the run.** The scheduler starts when the script is loaded, so `_show_camera_problems` holds the dialog back until the run ends, as it does for camera problems during a run. Fixed: the dialog ("Script problems") now opens when the script is loaded. Checked on 2026-10-21: the dialog opens when `7_bad_brackets.txt` is loaded. Commands already past when a script is loaded are now reported in the same dialog. Checked by loading `5_timing.txt` with the simulation at C2 − 2 min, which reported `8 command(s) of the script are already past`.
- [x] **Old scripts still load.** A script with the Canon form `"+/- 1 2/3"` should load and take 5 frames.
  Canon EOS 80D (2026-10-20): 5 frames, 0, −3 1/3, −1 2/3, +1 2/3, +3 1/3 EV.
- [x] **No false timing warnings.** Run a simulation of a bracketed script: no "will probably be skipped" warnings for commands the wizard spaced, and no dropped commands in the log.
  Canon EOS 80D (2026-10-21), wizard script with 21 corona brackets `"1 5"`, two 2 s earthshine pictures and an 8-frame one-way HDR (`sew-20261021-192413Z.log`): no warnings, all 24 commands ran, every bracket took 5 frames (115 frames). Each command released the shutter 0.1–0.47 s after its scheduled time. The tightest spot is the earthshine picture at C2+30 s: it ended 0.3 s before the bracket at C2+34 s, which the wizard spaces with the 2 s planned picture overhead (1.6 s measured).

## Wizard

- [x] **Test Camera saves the brackets.** The report has a line "The camera takes N brackets itself" (or "offers no bracketing over USB"), and the result is kept after saving and reopening the wizard.
  Canon EOS 80D (2026-10-20): the report line is there, and the brackets are saved in the camera profile in `~/.sew_wizard_config.json`. On 2026-10-21 they were still there after reopening the wizard. The status line next to `Test Camera...` does not mention brackets.
- [x] **Phenomena page, tested camera.** Only the camera's own steps and frame counts are offered. For Canon, the note names the frame count to set in the camera menu.
  Canon EOS 80D (2026-10-21): steps 1/3 to 3 EV with 3, 5 or 7 frames, and the note names the frame count.
- [x] **Phenomena page, untested camera.** Standard steps (1/3 to 3 EV) and 3, 5, 7 or 9 frames are offered.
  Checked 2026-10-21 with an untested camera entry.
- [x] **The generated script.** With "Bracket each corona exposure" on, the corona shots are `take_bracket` lines with the chosen bracket in quotes, the summary shows "Corona Bracket: …", and the brackets fit within totality.
  Canon EOS 80D (2026-10-21): `Total_Solar_Eclipse_2027_20261021.txt` has 21 `take_bracket` lines with `"1 5"`. The last ends at C2+4:52, 16 s before C3.
- [x] **Verify with Camera.** It warns when a bracket will be taken in software, and gives the Canon reminder about the menu setting.
  Canon EOS 80D (2026-10-21): the Canon reminder names 5 frames. Every bracket was one the camera takes itself, so the software warning did not come up.

## take_hdr (#159)

- [ ] **Round trip on each brand.** `take_hdr …, 1/1000, …, 4, "HDR"` gives 9 frames: 1/1000, 1/500, 1/250, 1/125, 1/60 and back. The log line `take_hdr will take 9 shots (round-trip) …` lists the speeds.
  Model: Canon EOS 80D (2026-10-20): 9 frames as listed, about 1.3 s apart (12.5 s in all).
- [x] **One way.** `…, 4, one-way, "HDR"` gives 5 frames, from 1/1000 to 1/60, and the longest is taken once.
  Model: Canon EOS 80D (2026-10-20)
- [x] **A camera set to 1/2 EV steps.** Frames should still be 1 EV apart, e.g. 1/1000, 1/500, 1/250. Before this change they were 1.5 EV apart.
  Model: Canon EOS 80D (2026-10-21): 3 stops from 1/1000 gave 1/1000, 1/500, 1/250, 1/125 and back.
- [ ] **Sony one-way with a matching mode.** With 4 stops, the log should say `take_hdr: 4 stops one-way taken as camera bracket "1 5" around 1/250`, and 5 frames 1 EV apart should be written. Sony takes the middle frame first. Check both `PC` and `PC+Camera` save mode.
  Model: ______
- [ ] **Sony one-way without a matching mode.** For example 3 stops: the frames should be taken one by one, as with a round trip.
  Model: ______
- [x] **Wizard.** Choosing "One way" under the HDR option writes `…, 4, one-way, "HDR at maximum eclipse"`, and the summary shows "HDR: 4 stops, one way". "Round trip" writes the line exactly as before.
  Canon EOS 80D (2026-10-21): `take_hdr, C2, +, 0:02:26.0, …, 1/1600, 4.0, 100, 7, one-way, "HDR at maximum eclipse"`. 8 frames from 1/1600 to 1/13 were taken.

## 1/2 EV exposure steps (#169)

- [x] **Canon or Nikon set to 1/2 EV steps.** `Test Camera...` shows "Exposure step 1/2 EV" (this only works if the camera then lists its shutter speeds in 1/2 EV steps), and lists AEB or bracketing steps such as `1/2`, `1`, `1 1/2`.
  Model: Canon EOS 80D (2026-10-20). With 1/2 EV increments the camera lists its shutter speeds in 1/2 EV steps (…, 1/90, 1/125, 1/180, …), and the apertures too.
- [x] **A bracket on a 1/2 EV camera.** `"1/2 3"` uses the camera's AEB or bracketing. `"1/3 3"` falls back to software and logs `take_bracket: the camera has no shutter speeds for 3 frames, 1/3 EV apart; …`.
  Model: Canon EOS 80D (2026-10-21): `"1/2 3"` with AEB gave 1/60, 1/90, 1/45. `"1/3 3"` gave 1/90, 1/60, 1/45 in software and logged `frames are up to 0.3 EV off`.
- [x] **A script made for 1/3 EV.** A script with 1/3 EV speeds (e.g. 1/320) runs on a 1/2 EV camera, with each speed rounded to the camera's nearest one.
  Model: Canon EOS 80D (2026-10-21): 1/320 was taken at 1/350, and a `"1 3"` AEB around it gave 1/350, 1/750, 1/180.
- [ ] **Sony set to 1/2 EV steps.** Check whether a Sony lists its shutter speeds in 1/2 EV steps (`gphoto2 --get-config shutterspeed`). If it does, `Test Camera...` shows the warning to set 1/3 EV. If it doesn't, the warning can never appear, so note that here.
  Result: ______

## Shot timing (Discussion #192)

Camera commands now only send the settings that changed. The busy-camera warning and the wizard also count the time a Sony needs to change drive mode: about 4 s for the first command after a switch between single pictures, a burst and a bracketing mode, and about 4.5 s on top of the exposures for a Sony bracket. Both numbers come from one log of a Sony A7R IIIA on the 2026 eclipse, so they need checking on more bodies. Read the times from the log file in `~/.SolarEclipseWorkbench/logs/`, which has milliseconds; the time between `Running job "…"` and `Job "…" executed successfully` is how long a command kept the camera busy, and the line `… released the shutter at … UTC: … s after its scheduled time` shows when it really started shooting.

- [x] **Identical brackets send no settings.** Schedule three identical `take_bracket` lines 10 s apart. The second and third should log `capturemode already "…" for bracketing` (Sony), and with DEBUG logging `Exposure settings unchanged, no set_config needed`. Note how much sooner they start after `Running job` than the first one.
  Model: Canon EOS 80D (2026-10-20): the first released the shutter 0.353 s after `Running job`, the second and third 0.252 s and 0.250 s after, so about 0.1 s sooner.
- [x] **A changed setting is still applied.** Run two `take_picture` lines with a different shutter speed, ISO and aperture each. Check in the EXIF data that both pictures have their own settings.
  Model: Canon EOS 80D (2026-10-20): 1/250 f/8 ISO 100 and 1/125 f/11 ISO 200, as scripted.
- [x] **A setting changed on the camera is put back.** Between two identical commands, turn the shutter speed dial on the camera. The second command should set the script's shutter speed again.
  Model: Canon EOS 80D (2026-10-20): the second picture is at 1/250 again, and SEW sent the settings (no `Exposure settings unchanged` line).
- [x] **Single pictures after a burst or bracket.** A `take_picture` after a `take_burst` or `take_bracket` should be a single frame, not a burst.
  Model: Canon EOS 80D (2026-10-20): one frame after each burst, bracket and HDR.
- [ ] **Sony: time to change drive mode.** Run a `take_picture` at 1/800, then 30 s later a `take_bracket` at 1/30, and then the same bracket again. The first bracket should take about 4 s longer than the second. Note both times, so `MODE_SWITCH_S` in `command_timing.py` can be adjusted.
  Model: ______  First bracket: ______ s  Second bracket: ______ s
- [ ] **Sony: duration of a bracket.** For `"Bracketing C 3.0 Steps 5 Pictures"` at 1/30 (2.4 s of exposures), note how long the camera is busy. The planning assumes about 7 s (`SONY_BRACKET_OVERHEAD_S`).
  Model: ______  Busy: ______ s
- [ ] **Canon and Nikon: no time to change drive mode.** Do the same as for Sony. If the first bracket after a single picture is clearly slower, note it here, so the brand can be added to `MODE_SWITCH_S`.
  Model: Canon EOS 80D (2026-10-20), `"3 5"` at 1/30, 30 s after a picture at 1/800.  First bracket: 9.12 s (shutter 0.343 s after the start)  Second bracket: 8.98 s (0.249 s). No drive-mode time.
- [ ] **The 2026 script is reported.** Load the script from Discussion #192 (brackets at C2-17.4 s, C2-8.2 s and C2-1 s) for a Sony. `Pre-C2 Bracketing 2` should be reported as probably skipped; the corona brackets 7.2 s apart should not be.
- [ ] **A wizard script for a Sony.** With "Bracket each corona exposure", earthshine and HDR on, a simulation should show no "will probably be skipped" warnings and no dropped commands in the log. The C3 beads burst starts about 4 s earlier than for a Canon, and the script comments say why.
  Model: ______
- [ ] **prepare_camera on a Sony.** In single-shot mode at 1/800, run `prepare_camera` with `burst` at 1/100, and 10 s later a `take_burst` at 1/100. The prepare should log `prepared capturemode "Continuous …"` and take no picture; the burst should start shooting about 1 s after `Running job`, not 4 s. Repeat with a bracket (`"Bracketing C 3.0 Steps 5 Pictures"`) followed by `take_bracket`.
  Model: ______  Prepare: ______ s  Burst after it: ______ s
- [ ] **prepare_camera on Canon and Nikon.** It sets only the exposure and takes no picture; the burst or bracket after it works as usual.
  Model: Canon EOS 80D (2026-10-20): no picture, `prepared exposure 1/100, f/8, ISO 100 for burst`. The 2 s burst after it (14 frames) started 0.266 s after the command, against 0.356 s without a prepare, and the `"3 5"` bracket after it took its 5 frames.
- [ ] **A wizard script for a Sony has the prepare lines.** `Prepare for C2 diamond ring` and `Prepare for C3 beads`, a few seconds before the bursts, and they show in the jobs table as `prepare_camera(…)`.
