# Solar Eclipse Workbench

![Solar Eclipse Workbench logo](img/logo-small.jpg)

## Table of contents
- [Solar Eclipse Workbench](#solar-eclipse-workbench)
  - [Table of contents](#table-of-contents)
  - [Installation instructions](#installation-instructions)
  - [Running Solar Eclipse Workbench](#running-solar-eclipse-workbench)


## Installation instructions

- Install poetry by executing the following line in the terminal (on Linux, or Mac)

```bash
curl -sSL https://install.python-poetry.org | sed 's/symlinks=False/symlinks=True/' | python3 -
```

- For modern Apple Mac computers (using Apple Silicon processors), install [homebrew](https://brew.sh/). Then install gphoto2 using homebrew:

```bash
brew install gphoto2
```

- Install the python environment by executing the following command in the Solar Eclipse Workbench directory

```bash
poetry install
```

## Running Solar Eclipse Workbench

- Before starting Solar Eclipse Workbench, make sure to enable the correct python environment by executing the following command in the installation directory: 
  
```bash
poetry shell
```

- There is a problem with gphoto2.  On macOS, Solar Eclipse Workbench needs to be started with sudo rights to be able to connect to the cameras.