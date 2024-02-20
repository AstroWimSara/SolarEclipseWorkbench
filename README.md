# Solar Eclipse Workbench

![Solar Eclipse Workbench logo](img/logo-small.jpg)

## Table of contents
- [Solar Eclipse Workbench](#solar-eclipse-workbench)
  - [Table of contents](#table-of-contents)
  - [Installation instructions](#installation-instructions)
  - [Installation instructions for Windows](#installation-instructions-for-windows)
  - [Running Solar Eclipse Workbench](#running-solar-eclipse-workbench)
  - [Converting scripts from Solar Eclipse Maestro](#converting-scripts-from-solar-eclipse-maestro)
    - [Known Solar Eclipse Maestro commands](#known-solar-eclipse-maestro-commands)
  - [Image attributions](#image-attributions)
    - [GUI icons](#gui-icons)


## Installation instructions

- Install poetry by executing the following line in the terminal (on Linux, or Mac)

```bash
curl -sSL https://install.python-poetry.org | sed 's/symlinks=False/symlinks=True/' | python3 -
```

- For modern Apple Mac computers (using Apple Silicon processors), install [homebrew](https://brew.sh/). Add your homebrew/bin directory to your PATH. Then install gphoto2 using homebrew:

```bash
export PATH=<location_of_homebrew_installation>/bin:$PATH
brew install gphoto2
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory

```bash
poetry install
```

## Installation instructions for Windows

- GPhoto2 is only available for Linux and macOS.  To run Solar Eclipse Workbench, wsl can be used.  
- Open a terminal in Windows
- Install wsl by executing the command
```bash
wsl --install
wsl --install Ubuntu-22.04
```
- Start using wsl by typing `wsl` in a terminal.
- Install all needed dependencies in wsl by executing:
```bash
curl -sSL https://install.python-poetry.org | python3 -
sudo apt update
sudo apt install libgl1
poetry install
```
- 

## Running Solar Eclipse Workbench

- Before starting Solar Eclipse Workbench, make sure to enable the correct python environment by executing the following command in the installation directory: 
  
```bash
poetry shell
sudo python src/solareclipseworkbench/gui.py
```

- There is a problem with gphoto2.  On macOS, Solar Eclipse Workbench needs to be started with sudo rights to be able to connect to the cameras.  In Linux (or Windows using wsl), sudo should not be used.
- The first time you run Solar Eclipse Workbench, some files are downloaded from the internet.  Make sure to do this before eclipse day!

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
