# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Solar Eclipse Workbench (`sew`) is a Python/PyQt6 desktop app for planning and automating solar eclipse photography. It calculates eclipse contact times (C1–C4, max) for an observer location, schedules camera commands (take a picture, burst, bracket, HDR, play a voice prompt, run a shell command) relative to those contact times using `apscheduler`, and fires them via `gphoto2` against connected DSLR/mirrorless cameras. A second entry point, `sew_wizard`, is a step-by-step GUI for generating the photography script files that `sew` executes.

## Commands

Environment is managed with `uv` (not raw pip/venv) and requires Python 3.11+.

```bash
uv sync --group dev          # install/sync the dev environment
uv run sew                   # run the GUI app from source
uv run sew_wizard            # run the script-generation wizard from source
```

Tests: root-level `test_*.py` files and `tests/` both hold tests; run with plain `pytest` (no custom pytest config exists — rootdir is the repo root).

```bash
uv run pytest                          # full suite
uv run pytest tests/test_solar_eclipse.py            # one file
uv run pytest tests/test_solar_eclipse.py::TestSolarEclipse::test_solve_quadrant   # one test
uv run pytest -k sony                  # by keyword
```

Note: imports across test files are inconsistent — most use `from solareclipseworkbench.x import ...` (the editable-installed package), a few use `from src.solareclipseworkbench.x import ...` (relying on repo root being on `sys.path`). Both work when tests are run from the repo root via `uv run pytest`; match whichever style is already used in the file you're editing.

Other scripts:
```bash
python3 scripts/sync_uv_lock_to_pyproject.py --apply --pin   # after `uv sync --upgrade`, sync resolved versions back into pyproject.toml
python scripts/get_gps_location.py --web                     # helper to pull GPS coords from a phone (see docs/GPS_PHONE.md)
python scripts/print_fnumber_choices.py                      # diagnose gphoto2 aperture widget values for a connected camera
```

Packaging: bump `version` in `pyproject.toml`, then `uv build && uv publish`.

## Architecture

All source lives in `src/solareclipseworkbench/`. Two console entry points are defined in `pyproject.toml`: `sew = gui:main` and `sew_wizard = wizard:main`.

**Astronomical core** (no UI/hardware dependencies):
- `solar_eclipse.py` — Besselian element math to find eclipses and local circumstances; reads `eclipse_besselian.csv` and `deltat.csv` shipped alongside the module.
- `besselian_element_generator.py`, `nutation.py`, `vec.py` — supporting astronomical calculations.
- `reference_moments.py` — turns a lon/lat/altitude/date into a dict of `ReferenceMomentInfo` (C1–C4, MAX, sunrise/sunset) with UTC + local time, azimuth, altitude. `calculate_reference_moments()` is the main entry point other modules call.
- `exposure_calculator.py` — exposure/shutter-speed recommendations as a function of solar altitude and eclipse phase; also rounds requested values to a camera's actual supported shutter-speed list.

**Scripting / scheduling pipeline** — this is the core control flow, spread across three files:
1. `scripts.py` — parses a text script file (see script format below) line by line, including `for`/`endfor` loop expansion and back-compat conversion of legacy Solar Eclipse Maestro commands (`TAKEPIC`, `TAKEBST`, `TAKEBKT`, `PLAY`, `FOR`). Produces a normalized, flattened script (`convert_script`/`convert_command`).
2. `utils.py` — `observe_solar_eclipse()` / `schedule_commands()` / `schedule_command()` take the normalized script plus the reference-moment dict and camera dict, resolve each line's absolute UTC execution time (including simulation-mode offsets and GPS/computer clock drift compensation), and register a job per command on an `apscheduler` `BackgroundScheduler`. The `COMMANDS` dict maps script command names to their implementing functions.
3. `commands.py` / `camera.py` / `notifications.py` — the actual command implementations: `execute_command` (background shell command), `take_picture`/`take_burst`/`take_bracket`/`take_hdr`/`sync_cameras` (gphoto2 camera control), `voice_prompt` (plays a sound file, see `check_notification` for pre-validation so a bad prompt name is caught at schedule time, not when it fires mid-eclipse).

