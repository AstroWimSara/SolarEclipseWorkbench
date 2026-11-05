# Solar Eclipse Workbench

![Solar Eclipse Workbench logo](src/solareclipseworkbench/img/logo-small.jpg)

**Important notice**:  Versions older than 2.0.0 calculate shutter speeds that are too long when the sun is below 5 degrees.  If you use an older version, [upgrade](#upgrading-solar-eclipse-workbench) and generate your scripts again.

## What it does

Solar Eclipse Workbench (SEW) takes the pictures of a solar eclipse for you, so you can watch the eclipse instead of the cameras.  It runs on Linux, macOS and Windows (in WSL) and controls Canon, Nikon and Sony cameras over USB with gphoto2.

- **Contact times for your location.**  For the eclipse date and your observing location (typed in, picked on a map, or read from a USB GPS receiver or your phone), SEW calculates the times of first contact (C1), second contact (C2), maximum eclipse, third contact (C3) and fourth contact (C4), with the altitude and azimuth of the Sun.  C2 and C3 are corrected for the profile of the lunar limb, and the Baily's beads windows around them are shown.
- **A script with what to do when.**  A photography script is a text file with one line per action, timed relative to the contact times, for example *take a bracket of 7 exposures 5 seconds after C2*.  Actions are taking a picture, a burst, a bracket or an HDR sequence, playing a voice prompt, or running a shell command.  The [Configuration Wizard](#running-the-configuration-wizard) writes a script for you from your cameras, lenses and the eclipse circumstances, with exposures that follow the Sun's altitude and the phase of the eclipse.  Scripts from Solar Eclipse Maestro can be used as well.
- **Running the script.**  SEW schedules every command at its exact time and fires the cameras.  Several cameras can be used at once.  The computer clock can be corrected with GPS time.  A simulation mode runs the script ahead of the eclipse, with real or virtual cameras, so you can rehearse it.
- **Checking before and after.**  The `Timeline` window shows per camera whether commands follow each other too closely to be taken in time, the `Run report` reads the log of a run back and tells what became of every command, and `Compare sites` puts candidate observing sites side by side (duration of totality, altitude of the Sun, cloud forecast).

More background, eclipse reports and the story behind SEW are on the [Deep Sky Wim blog](https://deepskywim.blogspot.com/search/label/Solar%20Eclipse%20Workbench).

## Table of contents

[//]: # (- [Solar Eclipse Workbench]&#40;#solar-eclipse-workbench&#41;)
[//]: # (  - [Table of contents]&#40;#table-of-contents&#41;)
- [Solar Eclipse Workbench](#solar-eclipse-workbench)
  - [What it does](#what-it-does)
  - [Table of contents](#table-of-contents)
  - [Installation instructions](#installation-instructions)
    - [Installation with the installer script on macOS and Linux](#installation-with-the-installer-script-on-macos-and-linux)
    - [Installation on macOS](#installation-on-macos)
    - [Installation on Ubuntu 26.04](#installation-on-ubuntu-2604)
    - [Installation on Ubuntu 24.04](#installation-on-ubuntu-2404)
    - [Installation on Windows 11](#installation-on-windows-11)
      - [Installation with the installer script](#installation-with-the-installer-script)
      - [Manual installation](#manual-installation)
    - [Make cameras accessible in wsl](#make-cameras-accessible-in-wsl)
      - [Replace the Windows USB driver with WinUSB (required for gphoto2)](#replace-the-windows-usb-driver-with-winusb-required-for-gphoto2)
    - [Sony PC Remote settings discussion](#sony-pc-remote-settings-discussion)
    - [Fujifilm X cameras](#fujifilm-x-cameras)
  - [Upgrading Solar Eclipse Workbench](#upgrading-solar-eclipse-workbench)
  - [Running Solar Eclipse Workbench](#running-solar-eclipse-workbench)
    - [Command line parameters](#command-line-parameters)
    - [UI functionality](#ui-functionality)
      - [Observing location](#observing-location)
      - [Eclipse date](#eclipse-date)
      - [Reference moments](#reference-moments)
      - [Camera overview](#camera-overview)
      - [Simulation mode](#simulation-mode)
      - [Job scheduling](#job-scheduling)
      - [Exposure compensation](#exposure-compensation)
      - [Interrupting scheduled jobs](#interrupting-scheduled-jobs)
      - [Datetime format](#datetime-format)
      - [Saving settings](#saving-settings)
      - [Live view](#live-view)
      - [Script timeline](#script-timeline)
      - [Run report](#run-report)
      - [Compare sites](#compare-sites)
      - [Phone dashboard](#phone-dashboard)
  - [Running the Configuration Wizard](#running-the-configuration-wizard)
  - [USB GPS device](#usb-gps-device)
    - [Supported hardware](#supported-hardware)
    - [One-time setup on Linux / WSL](#one-time-setup-on-linux--wsl)
    - [macOS](#macos)
    - [How to use](#how-to-use)
    - [GPS time correction](#gps-time-correction)
  - [USB relay shutter trigger](#usb-relay-shutter-trigger)
  - [Using two cameras of the same model, or one camera with multiple setups](#using-two-cameras-of-the-same-model-or-one-camera-with-multiple-setups)
    - [Step-by-step setup](#step-by-step-setup)
  - [Script file format](#script-file-format)
    - [General remarks](#general-remarks)
    - [Reference moments](#reference-moments-1)
    - [Commands](#commands)
  - [Astronomical calculations](#astronomical-calculations)
  - [Shortcomings](#shortcomings)
  - [Converting scripts from Solar Eclipse Maestro](#converting-scripts-from-solar-eclipse-maestro)
  - [Error handling](#error-handling)
  - [Commands that are too close together](#commands-that-are-too-close-together)
  - [Timing shots around C2 and C3](#timing-shots-around-c2-and-c3)
  - [Handling camera(s) disconnect(s)](#handling-cameras-disconnects)
  - [Development Guide](#development-guide)
    - [Installation on macOS](#installation-on-macos-1)
    - [Installation on Ubuntu 24.04](#installation-on-ubuntu-2404-1)
    - [Installation on Windows 11](#installation-on-windows-11-1)
  - [Run Solar Eclipse Workbench from the development environment](#run-solar-eclipse-workbench-from-the-development-environment)
  - [Upgrading all dependencies to the latest version](#upgrading-all-dependencies-to-the-latest-version)
  - [Create and upload a new pip package](#create-and-upload-a-new-pip-package)
  - [License](#license)
  - [Changelog](#changelog)
  - [Image attributions](#image-attributions)
    - [GUI icons](#gui-icons)

## Installation instructions

The quickest way is the installer script: [`install.sh`](#installation-with-the-installer-script-on-macos-and-linux) on macOS and Linux, [`install-sew.cmd`](#installation-with-the-installer-script) on Windows.  The sections after that describe the same steps by hand.

### Installation with the installer script on macOS and Linux

Open a terminal and run, as your normal user (not with `sudo`):

```bash
curl -LsSf https://raw.githubusercontent.com/AstroWimSara/SolarEclipseWorkbench/main/scripts/install.sh | bash
```

or download [`install.sh`](https://raw.githubusercontent.com/AstroWimSara/SolarEclipseWorkbench/main/scripts/install.sh) and run `bash install.sh`.  The script:

- installs [uv](https://docs.astral.sh/uv/) and, with it, Solar Eclipse Workbench in its own environment with its own Python.  The packages from PyPI include libgphoto2, GDAL and Qt, so on most computers no Homebrew, GDAL or Python installation is needed.
- on Linux (Debian, Ubuntu, Raspberry Pi OS), installs the few system packages that are still needed (gstreamer for the voice prompts, the Qt display libraries, and gphoto2 for the camera permissions) and asks for your password for that.  It adds you to the `plugdev` and `dialout` groups (cameras and USB GPS without `sudo`), and masks the `gvfs-gphoto2-volume-monitor` service so the desktop does not claim the cameras.  On another distribution, it says which packages to install yourself.
- on macOS older than 14 (Apple Silicon) or 15 (Intel), for which there is no prebuilt gphoto2 package, installs gphoto2 with [Homebrew](https://brew.sh/) so it can be built.  This needs Homebrew and the Xcode command line tools.
- adds `Solar Eclipse Workbench`, `Eclipse Wizard` (the wizard) and `Eclipse Simulation` (the application in [simulation mode](#simulation-mode), to rehearse a script) to the applications menu (Linux) or to `~/Applications` (macOS, also in Launchpad).  From a terminal, start them with `sew`, `sew_wizard` and `sew --sim`.

Log out and back in once if the script added you to a group.  Run the script again to upgrade.  Options: `--yes` (do not ask before starting), `--no-shortcuts`, `--dry-run` (only show what it would do) and `--uninstall` (removes the application and its shortcuts, and keeps your settings and logs).

It needs 64-bit Linux with glibc 2.34 or newer on x86-64 (Ubuntu 22.04, Debian 12 and newer) or 2.39 or newer on ARM64 (Ubuntu 24.04, Debian 13, Raspberry Pi OS Trixie and newer), because Qt is not published for older systems.  On those, use the manual installation below.

### Installation on macOS

- Create a new python environment.  You can use venv or any python environment manager for this (like anaconda, micromamba, ...)

```bash
python -m venv solareclipseworkbench
cd solareclipseworkbench
source bin/activate
```

- For modern Apple Mac computers (using Apple Silicon processors), install [homebrew](https://brew.sh/). Add your homebrew/bin directory to your PATH. Then install gphoto2 and GDAL (required by geopandas) using homebrew:

```bash
export PATH=<location_of_homebrew_installation>/bin:$PATH
brew install gphoto2 pkg-config gdal
```

- Note: macOS normally ships with an older system Python (for example 3.9.6). Since the instructions above use Homebrew to install `gphoto2`, it's convenient to also install a newer Python via Homebrew and create the virtual environment with that. Solar Eclipse Workbench does need python 3.11 or higher to work.  

```bash
# install Python 3.11 via Homebrew
brew install python@3.11

# create and activate the venv using the Homebrew Python
python3.11 -m venv solareclipseworkbench
cd solareclipseworkbench
source bin/activate
```

- Install the Solar Eclipse Workbench:

```bash
pip install solareclipseworkbench
```

### Installation on Ubuntu 26.04

- Install gstreamer to be able to play the sound notifications by executing the following line in the terminal

```bash
sudo apt update
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0 libxcb-cursor0 libcairo2-dev python3.14-venv gstreamer1.0-plugins-good
```

- Install gphoto2 to be able to access the cameras by executing the following line in the terminal

```bash
sudo apt install gphoto2 libgphoto2-dev python3-gphoto2
```

- Make sure that gvfs is not started automatically. Use `systemctl --user mask` to properly disable the gvfs gphoto2 services. **Do not use `chmod -x`** — removing the execute bit causes the Files (Nautilus) application to hang on open because GVFS still attempts to launch the binaries and waits for a timeout before giving up.

  Mask the systemd user services so they are never started.  Execute this as a normal user (not with sudo):

  ```bash
  systemctl --user mask gvfs-gphoto2-volume-monitor.service
  ```

  To verify:

  ```bash
  systemctl --user status gvfs-gphoto2-volume-monitor.service
  ```

  Both should show `masked`.

- Install `gdal-config`, required by `geopandas` (especially on Raspberry Pi):

```bash
sudo apt install libgdal-dev gdal-bin python3-pip
```

- Create a new python environment.  You can use venv or any python environment manager for this (like anaconda, micromamba, ...)

```bash
python3 -m venv solareclipseworkbench
cd solareclipseworkbench
source bin/activate
```

- Install the Solar Eclipse Workbench:

```bash
pip install solareclipseworkbench
```


### Installation on Ubuntu 24.04

- Install gstreamer to be able to play the sound notifications by executing the following line in the terminal

```bash
sudo apt update
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0 libxcb-cursor0 libcairo2-dev python3.12-venv gstreamer1.0-plugins-good
```

- Install gphoto2 to be able to access the cameras by executing the following line in the terminal

```bash
sudo apt install gphoto2 libgphoto2-dev python3-gphoto2
```

- Make sure that gvfs is not started automatically. Use `systemctl --user mask` to properly disable the gvfs gphoto2 service. **Do not use `chmod -x`** — removing the execute bit causes the Files (Nautilus) application to hang on open because GVFS still attempts to launch the binary and waits for a timeout before giving up.

  If you previously used `chmod -x`, first restore the execute bit:

  ```bash
  sudo chmod +x /usr/lib/gvfs/gvfs-gphoto2-volume-monitor
  ```

  Then mask the systemd user service so it is never started:

  ```bash
  systemctl --user mask gvfs-gphoto2-volume-monitor.service
  ```

  To verify:

  ```bash
  systemctl --user status gvfs-gphoto2-volume-monitor.service
  ```

  Both should show `masked`.

- Install `gdal-config`, required by `geopandas` (especially on Raspberry Pi):

```bash
sudo apt install libgdal-dev gdal-bin python3-pip
```

- Create a new python environment.  You can use venv or any python environment manager for this (like anaconda, micromamba, ...)

```bash
python3 -m venv solareclipseworkbench
cd solareclipseworkbench
source bin/activate
```

- Install the Solar Eclipse Workbench:

```bash
pip install solareclipseworkbench
```

### Installation on Windows 11

GPhoto2, which controls the cameras, is only available for Linux and macOS.  On Windows, Solar Eclipse Workbench therefore runs in WSL (Windows Subsystem for Linux), and its windows open on the Windows desktop like any other application.  Windows 10 version 21H2 or later also works.

#### Installation with the installer script

The installer script does all the steps of the [manual installation](#manual-installation) and [makes the cameras accessible in WSL](#make-cameras-accessible-in-wsl):

- Download [`install-sew.cmd`](https://raw.githubusercontent.com/AstroWimSara/SolarEclipseWorkbench/main/scripts/windows/install-sew.cmd) (right-click the link, `Save link as...`), for example to your `Downloads` folder.
- Double-click `install-sew.cmd`, as your normal user (not `Run as administrator`).  It downloads the actual installer, [`install-sew.ps1`](scripts/windows/install-sew.ps1), and runs it.  Your browser may warn that this kind of file can harm your computer (choose `Keep`), and Windows may show `Windows protected your PC` (click `More info`, then `Run anyway`).
- If you prefer PowerShell, download `install-sew.ps1` instead and run:

```powershell
powershell -ExecutionPolicy Bypass -File $HOME\Downloads\install-sew.ps1
```

- The script:
  - installs WSL and Ubuntu 24.04.  If Windows has to restart, the script continues by itself after you log in again.  Ubuntu asks for a new Linux user name and password once; at the Linux prompt that follows, type `exit` to continue.
  - installs [usbipd-win](https://github.com/dorssel/usbipd-win), which passes USB devices from Windows to WSL,
  - installs gphoto2, gstreamer (for the voice prompts) and Solar Eclipse Workbench in Ubuntu, using [uv](https://docs.astral.sh/uv/),
  - adds `Solar Eclipse Workbench`, `Solar Eclipse Workbench Wizard`, `Solar Eclipse Workbench (simulation)`, `Share cameras with Solar Eclipse Workbench` and `Update Solar Eclipse Workbench` to the Start menu, and Solar Eclipse Workbench to the desktop,
  - asks you to connect your cameras and USB GPS receiver, lists the USB devices, and shares the ones you choose with WSL.
- Windows asks for permission (UAC) for the steps that need administrator rights.  If an error mentions virtualization, enable it in the BIOS or UEFI settings (Intel VT-x, AMD-V or SVM) and run the script again.
- A camera or GPS receiver only has to be shared once.  For a new one, use `Share cameras with Solar Eclipse Workbench` from the Start menu.  Once a device is shared, Solar Eclipse Workbench attaches it to WSL by itself every time it looks for cameras (`Camera(s)`, the wizard's `Test Camera...`) or starts the USB GPS, so you no longer type `usbipd attach` after connecting a camera.
- If a camera then gives `Could not claim the USB device` (error -53), replace its Windows driver once, as described in [Replace the Windows USB driver with WinUSB](#replace-the-windows-usb-driver-with-winusb-required-for-gphoto2).
- To upgrade, use `Update Solar Eclipse Workbench` from the Start menu, or run the script again.
- The application keeps a minimised console window open next to it, with the log.

#### Manual installation

- Open a terminal or powershell in Windows
- Install wsl by executing the command

```bash
wsl --install
```

- Reboot your computer
- Install Ubuntu 24.04 in wsl, buy opening a new terminal or powershell and executing the following command:

```bash
wsl.exe --install Ubuntu-24.04
```

- If you see any errors, make sure to check them.  One of the possible problems is that virtualization is not enabled in the BIOS.  It is important to enable this.
  
- Start using wsl by typing `wsl` in a new terminal.

- Install gstreamer to be able to play the sound notifications by executing the following line in the terminal

```bash
sudo apt update
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0 libxcb-cursor0 libcairo2-dev python3.12-venv
sudo apt install -y gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-ugly gstreamer1.0-plugins-bad libgstreamer1.0-dev pulseaudio \
  alsa-utils python3-gi gir1.2-gstreamer-1.0
```

- Install gphoto2 to be able to access the cameras by executing the following line in the terminal

```bash
sudo apt install gphoto2/noble libgphoto2-dev python3-gphoto2 python3-pip
```

- Create a new python environment.  You can use venv or any python environment manager for this (like anaconda, micromamba, ...)

```bash
cd
python3 -m venv solareclipseworkbench
cd solareclipseworkbench
source bin/activate
```

- Eventually, to make the sound notifications a bit faster, install pygobject:

```bash
sudo apt install libcairo2-dev libgirepository-2.0-dev gcc python3-dev gobject-* gir1.2-*
pip install pygobject
```

- Install `gdal-config`, required by `geopandas` (especially on Raspberry Pi):

```bash
sudo apt install libgdal-dev gdal-bin
```

- Install the Solar Eclipse Workbench:

```bash
pip install solareclipseworkbench
```

### Make cameras accessible in wsl

The USB devices are not automatically accessible in wsl.  The [installer script](#installation-with-the-installer-script) does the steps below for you.  To make the cameras accessible manually, the following steps should be taken:
- Download the usbipd-win package from [GitHub](https://github.com/dorssel/usbipd-win/releases)
- Install the package
- Start a PowerShell terminal as administrator
- Connect the cameras to the computer
- Execute the following command in the PowerShell terminal

```bash
usbipd list
```

- The cameras should be listed (with their camera name or as MTP USB Device).  The camera_id is the busid of the camera.  This can be found in the list of usbipd list.  The camera_id is a number with a colon and a number (e.g. 1:2).  The command to bind the camera to wsl is

```bash
usbipd bind --busid <camera_id>
```

- Attach the camera to wsl by executing the following command in a PowerShell terminal.  Make sure that a wsl terminal is also open.  Solar Eclipse Workbench does this by itself for every shared device when it looks for cameras or starts the USB GPS (with usbipd-win 4 or newer), so you only need it to test the camera outside the application, e.g. with `lsusb` or `gphoto2 --auto-detect`.

```bash
usbipd attach --wsl --busid <camera_id>
```

- The camera should now be available in wsl. You can test this by executing the following command:

```bash
lsusb
```

- The camera can not be accessed yet by the normal user.  To make this work, the user should be added to the plugdev group.  This can be done by executing the following command in the wsl terminal, and log in into :

```bash 
sudo usermod -aG plugdev $USER
```

#### Replace the Windows USB driver with WinUSB (required for gphoto2)

After attaching the camera with `usbipd`, Windows still keeps its own PTP/WIA driver active.
gphoto2 uses **libusb** and cannot claim a device that the Microsoft PTP driver already holds — this causes the error `[-53] Could not claim the USB device`.
You must replace the driver once per camera model using **Zadig**:

1. Download and run **Zadig** from [https://zadig.akeo.ie](https://zadig.akeo.ie) **on the Windows host** (not inside WSL).
2. Connect the camera and attach it to WSL with `usbipd attach --wsl --busid <busid>`.
3. In Zadig, open *Options → List All Devices* and select the camera (it may appear as "MTP USB Device" or the camera model name).
4. In the driver drop-down on the right, select **WinUSB**.
5. Click **Replace Driver** and wait for it to finish.
6. Detach and re-attach the camera so the new driver is used:

```powershell
usbipd detach --busid <busid>
usbipd attach --wsl --busid <busid>
```

You only need to do this once; the WinUSB driver persists across reboots for that USB device.


## Sony PC Remote settings discussion

To enable `PC Remote` mode on your Sony camera, please go to `MENU`, then go to `Tools` section and look for `USB Connection` setting (most probably, you will find it on the 4th screen). Press on it and choose `PC Remote` option. Note - this path applies for pre-2020 cameras; for post-2020 cameras the location of this setting might be different.

On the same screen, also search for `PC Remote Settings`. If you can't find it, it means your camera does not support saving photos to your SD card when it's being controlled from PC through USB connection. If you do find it, then you have the ability to choose between saving to `PC` or `PC+Camera` (post-2020 cameras also support `Camera` option).

For cameras which lack `PC Remote Settings`, using USB connection will come with the penalty of slow transfer of the photos, as these cameras usually have only micro USB port, which supports only USB2.0 speeds. For a 12MP camera, this might be acceptable (a 5 frame 3EV bracketing sequence centered around 1/20 takes between 8 to 12 seconds to complete, depending on the initial state of camera), but for 24MP and moreso for 42MP cameras, this might be unacceptable. We would suggest you try using Wi-Fi connection through scripts and `command` commands, as it should be much faster (but requires you are tech savvy enough to write such scripts; if you want a reference, you can take a look [here](https://github.com/fliker09/sec2025-scripts) - search for scripts which contain `http` keyword in their name). Another option would be to install an app right on your camera, which will work in a similar way to SEW - you can find it [here](https://github.com/pyzahl/SoFiMagic) (this also requires you are a bit tech savvy, but at least no scripting is involved).

For cameras which do have `PC Remote Settings` available, the situation is much better. These cameras usually have an USB-C port, which provides USB3.0 speeds (they are much higher than USB2.0 ones!). There is also an option of saving RAW files to SD card (`PC+Camera` option), but this option should be compared against the `PC` one, as your card's write speed might be, in fact, slower than the USB3.0 transfer speed. Test both options and see which one is faster for you! On a Sony A7R IIIA, both `PC` and `PC+Camera` options take around 8 to 12 seconds for a 5 frame 3EV bracketing sequence centered around 1/20 takes between 8 to 12 seconds to complete, depending on the initial state of camera.

A note on multiple Sony cameras connected - if they all fire in parallel or at least close enough in timing to clash in their data transfers periods, it's preferable that no more than one of the cameras save to PC, with the other(s) having `PC+Camera` option chosen instead.

Warnings: if you intend to use `PC` option with a camera which has an USB-C port, please ensure that the cable is USB3.0 rated and that the port on the PC to which this cable connects is, in fact, a proper USB3.0 one.
Another thing to keep in mind - filename prefix. If you have multiple Sony cameras connected and more than one is in `PC` mode for some reason, you must ensure that each of them are using unique prefix! Please check out `Set File Name` setting in the `Tools` section (most probably on the 5th screen).

Final note on the `PC+Camera` option - SEW will not actually save JPEG files to PC, they will be ignored and the PTP events on camera flushed, with RAW files being consistently written to SD card (please don't forget to set `RAW+J PC Save Img` setting with `JPEG only` option!).

Camera clock - SEW cannot set the clock of a Sony camera over USB: pressing `Camera(s)` logs `Could not set date & time (unsupported operation?)`.  The clocks of consumer Sony bodies are also known to drift noticeably over a few days, so a clock set by hand well before the eclipse can be off by seconds on the day, and the times in the EXIF data of your pictures cannot be compared with the contact times.  This does not affect when SEW takes the pictures (that follows the computer clock, see [GPS time correction](#gps-time-correction)), only the times written in the files.  Set the camera clock as close to the eclipse as possible, or sync it from a script: [sony-location-info-link-sync](https://github.com/fliker09/sony-location-info-link-sync) can be run with a `command` line in your script.  The log of every run has the time each command released the shutter, in UTC with milliseconds, which is a reliable reference for when each picture was taken.


## Fujifilm X cameras

Fujifilm X bodies are controlled through the Fujifilm Shooting SDK, not through gphoto2, which cannot control them tethered.  The SDK is not part of Solar Eclipse Workbench: get it from Fujifilm and put it in `~/fujixsdk/`, or set `FUJI_SDK_PATH` to its folder.  The body then appears as `Fuji Fujifilm <model>`, e.g. `Fuji Fujifilm X-T4`, beside the gphoto2 cameras, and takes `take_picture`, `take_bracket`, `take_hdr`, `take_burst` and `prepare_camera`.

Set the drive dial to `S`: on `CH` the SDK cannot release the shutter.  A `take_burst` is therefore a run of single frames, about 0.5 to 1.8 frames per second on an X-T4.  The camera clock cannot be set over USB, and live view and the camera test of the wizard do not support a Fuji body yet.

See [Fujifilm X cameras](docs/FUJI.md) for the installation of the SDK and the settings of the body.

## Upgrading Solar Eclipse Workbench

If you installed with an installer script, run it again: `install.sh` on macOS and Linux, `Update Solar Eclipse Workbench` from the Start menu on Windows.  Or, in a terminal (in WSL on Windows):

```bash
uv tool upgrade solareclipseworkbench
```

If you installed by hand in a Python environment, activate it and run:

```bash
cd solareclipseworkbench
source bin/activate
pip install --upgrade solareclipseworkbench
```

After upgrading, verify the installed version with:

```bash
pip show solareclipseworkbench
```

## Running Solar Eclipse Workbench

- Canon and Nikon cameras can use 1/3 EV or 1/2 EV exposure steps: brackets and HDR sequences use the shutter speed closest to each exposure.  Sony cameras must use 1/3 EV (0.3EV) steps, because their shutter speeds are not set reliably over USB in 1/2 EV steps; `Test Camera...` in the wizard warns about this.  Also, check that the camera's `Auto Power Off` setting isn't too short, as once it's asleep, camera can't be awakened by the app. While the cameras are connected and idle, Solar Eclipse Workbench pings them every 20 seconds over USB to keep them awake (paused from 15s before C2 until 15s after C3, and just before scheduled commands), but not every body honours this, so disabling `Auto Power Off` (or setting it to at least 30 minutes) remains the safest choice. For Canon (`Auto power off`) and Nikon (standby timer) the app warns when you press `Camera(s)` if the setting is shorter than that; Sony does not expose this setting, so check it on the camera.

- Ensure that you are connected to the Internet the first time you run and use Solar Eclipse Workbench, as it will require to download several files required for calculations. Make sure to do this before eclipse day!

- Start Solar Eclipse Workbench by executing the following commands:

```bash
cd solareclipseworkbench
source bin/activate
sew
```

- You can add a parameters to set the needed parameters for the eclipse.  Some examples:

```bash
cd solareclipseworkbench
source bin/activate
sew -d 2024-04-08 -lon -104.63525 -lat 24.01491 -alt 1877.3
sew
```

### Command line parameters

The following command line parameters can be used to start up gui.py.


| Short parameter  | Long parameter        | Description                                                                   |
|------------------|-----------------------|-------------------------------------------------------------------------------|
| -h               | --help                | Show the help message and exit                                                |
| -d DATE          | --date DATE           | Date of the solar eclipse (in YYYY-MM-DD format)                              |
| -lon LONGITUDE   | --longitude LONGITUDE | Longitude of the location where to watch the solar eclipse (W is negative)    |
| -lat LATITUDE    | --latitude LATITUDE   | Latitude of the location where to watch the solar eclipse (N is positive)     |
| -alt ALTITUDE    | --altitude ALTITUDE   | Altitude of the location where to watch the solar eclipse (in meters)         |
| -s               | --sim                 | Start the application in simulation mode                                      |
| -vc              | --virtual-camera      | Use a virtual camera. Only for simulation mode!                               |
| -lc              | --low-cpu             | Disable auto update for eclipse visualization (essential for single core CPU) |
| -scm             | --sony-cont-mode      | Specify continuous mode search keyword name for Sony cameras                  |
|                  | --check SCRIPT        | Print the timeline of a script per camera and exit (see [Script timeline](#script-timeline)) |
|                  | --plot PNG            | With `--check`: also draw the timeline around totality to an image file      |
|                  | --report [LOG]        | Print the run report of a log file and exit (see [Run report](#run-report))  |
|                  | --compare [LOCATION ...] | Print candidate sites side by side for `--date` and exit (see [Compare sites](#compare-sites)) |
|                  | --forecast            | With `--compare`: also fetch the cloud cover at maximum eclipse from Open-Meteo |

### UI functionality

In the images below, a screenshot of the toolbar and the upper part of the UI are shown.

![ui toolbar](src/solareclipseworkbench/img/toolbar.png)

The icons on the UI toolbar must be clicked from left to right (and the required data must be provided, if applicable) in order for the values in the upper section of the UI to appear.  Alternatively, the data can be passed as command line arguments at start-up, as discussed in the previous section.

![ui top section](src/solareclipseworkbench/img/ui-top.png)

The functionality of the toolbar buttons is as follows (from left to right):

#### Observing location

- When pressing the "Location" icon, a pop-up window (see screenshot below) will appear, in which you are asked to fill out the longitude, latitude, and altitude of your observing location.  Both longitude and latitude are expressed in degrees, the altitude in meters.
- If these data were already inserted before somehow (manually, via command line arguments, or by loading a settings file), these values will appear there (you can modify them as you see fit).
- The location is marked with a red dot on the map, which follows the coordinates as you type.  When an eclipse date is set, the map also shows the path of totality (or annularity for an annular eclipse): the band between the northern and southern limits is shaded and the centre line is dashed, and the map zooms to the path and your location (the toolbar above the map zooms and pans; `Home` returns to that view).  The line below the map says how far you are from the centre line and on which side, how far inside (or outside) the path you are, and how long totality lasts at your location compared with the centre line, e.g. `16.0 km north of the centre line, 134.2 km inside the north limit. Totality here: 1m47s (centre line: 1m48s).`  The eclipse can be changed in the drop-down above the map (the same list as in the `Date` window, plus the eclipse that is set if it is already past), to see whether your location is in the path of another eclipse; pressing `OK` then also sets that eclipse as the eclipse date.  For a partial eclipse there is no path to draw.  The coastlines are coarse (1:110 million), so small islands may be missing; use the distances in the text rather than the drawing near a limit (Issue #68).
- When pressing the "OK" button, the data are accepted and will be filled out in the top section of the UI.
- **GPS from phone**: Click the **📱 Get GPS from Phone** button to capture your exact coordinates from your smartphone's GPS — no app required. A local HTTPS server starts on your laptop; open the displayed URL in your phone's browser and tap **Get My Location**. Works over WiFi or with your phone acting as a hotspot (useful at remote eclipse sites with no WiFi). See [docs/GPS_PHONE.md](docs/GPS_PHONE.md) for step-by-step instructions.
- **GPS from USB device**: Click the **🛰 Get GPS from USB Device** button to read coordinates and precise UTC time directly from a USB GPS receiver (such as the VK-162 G-Mouse) connected to your laptop. No gpsd installation is required. See [USB GPS device](#usb-gps-device) below for setup details.

![location pop-up](src/solareclipseworkbench/img/location-popup.png)

#### Eclipse date

- When pressing the "Date" icon, a pop-up window (see screenshot below) will appear, in which you can choose the date of the eclipse from a drop-down menu.  At any moment in time, the next 20 solar eclipses are included in the list.
- When pressing the "OK" button, the selected eclipse date is accepted and will be filled out in the top section of the UI.

![eclipse date pop-up](src/solareclipseworkbench/img/eclipse-date-popup.png)

#### Reference moments

- When pressing the "Reference moments" icon, the information for the reference moments of the eclipse is filled out in the top section of the UI.
- The reference moments of the eclipse are:
  - C1 (first contact);
  - C2 (second contact);
  - MAX (maximum eclipse);
  - C3 (third contact);
  - C4 (fourth contact);
  - sunrise;
  - sunset.
- The information that is shown for each of these reference moments is:
  - Time in the local timezone;
  - Time in UTC;
  - Countdown;
  - Altitude (in degrees);
  - Azimuth (in degrees).
- Sunrise and sunset are the moments the upper edge of the sun touches the horizon, as in almanacs and Stellarium.
- The altitude shown is the apparent altitude of the centre of the sun, i.e. including atmospheric refraction, which
  lifts the sun by about half a degree near the horizon.  At sunrise and sunset it is about -0.3°.  The exposure
  calculation uses the geometric altitude (without refraction).
- This information can only be populated when the location and the eclipse date have been indicated.  Note that the reference moments are not automatically updated in case either of them would be modified.
- Together with the information about the reference moments, the eclipse type (partial / total / annular) will be displayed.  For total and annular eclipses, also the time between C2 and C3 will be shown (next to the eclipse type).

##### Lunar limb correction and Baily's beads

- The Moon's limb is mountainous, so second and third contact do not happen when a smooth disc says they do: a valley lets sunlight through for another second or two, a mountain cuts totality short.  Corrections of a few seconds are normal, and 30 s is possible near the edge of the path.
- With the lunar limb profile installed, the C2 and C3 rows show the contact-point corrected times printed by Solar Eclipse Maestro.  Two extra rows show a photographic Baily's beads capture window around each internal contact.  Its inner edges, `BEADS_C2_END` and `BEADS_C3_START`, are the distinct whole-arc instants when the last bead vanishes and the first bead returns.  The checkbox below the table switches the correction off if you would rather see the mean-limb times; it is locked while a script has pending jobs so displayed contacts cannot disagree with already-scheduled shutters.
- The corrected contacts are what a script schedules against: `C2` and `C3` are the contact-point corrected times, `C2_MEAN` and `C3_MEAN` the uncorrected ones, and `BEADS_C2` / `BEADS_C3` (with `_START` and `_END`) the capture windows.  A window is published only when both edges were solved; an unresolved search produces no schedulable bead timestamps.
- The capture-window boundary is a photographic heuristic: by default it is where no more than 20° total of the lunar limb remains illuminated.  The solver's `arc_degrees` argument makes that threshold configurable; measurements around the reference cases moved the outer edge by about 0.18 s per degree.
- The limb profile itself is a 72 MB file, `lunar_limb_band_v1.bin`, which is not part of the checkout or the package.  It is downloaded automatically the first time the contact times are calculated with the correction on (the `Loading helper files...` window shows the progress), checked against its SHA-256 checksum, and saved in `~/.SolarEclipseWorkbench/`.  Without a network connection the download is tried once per session, and the mean-limb contacts are used.  You can also put the file there yourself, or in the directory Solar Eclipse Workbench is started from; set the environment variable `SEW_NO_LIMB_DOWNLOAD=1` to never download it.  The file is published as an asset of the [`lunar-limb-v1` release](https://github.com/AstroWimSara/SolarEclipseWorkbench/releases/tag/lunar-limb-v1) and is built by `tools/build_limb_blob.py` from **LOLA LDEM_128** (`LRO-L-LOLA-4-GDR-V1.0`).  Kaguya is relevant only to the separate, undocumented LRO/Kaguya profile blend used by Solar Eclipse Maestro.  Without the blob everything still works with mean-limb contacts, and the bead rows say "no limb profile".
- Contact geometry is top-of-atmosphere: atmospheric refraction is deliberately excluded.  At a solar altitude near 7.5°, its estimated effect is about 0.30 s at C2 and 0.22 s at C3.  Evaluating the lunar profile once at maximum instead of separately at C2/C3 changed four measured contacts on two eclipses by no more than 0.014 s.
- Published-profile validation has a data-source floor.  LOLA and Maestro's undocumented LRO/Kaguya blend differ by at least about 0.45 s at sampled contacts and by up to 1.25 s in the current three-sheet set, so the Maestro acceptance tolerance is 1.5 s; tighter assertions would measure source disagreement rather than solver precision.
- The wizard (`sew_wizard`) centres the beads bursts at C2 and C3 on these windows.  It writes them relative to `C2` and `C3` rather than against the `BEADS_*` moments, so a generated script keeps all its lines on a computer without the limb profile.
- The **"Baily's beads"** toolbar button (a diamond ring icon) opens a window that shows the beads for the current location and eclipse.  `Profile` plots the true lunar limb (purple) against the Sun's limb (orange) around the contact point, with the sunlight that still gets through filled in yellow; `Preview` draws the whole Moon over the Sun, with the limb relief exaggerated (10x to 100x) so the beads are visible.  With `Free`, the slider moves through the 8 seconds before and after C2 or C3 (the C2 and C3 shown in the reference moments); with `Live`, the window follows the clock (including the simulation offset) and counts down to the beads.  It switches to `Live` when a script is loaded.  The line above the drawing summarises the corrections, the length of both bead windows and the change in the duration of totality, and warns when a correction is larger than 15 s.  The window was written by @mrosseel.
- The two small lunar orientation kernels it needs (`moon_080317.tf` and `moon_pa_de421_1900-2050.bpc`) are downloaded from NAIF automatically, the same way the ephemeris is.

##### Solar radius

- The `Solar radius` row below the table sets the radius of the Sun used for all contact times.  Solar Eclipse Workbench computes its own Besselian elements, so this radius sets the size of the Moon's shadow and with it the duration of totality.  It is the largest systematic in the contact times, larger than the lunar limb correction: a larger Sun shortens totality.  For the 2026 eclipse in Spain (41.7639°, −2.9294°, 1180 m), 959.63" gives 0.9 s more totality than 959.95", with C2 0.4 s earlier and C3 0.5 s later; the middle of totality moves by less than 0.1 s.  Close to the edge of the path the difference grows much larger (Issue #197).
- **959.95" (default), Quaglia et al. 2021.**  Quaglia, Irwin, Emmanouilidis and Pessi ([arXiv:2107.09416](https://arxiv.org/abs/2107.09416)) measured 959.95" ± 0.05" from flash-spectrum video at the southern limit of the 2017 eclipse.  We use it because it is measured from eclipse contacts: the radius at which the photosphere is completely hidden, which is exactly what a contact time is.  Other techniques measure a different edge of the Sun.  Other eclipse measurements agree: IOTA's Baily's bead timings give 959.99" ± 0.06" and Jubier suggests 959.98".  The standard value below lies well outside this group of modern measurements.
- **959.63", Auwers 1891.**  The conventional value of eclipse prediction, used by Espenak's canon, Solar Eclipse Maestro (by default) and Eclipse Chaser Log.  It is a convention rather than a current measurement.  Choose it to compare the contact times directly with published predictions: any remaining difference then has another cause.
- **Custom value**: any radius between 955" and 965" can be typed in.
- The radius is the apparent radius at a distance of 1 au.  The choice is saved in `~/.SolarEclipseWorkbench.ini` and also used by the wizard, `sew --check` and `sew --compare`, and the log file records which radius a run used.  Like the limb correction, it is locked while a script has pending jobs.

#### Camera overview

- When pressing the "Camera" icon, the camera overview in the top section of the UI will be updated.  This shows for each camera the following information:
  - Camera name;
  - Battery level (in percentage);
  - Free memory (both in percentage and in GB).
- Apart from updating the camera information in the UI, the following is done for all cameras:
  - Syncing the time with the time of the computer the camera is connected to.  The camera clock is only changed when its current value can be read, and it is read back afterwards.  If the camera did not take the new time (some older cameras fall back to a default date such as 1980), the previous date and time are restored, a warning is shown, and SEW does not touch the clock of that camera again until it is restarted: set the date and time on the camera by hand in that case.  Sony cameras do not allow setting the clock over USB at all (see [Sony PC Remote settings discussion](#sony-pc-remote-settings-discussion)).  The `sync_cameras` script command works the same way;
  - Checking whether for the focus mode and the shooting mode are set to "Manual".  If this is not the case, a warning message is logged in the Console where the UI was started.

#### Simulation mode

- The "Simulation" icon will only be available in the toolbar when the UI is started in simulator mode (i.e. with the command line argument `-s` or `--sim`).
- When pressing this icon, a pop-up window (see screenshot below) will appear, in which you can specify when (w.r.t. one of the reference moments of the eclipse) you want to start the simulation.
- When pressing the "OK" button, the selected relative starting time of the simulation will be stored.  It will be applied when the jobs are being scheduled (see next section).

![simulation pop-up](src/solareclipseworkbench/img/simulation-popup.png)

#### Job scheduling

- When pressing the "File" icon, a file chooser will pop up, in which you can select the desired TXT file with the scheduled commands.
- When a file with scheduled commands is indeed selected, the scheduled jobs will appear in the bottom section of the UI.  As the timing of the commands is expressed in the loaded file w.r.t. the reference moments of the eclipse, you have to make sure that the information about the reference moments has already been filled out in the top section of the UI.
- When jobs are scheduled and hence displayed in the bottom part of the UI, the following information is shown for each job:
  - Countdown;
  - Execution time in the local timezone;
  - Execution time in UTC;
  - The command;
  - Description of the command.
- The `Commands` drop-down above the jobs table chooses how the commands are shown.  `In words` (the default) says what each command does, at the shutter speed the camera will use, e.g. `Bracket of 5 frames, 1 EV apart, around 1/1000 s, f/8, ISO 200 (VirtualCamera)`.  `As in the script` shows the command with its fields as they are written in the script, e.g. `take_bracket("VirtualCamera", 1/1000, 8, 200, 1 5)`.  The tooltip of a command shows the other form.  The choice is saved in `~/.SolarEclipseWorkbench.ini`.
- Important to know when in simulation mode:
  - Jobs that were scheduled in the past w.r.t. the start of the simulation, will not appear in the list of scheduled jobs.
  - The displayed local execution time of the jobs corresponds to the local time at the observing location, so this may be different from the timezone on you laptop (e.g. when you would be practising beforehand at home).

#### Exposure compensation

- When clouds, haze or dust make the Sun dimmer (or brighter) than the script expects, the buttons above the jobs table change the exposure of all following shots: `+1 EV` makes them one stop brighter, `−1 EV` one stop darker, and `Reset exposure` goes back to the exposures in the script.  The compensation in effect is shown between the buttons, and can go up to 5 EV either way.
- Only the shutter speed changes: the aperture and ISO stay as in the script.  The compensated speed is rounded to the nearest speed the camera supports, and is limited by the camera's shortest and longest speed.
- The compensation is applied when a shot fires, so it reaches every `take_picture`, `take_burst`, `take_bracket`, `take_hdr` and `prepare_camera` still to come, including those already scheduled.  A shot that is already being taken is not changed.  The jobs table shows the compensated shutter speed: `1/500 s (+1 EV)` in words, or the scripted and the compensated speed, e.g. `1/1000 → 1/500`, as in the script.
- The compensation is not saved: it starts at 0 EV every time the application starts.

#### Interrupting scheduled jobs

- In case the scheduled jobs would have to be interrupted (e.g. because you realised - hopefully in time - that you did not select the correct file), you have to press the "Stop" icon.  The scheduler will be shut down and the scheduled jobs will disappear from the bottom section of the UI.
- Use this icon with caution!

#### Datetime format

- When pressing the "Datetime format" icon, a pop-up window (see screenshot below) will appear, in which you can specify the date and time format.
- When pressing the "OK" button, the selected date and time format will be applied to all dates and times that are or will be displayed in the UI.
- When pressing the "Cancel" button, the old formatting will be kept.

![datetime format pop-up](src/solareclipseworkbench/img/datetime-format-popup.png)

#### Saving settings

- When pressing the "Save" icon, the location and eclipse date (if selected) will be stored in a settings file, together with the applied date and time format.
- The standard settings framework of `PyQt6` (`QSettings`) will be used: it stores the settings as `~/.SolarEclipseWorkbench.ini` (a hidden file in your home directory).
- Next time you open the UI, this settings file will be loaded and the specified data will be made available in the UI.
- In case command line arguments are used to open the UI, these take priority over the values from the settings file.

#### Live view

- When pressing the **"Live View"** icon in the toolbar, a floating preview window opens showing a live image from the connected camera, refreshed once per second.
- The live view is intended to help you verify that the Sun is still in the frame and remains in focus without having to stop the script, realign the telescope, and restart.
- The preview image uses gphoto2's `capture_preview` command.  This transfers a small JPEG thumbnail over USB and does **not** save anything to disk.  The camera continues to store actual eclipse photos directly to its SD card as scheduled.
- **USB lock safety**: before each preview frame the thread tries to acquire the camera's USB lock with a 50 ms timeout.  If a scheduled shot is firing at that exact moment, the preview frame is silently skipped.  This guarantees that shot timing is never compromised by live view.
- **During totality (C2−15s → C3+15s)** the preview is automatically paused so the USB bus is entirely free for the closely-spaced shots in the script.  The pause starts 15 seconds before C2 and the preview resumes 15 seconds after C3.  The window shows a yellow banner while paused.
- **Toggle button**: the "Disable / Enable Live View" button in the window lets you turn the preview off or on at any time — before, during, or after totality — without stopping the script or closing the window.
- If no camera is connected when the Live View button is clicked, a warning dialog is shown.
- **Preview size** (optional): the preview uses the live-view size set on the camera.  Canon EOS and recent Nikon bodies let it be changed (Canon `Large`/`Medium`/`Small`, Nikon `QVGA`/`VGA`/`XGA`), and the `Preview size` list in the window then selects a larger one for more detail, e.g. to check focus with the zoom.  The camera's own setting is restored when the window closes.  The size of the last frame is shown next to its time.  Sony bodies have a fixed preview size, and the list is greyed out.  A larger frame takes longer to transfer, and a scheduled shot that fires during a transfer waits for it, so during the partial phases such a shot can be a little later (typically some tens of milliseconds); the shots around totality are not affected, as live view is paused from 15 s before C2 until 15 s after C3.

#### Script timeline

- The **"Timeline"** icon draws a script per camera against the reference moments of the location and date that are set: every camera command is a bar from its start to the end of the time it is estimated to keep the camera busy, with C1–C4, MAX and the Baily's beads windows drawn across.  Commands that start late (because the camera is still busy) are orange, with a line back to their planned start; commands that will probably be dropped are a red cross.  Hovering over a bar shows the command, its time relative to the nearest contact, and what it is waiting for.
- The window opens on the script loaded last, or asks for one; `Script...` draws another one, before anything is loaded or a camera is connected.  `Totality` shows from 90 s before C2 to 90 s after C3, `Whole script` everything; the toolbar under the buttons zooms and pans.  `Refresh` reads the script again after editing it, and `Save as text...` writes the timeline of every camera to a text file.
- It uses the same estimates as the check that runs when a script is loaded (see [Commands that are too close together](#commands-that-are-too-close-together)), so a command drawn as dropped is one that check warns about, and a script fitted to a tested camera is drawn with the camera's measured timing.  Times are the real UTC times, without a simulation offset.
- From the command line: `sew --check myscript.txt -d 2027-08-02 -lon 32.65 -lat 25.69 -alt 80` prints the same per camera, with the commands that start late or are dropped first, and exits with code 1 when a command will be dropped or a line names a reference moment that does not exist.  Add `--plot timeline.png` to also draw it.

#### Run report

- The **"Run report"** icon reads a log file back and shows what became of every command of a run (a run starts each time a script is loaded): `shot`, `late` (the shutter was released more than 1 s after the planned time), `dropped: camera busy`, `missed by the scheduler`, `failed`, `no shutter release`, `not reached` (the log ends before it) or, for voice prompts and shell commands, `done`.
- The summary above the table gives, per camera, the number of commands per outcome, the median and largest delay of the shutter release per command type, the commands within 60 s of C2 and C3, and the commands that kept the camera busy longer than estimated, which is where the next command on that camera may have had to wait.  The warnings and errors logged during the run follow.
- The newest log in which a script was loaded opens first; the other logs are in the list, and `Open...` reads one from elsewhere.  `Refresh` reads the log again during a run, and `Save as text...` writes the full report.
- From the command line: `sew --report` prints the report of the last run in the newest log, `sew --report <log file>` of a given log.
- Use it after rehearsing a script in simulation mode with the cameras you will use (see [Timing shots around C2 and C3](#timing-shots-around-c2-and-c3)).  With the virtual camera every shot is reported as `shot` straight away; the real delays and busy times only show with a real camera.
- Logs written by version 2.0.0 or older have no planned commands: the report then only lists what those logs have.

#### Compare sites

- The **"Compare sites"** icon puts a shortlist of candidate sites side by side for the eclipse date that is set: the eclipse type and magnitude, the duration of totality (corrected for the lunar limb when the limb profile is installed, with the difference to the longest one on the list), the local time of C2, the altitude and azimuth of the Sun at maximum eclipse, and the Baily's beads windows around C2 and C3.  The longest totality is in bold, and a Sun lower than 10° is marked: check the horizon in that direction.
- Add sites with `Add current location` (the location of the main window), a saved location (from the `Location` window or the wizard) with `Add`, or `New row` to type in a name and coordinates.  Names and coordinates can be edited in the table.  The list is kept with the saved locations (in `~/.sew_wizard_config.json`), so it is still there the night before the eclipse.  `Compare` computes every site, which takes about half a second per site.
- `Cloud forecast` fetches the cloud cover at maximum eclipse (total, and low, mid and high clouds) from [Open-Meteo](https://open-meteo.com), interpolated between the hourly values; hovering over it shows the hourly cover from C1 to C4.  Forecasts reach about 15 days ahead, so until then the column says from which date one is available.  For an eclipse in the past it shows what the sky really was (the ERA5 reanalysis), e.g. to check a site afterwards.  This needs a network connection; the rest of the window does not.
- `Compare beads` shows the Baily's beads of the sites with totality next to each other, drawn like in the [`Baily's beads`](#lunar-limb-correction-and-bailys-beads) window (as a profile or as a picture, with the same exaggeration).  One slider moves every site to the same number of seconds from its own C2 or C3, so the views show how many beads each site gets and for how long at the same stage of the contact; under each view are its time in UTC and its bead window.  Near the limits of the path a bead window can last over ten seconds, and the slider then reaches further than ±8 s.  This needs the lunar limb profile.
- `Use this site` (or a double click on a result) makes the selected site the observing location and recomputes the reference moments, and `Save as text...` writes the comparison, longest totality first.
- From the command line: `sew --compare -d 2027-08-02` prints the shortlist of the window, `sew --compare "La Horra" "Tarifa" -d 2027-08-02 --forecast` the named saved locations with their cloud cover; `--longitude`, `--latitude` and `--altitude` add one more site.

#### Phone dashboard

- The **"Phone"** icon starts a small web page on the laptop for following the run from a phone, e.g. when the laptop is under a sunshade or away from the telescope.  Scan the QR code in the window that opens with a phone on the same network (the laptop's Wi-Fi, or the phone's hotspot).
- The page shows the countdown to the next contact in large digits, the contacts with their local time, the next eight commands with their countdown, and the battery level and free memory of every camera.  It has the `−1 EV`, `Reset` and `+1 EV` buttons of the [exposure compensation](#exposure-compensation), and `Abort run`, which (after a confirmation on the phone) stops the scheduler like the `Stop` icon: every command still to come is cancelled.
- When the [`Live View`](#live-view) window is open on the laptop, the page also shows its preview, as the window shows it: the zoomed part, with focus peaking and the crosshair when they are on.  Handy for checking the framing and focus at the telescope.  The page shows the frames the window already gets, so it adds no USB traffic: around totality the live view pauses, and the page says so and dims the last frame.  The `show` box above the preview hides it, to save the phone's battery and data (about 100 kB per second).
- Below the preview are the histogram of the full frame (log scale, with the clipped range in red and the percentages clipped and black) and the loupe: the part of the frame at the zoom centre at its own pixels, with its focus score and how close that is to the best score so far.  Both are worked out for the phone whether or not they are on in the `Live View` window.  Tapping the preview on the phone moves the loupe there, like a click in the window.  The `histogram` and `loupe` boxes hide them.
- The `Camera` list above the preview picks the camera to show, or `Off`, without anyone at the laptop: it closes the `Live View` window on the laptop and opens it on the chosen camera.  From 15 s before C2 until 15 s after C3, while live view is paused, the camera cannot be changed: opening and closing live view is USB traffic.
- The page counts down by itself between updates, and shows `NO CONNECTION` in red, with the buttons disabled, when it has not heard from the laptop for 5 seconds.
- The URL contains a random key, so others on the same network cannot use the controls without it; a new key is made every time the dashboard is started.  The page is plain HTTP (it needs no HTTPS, unlike the phone GPS page, so the phone shows no certificate warning).  It listens on port 8766, or the next free port.
- Closing the window leaves the dashboard running; `Stop dashboard` stops it.

> **Note**: Live view via gphoto2 is tested on the Nikon Z8.  Support on other bodies depends on whether their gphoto2 driver implements `capture_preview`.  Canon EOS bodies and most modern Nikon and Sony Alpha bodies support it; some entry-level or older bodies do not.

## Running the Configuration Wizard

The SEW Configuration Wizard (`sew_wizard`) is a graphical step-by-step tool that helps you create photography scripts for solar eclipse observations. It guides you through selecting an eclipse and location, configuring your camera and ISO settings, choosing phenomena to photograph, and optionally adding voice prompts.

- After installation, start the wizard by running:

```bash
sew_wizard
```

- Alternatively, if you are using the development environment with uv:

```bash
uv run sew_wizard
```

- Or run it directly from Python:

```bash
python -m solareclipseworkbench.wizard
```

On the equipment page, **Test Camera...** reads the shutter speeds, ISO values and apertures the connected camera offers with its lens, and (full test) measures how long a picture and a burst take and checks that the camera clock can be set.  The generated script is then fitted to the camera: exposures use the settings the camera really has (compensating with ISO or aperture where needed), and shots are spaced by the measured durations.  The diamond ring and Baily's beads bursts are planned in seconds of shooting: 2 s for a diamond ring burst, which a Nikon takes as that many seconds' worth of frames at its measured frame rate (untested: 10 frames per second).  The full test takes two bursts back to back (1 s and 5 s for Canon and Sony, 10 and 100 frames for Nikon) to measure how long the camera stays busy per second of shooting, or a Nikon's frame rate, on top of a fixed overhead.  A measured picture time only lengthens the default estimate; a burst is planned with its measured overhead plus a margin (1.5 × + 1 s), also when that is shorter than the default, so a camera with a fast card (e.g. a Nikon Z 8 or Canon EOS R5 with CFexpress) is not held back by the default estimate.  With the lunar limb profile, a beads burst on a tested camera covers the Baily's beads window plus 0.5 s on either side, up to the longest test burst (at most 5 s), and is shortened when it would move the diamond ring burst next to it by more than 2 s.  The generated script records the timing it was planned with in a `# timing:` header line, so the busy-camera warning when the script is loaded uses the same numbers.  The result is saved with the camera, so this is needed once per camera and lens.  On the last page, **Verify with Camera...** checks the finished script against the connected camera.

On the phenomena page, **Bracket each corona exposure** turns every shot of the corona series into a `take_bracket` with the chosen EV step and number of frames, spaced so each bracket has finished before the next one starts.  For a tested camera, only the brackets it takes itself are offered (read by **Test Camera...**); otherwise standard steps (1/3 to 3 EV) and 3, 5, 7 or 9 frames are offered, and a bracket the camera does not offer is taken in software.  Canon cameras cannot set the number of frames over USB: set `Number of bracketed shots` in the camera menu to the number chosen in the wizard.  **Verify with Camera...** warns when a bracket of the script will be taken in software.

For a detailed walkthrough of each wizard step, see the [Wizard Guide](docs/WIZARD_GUIDE.md).
For capturing your GPS coordinates from your smartphone (works over WiFi or phone hotspot — no internet required at the eclipse site), see [docs/GPS_PHONE.md](docs/GPS_PHONE.md).

## USB GPS device

Solar Eclipse Workbench can read your position **and** the precise UTC time directly from a
USB GPS receiver, such as the widely available **VK-162 G-Mouse** (u-blox 7 chipset).
No `gpsd` installation is required — the software communicates with the device directly.

### Supported hardware

Any USB GPS receiver that presents as a serial port and outputs standard NMEA 0183
sentences works.  Devices known to work include:

| Device | Chipset | USB ID |
|--------|---------|--------|
| VK-162 G-Mouse | u-blox 7 | 1546:01A7 |
| Generic u-blox 8 | u-blox 8 | 1546:01A8 |
| Prolific USB-Serial adapters | PL2303 | 067B:2303 |
| Silicon Labs CP210x | CP210x | 10C4:EA60 |

### One-time setup on Linux / WSL

The GPS receiver appears as `/dev/ttyACM0` (or `/dev/ttyUSB0`).  Your user must be in the
`dialout` group to open it without sudo:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in (or reboot) for the change to take effect.  You only need to do this
once.

**WSL users**: the USB device must also be shared with WSL using `usbipd`.  The [installer script](#installation-with-the-installer-script) adds you to the `dialout` group and shares the receiver if you choose it in the list; for a receiver you add later, use `Share cameras with Solar Eclipse Workbench` from the Start menu.  To share it manually, open a **PowerShell** terminal as administrator:

```powershell
usbipd list                  # find your GPS device, note its BUSID (e.g. 3-4)
usbipd bind --busid 3-4      # one-time: mark the device as shareable
```

Solar Eclipse Workbench attaches a shared receiver to WSL by itself when the USB GPS is started.  Outside the application, attach it with `usbipd attach --busid 3-4 --wsl`.

### macOS

The GPS receiver appears as `/dev/cu.usbmodemXXXX` or `/dev/cu.usbserialXXXX`.
No group setup is required — the device is ready to use immediately.

### How to use

1. Plug in the GPS receiver.
2. Open the **Location** pop-up (Location icon in the toolbar).
3. Click **🛰 Get GPS from USB Device**.
4. A dialog appears.  Wait for the satellite fix — this takes **1–3 minutes** in open sky
   on a cold start (faster if the receiver was recently used).
5. Once a fix is acquired, the longitude, latitude, and altitude fields are filled in
   automatically.
6. A message shows the **GPS–computer time offset** (difference between GPS UTC and your
   laptop's clock).  All scheduled actions are automatically corrected by this offset so
   they fire at exactly the right moment even if your computer clock is off by several
   seconds.
7. Click **OK** to confirm the location.

> **Tip**: if no altitude is reported by the GPS sentence, Solar Eclipse Workbench
> automatically fetches it from the Open-Elevation API as a fallback.

### GPS time correction

Every scheduled action (taking a photo, playing a voice prompt, etc.) uses the GPS–computer
time offset to compensate for any discrepancy between your laptop's clock and the satellite
network.  For example, if your computer is 3 seconds slow, all actions will be triggered
3 seconds earlier on the computer clock so that they happen at the correct astronomical time.

If no USB GPS fix was obtained, the computer clock is used as-is (offset = 0).

## USB relay shutter trigger

A USB relay board can fire a camera through its wired remote-release jack, as a cable release
does.  There is no USB in the path to the shutter, so a held contact lets the camera shoot at the
full rate of its own drive mode.  This is useful for the bursts around C2 and C3, on bodies that
shoot slowly over USB or cannot shoot a burst over USB at all.

- Supported boards: LCUS (CH340), DSD TECH SH-UR, Numato and dcttech HID boards.  HID boards need
  the `hid` extra: `pip install "solareclipseworkbench[hid]"`.
- Connect the relay with the **Relay** button in the toolbar.  **Test fire** takes one frame.
- In a script, use `relay_shoot`, `relay_burst`, `relay_bulb`, `relay_arm` and `relay_release`
  (see [Commands](#commands)).
- `sew_hardware` is a bench console to wire and test a trigger without the GUI.

[USB relay shutter trigger](docs/RELAY.md) explains how to identify the wires of a release cable,
how to wire the board, and what was measured on a Fujifilm X-T4: latency, pulse length, burst rate
and how the drive mode changes what a held contact does.

## Using two cameras of the same model, or one camera with multiple setups

SEW's default camera identification uses the gphoto2 model name (e.g. `Canon EOS 80D`) as
the key.  This works fine when each model is used only once, but fails in two situations:

- **Two bodies of the same model** connected at the same time — both would appear as the same key.
- **One body, multiple optical setups** — e.g. the same Canon EOS 80D used with a telescope in one
  script and with a lens in a different script, each referenced by a different name.

SEW handles both cases by reading each camera's **serial number** and mapping it to one or
more **alias names** that you choose.  Those aliases are then used exactly like a camera
name in your script — nothing else changes.

If you only use one camera per model and always use the model name in your scripts, no
setup is required and everything works as before.

### Step-by-step setup

1. **Open the wizard** and navigate to the *Equipment* page.
2. **Give the camera a unique alias name** in the *Camera Name* field
   (e.g. `Canon EOS 80D (telescope)`).
3. **Connect only that one camera** to the computer via USB, then click **"Detect Connected Camera"**.
   - SEW reads the camera's serial number and saves the mapping `serial → alias` in
     `~/.sew_wizard_config.json`.
   - A green ✓ appears next to the name field confirming the mapping is stored.
4. **To add a second alias for the same body** (e.g. for a different optical setup): enter
   the new alias name (e.g. `Canon EOS 80D (lens)`) and click **"Detect Connected Camera"**
   again with the same physical camera still connected.  SEW adds the new alias alongside the
   existing one — both point to the same serial number.
5. **To add a second physical body of the same model**: disconnect the first camera, enter a
   different alias (e.g. `Canon EOS 80D (tele)`), connect the second body, and click
   **"Detect Connected Camera"**.
6. **Use the alias names in your scripts** exactly as you would any camera name:

```
# Telescope script
take_picture, C1, -, 0:01:02.0, Canon EOS 80D (telescope), 1/2000, 8, 100, "Corona"

# Lens script (different file, used on a different occasion)
take_picture, C1, -, 0:01:02.0, Canon EOS 80D (lens), 1/1250, 5.6, 200, "Wide partial"
```

7. When SEW starts with the camera connected, it reads the serial number, looks up all
   registered aliases for that serial, and makes the camera available under **every** alias
   name — so whichever script you load, the right (or only) camera is found automatically.

> **Note**: The detection flow requires exactly one camera to be connected at the time you
> click the button. If zero or more than one camera is detected, SEW will show a warning.

## Script file format

### General remarks

Test your script before using it during a total solar eclipse!  Some cameras can take pictures very fast, some cameras need some time between taking two different pictures.

The following cameras are tested:

- Canon EOS 1000D
- Canon EOS 650D
- Canon EOS 80D
- Canon EOS R
- Nikon DSC D3400
- Nikon DSC D610
- Nikon Z8
- Nikon Z6iii
- Sony ILCE-7S (α7S)
- Sony ILCE-7M3 (α7 III)
- Sony ILCE-7RM3A (α7R IIIA)
- Sony ILCE-7R II (α7R II): Very slow, because it does not support the `PC+Camera` Save Destination mode, so every picture is downloaded over USB before the next one can be taken. Expect a practical capture rate of no more than one picture every 10 seconds with this camera.

It is possible to take pictures in burst mode.  The speed is limited by the speed of the camera (and card).

To test brackets, HDR sequences and shot timing on your own camera, see [Testing your camera](docs/CAMERA_TESTS.md).  It has test scripts for Canon, Nikon and Sony bodies.

### Reference moments

The reference moments of the eclipse that used in the scripts are:
  - C1: first contact
  - C2: second contact
  - MAX: maximum eclipse
  - C3: third contact
  - C4: fourth contact
  - SUNRISE: sunrise
  - SUNSET: sunset
  - LAST: Reference the time to the last command in the script.

### Commands

Solar Eclipse Workbench can use the following commands:

- **take_picture** - Set the aperture (use 8 instead of 8.0), shutter speed and ISO of the camera and take a picture.

```take_picture, C1, -, 0:01:02.0, Canon EOS 80D, 1/1250, 8, 200, "Pre-C1 uneclipsed (Iter. 1)"```

This command will take a picture 1 minutes and 2 seconds before first contact (C1) with the Canon EOS 80D.  The ISO will be set to 200, aperture to 8.0 and shutter speed to 1/1250s.

- **take_burst** - Set the aperture, shutter speed and ISO of the camera and take a burst of pictures during 3 seconds (for Sony and modern Canon cameras; Nikon and older Canon cameras will take 3 pictures in burst mode instead). Note - for Sony cameras the automatically chosen Continuous mode might be either High Speed or Low Speed (completely depends on the cameras's model). If you want to define a specific mode - check out the `--sony-cont-mode` command line option. As for Nikon cameras - your Continuous mode might be dictated by the physical dial. In such a case, please set it beforehand accordingly (it won't affect `take_picture` or `take_hdr`, so no need to touch it once set)! When a Nikon is connected, a banner reminds you of this, naming the commands the loaded script uses for that camera.

```take_burst, C1, +, 0:00:08.0, Canon EOS 80D, 1/2000, 5.6, 400, 3, "Burst test"```

- **take_bracket** - Set the aperture, shutter speed and ISO of the camera and take a bracket centred on that exposure.  The bracket is given as `"<EV step> <frames>"`, the same for every camera brand: `"1 3"` takes 3 frames 1 EV apart (at 1/60: 1/125, 1/60 and 1/30), `"0.7 5"` or `"1 2/3 5"` takes 5 frames.  The EV step can be a decimal (`0.3`, `0.7`, `1.3` are read as thirds) or a fraction, up to 3 EV; the number of frames is 3, 5, 7 or 9.  An invalid bracket is reported when the script is loaded.
  - Canon uses its AEB.  The number of AEB frames cannot be set over USB: set `Number of bracketed shots` in the camera's custom functions to the number of frames in the script, and use the same number of frames for every bracket.  A bracket with fewer frames than that setting is not centred: with 5 set, an EOS 80D shoots 0, -2, -1, +1, +2 steps, so a 3-frame bracket is 0, -2, -1 (an EOS R with its `Bracketing sequence` at -, 0, + shoots -2, -1, 0, +1, +2, so it is -2, -1, 0).  A bracket with more frames than the setting stops at the end of the camera's sequence and a warning is logged.  Some bodies (the EOS 80D and EOS R) do not report the bracketed shutter speed over USB, so the end of the sequence cannot be seen: they take every frame of the script, and a setting that is too low gives repeated frames instead.  `Verify with Camera...` in the wizard warns when a script mixes brackets with different numbers of frames.
  - Nikon uses its bracketing settings (step and pattern).  An important note for Nikon cameras with physical dial for capture mode - app will assume you already chose Continuous mode (please see `take_burst` above for more information).
  - Sony uses the matching continuous bracketing capture mode (`Bracketing C ...`).  You can look up the available modes using this command: `gphoto2  --get-config=/main/capturesettings/capturemode`.
  - When the camera does not offer the bracket (e.g. no Sony mode with that step and number of frames), it is taken in software: one picture per frame, at the shutter speed closest to each exposure.
  - Older scripts keep working: the Canon form `"+/- 1 2/3"` takes 5 frames, and a Sony capture mode name (e.g. `"Bracketing C 3.0 Steps 5 Pictures"`) is passed to the camera as is.

```take_bracket, C1, +, 0:00:08.0, Canon EOS 80D, 1/2000, 5.6, 400, "1 2/3 5", "Bracket test"```

- **take_hdr** - Take an HDR sequence by ramping the shutter speed from a starting (fastest) speed down by the given number of full stops and back up again, while keeping aperture and ISO fixed.  Uses `gp_camera_trigger_capture` for maximum speed so successive shots are fired without waiting for each file to be written to the card. The shutter speed choices available on the connected camera are queried at runtime, so the sequence always stays within the actual speeds the body supports. Each frame is 1 EV longer than the previous one, using the camera speed closest to that exposure, so the sequence is right whether the camera is set to 1/3 or 1/2 EV steps.  An optional sequence field before the description chooses how the sequence runs:
  - `round-trip` (the default when the field is left out): up to the longest exposure and back down again, 2 × stops + 1 shots.
  - `one-way`: up to the longest exposure only, stops + 1 shots, which is faster in a short totality.  A Sony takes it with its own continuous bracketing when it has a 1 EV mode with that number of frames (e.g. `Bracketing C 1.0 Steps 5 Pictures` for 4 stops), which is much faster than changing the shutter speed for every frame.

  The longest exposure is always taken once.  An unknown sequence, or fewer than 1 stop, is reported when the script is loaded.  An important warning for Sony cameras - if the camera is in `PC` mode, the total number of taken shots must not exceed the size of camera's buffer! Otherwise, the entire sequence will be lost. You can find the buffer size of some of the Sony cameras [here](https://capturetheuniverse.com/#buffer-size-usb-speed).

  The sequence for `stops=4` starting at `1/2000` would be: `1/2000 → 1/1000 → 1/500 → 1/250 → 1/125 → 1/250 → 1/500 → 1/1000 → 1/2000` (9 shots) as a round trip, and `1/2000 → 1/1000 → 1/500 → 1/250 → 1/125` (5 shots) one way.

```take_hdr, MAX, -, 0:00:10.0, Canon EOS R, 1/2000, 5.6, 100, 14, "HDR at mid-totality"```

```take_hdr, MAX, -, 0:00:05.0, Sony ILCE-7RM3A, 1/2000, 5.6, 100, 4, one-way, "HDR at mid-totality"```

  Arguments: camera name, starting shutter speed (fastest in the sequence), aperture, ISO, number of stops to ramp down.

- **prepare_camera** - Set the camera up for the command that follows, without taking a picture: its shutter speed, aperture and ISO and, on a Sony, its drive mode: `single`, `burst`, or a bracket as in `take_bracket`.  A Sony takes about 4 seconds to change between single pictures, continuous shooting and a bracketing mode; without `prepare_camera` the first burst or bracket after such a change starts that much later than scheduled.  Put it a few seconds before the first shot of a sequence, e.g. before the diamond ring at C2 and before the Baily's beads at C3, at a moment no other shot is due.  The command that follows then finds the camera ready and shoots right away.  Canon and Nikon change drive mode quickly, so for them only the exposure is set.  The wizard adds these lines for a Sony.

```prepare_camera, C2, -, 0:00:14.5, Sony ILCE-7RM3A, 1/400, 5.6, 400, burst, "Prepare for C2 diamond ring"```

```prepare_camera, C2, -, 0:00:30.0, Sony ILCE-7RM3A, 1/30, 8, 400, "Bracketing C 3.0 Steps 5 Pictures", "Prepare for the C2 brackets"```

  Arguments: camera name, shutter speed, aperture, ISO, drive mode.

- **relay_shoot**, **relay_burst**, **relay_bulb**, **relay_arm**, **relay_release** - Fire the camera through a USB relay on its remote-release jack (see [USB relay shutter trigger](#usb-relay-shutter-trigger)).  `relay_shoot` takes one frame.  `relay_burst` holds the shutter for a number of seconds; with an interval as second argument and S1 on its own channel, it pulses the shutter at that interval.  `relay_bulb` holds a bulb exposure (the camera must be set to B).  `relay_arm` keeps the half press closed, which shortens the release lag, until `relay_release` opens every contact.  The relay is looked up when the command fires, so it can be connected after the script is loaded.

```relay_arm, C2, -, 00:00:08.0, "Wake the camera"```

```relay_burst, C2, -, 00:00:05.0, 4.5, "Diamond ring and Baily's beads"```

```relay_burst, C3, -, 00:00:01.0, 2, 0.25, "Eight frames, 0.25 s apart"```

```relay_release, C2, +, 00:00:01.0, "Release the half press"```

- **voice_prompt** - Play a sound file.

```voice_prompt, C4, -, 00:00:03, C4_IN_3_SECONDS, "3 seconds before C4 voice prompt"```

This command will play the C4_IN_3_SECONDS sound file 3 seconds before fourth contact (C4).

- **sync_cameras** - Read out the camera settings

```sync_cameras, C2, -, 00:00:04, "Sync the camera status"```

- **command** - Execute a command on the computer.  This can be used to execute a script or to run a program.

```command, C1, -, 00:00:05, "/home/user/scripts/print_date.sh", "Print the date"```

This command will execute the script `print_date.sh` 5 seconds before first contact (C1).  The script should be executable and should not require any user input.

- **for** - Repeat a command a number of times

```for,C1,C4,10,-10,+10```

This command will repeat the commands between C1 and C4 with an interval of 10 seconds.  The for loop will start 10 seconds before C1 and will end 10 seconds after C4.
All commands that follow will be repeated up to the **endfor** command.  The time for the commands will be adapted automatically.

Example 1:

```
for,C1,C4,10,-10.0,10.0
take_picture,(VAR), +, 0:00:00.0, Canon EOS 80D, 1/1250, 6, 100, "Partial C1-C4"
take_picture,(VAR), +, 0:00:00.0, Canon EOS R, 1/800, 8, 100, "Partial C1-C4"
endfor
```

Example 2:

```
for,C1,C4,600,-20.0,10.0
sync_cameras,(VAR), +, 00:00:00, "Sync the camera status"
endfor
```

- It is also possible to use the following commands from Solar Eclipse Maestro:

| Command              | Since version |
|----------------------|---------------|
| FOR,(INTERVALOMETER) | 1.0           |
| TAKEPIC              | 1.0           |
| PLAY                 | 1.0           |
| TAKEBST              | 1.0           |
| TAKEBKT              | 1.0           |


## Astronomical calculations

- Astropy/IERS is used to compute Delta T (TT − UT1) for eclipse reference times.  This is the most up to date information available, but it requires an internet connection to download the latest IERS tables.  If no internet is available, a CSV-based fallback is used.
  - For the 2026 eclipse, the fallback value for Delta T is 69.1085.
- The solar radius is 959.95" ± 0.05" by default (Quaglia et al. 2021), measured from eclipse contacts.  This is slightly larger than the conventional 959.63" (Auwers 1891) of published predictions, which can be selected instead, as can a value of your own.  See [Solar radius](#solar-radius) for why this value is the default.

## Shortcomings

- In normal mode, only one picture per two seconds can be made.
- The computer you are using will probably fall asleep during the solar eclipse.  You can prevent this on macOS and Linux using [caffeine](https://www.caffeine-app.net/).  On Windows, you can use the Windows [powertoys](https://awake.den.dev/).
- Sony cameras after cold boot might return wrong configuration values. Please press `Camera(s)` button to retrieve them one more time.
- Nikon cameras after fresh connection might take a long time to finish their first shot. A potential mitigation is ensuring that the SD card has no other shots on it already.
- Sony might set wrong shutter speed for some of the exposures when using `take_hdr` command. USB3 connection is prone to cause this more often than USB2 one. No solution has been devised yet.

## Converting scripts from Solar Eclipse Maestro

Scripts from Solar Eclipse Maestro are converted automatically to scripts that can be used by Solar Eclipse Workbench.

## Error handling

If something goes wrong, an error message will be shown in the terminal and logged in the log file.

Every start of `sew` (and of `sew_wizard`) writes a new log file in `~/.SolarEclipseWorkbench/logs/`, named after the moment it started, e.g. `sew-20260812-171503Z.log`.  Log files are never overwritten or deleted by the application, so the log of an eclipse is still available afterwards, however often the application was restarted.  The log contains every command that was scheduled and executed (or skipped), the contact times, the GPS clock offset and the connected cameras.  Timestamps are ISO 8601 in UTC with millisecond resolution (e.g. `2026-08-12T17:46:38.123Z`), in the log file and on the console, like the contact times, so they can be compared directly with the times of the pictures.  Every camera command also logs when it really released the shutter, and how long after its scheduled time that was, e.g. `take_bracket released the shutter at 18:29:30.912 UTC: 1.228 s after its scheduled time`: settings are sent to the camera first, which takes a few tenths of a second when nothing changes, but several seconds on a Sony that has to change drive mode.

## Commands that are too close together

A camera can only execute one command at a time, and a command keeps the camera busy for considerably longer than its exposure time: settings are sent over USB before the picture is taken, and after a `take_burst` the camera has to write its buffer to the card.  A command that has to wait more than 1.5 seconds for its camera is skipped rather than executed late.  When a script is loaded, Solar Eclipse Workbench estimates how long each command keeps its camera busy and warns about every command that will probably be skipped, so the script can be corrected before the eclipse.  As a rule of thumb, allow about 2 seconds plus the exposure time for `take_picture`, and about 6 seconds plus the burst duration for `take_burst`.  A Sony bracket takes about 4.5 seconds on top of its exposures, and on a Sony the first command after a change of drive mode (single pictures, burst, a bracketing mode) takes about 4 seconds longer; a `prepare_camera` ahead of time takes that change out of the sequence.

## Timing shots around C2 and C3

The seconds around second and third contact (Baily's beads, the diamond ring, the chromosphere) are the hardest to time.  A few things to keep in mind when writing these lines yourself:

- **A burst or a bracket covers a stretch of time, not a moment.**  Its frames follow one after the other from the scheduled time, plus the few tenths of a second needed to send the settings.  A 5-frame bracket of 3 EV steps around 1/30 shoots all its frames within about 2.5 seconds (the 2 s exposure is one of them) and then keeps the camera busy writing to the card: about 7 seconds in all on a Sony A7R IIIA.  Before C2, the *last* frame should come before C2; after C3, the *first* frame should come after C3.  The same offset on both sides therefore does not give the same result (Discussion #192).  Keep in mind too that the longest, overexposed frames of a bracket make the crescent look wider, as if taken later.
- **Keep 1.5 to 2 seconds away from the contacts, rather than 1 second.**  Different programs give contact times that differ by up to about a second (for the 2026 eclipse in Spain, SEW with the lunar limb correction, Solar Eclipse Maestro and Eclipse Chaser Log differed by up to 0.7 s at C2 and 1.0 s at C3), and the camera needs time to get going.
- **C2 and C3 do not look the same.**  The mountains and valleys at the edge of the Moon decide where and for how long the Baily's beads show, and that is different at C2 and C3.  Use the limb-corrected contact times and the `BEADS_C2` / `BEADS_C3` windows (see [Lunar limb correction and Baily's beads](#lunar-limb-correction-and-bailys-beads)), the `Baily's beads` window, or the simulations on the Eclipse Chaser Log map, rather than mirroring your C2 lines at C3.
- **Prepare the camera before a sequence.**  On a Sony, the first command after a change between single pictures, a burst and a bracketing mode takes about 4 seconds longer.  Put a `prepare_camera` a few seconds before the first shot of the C2 and C3 sequences (the wizard does this for you).
- **First and fourth contact are not visible when they happen.**  The Moon's bite shows once it is a couple of pixels deep: with a 75 mm lens that took about 45 seconds after C1 in 2026, with a telescope a few seconds.  The wizard spaces its C1 and C4 shots accordingly from the focal length and the pixel size of your camera (`Test Camera...` fills in the pixel size for common Canon, Nikon and Sony bodies).
- **Rehearse, and read the log.**  Run your script in simulation mode with the cameras you will use.  The log has, for every command, `… released the shutter at … UTC: … s after its scheduled time`, so you can see how late each sequence really starts and adjust the offsets.  The [Run report](#run-report) lines this up per command, and the [Script timeline](#script-timeline) shows which commands are too close together before you run.

## Handling camera(s) disconnect(s)

In case your camera was turned off or disconnected from USB, you don't have to restart the app to reconnect back to your camera. Once your camera is back online, press `Stop`, agree to remove the scheduled jobs, press `Camera(s)` and see if the camera is properly detected. After that, load your script again (thankfully, the file dialog will remember your last directory) and the execution will resume (do note that the events missed while you were restoring the connection will not be re-attempted).

Note - this should work fine even if multiple cameras are connected and only one of them is affected. In case it doesn't work for some reason, turn off / disconnect from USB all of the cameras and try again.

## Development Guide

When you want to help with the development of Solar Eclipse Workbench, some extra installation is needed.

### Installation on macOS

- For modern Apple Mac computers (using Apple Silicon processors), install [homebrew](https://brew.sh/). Add your homebrew/bin directory to your PATH. Then install gphoto2 and GDAL (required by geopandas) using homebrew:

```bash
export PATH=<location_of_homebrew_installation>/bin:$PATH
brew install gphoto2 pkg-config gdal
```

- Install uv by executing the following line in the terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Check out the source code:

```bash
git clone https://github.com/AstroWimSara/SolarEclipseWorkbench.git
cd SolarEclipseWorkbench
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory:

```bash
uv python install 3.11
uv sync --group dev
uv pip install PyObjC
```

### Installation on Ubuntu 24.04

- Install uv by executing the following line in the terminal:

```bash
sudo apt install curl git gstreamer1.0-plugins-base-apps gstreamer1.0-plugins-good
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Check out the source code:

```bash
git clone https://github.com/AstroWimSara/SolarEclipseWorkbench.git
cd SolarEclipseWorkbench
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory:

```bash
uv python install 3.11
uv sync --group dev
```

- Eventually, to make the sound notifications a bit faster, install pygobject:

```bash
sudo apt install libcairo2-dev libgirepository-2.0-dev gcc
uv pip install pygobject
```

### Installation on Windows 11

- GPhoto2 is only available for Linux and macOS.  To run Solar Eclipse Workbench, wsl should be used.
- Open a terminal in Windows
- Install wsl by executing the command

```bash
wsl --install
```

- Start using wsl by typing `wsl` in a new terminal.

- Install uv by executing the following line in the terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Check out the source code:

```bash
git clone https://github.com/AstroWimSara/SolarEclipseWorkbench.git
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory:

```bash
cd SolarEclipseWorkbench
uv python install 3.11
uv sync --group dev
```

- Install needed packages:

```bash
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0 libxcb-cursor0 libcairo-dev
```

- Eventually, to make the sound notifications a bit faster, install pygobject:

```bash
sudo apt install libcairo2-dev libgirepository-2.0-dev gcc python3-dev gobject-* gir1.2-*
uv pip install pygobject
```

## Run Solar Eclipse Workbench from the development environment

```bash
uv run sew
```

## Upgrading all dependencies to the latest version

```bash
uv sync --upgrade
python3 scripts/sync_uv_lock_to_pyproject.py --apply --pin
```

## Create and upload a new pip package

To create a new pip package, first change the version number in pyproject.toml and then execute the following commands in the Solar Eclipse Workbench directory:

```bash
uv build
uv publish
```

## License

[GPL-3.0](LICENSE)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed list of changes and updates to the package.


## Image attributions

### GUI icons

- <a href="https://www.flaticon.com/free-icons/map" title="map icons">Map icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/clock" title="clock icons">Clock icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/camera" title="camera icons">Camera icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/calendar" title="calendar icons">Calendar icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/settings" title="settings icons">Settings icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/stop-sign" title="stop sign icons">Stop sign icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/folder" title="folder icons">Folder icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/simulation" title="simulation icons">Simulation icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/save" title="save icons">Save icons created by Freepik - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/refresh" title="refresh icons">Refresh icons created by Magnific - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/live-video" title="live video icons">Live video icons created by bearicons - Flaticon</a>
