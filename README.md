# Solar Eclipse Workbench

![Solar Eclipse Workbench logo](src/solareclipseworkbench/img/logo-small.jpg)

## Table of contents

[//]: # (- [Solar Eclipse Workbench]&#40;#solar-eclipse-workbench&#41;)
[//]: # (  - [Table of contents]&#40;#table-of-contents&#41;)
- [Solar Eclipse Workbench](#solar-eclipse-workbench)
  - [Table of contents](#table-of-contents)
  - [Installation instructions](#installation-instructions)
    - [Installation on macOS](#installation-on-macos)
    - [Installation on Ubuntu 26.04](#installation-on-ubuntu-2604)
    - [Installation on Ubuntu 24.04](#installation-on-ubuntu-2404)
    - [Installation on Windows 11](#installation-on-windows-11)
    - [Make cameras accessible in wsl](#make-cameras-accessible-in-wsl)
      - [Replace the Windows USB driver with WinUSB (required for gphoto2)](#replace-the-windows-usb-driver-with-winusb-required-for-gphoto2)
    - [Sony PC Remote settings discussion](#sony-pc-remote-settings-discussion)
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
      - [Interrupting scheduled jobs](#interrupting-scheduled-jobs)
      - [Datetime format](#datetime-format)
      - [Saving settings](#saving-settings)
      - [Live view](#live-view)
  - [Running the Configuration Wizard](#running-the-configuration-wizard)
  - [USB GPS device](#usb-gps-device)
    - [Supported hardware](#supported-hardware)
    - [One-time setup on Linux / WSL](#one-time-setup-on-linux--wsl)
    - [macOS](#macos)
    - [How to use](#how-to-use)
    - [GPS time correction](#gps-time-correction)
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
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0 libxcb-cursor0 libcairo2-dev python3.14-venv
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
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0 libxcb-cursor0 libcairo2-dev python3.12-venv
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

- GPhoto2 is only available for Linux and macOS.  To run Solar Eclipse Workbench, wsl should be used.
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

The USB devices are not automatically accessible in wsl.  To make the cameras accessible, the following steps should be taken:
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

- Attach the camera to wsl by executing the following command in a PowerShell terminal.  Make sure that a wsl terminal is also open. **This should be done every time the camera is connected to the computer!!**

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

Warning: if you intend to use `PC` option with a camera which has an USB-C port, please ensure that the cable is USB3.0 rated and that the port on the PC to which this cable connects is, in fact, a proper USB3.0 one.

Final note on the `PC+Camera` option - SEW will not actually save JPEG files to PC, they will be ignored and the PTP events on camera flushed, with RAW files being consistently written to SD card (please don't forget to set `RAW+J PC Save Img` setting with `JPEG only` option!).


## Upgrading Solar Eclipse Workbench

To upgrade Solar Eclipse Workbench to the latest version, activate your Python environment and run:

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

- Please ensure that all of the connected cameras use 0.3EV exposure step (proper support for 0.5EV will arrive in a future version, for Canon and Nikon). Also, check that the camera's `Auto Power Off` setting isn't too short, as once it's asleep, camera can't be awakened by the app.

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

### UI functionality

In the images below, a screenshot of the toolbar and the upper part of the UI are shown.

![ui toolbar](src/solareclipseworkbench/img/toolbar.png)

The icons on the UI toolbar must be clicked from left to right (and the required data must be provided, if applicable) in order for the values in the upper section of the UI to appear.  Alternatively, the data can be passed as command line arguments at start-up, as discussed in the previous section.

![ui top section](src/solareclipseworkbench/img/ui-top.png)

The functionality of the toolbar buttons is as follows (from left to right):

#### Observing location

- When pressing the "Location" icon, a pop-up window (see screenshot below) will appear, in which you are asked to fill out the longitude, latitude, and altitude of your observing location.  Both longitude and latitude are expressed in degrees, the altitude in meters.
- If these data were already inserted before somehow (manually, via command line arguments, or by loading a settings file), these values will appear there (you can modify them as you see fit).
- When pressing the "Plot" button, the specified location (longitude, latitude) will be marked with a red dot on the world map.  Note that this plot is not updated automatically when you change the values.
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
- This information can only be populated when the location and the eclipse date have been indicated.  Note that the reference moments are not automatically updated in case either of them would be modified.
- Together with the information about the reference moments, the eclipse type (partial / total / annular) will be displayed.  For total and annular eclipses, also the time between C2 and C3 will be shown (next to the eclipse type).

#### Camera overview

- When pressing the "Camera" icon, the camera overview in the top section of the UI will be updated.  This shows for each camera the following information:
  - Camera name;
  - Battery level (in percentage);
  - Free memory (both in percentage and in GB).
- Apart from updating the camera information in the UI, the following is done for all cameras:
  - Syncing the time with the time of the computer the camera is connected to;
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
  - Representation of the command;
  - Description of the command.
- Important to know when in simulation mode:
  - Jobs that were scheduled in the past w.r.t. the start of the simulation, will not appear in the list of scheduled jobs.
  - The displayed local execution time of the jobs corresponds to the local time at the observing location, so this may be different from the timezone on you laptop (e.g. when you would be practising beforehand at home).

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

- When pressing the **"Live View"** icon (rightmost toolbar button), a floating preview window opens showing a live image from the connected camera, refreshed once per second.
- The live view is intended to help you verify that the Sun is still in the frame and remains in focus without having to stop the script, realign the telescope, and restart.
- The preview image uses gphoto2's `capture_preview` command.  This transfers a small JPEG thumbnail over USB and does **not** save anything to disk.  The camera continues to store actual eclipse photos directly to its SD card as scheduled.
- **USB lock safety**: before each preview frame the thread tries to acquire the camera's USB lock with a 50 ms timeout.  If a scheduled shot is firing at that exact moment, the preview frame is silently skipped.  This guarantees that shot timing is never compromised by live view.
- **During totality (C2−15s → C3+15s)** the preview is automatically paused so the USB bus is entirely free for the closely-spaced shots in the script.  The pause starts 15 seconds before C2 and the preview resumes 15 seconds after C3.  The window shows a yellow banner while paused.
- **Toggle button**: the "Disable / Enable Live View" button in the window lets you turn the preview off or on at any time — before, during, or after totality — without stopping the script or closing the window.
- If no camera is connected when the Live View button is clicked, a warning dialog is shown.

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

**WSL users**: the USB device must also be attached to WSL using `usbipd`.  Open a
**PowerShell** terminal as administrator:

```powershell
usbipd list                  # find your GPS device, note its BUSID (e.g. 3:4)
usbipd bind --busid 3:4      # one-time: mark the device as shareable
usbipd attach --busid 3:4 --wsl   # attach before each session
```

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

- **take_burst** - Set the aperture, shutter speed and ISO of the camera and take a burst of pictures during 3 seconds (for Sony and modern Canon cameras; Nikon and older Canon cameras will take 3 pictures in burst mode instead). Note - for Sony cameras the automatically chosen Continuous mode might be either High Speed or Low Speed (completely depends on the cameras's model). If you want to define a specific mode - check out the `--sony-cont-mode` command line option.

```take_burst, C1, +, 0:00:08.0, Canon EOS 80D, 1/2000, 5.6, 400, 3, "Burst test"```

- **take_bracket** - Set the aperture, shutter speed and ISO of the camera and take a bracket of 5 pictures with the given steps. Make sure to have 5 steps enabled for bracketing. Options for the steps are: +/- 1/3, +/- 2/3, +/- 1, +/- 1 1/3, +/- 1 2/3, +/- 2, +/- 2 1/3, +/- 2 2/3, +/- 3. This method only works in Canon. It kind of works with Nikon as well, but not in a true burst mode, it just tries to replicate it (there is a rewrite in progress for a proper burst support). Sony doesn't support this syntax, so instead you have to provide the desired mode name in this field instead (e.g. `"Bracketing C 3.0 Steps 5 Pictures"`). You can look up for the available modes using this command: `gphoto2  --get-config=/main/capturesettings/capturemode`.

```take_bracket, C1, +, 0:00:08.0, Canon EOS 80D, 1/2000, 5.6, 400, "+/- 1 2/3", "Bracket test"```

- **take_hdr** - Take an HDR sequence by ramping the shutter speed from a starting (fastest) speed down by the given number of full stops and back up again, while keeping aperture and ISO fixed.  Uses `gp_camera_trigger_capture` for maximum speed so successive shots are fired without waiting for each file to be written to the card. The shutter speed choices available on the connected camera are queried at runtime, so the sequence always stays within the actual speeds the body supports. Total shots fired: 2 × stops + 1 (the slowest exposure appears once at the midpoint).

  The sequence for `stops=4` starting at `1/2000` would be: `1/2000 → 1/1000 → 1/500 → 1/250 → 1/125 → 1/250 → 1/500 → 1/1000 → 1/2000` (9 shots).

```take_hdr, MAX, -, 0:00:10.0, Canon EOS R, 1/2000, 5.6, 100, 14, "HDR at mid-totality"```

  Arguments: camera name, starting shutter speed (fastest in the sequence), aperture, ISO, number of stops to ramp down.

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
- The used solar radius is equal to 959.95 ±0.05 arcseconds. This value is slightly larger than the canonical solar radius (i.e. 959.63 arcseconds).  This is the latest value from the Besselian Elements team (L. Quaglia et al.).

## Shortcomings

- In normal mode, only one picture per two seconds can be made.
- The computer you are using will probably fall asleep during the solar eclipse.  You can prevent this on macOS and Linux using [caffeine](https://www.caffeine-app.net/).  On Windows, you can use the Windows [powertoys](https://awake.den.dev/).
- Sony cameras after cold boot might return wrong configuration values. Please press `Camera(s)` button to retrieve them one more time.
- Nikon cameras after fresh connection might take a long time to finish their first shot. A potential mitigation is ensuring that the SD card has no other shots on it already.

## Converting scripts from Solar Eclipse Maestro

Scripts from Solar Eclipse Maestro are converted automatically to scripts that can be used by Solar Eclipse Workbench.

## Error handling

If something goes wrong, an error message will be shown in the terminal and logged in the log file `/tmp/solareclipseworkbench.log`.

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
sudo apt install curl git gstreamer1.0-plugins-base-apps
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