**Camera layer** (`camera.py`, largest module): wraps `gphoto2` for Canon/Nikon/Sony bodies, which differ significantly in supported config paths (bracketing syntax, continuous-shooting modes, PC vs PC+Camera save destination). `CameraSettings` holds shutter/aperture/ISO. `LiveViewThread` drives the live-view preview window and coordinates a USB lock with scheduled shots (a preview frame is silently skipped rather than delaying or blocking a scheduled shot; live view auto-pauses from 15s before C2 to 15s after C3 so the USB bus is free during totality). `get_camera_dict()` enumerates connected cameras and applies user-configured aliases (for running two bodies of the same model).

**GUI** (`gui.py`, largest file by line count): implements the main app window using an explicit MVC split — `SolarEclipseModel`, `SolarEclipseView`, `SolarEclipseController` (see module docstring). Built on PyQt6 + matplotlib (eclipse visualization) + geopandas (map). `location_ui.py` provides the location-picker widget and `ConfigManager` (persisted settings, incl. camera aliases and Sony continuous-mode preference), using `QSettings`, which stores to `~/.SolarEclipseWorkbench.ini`.

**Wizard** (`wizard.py`, second-largest file): a separate PyQt6 multi-page wizard (`sew_wizard` entry point) that walks the user through eclipse selection, location (including phone-GPS pairing via `phone_gps.py` and USB GPS via `usb_gps.py`), and camera/exposure configuration to generate a script file consumable by `sew`. Reuses `exposure_calculator.py` and `reference_moments.py`.

**GPS** (`phone_gps.py`, `usb_gps.py`): two independent ways to get an accurate location/time source — a phone-based web flow (also exposed via `scripts/get_gps_location.py`, documented in `docs/GPS_PHONE.md`) and a serial NMEA USB GPS receiver. GPS-vs-computer clock offset feeds into `schedule_command`'s `gps_time_offset` to correct shot timing.

**`hardware_problems.py`**: centralized reporting of hardware/config issues (missing camera, bad voice prompt, etc.) surfaced to the GUI console rather than raising and killing the scheduler.

**Data files bundled with the package** (declared in `pyproject.toml` package-data): `eclipse_besselian.csv`, `deltat.csv`, `sound/**`, `example_scripts/**`, `img/**`, `*.bsp`. Root-level `de421.bsp`, `de440s.bsp`, `moon_080317.tf`, `moon_pa_de421_1900-2050.bpc`, `lunar_limb_band_v1.bin` are Skyfield/SPICE ephemeris data used for astronomical calculations, not source.

## Script file format (what `scripts.py`/`utils.py` parse)

Photography scripts are CSV-like text files where each line schedules a command relative to a reference moment (`C1`, `C2`, `MAX`, `C3`, `C4`, `SUNRISE`, `SUNSET`, or `LAST` = time of the previous command), with a `+`/`-` sign and an `hh:mm:ss.s` offset. Commands: `take_picture`, `take_burst`, `take_bracket`, `take_hdr`, `voice_prompt`, `sync_cameras`, `command`, plus `for`/`endfor` loops. Full syntax and camera-specific quirks (Canon bracket-step syntax vs Sony named modes vs Nikon `"step count"` syntax, Sony PC-mode buffer limits for `take_hdr`) are documented in the README's "Script file format" section — read it before changing script parsing/scheduling logic.

## Known constraints worth knowing before touching related code

- Below ~5° solar altitude, exposure/shutter-speed math has historically been fragile (see README's pinned notice and `e12b46f`/related commits) — be careful with changes to `exposure_calculator.py` near low-altitude/partial-phase edge cases.
- Camera command timing accuracy is enforced by the scheduler's default 1s misfire grace time plus a hard timeout inside the camera USB-lock path (shots are dropped rather than fired late) — don't relax either without understanding the totality-timing implications.
- Sony cameras in `PC` (not `PC+Camera`) save-destination mode can lose an entire `take_hdr` sequence if shot count exceeds the camera's internal buffer.
