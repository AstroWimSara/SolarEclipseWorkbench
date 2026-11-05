# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- Fujifilm X cameras, through the Fujifilm Shooting SDK instead of gphoto2 (which cannot control them tethered): `take_picture`, `take_bracket`, `take_hdr`, `take_burst` and `prepare_camera`.  The body settings that cost frames (auto ISO, autofocus, JPEG, drive mode, ...) are reported when the camera is detected, and gphoto2 leaves Fuji bodies alone when the SDK is installed.  The SDK itself must be installed separately; see [Fujifilm X cameras](docs/FUJI.md) - by @mrosseel
- USB relay shutter trigger: a USB relay board fires the camera through its wired remote-release jack, so a burst runs at the full rate of the camera's drive mode with no USB in the path.  LCUS, DSD TECH SH-UR, Numato and dcttech HID boards are supported (HID needs the new `hid` extra), and other packages can add a board type.  A `Relay` toolbar button connects, tests and releases the relay; the script commands `relay_shoot`, `relay_burst`, `relay_bulb`, `relay_arm` and `relay_release` fire it, and overlapping relay commands are reported when the script is loaded.  `sew` opens a relay with `--relay`, and `sew_hardware` is a bench console to wire and test a trigger.  See [USB relay shutter trigger](docs/RELAY.md) - by @mrosseel

## [2.0.0] - 2026-11-03

### Added

