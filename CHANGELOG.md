# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.0.0rc1] - 2026-07-31

### Added
- Sony: `take_bracket` is now supported, please consult README (Issue #146)
- It is now possible to re-connect cameras without restarting the app, please consult README (Issue #149)
- Sony: `--sony-cont-mode` command line option has been added, to override automatic selection of the Continuous capture mode, please consult README (Issue #145)
- Timings for reference moments now show milliseconds to first digit (Issue #137)
- Scheduler has been replaced, it now supports precision down to microseconds (Issue #137)
- Sony: banner with warning(s) can now be closed

## Fixed
- Sony: `take_burst` is now properly supported, please consult README (Issue #145)
- Sony: `PC` mode is now working correctly and downloads all files from camera(s)
- Sony: no more 4 seconds delay before shooting if no lens is detected
- Sony: many small vendor specific fixes and additions (Issues #147, #150 and #151)
- Live View: it can now be properly disabled
- Improved log messaging (more to come)
- Rewrote the Sony section in the README
- Sony: banner with warning(s) is now more informative (updated the text)
- Reclaim the USB device from macOS' PTP daemon (and fix the -53 advice)- #164 by @mrosseel
  - This means that on macOS, Solar Eclipse Workbench should not be started with *sudo* anymore.
- Stop the previous scheduler when a new script is loaded- #163 by @mrosseel
  - Loading a second script left two schedulers running and every command fired twice.

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
