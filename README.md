# Solar Eclipse Workbench

![Solar Eclipse Workbench logo](img/logo-small.jpg)

## Table of contents
- [Solar Eclipse Workbench](#solar-eclipse-workbench)
  - [Table of contents](#table-of-contents)
  - [Installation instructions](#installation-instructions)
    - [Installation on macOS](#installation-on-macos)
    - [Installation on Ubuntu 22.04](#installation-on-ubuntu-2204)
  - [Installation instructions for Windows 11](#installation-instructions-for-windows-11)
  - [Running Solar Eclipse Workbench](#running-solar-eclipse-workbench)
    - [Command line parameters](#command-line-parameters)
  - [Script file format](#script-file-format)
  - [Shortcomings](#shortcomings)
  - [Converting scripts from Solar Eclipse Maestro](#converting-scripts-from-solar-eclipse-maestro)
    - [Known Solar Eclipse Maestro commands](#known-solar-eclipse-maestro-commands)
  - [Image attributions](#image-attributions)
    - [GUI icons](#gui-icons)


## Installation instructions

### Installation on macOS

- Install poetry by executing the following line in the terminal

```bash
curl -sSL https://install.python-poetry.org | sed 's/symlinks=False/symlinks=True/' | python3 -
```

- For modern Apple Mac computers (using Apple Silicon processors), install [homebrew](https://brew.sh/). Add your homebrew/bin directory to your PATH. Then install gphoto2 using homebrew:

```bash
export PATH=<location_of_homebrew_installation>/bin:$PATH
brew install gphoto2
```

- Check out the source code:

```bash
git clone https://github.com/AstroWimSara/SolarEclipseWorkbench.git
cd SolarEclipseWorkbench
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory

```bash
poetry install
poetry shell
pip3 install PyObjC
```

### Installation on Ubuntu 22.04

- Install poetry by executing the following line in the terminal

```bash
sudo apt install curl git
curl -sSL https://install.python-poetry.org | sed 's/symlinks=False/symlinks=True/' | python3 -
```

- Check out the source code:

```bash
git clone https://github.com/AstroWimSara/SolarEclipseWorkbench.git
cd SolarEclipseWorkbench
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory

```bash
poetry install
poetry shell
```

- Eventually, to make the sound notifications a bit faster, install pygobject:

```bash
sudo apt install libcairo2-dev libgirepository1.0-dev gcc
pip install pygobject
```

## Installation instructions for Windows 11

- GPhoto2 is only available for Linux and macOS.  To run Solar Eclipse Workbench, wsl should be used.  
- Open a terminal in Windows
- Install wsl by executing the command
- 
```bash
wsl --install
```

- Start using wsl by typing `wsl` in a new terminal.

- Install poetry by executing the following line in the terminal

```bash
curl -sSL https://install.python-poetry.org | sed 's/symlinks=False/symlinks=True/' | python3 -
```

- Check out the source code:

```bash
git clone https://github.com/AstroWimSara/SolarEclipseWorkbench.git
```

- Log out from wsl (by typing `exit`) and log in again.
- Install the python environment by executing the following command in the Solar Eclipse Workbench directory

```bash
cd SolarEclipseWorkbench
poetry install
poetry shell
```

- Install needed packages

```bash
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libxkbcommon-x11-0
```

- Sound on WSL does not work.  It should be possible to make he sound work by following the steps from this page: 
https://www.reddit.com/r/bashonubuntuonwindows/comments/hrn1lz/wsl_sound_through_pulseaudio_solved/
If this doesn't work, make sure not to include sound notifications in your script.

- Eventually, to make the sound notifications a bit faster, install pygobject:

```bash
sudo apt install libcairo2-dev libgirepository1.0-dev gcc python3-dev
pip install pygobject
```

## Running Solar Eclipse Workbench

- Before starting Solar Eclipse Workbench, make sure to enable the correct python environment by executing the following command in the installation directory: 
  
```bash
poetry shell
```

- The main script to start is _sew.py_.  You can add a parameters to set the needed parameters for the eclipse.  Some examples:

```bash
# On macos, start the commands with sudo
sudo python src/solareclipseworkbench/sew.py -d 2024-04-08 -lon -104.63525 -lat 24.01491 -alt 1877.3 -s config/scripts/voice_prompts.txt -r c1 -m 2
sudo python src/solareclipseworkbench/sew.py -g

# In Linux or using WSL on Windows, start the command without sudo
python src/solareclipseworkbench/sew.py -d 2024-04-08 -lon -104.63525 -lat 24.01491 -alt 1877.3 -s config/scripts/testEOS80D.txt -r c1 -m 2
python src/solareclipseworkbench/sew.py -g
```

- There is a problem with gphoto2.  On macOS, Solar Eclipse Workbench needs to be started with sudo rights to be able to connect to the cameras.  In Linux (or Windows using wsl), sudo should not be used.
- The first time you run Solar Eclipse Workbench, some files are downloaded from the internet.  Make sure to do this before eclipse day!

### Command line parameters

The following command line parameters can be used to start up sew.py.

| Short parameter | Long parameter        | Description                                                                |
|-----------------|-----------------------|----------------------------------------------------------------------------|
| -h              | --help                | Show the help message and exit                                             |
| -g              | --gui                 | Start the Solar Eclipse Workbench GUI                                      |
| -d DATE         | --date DATE           | Date of the solar eclipse (in YYYY-MM-DD format)                           |
| -lon LONGITUDE  | --longitude LONGITUDE | Longitude of the location where to watch the solar eclipse (W is negative) |
| -lat LATITUDE   | --latitude LATITUDE   | Latitude of the location where to watch the solar eclipse (N is positive)  |
| -alt ALTITUDE   | --altitude ALTITUDE   | Altitude of the location where to watch the solar eclipse (in meters)      |
| -s SCRIPT       | --script SCRIPT       | Script to execute (with voice prompts and camera commands)                 |
| -c1 C1          | --c1 C1               | Minutes to C1 when simulating.                                             |


## Script file format

Solar Eclipse Workbench can use the following commands:

- **take_picture** - Set the aperture, shutter speed and ISO of the camera and take a picture.

```take_picture, C1, -, 0:01:02.0, Canon EOS 80D, 1/1250, 8.0, 200, "Pre-C1 uneclipsed (Iter. 1)"```

This command will take a picture 1 minutes and 2 seconds before first contact (C1) with the Canon EOS 80D.  The ISO will be set to 200, aperture to 8.0 and shutter speed to 1/1250s.

- **take_burst**  - Set the aperture, shutter speed and ISO of the camera and take a burst of pictures during 3 seconds.

```take_burst, C1, +, 0:00:08.0, Canon EOS 80D, 1/2000, 5.6, 400, 3, "Burst test"```

- **voice_prompt** - Play a sound file.  

```voice_prompt, C4, -, 00:00:03, C4_IN_3_SECONDS, "3 seconds before C4 voice prompt"```

This command will play the C4_IN_3_SECONDS sound file 3 seconds before fourth contact (C4).

- **sync_cameras** - Read out the camera settings

```sync_cameras, C2, -, 00:00:04, "Sync the camera status"```

## Shortcomings

- In normal mode, only one picture every two seconds can be made.

## Converting scripts from Solar Eclipse Maestro

Scripts from Solar Eclipse Maestro can be converted to scripts that can be used by Solar Eclipse Workbench.  Execute:

```bash
python scripts/convert_sem_files.py -i solar_eclipse_maestro_files.txt -o my_script.txt
```

### Known Solar Eclipse Maestro commands

At this moment, Solar Eclipse Workbench only knows a subset of commands from Solar Eclipse Maestro.  These commands can be used:

| Command              | Since version |
|----------------------|---------------|
| FOR,(INTERVALOMETER) | 1.0           |
| TAKEPIC              | 1.0           |
| PLAY                 | 1.0           |

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