- Test scripts for Canon, Nikon and Sony bodies in `docs/camera_tests/`, and a guide, [Testing your camera](docs/CAMERA_TESTS.md), on how to run them and what to send back: brackets, HDR sequences, shot timing and `prepare_camera`, with what each line should give
- Connected cameras are kept awake before the script starts: idle cameras are pinged over USB every 20 seconds so their auto power off does not put them to sleep (paused around totality and just before scheduled commands, so shots are never delayed), and a camera that stops responding is reported in the GUI
- Warning when pressing `Camera(s)` if a Canon's `Auto power off` or a Nikon's standby timer is shorter than 30 minutes (Sony does not expose this setting)
- Warning when a script is loaded if a command will probably be skipped because its camera is still busy with an earlier command (estimated from the exposure time, the USB overhead and, for bursts, the time to empty the camera buffer)
- Wizard: `Test Camera...` on the equipment page reads the shutter speeds, ISO values and apertures the camera offers with its lens, its burst support and state, and (full test) sets and verifies the camera clock and measures how long a picture and a burst take.  The result is saved with the camera, and the generated script is fitted to it: exposures are moved to settings the camera really has, keeping the brightness the same (with ISO or aperture where the shutter speed alone cannot), shots the camera cannot expose as planned are marked, and shots are spaced by the measured durations
- Wizard: `Verify with Camera...` checks the generated script against the connected camera: the camera name, availability of every ISO, shutter speed and aperture, mode dial, focus, battery, card space, auto power off, burst support, clock and timing.  The summary also shows the timing check of the generated script
- Each run writes its own log file in `~/.SolarEclipseWorkbench/logs/`, with UTC millisecond timestamps, the contact times, GPS offset and cameras of the run; log files are never overwritten (Issue #191)
- Banner reminder for Nikon cameras to set the release-mode dial to a Continuous mode for `take_burst` and `take_bracket`, which the app cannot change on bodies with a physical dial (`take_hdr` takes single frames, so it works in any mode).  Once a script is loaded, it names the commands the script uses per Nikon, and disappears when the script only takes single pictures.  Sony and Nikon messages share one banner, and a closed banner comes back when its message changes (Issue #160)

- Wizard: `Bracket each corona exposure` on the phenomena page writes the corona series as `take_bracket` commands with the chosen EV step and number of frames, spaced by the time a bracket takes.  `Test Camera...` reads the brackets the camera takes itself (Canon AEB steps, Nikon steps and patterns, Sony continuous bracketing modes) and only those are offered; an untested camera gets standard values.  `Verify with Camera...` warns when a bracket will be taken in software, and reminds Canon users to set the number of bracketed shots in the camera menu (Issue #171)

- `Save` now reports its outcome in a new status bar at the bottom of the main window and in the log: where the settings were saved, a warning when the location was left out because longitude, latitude or altitude is not set, and an error when the settings file cannot be written.  The status bar also shows the toolbar button descriptions on hover (Issue #181)
- Lunar limb correction: C2 and C3 are computed against the Moon's true, mountainous limb instead of a mean disc, and the Baily's beads window around each internal contact is shown and can be scheduled against (`BEADS_C2`, `BEADS_C3`, `_START`, `_END`).  The mean-limb times remain available as `C2_MEAN` and `C3_MEAN`, and a checkbox under the reference moments switches the correction off.  Needs the 72 MB `lunar_limb_band_v1.bin` limb profile, which is downloaded automatically the first time it is needed and saved in `~/.SolarEclipseWorkbench/`; without it (e.g. no network) the mean-limb contacts are used as before.  Please consult README - by @mrosseel
- `Baily's beads` window, opened from a new toolbar button: the true lunar limb against the Sun's limb around C2 and C3 for the current location, as a profile or as a picture of the Moon over the Sun with exaggerated relief.  A slider moves through the seconds around each contact, or the window follows the clock during the eclipse - by @mrosseel
- Wizard: the first and fourth contact shots (C1 - step, C1, C1 + step, and the same around C4) are spaced so the shot after C1 shows the Moon's first bite and the shot before C4 its last one.  Nothing is visible at C1 itself: the bite shows once it is a couple of pixels deep (and deeper than the seeing), which takes tens of seconds with a short lens and a few seconds with a telescope.  `Automatic` (the default) works this out from the focal length and a new `Pixel Size` setting on the equipment page, saved with the camera; the step can also be set by hand.  `Test Camera...` fills in the pixel size for about 50 common Canon, Nikon and Sony bodies from the camera model; for other cameras it asks to enter it.  The partial-phase shots move along so they never collide with the contact shots (Discussion #192)
- README: a new section `Timing shots around C2 and C3` (a burst or bracket covers a stretch of time, keep 1.5 to 2 s from the contacts, C2 and C3 differ because of the lunar limb, prepare the camera, rehearse and read the log), and a note that SEW cannot set the clock of a Sony camera over USB, with a pointer to a sync tool that can run from a `command` line (Discussion #192)
- Every camera command logs when it really released the shutter, and how long after its scheduled time and after the command started that was, e.g. `take_bracket released the shutter at 18:29:30.912 UTC: 1.228 s after its scheduled time (1.226 s after the command started)`.  The time is taken just before the trigger is sent, so the line shows the delay the camera setup adds before a shot (Discussion #192)
- Wizard: for a Sony, the Baily's beads bursts are timed on the camera starting to shoot about 0.3 s after the command (measured on an A7R IIIA when its settings do not change), instead of the 1 s used for other brands, so the bursts are no longer aimed about 0.7 s early (Discussion #192)
- `prepare_camera` script command: sets the camera up for the command that follows (shutter speed, aperture, ISO and, on a Sony, the drive mode: `single`, `burst` or a bracket) without taking a picture.  A Sony takes about 4 s to change drive mode; done ahead of time, that change no longer delays the first shot of a sequence.  The wizard writes a `prepare_camera` for a Sony before the C2 diamond ring burst and before the C3 beads burst, so both bursts shoot at the planned time (Discussion #192)
- Wizard: with the lunar limb profile, the Baily's beads bursts at C2 and C3 are centred on the Baily's beads windows of the location instead of starting at a fixed C2-4 s and C3+1 s, which could miss most of the beads (at the 2026 centre line the C2 window runs from C2-0.1 s to C2+3.1 s).  The diamond ring bursts, the first totality shot, the chromosphere shot and the end of the corona sequence move along, and each window is written as a comment.  The bursts are still written relative to C2 and C3, so the script also runs without the limb profile.  The bursts are now called `C2 beads` and `C3 beads`
- Live view: an optional `Preview size` selector shows larger preview frames on cameras that let the live-view size be changed (Canon EOS, recent Nikon bodies).  The default stays the camera's own setting, which is restored when the window closes; the selector is disabled around totality, and the size of each frame is shown next to its time
- Exposure compensation during the eclipse: `+1 EV` and `−1 EV` buttons above the jobs table make all following shots one stop brighter or darker, e.g. when clouds or dust dim the Sun, and `Reset exposure` returns to the exposures of the script.  Only the shutter speed changes (aperture and ISO stay as scripted), up to 5 EV either way.  The change applies to every shot that fires afterwards, including those already scheduled; the jobs table shows the scripted and the compensated shutter speed (e.g. `1/1000 → 1/500`), and the log notes the compensation of each shot

### Changed

- Canon and Nikon cameras set to 1/2 EV exposure steps are supported: `take_bracket` and `take_hdr` choose the shutter speed closest to each exposure in EV instead of assuming 1/3 EV steps, and the wizard offers 1/2, 1 1/2 and 2 1/2 EV bracket steps for untested cameras.  `Test Camera...` and `Verify with Camera...` show the exposure step the camera is set to, and warn when a Sony is set to 1/2 EV (Sony still needs 1/3 EV steps).  A software bracket whose frames cannot be placed on the camera's shutter speeds (e.g. 1/3 EV steps on a 1/2 EV camera) is logged as a warning (Issue #169)
- `take_hdr` can run one way (`one-way`: from the shortest to the longest exposure, stops + 1 shots) as well as the round trip it always did (`round-trip`, still the default): add the sequence after the number of stops, e.g. `..., 4, one-way, "HDR"`.  The longest exposure is taken once either way.  A Sony takes a one-way sequence with its own continuous bracketing when it has a matching 1 EV mode.  Frames are now 1 EV apart in exposure rather than three places apart in the shutter speed list, so `take_hdr` also works with cameras set to 1/2 EV steps.  An unknown sequence or a number of stops below 1 is reported when the script is loaded.  The wizard offers the choice under `HDR burst at maximum eclipse` (Issue #159)
- `take_bracket` takes a bracket as `"<EV step> <frames>"` for every camera brand, e.g. `"1 3"` or `"0.7 5"`, instead of always 5 frames in a brand-specific syntax.  Canon picks the matching AEB step, Nikon its step and pattern, Sony the matching continuous bracketing mode; when the camera does not offer the bracket it is taken in software, with the frames placed in EV (not shutter speed list positions).  The Canon `"+/- 1 2/3"` form (5 frames) and Sony mode names still work.  An invalid bracket is reported when the script is loaded, and the busy-camera warning now counts every frame of a bracket (Issue #161)
- Back to the newest python-gphoto2 (2.6.4, with libgphoto2 2.5.34); `take_burst` on Canon now works with both the old and the new libgphoto2
- Updated dependencies: apscheduler 3.11.3, astropy 8.0.2, astropy-iers-data 0.2026.11.2, geodatasets 2026.10.0, geopandas 1.2.0, geopy 2.5.0, matplotlib 3.11.2, playsound3 3.3.2, PyQt6 6.12.0, pytz 2026.6, skyfield 1.55 and timezonefinder 9.0.0 (not 9.2, which needs Python 3.12)
- Every log message about one camera now starts with that camera's name (its alias when one is configured), so a DEBUG log with several cameras connected shows which body each message is about (Issue #156)
- The eclipse plot and the jobs table are now separated by a splitter: drag it to give the scheduler more room, e.g. on widescreen displays.  Its position is remembered with `Save` and when closing the application (Issue #182)
- Camera commands only send the settings that differ from what the camera reports, and skip the USB round-trip altogether when nothing differs.  A `take_picture` no longer reads the camera configuration twice, and a Sony `take_bracket` or `take_burst` that is already in the right capture mode does not set it again, so a series of identical shots (e.g. brackets around C2 and C3) starts sooner after its scheduled time (Discussion #192)
- The busy-camera warning when a script is loaded and the wizard's spacing count the time a Sony needs to change drive mode (single picture, burst, a bracketing mode): about 4 s for the first command after a change, and about 4.5 s on top of the exposures for a Sony bracket.  Both were measured on the 2026 eclipse, where the first bracket after the partial phase took 11 s and the next bracket was dropped; that script is now reported when it is loaded.  The wizard keeps the first totality shots, the earthshine and HDR shots among bracketed corona shots, and the chromosphere shot far enough apart (Discussion #192)
- Wizard: the diamond ring and Baily's beads bursts are planned in seconds of shooting for every camera brand: 2 s for a diamond ring burst.  A Nikon gets that many seconds' worth of frames at its measured frame rate (20 fps on a Z 8 gives 40 frames instead of 30); an untested Nikon is assumed to shoot 10 fps (20 frames instead of 30).  With the lunar limb profile, a beads burst on a tested camera covers its Baily's beads window plus 0.5 s on either side, up to the longest test burst (at most 5 s); it is shortened when it would move the diamond ring burst next to it by more than 2 s, and the diamond ring burst always waits until the beads burst is estimated to have finished.  An untested camera keeps 2 s beads bursts
- Wizard: the full `Test Camera...` takes two test bursts back to back for every brand: 1 s and 5 s for Canon and Sony, 10 and 100 frames for Nikon.  They give the camera's busy time per second of shooting (more than 1 s when it empties its buffer slower than it fills it) or a Nikon's frame rate, and the fixed overhead, and the C2/C3 bursts are spaced with them.  Every brand is planned with its measured overhead plus a margin (1.5 × + 1 s), also when that is shorter than the default 6 s, so a camera writing to a fast card (e.g. a Nikon Z 8 or Canon EOS R5 with CFexpress) no longer waits 6 to 9 s after each burst; an untested camera keeps the default.  A script fitted to a fully tested camera records this timing in a `# timing:` header line, which the busy-camera warning (when the script is loaded) and `Verify with Camera...` use instead of the defaults

### Fixed

- An HDR sequence was planned at 1.5 s per frame on every camera, both in the wizard and in the load-time check of a script.  A Canon EOS R needs about 1.9 s, so its 8-frame HDR kept the camera 1.3 s longer than planned and the next corona bracket fired 1.1 s late.  HDR frames are now planned with the camera's measured picture overhead minus 0.5 s when that is longer
- A saved location at sea level (altitude 0 m), or on the equator or the prime meridian, was not restored at the next start, so the reference moments were not calculated either: a value of 0 was taken for "not set".  The same applied to `--longitude`, `--latitude` and `--altitude` on the command line
- Canon `take_bracket` with 5 or more frames stopped after 3 frames on bodies that always report the dial shutter speed during AEB, such as the EOS 80D: SEW took the base speed after the third frame for the end of the camera's sequence.  When the camera reports the base speed before the second frame (which is never at the base exposure), every frame of the script is now taken, and the log reminds you to set `Number of bracketed shots` (#161)
- Canon AEB: `Number of bracketed shots` must match the bracket, not be "at least" its number of frames as the README and `Verify with Camera...` said.  With 5 set, an EOS 80D shoots 0, -2, -1, +1, +2 steps, so a 3-frame bracket came out as 0, -2, -1 (on an EOS R with its bracketing sequence at -, 0, +: -2, -1, 0).  `Verify with Camera...` now names the exact setting, and warns when a script mixes brackets with different numbers of frames (#161)
- Problems found while a script is loaded, such as a bad bracket, were only shown in a dialog after the run: loading a script starts its schedule, and during a run problems only go in the window title.  They are now shown when the script is loaded, while it can still be fixed
- Commands whose time had already passed when the script was loaded (a script loaded late, or a simulation started too close to its reference moment) were skipped with only a line in the log.  They are now reported when the script is loaded, with the first and last of them
- Live view: on a camera that reports a preview size it does not offer (an EOS 80D reports `val 0` next to Large, Medium and Small), the size box now starts at `Camera default` instead of showing `Large`, and closing the window no longer tries to put `val 0` back, which the camera refused with a warning in the log
- Wizard: shutter speeds between 1/4 s and 1 s are written as the speed that was calculated: 0.8 s was written as `1` and 0.4 s and 0.6 s as `0.5`, up to 1/3 stop off in the generated script
- Nikon `take_burst`: a release mode or number of frames the camera refuses is now logged as a warning instead of failing silently (gphoto2 returns an error code instead of raising).  A refused change to continuous mode (release mode set with a dial or button, e.g. on a Z 8) also left its value queued on the configuration, so the number of frames could then be refused as well and the burst became a single frame.  More frames than the camera takes per burst are capped to its maximum, with a warning
- A script line scheduled against a reference moment that does not exist is now reported when the script is loaded, with the number of lines it cost, instead of disappearing silently.  `BEADS_C2` and the other limb-corrected moments only exist when the correction is on and the limb profile is installed, so the same script can schedule perfectly one day and lose its contact bursts the next - by @mrosseel
- Loading a script written for a longer totality than the one at your location is now reported: a camera command running into the last seconds before third contact is still holding the shutter when the beads sequence needs it - by @mrosseel  Commands written relative to C3 (such as the wizard's chromosphere shot at C3-2 s) are not counted, and the check now also works in simulation mode and with a GPS clock offset
- An unrecognised command in a script is logged instead of being dropped without a word - by @mrosseel
- Cameras could not be used when the computer's language is not English, e.g. a Sony in Manual mode was reported as `Manuale` on an Italian system and rejected (Issue #185).  gphoto2 values and numbers are now always in English (C locale); the character set still follows the system language, so `export LC_ALL=C` is no longer needed
- The values in the main window (reference moments, date and time) were drawn higher than their row titles; they are now vertically centred on the same line (Issue #190)
- The row titles of the reference moments (e.g. `Second contact (C2)`) were cut off with a larger system font, because the reference moments box was always 600 pixels wide.  The box now grows when the font needs it, and keeps the same width while counting down
- A closed Sony settings banner no longer reappears when a scheduled `sync_cameras` command runs; pressing `Camera(s)` still shows it again (Issue #187)
- Sunrise and sunset are now searched over the local calendar day of the eclipse.  Far from Greenwich the wrong day could be returned, e.g. the next morning's sunrise for Australia (Issue #188)
- Sun altitudes in the GUI and in the wizard's script comments are now the apparent altitude (with atmospheric refraction), consistent with sunrise/sunset and with what Stellarium shows.  Before, the geometric altitude was shown, so a shot labelled "sun 0.1°" came about 5 minutes before the displayed sunset (Issue #188).  Exposures are still calculated with the geometric altitude
- Wizard: partial phase and C1/C4 shots are now kept while the sun is partly below the horizon, until the sun has completely set (or from the moment it starts to rise).  Before, they stopped when the centre of the sun reached the geometric horizon, a few minutes before sunset (Issue #188)
- `take_burst` on Canon took no picture with python-gphoto2 2.6.4 (Issue #131): libgphoto2 2.5.34 renamed the remote release values (`Press Full` became `Press Full MF`, and releasing is now `Release`).  The values are now taken from what the installed libgphoto2 offers
- `take_burst` on Canon took only one picture on bodies without a plain `Continuous` drive mode, such as the EOS R10 (Issue #131).  The best continuous drive mode the camera offers is now used (`Continuous high speed` first)
- Canon `take_burst` failures were silent: errors when setting the drive mode or pressing the shutter are now reported, a burst that cannot hold the shutter falls back to single pictures, and the shutter is always released
- With a USB GPS fix, the displayed clock, the C1–C4/MAX/sunrise/sunset countdowns and the execution times in the jobs table now follow GPS time; previously only the scheduled commands were corrected, so the countdowns were off by the computer clock error
- The USB GPS clock offset is measured more precisely: stale buffered NMEA sentences are discarded, the time is taken when the RMC sentence arrives, and the best of 5 samples is used
- Wizard: the C2 diamond ring burst was skipped because it started only 6 s after the Baily's beads burst, while a burst keeps the camera busy for about 8 s.  The C2/C3 bursts are now spaced by the estimated burst duration, follow the order of the phenomena (diamond ring then beads before C2, beads then diamond ring after C3), and the partial and early totality shots next to them leave room for them
- Wizard: Sony bursts were 30 seconds long (Sony bursts are given in seconds, not frames); they are now 2 seconds
- Wizard: the HDR sequence could start while the first earthshine exposure was still running; it now starts after it, and is placed relative to C2 like the other totality shots
- Wizard: corona shots could start up to 1 s late because their start was rounded up to a whole second while the next shot was spaced from the unrounded time
- Setting the camera clock could leave older cameras at a default date (1980 or similar).  The plain PTP date property was written as "YYYY-MM-DD hh:mm:ss" instead of the PTP format "YYYYMMDDThhmmss", and the result was never checked.  The clock is now set through libgphoto2's own `syncdatetime` where the camera offers it, written in the format the camera reports otherwise, and read back: a camera that does not take the time gets its previous date and time back, a warning is shown, and its clock is left alone for the rest of the session.  Setting the clock also no longer competes with a scheduled shot for the USB connection
- A shot dropped because its camera was still busy with an earlier command was logged without the name of the camera
- Two Sony log messages (event drain at disconnect, forced USB lock release) showed a literal `%s` instead of the camera name
- A camera that libgphoto2 does not know yet, such as the Sony A7 V, is detected as `USB PTP Class Camera` and was handled as a camera of unknown brand: no Sony drive modes, bursts or brackets, and storage errors in the camera overview.  The brand is now taken from the manufacturer the camera reports over USB, a warning says the camera is not in libgphoto2's list yet, and the camera keeps the name `USB PTP Class Camera` in scripts
- Opening a Sony camera by name tried to set the capture target, which a Sony does not allow once USB is connected
- The log file in `/tmp` was overwritten at every start, so the log of an eclipse was lost as soon as the application was restarted; log messages from camera and scheduler threads were also dropped while the eclipse visualisation or contact times were being calculated

## [2.0.0rc5] - 2026-08-07

### Fixed

- Post-C3 partials shutter speeds math looks broken - #184 by @WimDeMeester

## [2.0.0rc4] - 2026-08-07

### Fixed

- for command can now handle float interval; jobs scrolling improved - #186 by @fliker09

## [2.0.0rc3] - 2026-08-06

### Fixed

- Improved Sony stability - #183 by @fliker09


## [2.0.0rc2] - 2026-08-05

### Fixed
- Exposures longer than 3 seconds won't cause potential clashes with the next exposure - #172 by @fliker09


## [2.0.0rc1] - 2026-08-05

### Added
- Show camera problems in the GUI instead of only in the log - #166 by @mrosseel
- Sony camera support.  Working in Solar Eclipse Workbench with Sony cameras works now fluently by @fliker09
  - Sony: `take_bracket` is now supported, please consult README - #146 by @fliker09
  - Sony: `--sony-cont-mode` command line option has been added, to override automatic selection of the Continuous capture mode, please consult README - #145 by @fliker09
- It is now possible to re-connect cameras without restarting the app, please consult README - #149 by @fliker09
- Timings for reference moments now show milliseconds to first digit - #137 by @fliker09
- Scheduler has been replaced, it now supports precision down to microseconds - #137 by @fliker09
- Sony: banner with warning(s) can now be closed by @fliker09
- Canon: DIGIC III cameras are now properly supported (tested with a 1000D body) by @fliker09
- HDR sequences are now supported by Nikon and Sony cameras as well - #159 by @fliker09
- Nikon: in-camera bracketing is now supported - #158 by @fliker09

### Fixed
- Sony: `take_burst` is now properly supported, please consult README - #145 by @fliker09
- Sony: `PC` mode is now working correctly and downloads all files from camera(s) by @fliker09
- Sony: no more 4 seconds delay before shooting if no lens is detected by @fliker09
- Sony: many small vendor specific fixes and additions - #147, #150 and #151 by @fliker09
- Live View: it can now be properly disabled by @fliker09
- Improved log messaging (more to come) by @fliker09
- Rewrote the Sony section in the README by @fliker09
- Sony: banner with warning(s) is now more informative (updated the text) by @fliker09
- Simulation mode now shows the correct countdown. Apply the simulation offset to countdowns and live-view pause #162 by @mrosseel and @fliker09
- Reclaim the USB device from macOS' PTP daemon (and fix the -53 advice) - #164 by @mrosseel
  - This means that on macOS, Solar Eclipse Workbench should not be started with *sudo* anymore.
- Stop the previous scheduler when a new script is loaded - #163 by @mrosseel
  - Loading a second script left two schedulers running and every command fired twice.
- Close every camera on exit, not just up to the first failure - #165 by @mrosseel
- Canon: if a camera doesn't support 5 frame bracketing sequence, it will stop after the 3rd shot by @fliker09
- HDR sequences are now using 1EV steps for the ramping - #159 by @fliker09
- Nikon: shutter speeds are now properly read from the camera by @fliker09
- Testing suite have been updated to support the update Sony code by @mrosseel
- Canon: aperture is now properly set when shooting a single picture by fliker09
- Exposures longer than 3 seconds won't cause potential clashes with the next exposure - #172 by @fliker09

## [1.10.7] - 2026-07-23

### Fixed
- Fixed 'Skipping line in script (not enough fields)' messages for empty lines in CSV file: #141
- 'Reference moments' button freezes the app when pressing first time.  Now showing a progress indicator: #136
- 'command' command in csv script does not longer block the scheduler.  The command is now started and the scheduler continues to the next command.  
- Removed extra scrollbar in GUI: #142
- First PR by @fliker09
  - Documentation update
  - Extended timeout for GPS location retrieval from 2 minutes to 3 minutes.
  - Add `--low-cpu` option to `sew` command line to prevent auto-refresh of eclipse plot on low powered devices.
  - Made Stop button ask for confirmation, to avoid accidental disruption.

## [1.10.6] - 2026-07-01

### Fixed
- take_burst not working on Canon R10 (Issue #131).  This problem was introduced by the update to gphoto2 2.6.4.

## [1.10.5] - 2026-07-01

### Fixed
- SEW crashes when loading location from GPS (Issue #130).

## [1.10.4] - 2026-06-25

### Fixed
- Running an eclipse simulation from the command line — python -m solareclipseworkbench.sew 
  without --gui — failed.  First PR by @mrosseel

## [1.10.3] - 2026-06-20

### Fixed
- **Canon EOS R: live view before first picture broke both preview and capture** — On Canon
  EOS R (and other EOS mirrorless) bodies, opening the Live View window before any picture had
  been taken caused gphoto2's internal `eos_remotemode` to be initialised to 1
  (`EOS_SetRemoteMode(0x01)`) by `gp_camera_capture_preview`.  `gp_camera_trigger_capture`
  on EOS R requires `eos_remotemode = 0x15` and only sends `EOS_SetRemoteMode` when the cached
  value is 0 (uninitialised).  Because the cached value was already 1, `trigger_capture`
  skipped the call, attempted to fire the shutter in the wrong mode, and failed — taking no
  picture and also preventing further preview frames.  Canon DSLR bodies (EOS 80D, EOS 1000D)
  were unaffected because both paths use mode 1 on those bodies.

  **Fix**: `GPhotoCameraAdapter` now carries two new flags:
  `_capture_preview_was_called` (set by `LiveViewThread` just before every
  `gp_camera_capture_preview` call) and `_first_capture_done` (set after the first successful
  `gp_camera_trigger_capture`).  When `take_picture` or `take_hdr` is about to fire the first
  capture on a Canon camera and `_capture_preview_was_called` is True, it calls
  `_reset_canon_eos_ptp_session()` which issues `gp_camera_exit` + `gp_camera_init` to close
  and re-open the PTP session, resetting `eos_remotemode` to 0.  The subsequent
  `trigger_capture` then correctly sends `EOS_SetRemoteMode(0x15)` and all later preview and
  capture calls work as expected.  The reset happens **at most once** per camera connection
  and adds no overhead to any shot after the first.

- **Canon `take_burst`: press-and-hold remote release only fired a single frame on some Canon bodies (EOS R, EOS 80D)** — `take_burst()` now resets the EOS PTP session when live view was used before the first capture (same one-time check as `take_picture`) and attempts to set the camera's `drivemode` to `Continuous` before pressing `eosremoterelease`, allowing a press-and-hold to produce a sustained burst. When the `drivemode` widget is absent the code falls back to the original remote-release sequence so behaviour remains safe on bodies without the widget.

## [1.10.1] - 2026-06-05

### Added
- **Nikon take_bracket**: Implement software bracketing for Nikon bodies using the camera's `shutterspeed` choices and `gp_camera_trigger_capture`. `take_bracket(camera, settings, steps)` now works for Nikon and accepts the same '+/- 1/3' through '+/- 3' step strings used for Canon. No manual AEB configuration is required on the camera body.

### Fixed
- **Bracket frame count parity**: Nikon bracketing now fires 5 frames (base ± step and ± 2×step), matching Canon AEB behaviour.

## [1.10.0] - 2026-06-04

### Added
- **Live view zoom & pan**: The Live View window now includes a `Zoom` control with `Fit`, `5x`, and `10x` options. When zoomed in the preview displays a centre-cropped magnification and exposes horizontal and vertical pan sliders to move the crop region. The existing blue centre crosshair is preserved.

## [1.9.2] - 2026-04-25

### Fixed
- **Sony storage-info fallback no longer triggers USB reinit loops**: some Sony bodies
  (including ZV-E10 in PC Remote mode) can expose an empty storage summary over PTP, causing
  `get_storageinfo()` to return gphoto2 error `-1`. SEW now treats this as "storage unknown"
  for Sony cameras and returns `-1.0` (shown as `N/A` in the UI) instead of forcing camera
  reinitialisation. This prevents follow-up `-53` USB-claim errors during camera overview
  polling.

### Added
- **Regression tests for Sony storage-info handling**: added
  `tests/test_sony_storageinfo.py` to verify that Sony `-1` storage responses are handled
  gracefully without reinitialising the camera, while non-Sony behavior remains unchanged.

## [1.9.1] - 2026-04-20

### Fixed
- **Sony ILCE model detection in camera vendor classification**: SEW now treats
  ILCE-prefixed model names (for example `ILCE-7M5`) as Sony everywhere vendor
  detection is used. This ensures Sony-specific adapter selection and behavior
  are applied even when gphoto2 reports the model without a literal `Sony`
  prefix.

- **Focus mode check accepts localized and firmware-specific values**: `get_focus_mode()` now
  normalises values returned by gphoto2 that vary by camera firmware language or version.
  Sony cameras with German firmware report `"Manuell"` instead of `"Manual"`, and some Sony
  firmware versions report `"undefined"` when the lens/body switch is in the manual focus
  position. Both are now treated as `"Manual"` so no spurious warning is shown.

- **Sony downloader no longer starts on unknown/localized save-destination values**: the GUI
  previously auto-started the Sony background downloader when the camera's PC-Remote **Save
  Destination** could not be read via gphoto2. On localized firmware this could make SEW assume
  the camera was in PC-only mode and start copying files to `~/Pictures/SolarEclipseWorkbench`,
  stealing USB bandwidth from scheduled captures. The downloader is now started only when the
  destination is confidently identified as PC-only; unknown values are treated conservatively as
  no-download.

- **Live preview crash on Nikon/Sony adapters**: Fixed a `TypeError` in `LiveViewWindow._poll_frame`
  where `QImage.fromData(...)` could receive a `gphoto2.file.CameraFile` object instead of raw bytes.
  `LiveViewThread` now uses the virtual-preview path only for `VirtualCamera` instances. Wrapped
  gphoto2 cameras (including Nikon and Sony adapters) now always use the gphoto preview path that
  extracts JPEG bytes correctly.

- **Defensive live-preview frame handling in GUI**: `_poll_frame` now normalises `memoryview` and
  `bytearray` frames to `bytes`, and safely logs/skips unsupported frame types instead of crashing.

- **Sony burst timing and sequencing around C2/C3**: `take_burst()` for Sony no longer waits on
  `_wait_for_capture_complete()` (Sony cameras do not emit `GP_EVENT_CAPTURE_COMPLETE`). The burst
  loop now uses Sony-specific event draining (`_sony_drain_events` before each trigger and
  `_drain_camera_events` after), matching the `take_picture()` path. This prevents long per-frame
  waits that could stretch 30-frame bursts and cause nearby scheduled shots to be dropped or delayed.

### Added
- **Regression test for preview frame types**: Added `tests/test_live_view_preview_types.py` to
  verify that non-virtual cameras exposing a delegated `capture_preview()` method still use the
  gphoto preview path and deliver `bytes` to the GUI.

- **Regression test for Sony save-destination downloader logic**: Added
  `tests/test_sony_save_destination.py` to verify that the background downloader is enabled only
  for clearly PC-only destinations, and not for mixed or unavailable values.

- **Regression test for Sony burst event handling**: Added `tests/test_sony_burst.py` to verify
  that Sony burst capture uses the non-blocking event-drain path and does not call
  `_wait_for_capture_complete()`.

- **Aperture read-back check**: After setting the aperture via gphoto2, SEW now reads
  the value back from the camera and logs a `WARNING` if the camera reports a different
  f-number than was requested. Sony Alpha bodies (and cameras with a fixed-aperture
  lens) silently accept the PTP set-config command without applying it — the read-back
  check makes this visible in the log and console so the user knows to set the aperture
  manually on the lens or camera body.

## [1.9.0] - 2026-04-17

### Added
- **USB GPS support**: A new **🛰 Get GPS from USB Device** button in the Location pop-up
  reads coordinates and precise UTC time directly from a USB GPS receiver (e.g. VK-162
  G-Mouse, u-blox 7/8/9, Prolific PL2303, Silicon Labs CP210x).  No `gpsd` installation
  is required — NMEA sentences are parsed directly via `pyserial` and `pynmea2`.
  Works on Linux, macOS, and WSL.

- **GPS–computer time offset correction**: When a USB GPS fix is acquired, the offset
  between GPS satellite time and the computer's system clock is measured.  Every
  subsequently scheduled action (photo, burst, voice prompt, etc.) is shifted by this
  offset so that it fires at the correct astronomical moment, even when the laptop clock
  is several seconds off.  If no GPS fix is available the computer clock is used
  unchanged (offset = 0).

- **New module `usb_gps.py`**: Self-contained module providing `find_gps_device()`,
  `check_serial_permission()`, and `UsbGpsWorker` (QThread) that emits
  `location_received(dict)`, `status(str)`, and `error(str)` signals.  The worker
  automatically discovers the GPS port, checks `dialout` group membership on Linux, and
  times out gracefully if no fix is received within 120 seconds.

- **`pynmea2`** added as a project dependency (`pyproject.toml`).

### Changed
- `observe_solar_eclipse`, `schedule_commands`, and `schedule_command` in `utils.py`
  each gained an optional `gps_time_offset: timedelta` keyword argument (default
  `timedelta(0)`) so existing call sites remain unaffected.
- `SolarEclipseModel` in `gui.py` gained a `gps_time_offset` attribute that is populated
  when the user accepts a location obtained via USB GPS.

## [1.8.1] - 2026-04-15

### Added
- **Live view window**: A new **Live View** toolbar button opens a floating preview window that
  shows a 1 fps JPEG thumbnail from the connected camera via gphoto2 `capture_preview`.  This
  lets you verify that the Sun is still centred in the frame and in focus without interrupting
  the running script.

  Key properties:
  - Preview frames are fetched in a background thread (`LiveViewThread` in `camera.py`) that
    tries to acquire the per-camera USB lock with a 50 ms timeout.  When a scheduled shot is
    firing the frame is silently skipped, so **shot timing is never affected**.
  - The live view image is transferred as a small JPEG thumbnail only; the camera still saves
    full-resolution photos directly to its SD card as usual.
  - **Auto-pause during totality**: the preview pauses automatically 15 seconds
    before C2 and resumes 15 seconds after C3, giving scheduled shots uncontested
    USB access during the critical totality window.  A yellow status banner in the
    window indicates the paused state.
  - A **"Disable / Enable Live View"** toggle button in the window lets the user turn the
    preview off or on at any time — before, during, or after totality — without stopping the
    script.
  - Closing the main window also stops the live view thread cleanly.
  - Live view requires a real gphoto2 camera to be connected.  A warning dialog is shown
    when no camera is available.

### Changed
- **Wizard C1→C2 partial phase uses C2-relative offsets**: The generated script now
  references the C1→C2 equispaced partial-phase shots as `C2, -, offset` instead of
  `C1, +, offset`. Using C2 as the anchor prevents timing conflicts between the partial
  sequence and the totality sequence: both now count down to the same reference contact,
  so even if the partial interval is not perfectly calibrated the shots will always stop
  safely before C2.

## [1.7.2] - 2026-04-05

### Fixed
- **Nikon burst/reset TypeError**: Prevent a crash in `take_burst` when resetting Nikon `stillcapturemode` and `burstnumber` by using numeric widget values (`0` / `1`) instead of strings. Fixes a `TypeError` from the gphoto2 binding that could cause subsequent commands to be repeated after a burst.

## [1.7.1] - 2026-03-30

### Changed
- **Eclipse visualization update rate reduced**: The `EclipsePlotWidget` and its
  controller now update the plotted Sun & Moon geometry every 5 seconds (instead of
  every 1 second). A dedicated 5 s timer drives the plot while the on-screen clock
  continues to update at 1 Hz. This reduces CPU usage and battery drain during
  live observation.

### Fixed
- **Eclipse date parsing**: Prevent a crash when selecting an eclipse in locales that use longer month names (for example French "août"). The GUI now extracts the date portion from the eclipse combobox by splitting on " - " instead of using a fixed-width slice, avoiding truncated years and `ValueError` from `strptime`.

- **Starting time (simulation)**: The "Starting time" dialog now omits reference moments that are not available for the chosen location/date (for example, `C2`/`C3` are not offered for partial eclipses, and `C1`/`C4`/`MAX` are not offered when no eclipse occurs). This prevents selecting an invalid simulation start relative to a nonexistent contact.

## [1.7.0] - 2026-03-28

### Added
- **Eclipse visualization**: Added an interactive Sun & Moon renderer (`EclipsePlotWidget`) to
  the main GUI that draws the apparent solar and lunar discs to scale in local horizontal
  coordinates (solar radii). The widget accounts for topocentric parallax and apparent
  angular sizes so the preview matches on-site geometry and helps verify contact timings.

- **Sony camera support**: Sony Alpha DSLR and mirrorless cameras (e.g. ILCE-7M3, ILCE-7RM5,
  A7 IV, A9 III) are now fully supported alongside Canon and Nikon.

  A new `SonyCamera` adapter class (`camera.py`) wraps the gphoto2 camera object and sets
  `vendor = 'Sony'`, enabling all vendor-specific branches in the capture pipeline.

  Vendor-specific behaviour for Sony:
  - **Exposure mode**: `expprogram` widget is set to `"M"` (Manual string value, as used by
    Sony Alpha bodies — distinct from Nikon's numeric `"1"` code).
  - **Auto-ISO**: disabled via the `autoiso` widget before every capture so that the
    manually programmed ISO value is actually used.
  - **Aperture**: set via the `f-number` widget (same as Nikon; Canon uses `aperture`).
  - **Single-frame guard**: `capturemode` is reset to `0` (Single) at the start of each
    `take_picture` call so that leftover burst settings from a previous `take_burst` do not
    cause unwanted continuous shooting.
  - **Burst mode** (`take_burst`): switches `capturemode` to `1` (Continuous), fires
    *N* `gp_camera_trigger_capture` calls (burst parameter = number of frames, same
    convention as Nikon), then resets `capturemode` to `0` (Single) afterwards.
  - **Shooting mode query** (`get_shooting_mode`): reads `expprogram` and maps `"M"` →
    `"Manual"`, consistent with the Nikon path.

  `get_camera()` and `get_camera_by_port()` both now wrap Sony model names in `SonyCamera`
  (detection: `"Sony"` in model name string).

- **Example script for Sony cameras** (`example_scripts/testSony.txt`): demonstrates
  `take_picture`, `take_burst` (with frame-count parameter), and `take_hdr` for a
  `Sony ILCE-7M3` across all four contacts and totality.

- **Wizard: configurable HDR starting shutter speed**: When the "HDR burst at maximum
  eclipse (`take_hdr`)" option is enabled on the *Phenomena* page, a new "Starting shutter
  speed" row now appears beneath the stops spinner.  Two modes are available:
  - **Auto-calculate** (default): the fastest speed in the HDR ramp is derived
    automatically from the inner-corona exposure calculation, preserving the existing
    behaviour.
  - **Manual**: a drop-down combo box lets the user pick any standard shutter speed from
    `1/8000` down to `1/4`.  The selected speed is used directly as the starting (fastest)
    speed passed to the generated `take_hdr` command.

  Both the HDR exclusion window (used to block out corona shots around MAX) and the
  generated `take_hdr` script line honour the chosen speed.  The combo box and radio buttons
  are disabled while the HDR checkbox is unchecked, and the combo box is additionally
  disabled while "Auto-calculate" is selected.

### Changed
- **Wizard burst parameter now includes Sony**: The two `take_burst` lines generated for
  Baily's beads and diamond-ring events (around C2 and C3) previously used a duration of
  `2` seconds for Canon and `30` frames for Nikon. Sony is now treated the same as Nikon
  (frame-count convention), so the generated parameter is `30` frames when the camera name
  contains `"sony"`.
- **Wizard camera name placeholder** updated from `"e.g., Canon EOS 80D, Nikon D850"` to
  `"e.g., Canon EOS 80D, Nikon D850, Sony Alpha A7"` to make Sony support discoverable.
- **`take_hdr` compatibility note updated**: documentation and comments now reflect that
  `take_hdr` works on Canon, Nikon, *and* Sony cameras (Sony uses the same
  `gp_camera_trigger_capture` path as Nikon).
- **Wizard usable on 1680×1050 screens**: The wizard window minimum height was reduced from
  900 px to 620 px and the default startup size from 900 px to 850 px tall.  The three
  content-heavy pages (*Eclipse Configuration*, *Equipment Configuration*, *Phenomena
  Selection*) are now wrapped in a `QScrollArea` so all content is reachable by scrolling
  even when the window is shorter than the page content.  The horizontal scroll bar is
  suppressed; only vertical scrolling is possible.  The summary text area on the final page
  was also capped at a smaller maximum height so it does not consume excess vertical space.
  All wizard navigation buttons (Next, Back, Finish, Cancel) remain fully visible at all
  supported window sizes.
- **Build system migrated from Poetry to uv**: `pyproject.toml` now uses standard PEP 621
  metadata (`[project]`) with a `setuptools` build backend, replacing the previous
  `[tool.poetry]` setup.  Developer dependencies (pytest) are declared in
  `[dependency-groups]`.  Use `uv sync --group dev` to set up the environment and
  `uv run sew` / `uv run sew_wizard` to run the application during development.

## [1.6.0] - 2026-03-10

### Added
- **`take_hdr` command**: New HDR sequencing command for eclipse totality photography.
  Uses `gp_camera_trigger_capture` instead of the blocking `gp_camera_capture` so shots are
  fired without waiting for each file to be written to the card, maximising throughput.
  The shutter speed choices are queried directly from the connected camera body at runtime
  (via the `shutterspeed` widget choices list), ensuring the ramp sequence always stays
  within the speeds the body actually supports — no hardcoded table. A symmetric exposure
  sequence is generated: `start_speed → (N stops slower) → start_speed` (2N+1 total shots).
  Canon and Nikon are both supported; Canon USB event queues are drained after the sequence
  to prevent stalls on subsequent operations. Also includes a `VirtualCamera` fallback for
  simulator mode. The command is fully wired into the script parser (`scripts.py`),
  scheduler (`utils.py`), and `__init__.py` exports.

  Script syntax: `take_hdr, MAX, -, 0:00:10.0, Canon EOS R, 1/2000, 5.6, 100, 14, "HDR at mid-totality"`

  New internal helpers added to `camera.py`:
  - `_parse_shutter_speed_seconds()` — parses gphoto2 speed strings to floats.
  - `_get_shutter_speed_choices()` — queries the camera's actual supported speeds, sorted
    fastest→slowest; falls back to a built-in table if the widget is unavailable.
  - `_drain_camera_events()` — consumes pending USB events after trigger_capture sequences.
- **Wizard: optional HDR burst at maximum eclipse**: The *Phenomena* page now includes an
  "HDR burst at maximum eclipse" checkbox. When enabled, a `take_hdr` command is inserted at
  MAX − 10 s in the generated script, using the inner-corona exposure as the fastest speed and
  the number of stops chosen via the accompanying spin-box (default: 7, range 2–16).
- **Delete Saved Cameras**: A "Delete Camera" button has been added to the *Equipment* page of
  the wizard, next to the camera drop-down. The button is enabled only when a saved camera is
  selected. Clicking it shows a confirmation dialog and, on confirmation, removes the camera from
  `~/.sew_wizard_config.json` and from the drop-down, then resets the page to "New Camera...".
  A `delete_camera()` method was added to `ConfigManager` to support this.
- **Dual-camera support for same model, and multi-config per camera**: Two cameras of the
  same brand and model (e.g. two Canon EOS 80D bodies) can now be used simultaneously.
  Additionally, the same physical camera body can be saved under **multiple** configuration
  names (e.g. `"Canon EOS 80D (telescope)"` and `"Canon EOS 80D (lens)"`) so that
  different scripts can target the right optical setup without any code change.

  A serial-number → aliases mapping is stored in `~/.sew_wizard_config.json` under
  `camera_aliases`.  At runtime, each detected camera's serial number is read via the
  gphoto2 `serialnumber` widget and looked up in this map; if a match is found the camera
  is exposed under **all** its registered alias names, so whichever alias the current script
  uses will be found.  If no alias map exists the original behaviour (model name as key) is
  preserved unchanged.

  New internal helpers in `camera.py`:
  - `get_camera_by_port(model_name, port, alias)` — opens a camera at a specific USB port and
    optionally assigns it an alias name, avoiding the conflict that arises when two bodies of
    the same model are auto-detected.
  - `get_serial_number(camera)` — reads the `serialnumber` gphoto2 widget; returns `None` if
    the camera does not expose a serial number.
  - `get_camera_dict()` now accepts an optional `alias_map` dict and applies the mapping when
    provided.

  New methods on `ConfigManager` (`location_ui.py`):
  - `get_camera_aliases()`, `set_camera_alias()`, `delete_camera_alias()`,
    `get_serial_for_alias()`.

  **Wizard UX** (`wizard.py`): The *Equipment* page gains a **"Detect Connected Camera"**
  button. Connect exactly one camera, enter its alias name, click the button — SEW reads the
  serial number and saves the mapping. A green ✓ next to the name field confirms a mapping is
  stored; a grey hint appears otherwise. Repeat the process (one camera at a time) for each
  body that shares a model name with another.

### Changed
- **`take_picture` now uses `trigger_capture` instead of `capture_image`**: The shutter is
  fired with `gp_camera_trigger_capture`, which returns immediately without blocking on the
  file being written to the memory card. Pending USB events (CaptureComplete / ObjectAdded)
  are drained with `_drain_camera_events()` afterwards. A fallback to `GP_CAPTURE_IMAGE` is
  retained for cameras whose driver does not support `trigger_capture`.
- **`take_picture` camera settings applied in one USB round-trip**: `__adapt_camera_settings`
  previously issued a separate `gp_camera_set_config` call (plus a 100 ms sleep) for each of
  ISO, aperture, and shutter speed. ISO and shutter speed are now mutated in memory on the
  shared config tree and pushed to the camera in a single round-trip with no forced sleep,
  reducing per-shot overhead by ~300 ms. Aperture is kept in its own isolated round-trip so
  that a failure on a telescope or fixed-aperture lens never silently rolls back the ISO and
  shutter speed that were already applied.


## [1.5.1] - 2026-03-05

### Added
- **Delete Saved Locations**: A "Delete Location" button has been added to `LocationWidget` (used
  by both the main GUI location popup and the wizard). When a saved location is selected from the
  drop-down, the button becomes active; clicking it shows a confirmation dialog and, on
  confirmation, removes the location from `~/.sew_wizard_config.json` and from the drop-down.
  A `delete_location()` method was added to `ConfigManager` to support this.

### Fixed
- **Nikon burst mode not reset after `take_burst`**: After a `take_burst` command completed, the
  Nikon camera's capture mode (`capturemode` / `stillcapturemode`) and `burstnumber` were left in
  burst/continuous state. All subsequent `take_picture` commands therefore fired bursts instead of
  single frames. `take_burst` now resets the camera back to single-frame mode (and `burstnumber`
  to 1) immediately after the burst capture. As a second layer of defence, `take_picture` also
  explicitly enforces single-frame mode on Nikon cameras before each capture.
- **Timezone detection for sea/ocean locations**: Observing locations over water (e.g. in the
  Mediterranean Sea) were assigned `Etc/GMT` (UTC) because `TimezoneFinder.timezone_at()` only
  covers land polygons. The new `_find_timezone()` helper in `reference_moments.py` now uses
  `timezone_at_land()` first; when that returns `None` (sea location), it scans surrounding
  points at increasing step sizes (0.5°–5°) until the nearest land timezone is found. This
  ensures that, for example, a location at 39.924°N, 1.4271°E is correctly assigned
  `Europe/Madrid` instead of UTC. The same fix is applied to the job-scheduling table in the
  GUI (`gui.py`).

## [1.5.0] - 2026-02-26

### Added
- **GPS Location from Smartphone (`📱 Get GPS from Phone`)**: Capture your exact observation
  coordinates directly from your phone's GPS — no app installation required.
  - New `phone_gps` module (`src/solareclipseworkbench/phone_gps.py`) with a `WebGpsServer` class
    that starts a self-signed HTTPS server on the laptop.
  - Phone opens the URL in any browser (Chrome, Safari, Firefox); the browser Geolocation API
    reads the GPS and submits coordinates via a plain HTML form (immune to SSL/CORS blocking).
  - **📱 Get GPS from Phone** button added to `LocationWidget`, used by both the wizard and the
    main GUI location popup. When clicked, a dialog shows the server URL and waits for the phone
    to submit; latitude, longitude and altitude are filled in automatically on receipt.
  - Automatic **altitude fallback**: if the browser does not supply altitude (common on Android
    with WiFi/cell positioning), the Open-Elevation API is queried in the background using the
    received lat/lon, consistent with the existing geocoding workflow.
  - Works over **WiFi or phone hotspot** — no internet connection is needed at the observation
    site. Step-by-step hotspot instructions for Android and iPhone are in `docs/GPS_PHONE.md`.
  - New standalone script `scripts/get_gps_location.py` with `--web` (recommended) and
    `--smartphone HOST` modes, replacing the old Garmin-specific script.
- **GPS Phone documentation** (`docs/GPS_PHONE.md`): Full guide covering WiFi, phone-as-hotspot
  (Android + iPhone), accepting the self-signed certificate warning in Chrome/Safari/Firefox,
  manual coordinate entry as a fallback, and a troubleshooting table.

## [1.4.0] - 2026-02-23

### Added
- **Location Search & Saved Locations in GUI**: The Location popup in the main GUI now includes the
  same saved-locations drop-down and address-search functionality.
  - Saved-locations drop-down populated from `~/.sew_wizard_config.json`; last-used location is
    automatically selected when the popup opens.
  - Address-search bar (requires `geopy`) geocodes any city, street, or landmark via Nominatim and
    fetches elevation from the Open-Elevation API in a background thread.
  - "Save Location" button to persist a named location for future sessions.
  - The map auto-updates whenever coordinates change (300 ms debounce); the manual "Plot" button has
    been removed.
- **Script Generation Wizard (`sew_wizard`)**: New PyQt6-based 5-page wizard for automated eclipse photography script generation
  - Page 1: Eclipse configuration with date, location, and free geocoding service
  - Page 2: Camera equipment settings (name, ISO range, aperture, sync intervals)
  - Page 3: Phenomena selection (partial, diamond ring, Baily's beads, corona, prominences, chromosphere, earthshine, voice prompts, solar filter)
  - Page 4: Summary and script preview
- **Exposure Calculator**: Scientific exposure calculation based on Xavier Jubier's data
  - 2D interpolation using sun altitude (0-60°) and observer altitude (0-3000m)
  - 18 phenomenon exposure tables covering all eclipse phases
  - Support for ND 4.0 and ND 5.0 solar filters
  - Automatic ISO adjustment when exposures exceed hand-held limits (1/30s)
  - Realistic camera shutter speeds (standard 1/3-stop increments)
- **Comprehensive Partial Phase Coverage**: Generate 300+ shots automatically
  - All partial phase shots from C1→C2 and C3→C4
  - User-configurable intervals (time-based or magnitude-based)
  - Sun altitude filtering to skip shots when sun is below horizon
  - Applied to C1/C4 contact moments and all partial phases
- **Free Geocoding Service**: Convert addresses to coordinates without API keys
  - Nominatim (OpenStreetMap) for address → latitude/longitude
  - Open-Elevation API for altitude lookup
  - Background thread processing to prevent UI blocking
  - Visual feedback with status messages
- **Smart Totality Optimization**:
  - Adaptive corona shot intervals based on totality duration
  - Automatic gap filling between major phenomenon
  - Earthshine feasibility checking (only during totality with sufficient time)
  - Prominence shots in early totality
  - Chromosphere shots before C3
  - 10-second buffer zones to prevent command overlap
- **Camera-Specific Optimizations**:
  - Nikon burst mode: parameter = number of pictures (default: 30)
  - Canon burst mode: parameter = duration in seconds (default: 3)
  - Automatic detection based on camera name
- **Time Format Improvements**: Consistent h:mm:ss.0 format throughout all scripts
- **CSV Parsing**: Proper handling of commas in command descriptions for reliable import/export

### Changed
- **Script Parsing**: Updated `utils.py` and `scripts.py` to use Python csv module for robust parsing
- **Settings file location**: The GUI settings file (`SolarEclipseWorkbench.ini`) is now stored as a hidden file in the home directory (`~/.SolarEclipseWorkbench.ini`) instead of the current working directory, consistent with `~/.sew_wizard_config.json`.

### Fixed
- **Nikon Z8 (and Z-series mirrorless) camera support**:
  - Camera initialization no longer crashes when the `drivemode` widget is absent; the Z-series
    uses a different capture-mode model and does not expose this gphoto2 widget.
  - `__adapt_camera_settings` now automatically sets the camera to Manual (M) mode before
    applying ISO, aperture, and shutter speed. On the Z8 the Exposure Time property is read-only
    in any mode other than Manual, so the software previously failed to apply settings.
  - The `autoiso` widget (also absent on the Z8) is now accessed in a try-except block so its
    absence is silently ignored.
  - Burst mode (`take_burst`) tries the `capturemode` widget first (older Nikon DSLRs) and falls
    back to `stillcapturemode` with a numeric value (Z-series mirrorless cameras).
  - `gp_widget_set_value` calls for exposure-program now pass a `str` value as required by the
    gphoto2 Python binding (was incorrectly passing an `int`, causing a `TypeError`).
- **macOS USB device contention (`[-53] Could not claim the USB device`)**:
  - `get_free_space` and `get_space` now return the last successfully cached value when error -53
    is received, instead of attempting a full camera reinitialisation (which always fails for the
    same reason and produced cascading tracebacks).
  - `get_battery_level` downgrades the -53 log message from WARNING to DEBUG, since the macOS
    `ptpcamerad` daemon reclaiming the USB connection after a capture is normal and expected.
  - `CameraOverview._gather_camera_info` reuses existing camera objects instead of opening fresh
    USB connections on every sync, avoiding collisions with the connection held by `take_picture`.
  - Updated TODO.md with permanent macOS solutions: setting "No application" in Image Capture
    (recommended) or `sudo launchctl disable system/com.apple.ptpcamerad`.


## [1.3.0] - 2026-02-04

### Added
- Introduce `BaseCamera` and a `VirtualCamera` for simulator mode.
- Add `GPhotoCameraAdapter` and vendor adapters (`CanonCamera`, `NikonCamera`) to wrap gphoto2 cameras.
- `get_camera_dict(..., is_simulator=True)` returns a `VirtualCamera` for easy testing and demos.
- Add gphoto-style stubs on `VirtualCamera` (`get_config`, `set_config`, `get_storageinfo`, `exit`) for compatibility.
- Background probing of cameras off the GUI thread; model updates scheduled on the main thread to avoid UI freezes.
- Added defensive helpers and fallbacks for gphoto2 errors (storage/time/config) and a one-time reinitialisation retry.
- Low-level gphoto fallbacks for capture operations to improve reliability with real cameras.
- Tests and example script for the virtual camera added (`tests/test_virtual_camera.py`, example_scripts/testVirtualCamera.txt).
- Documented simulator CLI flag in README; added runtime prints/logging to aid diagnostics.
 - Use Astropy/IERS to compute Delta T (TT − UT1) for eclipse reference times
 - Keep CSV-based Delta T as a fallback if no internet is available; added robust parsing of `td_ge`/`t0` and safeguards when ephemeris files are unavailable.


## [1.2.4] - 2026-01-16

### Added
- Add LAST command to the scripts
- Execute external commands from scripts
- Installation using `pip install solareclipseworkbench`
- Calculate the reference moments in Solar Eclipse Workbench, not using an external library anymore.  The Besselian elements are taken from the Five Millennium Canon of Solar Eclipses, which is available at https://eclipse.gsfc.nasa.gov/SEcat5/SEcat5.html.
- Extra information about the eclipses (maximum duration, type of eclipse, etc.) is now available in the drop-down menu to select eclipses.
- Added first unittests for the solar_eclipse module.
- Calculate the Besselian elements directly in the code.
- Adapt solar radius to the most recent value of 959.95 ±0.05 arcseconds as found by the Besselian elements team (https://www.besselianelements.com/).


## [1.1.1] - 2025-04-28

### Fixed

- Fix crash when reference moment not known

## [1.1.0] - 2025-03-25

Version 1.1.0 fixes some bugs, makes it possible to take pictures through a telescope and provides new scripting possibilities. Version for the partial solar eclipse of March 29, 2025.

### Added
- Take pictures when a camera is attached to a telescope

### Fixed
- No longer counting down after the eclipse
- Fix astronomy import
- Scripts updates

## [1.0.0] - 2024-03-29

### Added
First version of Solar Eclipse Workbench. To be tested during the total solar eclipse of April 8, 2024 in Mexico, USA and Canada.

- Add logo
- Add poetry and installation instructions
- Placeholders for basic commands
- Added all needed camera methods
- Camera overview
- Fixes for the camera class
- Placeholder for location-related functions
- Fix get_camera_overview after testing
- Scheduling commands
- Calculate eclipse reference moments
- Documentation updates
- Extra calulations for the reference times
- Notifications
- Fix timezone
- Placeholder for GUI
- Handling of different eclipse types
- Add support for annular eclipses
- Script to convert Solar Eclipse Maestro scripts
- Countdown to reference moments
- Schedule tasks
- Documentation + corrected formatting of countdown clocks
- First version of camera widget
- Schedule tasks
- Update camera overview
- Documentation + clean-up
- Synchronisation of the cameras
- General script and documentation updates
- Simulator mode + job scheduling
- Add take_burst method
- Start simulation at given time relative to reference moment.
- Add camera_name to CameraSettings
- Start of simulation + Display scheduled jobs
- Added simulator icon
- Fix crash if camera is not known
- Visualisation of scheduled jobs
- Camera updates
- Apply time format from setting to scheduled jobs
- Show duration for total eclipses
- Proper alignment of scheduled jobs table cells
- Improved robustness + proper formatting
- Camera overview + Time formatting
- Add possibility to start up gui.py using parameters for location and eclipse date.
- Improved logging + Added setters for controller
- Saving & loading settings
- Extract camera overview as dictionary
- Save settings via toolbar icon
- Made file chooser more robust
- Fix cameras_sync command
- Documented UI functionality
- Calculate next 20 solar eclipses and display in drop-down menu
- Fix cancel button of SettingsPopup
- Disable/enable camera icon in UI toolbar
- Add output from logger to file
- Disconnect camera(s) when UI is closed
- Convert TAKEBST and TAKEBKT to Solar Eclipse Workbench command in convert_sem_files script.
- Scroll to jobs that are up next
- Add pkg-config to installation instruction for apple silicon
