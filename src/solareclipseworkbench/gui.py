""" Solar Eclipse Workbench GUI, implemented according to the MVC pattern:

    - Model: SolarEclipseModel
    - View: SolarEclipseView
    - Controller: SolarEclipseController
"""
import argparse
import datetime
import logging
import math
import os.path
import queue
import sys
import time
from dataclasses import dataclass
from importlib.metadata import version, PackageNotFoundError
from enum import Enum
from pathlib import Path
from typing import Union, Optional

import geopandas
import numpy as np
import pandas as pd
import pytz
from PyQt6.QtCore import QTimer, QRect, Qt, QAbstractTableModel, QModelIndex, QSettings, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QIntValidator, QCloseEvent, QPixmap, QImage, QPainter, QPen, QColor
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, \
QGridLayout, QGroupBox, QComboBox, QPushButton, QLineEdit, QFileDialog, QScrollArea, QSlider, QTableView, \
QMessageBox, QDialog, QPlainTextEdit, QProgressBar, QToolButton
from PyQt6 import QtWidgets
from apscheduler.job import Job
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from astropy.time import Time
from geodatasets import get_path
from gphoto2 import GPhoto2Error, Camera
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from skyfield.api import load, wgs84

import threading

from solareclipseworkbench.camera import get_camera_dict, get_battery_level, get_free_space, get_space, \
get_shooting_mode, get_focus_mode, set_time, CameraSettings, LiveViewThread, get_sony_save_destination, \
get_sony_image_quality, _is_sony_camera_instance
from solareclipseworkbench.observer import Observer, Observable
from solareclipseworkbench.qt_utils import apply_system_color_scheme
from solareclipseworkbench.reference_moments import calculate_reference_moments, ReferenceMomentInfo
from solareclipseworkbench.location_ui import ConfigManager, LocationWidget
from solareclipseworkbench.constants import SUN_RADIUS, MOON_RADIUS
from solareclipseworkbench import configuration

ICON_PATH = Path(__file__).parent.resolve() / "img"

TIME_FORMATS = {
    "24 hours": "%H:%M:%S",
    "12 hours": "%I:%M:%S"}

DATE_FORMATS = {
    "dd Month yyyy": "%d %b %Y",
    "dd/mm/yyyy": "%d/%m/%Y",
    "mm/dd/yy": "%m/%d/%Y"
}

BEFORE_AFTER = {
    "before": 1,
    "after": -1
}

REFERENCE_MOMENTS = ["C1", "C2", "MAX", "C3", "C4", "sunset", "sunrise"]

LOGGER = logging.getLogger("Solar Eclipse Workbench UI")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s', datefmt='%a, %d %b %Y %H:%M:%S', filename="/tmp/solareclipseworkbench.log", filemode='w')


class BannerNotification(QFrame):
    def __init__(self, text="", parent=None):
        super().__init__(parent)

        # Scope style ONLY to this class to prevent internal widget inheritance bugs
        self.setStyleSheet('''
            BannerNotification {
                background-color: #FFF3CD;
                border-radius: 4px;
            }
            QLabel {
                color: #856404;
                background: transparent;
                border: none;
            }
            QToolButton {
                border: none;
                background: transparent;
                color: #856404;
                font-weight: bold;
            }
            QToolButton:hover {
                color: #000000;
            }
        ''')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self.label = QLabel(text)
        self.label.setWordWrap(True)

        self.close_btn = QToolButton()
        self.close_btn.setText("✕")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # Explicitly hide the root frame (self) when clicked
        self.close_btn.clicked.connect(self.hide)

        layout.addWidget(self.label, 1)
        layout.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)

    def setText(self, text: str):
        self.label.setText(text)


class SolarEclipseModel:
    """ Model for the Solar Eclipse Workbench UI in the MVC pattern. """

    def __init__(self):
        """ Initialisation of the model of the Solar Eclipse Workbench UI.

        This model keeps stock of the following information:

            - The longitude, latitude, and altitude of the location at which the solar eclipse will be observed;
            - The date of the eclipse that will be observed;
            - The current time (local time + UTC);
            - The information of the reference moments (C1, C2, maximum eclipse, C3, C4, sunrise, and sunset) of the
              solar eclipse: time (local time + UTC), azimuth, and altitude;
            - A dictionary with the connected cameras.
        """

        # Location

        self.is_location_set = False
        self.longitude: Union[float, None] = None
        self.latitude: Union[float, None] = None
        self.altitude: Union[float, None] = None

        # Eclipse date

        self.is_eclipse_date_set = False
        self.eclipse_date: Union[Time, None] = None

        # Time

        self.local_time: Union[datetime.datetime, None] = None
        self.utc_time: Union[datetime.datetime, None] = None

        # Reference moments

        self.reference_moments: Union[dict, None] = None

        self.c1_info: Union[ReferenceMomentInfo, None] = None
        self.c2_info: Union[ReferenceMomentInfo, None] = None
        self.max_info: Union[ReferenceMomentInfo, None] = None
        self.c3_info: Union[ReferenceMomentInfo, None] = None
        self.c4_info: Union[ReferenceMomentInfo, None] = None
        self.sunrise_info: Union[ReferenceMomentInfo, None] = None
        self.sunset_info: Union[ReferenceMomentInfo, None] = None

        # Camera(s)

        self.camera_overview: CameraOverviewTableModel = CameraOverviewTableModel()

        # GPS–computer time offset: set when the user acquires a USB GPS fix.
        # timedelta(0) means "use computer clock", which is the default.
        self.gps_time_offset: datetime.timedelta = datetime.timedelta(0)

    def set_position(self, longitude: float, latitude: float, altitude: float):
        """ Set the geographical position of the observing location.

        Args:
            - longitude: Longitude of the location [degrees]
            - latitude: Latitude of the location [degrees]
            - altitude: Altitude of the location [meters]
        """

        self.longitude = longitude
        self.latitude = latitude
        self.altitude = altitude

        self.is_location_set = True

    def set_eclipse_date(self, eclipse_date: Time):
        """ Set the eclipse date.

        Args:
            - eclipse_date: Eclipse date
        """

        self.eclipse_date = eclipse_date

        self.is_eclipse_date_set = True

    def get_reference_moments(self):
        """ Calculate and return timing of reference moments, eclipse magnitude, and eclipse type.

        Returns:
            - Dictionary with the information about the reference moments (C1, C2, maximum eclipse, C3, C4, sunrise,
              and sunset)
            - Magnitude of the eclipse (0: no eclipse, 1: total eclipse)
            - Eclipse type (total / annular / partial / no eclipse)
        """

        self.reference_moments, magnitude, eclipse_type = calculate_reference_moments(self.longitude, self.latitude,
                                                                                      self.altitude, self.eclipse_date)

        # No eclipse

        if eclipse_type == "No eclipse":
            self.c1_info = None
            self.c2_info = None
            self.max_info = None
            self.c3_info = None
            self.c4_info = None

        # Partial / total eclipse

        elif eclipse_type == "Partial":
            self.c1_info = self.reference_moments["C1"]
            self.c2_info = None
            self.max_info = self.reference_moments["MAX"]
            self.c3_info = None
            self.c4_info = self.reference_moments["C4"]

        # Total eclipse

        else:
            self.c1_info = self.reference_moments["C1"]
            self.c2_info = self.reference_moments["C2"]
            self.max_info = self.reference_moments["MAX"]
            self.c3_info = self.reference_moments["C3"]
            self.c4_info = self.reference_moments["C4"]

        self.sunrise_info = self.reference_moments["sunrise"]
        self.sunset_info = self.reference_moments["sunset"]

        return self.reference_moments, magnitude, eclipse_type

    # def set_camera_overview(self, camera_overview: dict):
    #     """ Set the camera overview to the given dictionary.
    #
    #     Args:
    #         - camera_overview: Dictionary containing the camera overview
    #     """
    #
    #     self.camera_overview = camera_overview

    def sync_camera_time(self):
        """ Set the time of all connected cameras to the time of the computer."""

        if not self.camera_overview or not getattr(self.camera_overview, 'camera_overview_dict', None):
            logging.debug('sync_camera_time: no camera overview available yet; skipping')
            return

        seen_ids: set = set()
        for camera_name, camera in self.camera_overview.camera_overview_dict.items():
            if id(camera) in seen_ids:
                continue
            seen_ids.add(id(camera))
            logging.info(f"Syncing time for camera {camera_name}")
            set_time(camera)

    def check_camera_state(self):
        """ Check whether the focus mode and shooting mode of all connected cameras is set to 'Manual'.

        For the camera(s) for which the focus mode and/or shooting mode is not set to 'Manual', a warning message is
        logged.

        Returns:
            List of warning strings (empty if all cameras are in Manual mode).
        """

        warnings = []

        if not self.camera_overview or not getattr(self.camera_overview, 'camera_overview_dict', None):
            logging.debug('check_camera_state: no camera overview available yet; skipping')
            return warnings

        seen_ids: set = set()
        for camera_name, camera in self.camera_overview.camera_overview_dict.items():
            if id(camera) in seen_ids:
                continue
            seen_ids.add(id(camera))

            # Focus mode

            try:
                focus_mode = get_focus_mode(camera)
                if focus_mode.lower() != "manual":
                    msg = (f"Focus mode for {camera_name} should be 'Manual' (currently '{focus_mode}').\n"
                           f"Switch the lens autofocus switch to MF.")
                    LOGGER.warning(msg)
                    warnings.append(msg)
            except GPhoto2Error:
                msg = f"Could not read focus mode for {camera_name}."
                LOGGER.warning(msg)
                warnings.append(msg)

            # Shooting mode

            try:
                shooting_mode = get_shooting_mode(camera_name, camera)
                if shooting_mode.lower() != "manual":
                    msg = (f"Shooting mode for {camera_name} should be 'Manual' (currently '{shooting_mode}').\n"
                           f"Turn the camera's mode dial to M.")
                    LOGGER.warning(msg)
                    warnings.append(msg)
            except GPhoto2Error:
                msg = f"Could not read shooting mode for {camera_name}."
                LOGGER.warning(msg)
                warnings.append(msg)

        return warnings


class SolarEclipseView(QMainWindow, Observable):
    """ View for the Solar Eclipse Workbench UI in the MVC pattern. """

    def __init__(self, is_simulator: bool = False, low_cpu_mode: bool = False):
        """ Initialisation of the view of the Solar Eclipse Workbench UI.

        This view is responsible for:

            - Visualisation of:
                - The current date ant time (local time + UTC);
                - The location at which the solar eclipse will be observed (longitude, latitude, and altitude);
                - The date and type (total/partial/annular) of the observed eclipse;
                - The information of the reference moments (C1, C2, maximum eclipse, C3, C4, sunrise, and sunset) of the
                  observed solar eclipse: time (local time + UTC), azimuth, and altitude;
                - The information about the connected cameras: camera name, battery level, and free memory;
            - Bringing up a pop-up window in which the location at which the solar eclipse will be observed (longitude,
              latitude, and altitude) can be chosen and visualised;
            - Bringing up a pop-up in which the date of the solar eclipse can be selected from a drop-down menu;
            - Load the information of the reference moments of the observed solar eclipse;
            - Load the information about the connected cameras and synchronises their time to the time of the computer
              they are connected to;
            - Load the configuration file to schedule the tasks (voice prompts, taking pictures, updating the camera
              state);
            - Choose the time and date format.

        Args:
            - is_simulator: Indicates whether the UI should be started in simulator mode
        """

        super().__init__()

        self.controller = None
        self.is_simulator = is_simulator
        self.low_cpu_mode = low_cpu_mode

        self.setGeometry(300, 300, 1500, 1000)
        try:
            _version = version("solareclipseworkbench")
        except PackageNotFoundError:
            _version = "unknown"
        self.setWindowTitle(f"Solar Eclipse Workbench v{_version}")

        self.date_format = list(DATE_FORMATS.keys())[0]
        self.time_format = list(TIME_FORMATS.keys())[0]

        self.toolbar = None
        self.location_action = QAction("Location", self)
        self.date_action = QAction("Date", self)
        self.reference_moments_action = QAction("Reference moments", self)
        self.camera_action = QAction("Camera(s)", self)
        self.simulator_action = QAction("Simulator", self)
        self.file_action = QAction("File", self)
        self.shutdown_scheduler_action = QAction("Stop", self)
        self.datetime_format_action = QAction("Datetime format", self)
        self.save_action = QAction("Save", self)
        self.live_view_action = QAction("Live View", self)

        self.place_time_frame = QFrame()

        self.eclipse_date_widget = QWidget()
        self.eclipse_date_label = QLabel(f"Eclipse date [{self.date_format}]")
        self.eclipse_date = QLabel("")

        self.reference_moments_widget = QWidget()

        self.c1_time_local_label = QLabel()
        self.c1_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c2_time_local_label = QLabel()
        self.c2_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.max_time_local_label = QLabel()
        self.max_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c3_time_local_label = QLabel()
        self.c3_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c4_time_local_label = QLabel()
        self.c4_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sunrise_time_local_label = QLabel()
        self.sunrise_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sunset_time_local_label = QLabel()
        self.sunset_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c1_time_utc_label = QLabel()
        self.c1_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c2_time_utc_label = QLabel()
        self.c2_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.max_time_utc_label = QLabel()
        self.max_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c3_time_utc_label = QLabel()
        self.c3_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c4_time_utc_label = QLabel()
        self.c4_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sunrise_time_utc_label = QLabel()
        self.sunrise_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sunset_time_utc_label = QLabel()
        self.sunset_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c1_countdown_label = QLabel()
        self.c1_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c2_countdown_label = QLabel()
        self.c2_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.max_countdown_label = QLabel()
        self.max_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c3_countdown_label = QLabel()
        self.c3_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c4_countdown_label = QLabel()
        self.c4_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sunrise_countdown_label = QLabel()
        self.sunrise_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sunset_countdown_label = QLabel()
        self.sunset_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c1_azimuth_label = QLabel()
        self.c1_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c2_azimuth_label = QLabel()
        self.c2_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.max_azimuth_label = QLabel()
        self.max_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c3_azimuth_label = QLabel()
        self.c3_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c4_azimuth_label = QLabel()
        self.c4_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c1_altitude_label = QLabel()
        self.c1_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c2_altitude_label = QLabel()
        self.c2_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.max_altitude_label = QLabel()
        self.max_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c3_altitude_label = QLabel()
        self.c3_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.c4_altitude_label = QLabel()
        self.c4_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.date_label = QLabel(f"Date [{self.date_format}]")
        self.date_label_local = QLabel()
        self.date_label_local.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label_local = QLabel()
        self.time_label_local.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label_local.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_label_utc = QLabel()
        self.date_label_utc.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label_utc = QLabel()
        self.time_label_utc.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.longitude_label = QLabel()
        self.longitude_label.setToolTip(
            "Positive values: East of Greenwich meridian; Negative values: West of Greenwich meridian")
        self.latitude_label = QLabel()
        self.latitude_label.setToolTip("Positive values: Northern hemisphere; Negative values: Southern hemisphere")
        self.altitude_label = QLabel()

        self.eclipse_type = QLabel()

        self.camera_overview = QTableView()

        self.eclipse_visualization = EclipsePlotWidget()

        self.jobs_table = QJobsTableView()

        # One-line Sony banner (hidden by default; shown when a Sony camera is present)
        self.sony_banner_label = BannerNotification()
        self.sony_banner_label.setVisible(False)

        self.init_ui()

    def save_settings(self):
        """ Save the settings.

        The settings that are saved are:

            - Longitude [degrees];
            - Latitude [degrees];
            - Altitude [m];
            - Eclipse date;
            - Date format;
            - Time format.
        """

        # Location

        longitude = self.longitude_label.text()
        latitude = self.latitude_label.text()
        altitude = self.altitude_label.text()

        if longitude and latitude and altitude:
            self.settings.setValue("longitude", float(longitude))
            self.settings.setValue("latitude", float(latitude))
            self.settings.setValue("altitude", float(altitude))

        # Eclipse date

        self.settings.setValue("eclipse_date", self.eclipse_date.text())

        # Date & time format

        self.settings.setValue("date_format", self.date_format)
        self.settings.setValue("time_format", self.time_format)

    def init_ui(self):
        """ Add all components to the UI. """

        app_frame = QFrame()
        app_frame.setObjectName("AppFrame")

        self.add_toolbar()

        vbox_left = QVBoxLayout()

        place_time_group_box = QGroupBox()
        place_time_grid_layout = QGridLayout()

        place_time_grid_layout.addWidget(QLabel("Local", alignment=Qt.AlignmentFlag.AlignRight), 0, 1)
        place_time_grid_layout.addWidget(QLabel("UTC", alignment=Qt.AlignmentFlag.AlignRight), 0, 2)

        place_time_grid_layout.addWidget(self.date_label, 1, 0)
        place_time_grid_layout.addWidget(self.date_label_local, 1, 1)
        place_time_grid_layout.addWidget(self.date_label_utc, 1, 2)

        place_time_grid_layout.addWidget(QLabel("Time"), 2, 0)
        place_time_grid_layout.addWidget(self.time_label_local, 2, 1)
        place_time_grid_layout.addWidget(self.time_label_utc, 2, 2)

        place_time_group_box.setLayout(place_time_grid_layout)
        place_time_group_box.setFixedWidth(400)
        vbox_left.addWidget(place_time_group_box)

        location_group_box = QGroupBox()
        location_grid_layout = QGridLayout()
        location_grid_layout.addWidget(QLabel("Longitude [°]"), 0, 0)
        location_grid_layout.addWidget(self.longitude_label, 0, 1)
        location_grid_layout.addWidget(QLabel("Latitude [°]"), 1, 0)
        location_grid_layout.addWidget(self.latitude_label, 1, 1)
        location_grid_layout.addWidget(QLabel("Altitude [m]"), 2, 0)
        location_grid_layout.addWidget(self.altitude_label, 2, 1)
        location_group_box.setLayout(location_grid_layout)
        location_group_box.setFixedWidth(400)
        vbox_left.addWidget(location_group_box)

        eclipse_date_group_box = QGroupBox()
        eclipse_date_grid_layout = QGridLayout()
        eclipse_date_grid_layout.addWidget(self.eclipse_date_label, 0, 0)
        eclipse_date_grid_layout.addWidget(self.eclipse_date, 0, 1)
        eclipse_date_grid_layout.addWidget(QLabel("Eclipse type"), 1, 0)
        eclipse_date_grid_layout.addWidget(self.eclipse_type, 1, 1)

        eclipse_date_group_box.setLayout(eclipse_date_grid_layout)
        eclipse_date_group_box.setFixedWidth(400)
        vbox_left.addWidget(eclipse_date_group_box)

        reference_moments_group_box = QGroupBox()
        reference_moments_grid_layout = QGridLayout()
        reference_moments_grid_layout.addWidget(QLabel("Time (local)", alignment=Qt.AlignmentFlag.AlignRight), 0, 1)
        reference_moments_grid_layout.addWidget(self.c1_time_local_label, 1, 1)
        reference_moments_grid_layout.addWidget(self.c2_time_local_label, 2, 1)
        reference_moments_grid_layout.addWidget(self.max_time_local_label, 3, 1)
        reference_moments_grid_layout.addWidget(self.c3_time_local_label, 4, 1)
        reference_moments_grid_layout.addWidget(self.c4_time_local_label, 5, 1)
        reference_moments_grid_layout.addWidget(self.sunrise_time_local_label, 6, 1)
        reference_moments_grid_layout.addWidget(self.sunset_time_local_label, 7, 1)
        reference_moments_grid_layout.addWidget(QLabel("Time (UTC)", alignment=Qt.AlignmentFlag.AlignRight), 0, 2)
        reference_moments_grid_layout.addWidget(self.c1_time_utc_label, 1, 2)
        reference_moments_grid_layout.addWidget(self.c2_time_utc_label, 2, 2)
        reference_moments_grid_layout.addWidget(self.max_time_utc_label, 3, 2)
        reference_moments_grid_layout.addWidget(self.c3_time_utc_label, 4, 2)
        reference_moments_grid_layout.addWidget(self.c4_time_utc_label, 5, 2)
        reference_moments_grid_layout.addWidget(self.sunrise_time_utc_label, 6, 2)
        reference_moments_grid_layout.addWidget(self.sunset_time_utc_label, 7, 2)
        reference_moments_grid_layout.addWidget(QLabel("Countdown", alignment=Qt.AlignmentFlag.AlignRight), 0, 3)
        reference_moments_grid_layout.addWidget(self.c1_countdown_label, 1, 3)
        reference_moments_grid_layout.addWidget(self.c2_countdown_label, 2, 3)
        reference_moments_grid_layout.addWidget(self.max_countdown_label, 3, 3)
        reference_moments_grid_layout.addWidget(self.c3_countdown_label, 4, 3)
        reference_moments_grid_layout.addWidget(self.c4_countdown_label, 5, 3)
        reference_moments_grid_layout.addWidget(self.sunrise_countdown_label, 6, 3)
        reference_moments_grid_layout.addWidget(self.sunset_countdown_label, 7, 3)
        reference_moments_grid_layout.addWidget(QLabel("Azimuth [°]", alignment=Qt.AlignmentFlag.AlignRight), 0, 4)
        reference_moments_grid_layout.addWidget(self.c1_azimuth_label, 1, 4)
        reference_moments_grid_layout.addWidget(self.c2_azimuth_label, 2, 4)
        reference_moments_grid_layout.addWidget(self.max_azimuth_label, 3, 4)
        reference_moments_grid_layout.addWidget(self.c3_azimuth_label, 4, 4)
        reference_moments_grid_layout.addWidget(self.c4_azimuth_label, 5, 4)
        reference_moments_grid_layout.addWidget(QLabel("Altitude [°]", alignment=Qt.AlignmentFlag.AlignRight), 0, 5)
        reference_moments_grid_layout.addWidget(self.c1_altitude_label, 1, 5)
        reference_moments_grid_layout.addWidget(self.c2_altitude_label, 2, 5)
        reference_moments_grid_layout.addWidget(self.max_altitude_label, 3, 5)
        reference_moments_grid_layout.addWidget(self.c3_altitude_label, 4, 5)
        reference_moments_grid_layout.addWidget(self.c4_altitude_label, 5, 5)
        reference_moments_grid_layout.addWidget(QLabel("First contact (C1)"), 1, 0)
        reference_moments_grid_layout.addWidget(QLabel("Second contact (C2)"), 2, 0)
        reference_moments_grid_layout.addWidget(QLabel("Maximum eclipse"), 3, 0)
        reference_moments_grid_layout.addWidget(QLabel("Third contact (C3)"), 4, 0)
        reference_moments_grid_layout.addWidget(QLabel("Fourth contact (C4)"), 5, 0)
        reference_moments_grid_layout.addWidget(QLabel("Sunrise"), 6, 0)
        reference_moments_grid_layout.addWidget(QLabel("Sunset"), 7, 0)
        reference_moments_group_box.setLayout(reference_moments_grid_layout)
        reference_moments_group_box.setFixedWidth(600)

        # noinspection SpellCheckingInspection
        input_hbox = QHBoxLayout()
        input_hbox.addLayout(vbox_left)
        input_hbox.addWidget(reference_moments_group_box)

        self.camera_overview.setFixedHeight(300)
        input_hbox.addWidget(self.camera_overview)

        # noinspection SpellCheckingInspection
        output_hbox = QHBoxLayout()
        output_hbox.addWidget(self.eclipse_visualization)
        # output_hbox.addWidget(self.canvas)
        output_hbox.addWidget(self.jobs_table)

        global_layout = QVBoxLayout()
        # show reminder banner at top
        global_layout.addWidget(self.sony_banner_label)
        global_layout.addLayout(input_hbox)

        global_layout.addLayout(output_hbox)

        app_frame.setLayout(global_layout)

        self.setCentralWidget(app_frame)

    def add_toolbar(self):
        """ Create the toolbar of the UI.

        The toolbar has buttons for:

            - Bringing up a pop-up window in which the location at which the solar eclipse will be observed (longitude,
              latitude, and altitude) can be chosen and visualised;
            - Bringing up a pop-up in which the date of the solar eclipse can be selected from a drop-down menu;
            - Loading the information of the reference moments of the observed solar eclipse;
            - Loading the information about the connected cameras and synchronises their time to the time of the
              computer they are connected to;
            - Loading the configuration file to schedule the tasks (voice prompts, taking pictures, updating the camera
              state);
            - Bringing up a pop-up window in which you can choose the time and date format.
        """

        self.toolbar = self.addToolBar('MainToolbar')

        # Location

        self.location_action.setStatusTip("Location")
        self.location_action.setIcon(QIcon(str(ICON_PATH / "location.png")))
        self.location_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.location_action)

        # Date

        self.date_action.setStatusTip("Date")
        self.date_action.setIcon(QIcon(str(ICON_PATH / "calendar.png")))
        self.date_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.date_action)

        # Reference moments

        self.reference_moments_action.setStatusTip("Reference moments")
        self.reference_moments_action.setIcon(QIcon(str(ICON_PATH / "clock.png")))
        self.reference_moments_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.reference_moments_action)

        # Camera(s)

        self.camera_action.setStatusTip("Camera(s)")
        self.camera_action.setIcon(QIcon(str(ICON_PATH / "camera.png")))
        self.camera_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.camera_action)

        if self.is_simulator:
            self.simulator_action.setStatusTip("Configure simulator")
            self.simulator_action.setIcon(QIcon(str(ICON_PATH / "simulator.png")))
            self.simulator_action.triggered.connect(self.on_toolbar_button_click)
            self.toolbar.addAction(self.simulator_action)

        # Configuration file

        self.file_action.setStatusTip("File")
        self.file_action.setIcon(QIcon(str(ICON_PATH / "folder.png")))
        self.file_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.file_action)

        # Shutdown scheduler

        self.shutdown_scheduler_action.setStatusTip("Shut down scheduler")
        self.shutdown_scheduler_action.setIcon(QIcon(str(ICON_PATH / "stop.png")))
        self.shutdown_scheduler_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.shutdown_scheduler_action)

        # Date & time format

        self.datetime_format_action.setStatusTip("Datetime format")
        self.datetime_format_action.setIcon(QIcon(str(ICON_PATH / "settings.png")))
        self.datetime_format_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.datetime_format_action)

        # Save settings

        self.save_action.setStatusTip("Save configuration")
        self.save_action.setIcon(QIcon(str(ICON_PATH / "save.png")))
        self.save_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.save_action)

        # Live View

        self.live_view_action.setStatusTip("Open live view window (1 fps preview from camera)")
        self.live_view_action.setIcon(QIcon(str(ICON_PATH / "camera.png")))
        self.live_view_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.live_view_action)

        # Refresh Plot
        if self.low_cpu_mode:
            self.refresh_plot_action = QAction("Refresh Plot", self)
            self.refresh_plot_action.setStatusTip("Manually update the eclipse geometry plot")
            self.refresh_plot_action.setIcon(QIcon(str(ICON_PATH / "refresh.png")))
            self.refresh_plot_action.triggered.connect(self.on_toolbar_button_click)
            self.toolbar.addAction(self.refresh_plot_action)

    def on_toolbar_button_click(self):
        """ Action triggered when a toolbar button is clicked."""

        sender = self.sender()
        self.notify_observers(sender)

    def update_time(self, current_time_local: datetime.datetime, current_time_utc: datetime.datetime,
                    countdown_c1: datetime.timedelta, countdown_c2: datetime.timedelta,
                    countdown_max: datetime.timedelta, countdown_c3: datetime.timedelta,
                    countdown_c4: datetime.timedelta, countdown_sunrise: datetime.timedelta,
                    countdown_sunset: datetime.timedelta):
        """ Update the displayed current time and countdown clocks.

        Args:
            - current_time_local: Current time in local timezone
            - current_time_utc: Current time in UTC timezone
            - countdown_c1: Countdown clock to C1
            - countdown_c2: Countdown clock to C2
            - countdown_max: Countdown clock to maximum eclipse
            - countdown_c3: Countdown clock to C3
            - countdown_c4: Countdown clock to C4
            - countdown_sunrise: Countdown clock to sunrise
            - countdown_sunset: Countdown clock to sunset
        """

        self.eclipse_date_label.setText(f"Eclipse date [{self.date_format}]")

        self.date_label.setText(f"Date [{self.date_format}]")
        self.date_label_local.setText(datetime.datetime.strftime(current_time_local, DATE_FORMATS[self.date_format]))
        self.date_label_utc.setText(datetime.datetime.strftime(current_time_utc, DATE_FORMATS[self.date_format]))

        self.time_label_local.setText(format_time(current_time_local, self.time_format))
        self.time_label_utc.setText(format_time(current_time_utc, self.time_format))

        if not countdown_c1 or countdown_c1.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_c1))
        self.c1_countdown_label.setText(label_text)

        if not countdown_c2 or countdown_c2.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_c2))
        self.c2_countdown_label.setText(label_text)

        if not countdown_max or countdown_max.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_max))
        self.max_countdown_label.setText(label_text)

        if not countdown_c3 or countdown_c3.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_c3))
        self.c3_countdown_label.setText(label_text)

        if not countdown_c4 or countdown_c4.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_c4))
        self.c4_countdown_label.setText(label_text)

        if not countdown_sunrise or countdown_sunrise.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_sunrise))
        self.sunrise_countdown_label.setText(label_text)

        if not countdown_sunset or countdown_sunset.total_seconds() <= 0:
            label_text = "-"
        else:
            label_text = str(format_countdown(countdown_sunset))
        self.sunset_countdown_label.setText(label_text)


    def show_reference_moments(self, reference_moments: dict, magnitude: float, eclipse_type: str):
        """ Display the given reference moments, magnitude, and eclipse type.

        Args:
            - reference_moments: Dictionary with the reference moments (C1, C2, maximum eclipse, C3, C4, sunrise, and
                                 sunset)
            - magnitude: Eclipse magnitude (0: no eclipse, 1: total eclipse)
            - eclipse_type: Eclipse type (total / annular / partial / no eclipse)
        """

        if eclipse_type == "Partial" or eclipse_type == "Annular":
            self.eclipse_type.setText(eclipse_type + f" ({round(magnitude, 2)})")
        elif eclipse_type == "No eclipse":
            self.eclipse_type.setText(eclipse_type)
        else:
            minutes, seconds = divmod(reference_moments["duration"].seconds, 60)
            self.eclipse_type.setText(f"{eclipse_type} ({minutes}:{seconds:02})")

        # First contact

        if "C1" in reference_moments:
            c1_info: ReferenceMomentInfo = reference_moments["C1"]
            self.c1_time_utc_label.setText(format_time(c1_info.time_utc, self.time_format))
            self.c1_time_local_label.setText(format_time(c1_info.time_local, self.time_format))
            self.c1_azimuth_label.setText(str(int(c1_info.azimuth)))
            self.c1_altitude_label.setText(str(int(c1_info.altitude)))
        else:
            self.c1_time_utc_label.setText("")
            self.c1_time_local_label.setText("")
            self.c1_azimuth_label.setText("")
            self.c1_altitude_label.setText("")

        # Second contact

        if "C2" in reference_moments:
            c2_info: ReferenceMomentInfo = reference_moments["C2"]
            self.c2_time_utc_label.setText(format_time(c2_info.time_utc, self.time_format))
            self.c2_time_local_label.setText(format_time(c2_info.time_local, self.time_format))
            self.c2_azimuth_label.setText(str(int(c2_info.azimuth)))
            self.c2_altitude_label.setText(str(int(c2_info.altitude)))
        else:
            self.c2_time_utc_label.setText("")
            self.c2_time_local_label.setText("")
            self.c2_azimuth_label.setText("")
            self.c2_altitude_label.setText("")

        # Maximum eclipse

        if "MAX" in reference_moments:
            max_info: ReferenceMomentInfo = reference_moments["MAX"]
            self.max_time_utc_label.setText(format_time(max_info.time_utc, self.time_format))
            self.max_time_local_label.setText(format_time(max_info.time_local, self.time_format))
            self.max_azimuth_label.setText(str(int(max_info.azimuth)))
            self.max_altitude_label.setText(str(int(max_info.altitude)))
        else:
            self.max_time_utc_label.setText("")
            self.max_time_local_label.setText("")
            self.max_azimuth_label.setText("")
            self.max_altitude_label.setText("")

        # Third contact

        if "C3" in reference_moments:
            c3_info: ReferenceMomentInfo = reference_moments["C3"]
            self.c3_time_utc_label.setText(format_time(c3_info.time_utc, self.time_format))
            self.c3_time_local_label.setText(format_time(c3_info.time_local, self.time_format))
            self.c3_azimuth_label.setText(str(int(c3_info.azimuth)))
            self.c3_altitude_label.setText(str(int(c3_info.altitude)))
        else:
            self.c3_time_utc_label.setText("")
            self.c3_time_local_label.setText("")
            self.c3_azimuth_label.setText("")
            self.c3_altitude_label.setText("")

        # Fourth contact

        if "C4" in reference_moments:
            c4_info: ReferenceMomentInfo = reference_moments["C4"]
            self.c4_time_utc_label.setText(format_time(c4_info.time_utc, self.time_format))
            self.c4_time_local_label.setText(format_time(c4_info.time_local, self.time_format))
            self.c4_azimuth_label.setText(str(int(c4_info.azimuth)))
            self.c4_altitude_label.setText(str(int(c4_info.altitude)))
        else:
            self.c4_time_utc_label.setText("")
            self.c4_time_local_label.setText("")
            self.c4_azimuth_label.setText("")
            self.c4_altitude_label.setText("")

        # Sunrise

        sunrise_info: ReferenceMomentInfo = reference_moments["sunrise"]
        self.sunrise_time_utc_label.setText(format_time(sunrise_info.time_utc, self.time_format))
        self.sunrise_time_local_label.setText(format_time(sunrise_info.time_local, self.time_format))

        # Sunset

        sunset_info: ReferenceMomentInfo = reference_moments["sunset"]
        self.sunset_time_utc_label.setText(format_time(sunset_info.time_utc, self.time_format))
        self.sunset_time_local_label.setText(format_time(sunset_info.time_local, self.time_format))

    def closeEvent(self, close_event: QCloseEvent):
        """ Ask for confirmation before closing the application. """
        reply = QMessageBox.question(
            self,
            "Confirm Exit",
            "Are you sure you want to exit Solar Eclipse Workbench?\n\n"
            "Any running scheduler will be stopped.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Notify controller so it can clean up cameras, scheduler, etc.
            self.notify_observers(close_event)
            close_event.accept()
        else:
            close_event.ignore()


class SolarEclipseController(Observer):
    """ Controller for the Solar Eclipse Workbench UI in the MVC pattern. """

    def __init__(self, model: SolarEclipseModel,
                 view: SolarEclipseView,
                 is_simulator: bool,
                 low_cpu_mode: bool):
        """ Initialisation of the controller of the Solar Eclipse Workbench UI.

        Args:
            - model: Model for the Solar Eclipse Workbench UI
            - view: View for the Solar Eclipse Workbench UI
            - is_simulator: Indicates whether the UI should be started in simulator mode
        """

        self.model = model
        self.jobs_model: Union[JobsTableModel, None] = None
        self.model.camera_overview = CameraOverviewTableModel()

        self.view: SolarEclipseView = view
        self.view.camera_overview.setModel(self.model.camera_overview)
        self.view.camera_overview.resizeColumnsToContents()
        self.view.camera_overview.setColumnWidth(0, 100)
        self.view.add_observer(self)

        self.is_simulator: bool = is_simulator

        self.scheduler: Union[BackgroundScheduler, None] = None
        self.sim_reference_moment: Union[str, None] = None
        self.sim_offset_minutes: Union[int, None] = None

        self.location_popup: Union[LocationPopup, None] = None
        self.eclipse_popup: Union[EclipsePopup, None] = None
        self.simulator_popup: Union[SimulatorPopup, None] = None
        self.settings_popup: Union[SettingsPopup, None] = None

        self.time_display_timer = QTimer()
        self.time_display_timer.timeout.connect(self.update_time)
        self.time_display_timer.setInterval(1000)
        self.time_display_timer.start()

        # Update the eclipse visualization less frequently to save CPU/battery.
        # The main time display remains at 1 Hz; the plot updates every 5 seconds.
        self.visualization_timer = QTimer()
        self.visualization_timer.timeout.connect(self.update_visualization)
        self.visualization_timer.setInterval(5000)

        if not low_cpu_mode:
            self.visualization_timer.start()

        self._live_view_window: Union[LiveViewWindow, None] = None

        self.load_settings()

    def update_time(self):
        """ Update the displayed current time and countdown clocks."""

        current_time_local = datetime.datetime.now()
        current_time_utc = current_time_local.astimezone(tz=datetime.timezone.utc)

        self.model.local_time = current_time_local
        self.model.utc_time = current_time_utc

        countdown_c1 = self.model.c1_info.time_utc - current_time_utc if self.model.c1_info else None
        countdown_c2 = self.model.c2_info.time_utc - current_time_utc if self.model.c2_info else None
        countdown_max = self.model.max_info.time_utc - current_time_utc if self.model.max_info else None
        countdown_c3 = self.model.c3_info.time_utc - current_time_utc if self.model.c3_info else None
        countdown_c4 = self.model.c4_info.time_utc - current_time_utc if self.model.c4_info else None
        countdown_sunrise = self.model.sunrise_info.time_utc - current_time_utc if self.model.sunrise_info else None
        countdown_sunset = self.model.sunset_info.time_utc - current_time_utc if self.model.sunset_info else None

        self.view.update_time(current_time_local, current_time_utc, countdown_c1, countdown_c2, countdown_max,
                              countdown_c3, countdown_c4, countdown_sunrise, countdown_sunset)

        # Auto-pause live view 15 s before C2 until 15 s after C3 so scheduled
        # shots around second and third contact have uncontested USB access.
        if self._live_view_window is not None:
            c2 = self.model.c2_info
            c3 = self.model.c3_info
            _MARGIN = datetime.timedelta(seconds=15)
            in_totality = (
                c2 is not None
                and c3 is not None
                and (c2.time_utc - _MARGIN) <= current_time_utc <= (c3.time_utc + _MARGIN)
            )
            self._live_view_window.set_totality_paused(in_totality)

        # self.view.eclipse_visualization.plot(current_time_utc)    FIXME

        self.update_jobs_countdown()

    def update_jobs_countdown(self):
        """ Update the countdown of the scheduled jobs. """

        if self.jobs_model:
            self.jobs_model.update_countdown()

    def update_visualization(self):
        """Update the eclipse visualization at a reduced frequency.

        Uses the controller's current UTC time if available; falls back to
        computing the current UTC time if needed.
        """
        try:
            t = getattr(self.model, 'utc_time', None)
            if t is None:
                current_time_local = datetime.datetime.now()
                t = current_time_local.astimezone(tz=datetime.timezone.utc)

            self.view.eclipse_visualization.plot(t)
        except Exception:
            logging.exception("Error updating eclipse visualization")

    def do(self, actions):
        pass

    def update(self, changed_object):
        """ Take action when a notification is received from an observable.

        The following notifications can be received:

            - Change in location at which the solar eclipse will be observed;
            - Change in date at which the solar eclipse will be observed;
            - Change in simulation starting time (only when the UI was started in simulation mode);
            - Change in date and/or time format;
            - Closure of the UI window;
            - One of the buttons in the toolbar of the view is clicked.

        Args:
            - changed_object: Object from which the update was requested
        """

        if isinstance(changed_object, LocationPopup):
            longitude = float(changed_object.longitude.text())
            latitude = float(changed_object.latitude.text())
            altitude = float(changed_object.altitude.text())

            self.model.set_position(longitude, latitude, altitude)

            # Carry over any GPS–computer time offset measured by the USB GPS
            self.model.gps_time_offset = changed_object.location_widget.gps_time_offset

            self.view.longitude_label.setText(str(longitude))
            self.view.latitude_label.setText(str(latitude))
            self.view.altitude_label.setText(str(altitude))

            self.view.eclipse_visualization.set_location(longitude, latitude, altitude)

            return

        elif isinstance(changed_object, EclipsePopup):
            # Extract the date portion from the combobox entry (format: "<date> - <type> - ...").
            eclipse_text = changed_object.eclipse_combobox.currentText()
            eclipse_date_str = eclipse_text.split(" - ", 1)[0]
            self.model.set_eclipse_date(
                Time(datetime.datetime.strptime(eclipse_date_str, DATE_FORMATS[self.view.date_format])))

            self.view.eclipse_date.setText(eclipse_date_str)
            return

        elif isinstance(changed_object, SimulatorPopup):
            self.sim_reference_moment = changed_object.reference_moment_combobox.currentText()
            self.sim_offset_minutes = (int(changed_object.offset_minutes.text())
                                       * BEFORE_AFTER[changed_object.before_after_combobox.currentText()])
            return

        elif isinstance(changed_object, SettingsPopup):
            date_format = changed_object.date_combobox.currentText()
            self.view.date_format = date_format
            if self.model.eclipse_date:
                self.view.eclipse_date.setText(self.model.eclipse_date.strftime(DATE_FORMATS[date_format]))

            time_format = changed_object.time_combobox.currentText()
            self.view.time_format = time_format

            if self.model.c1_info:
                self.view.c1_time_utc_label.setText(format_time(self.model.c1_info.time_utc, time_format))
                self.view.c1_time_local_label.setText(format_time(self.model.c1_info.time_local, time_format))

            if self.model.c2_info:
                self.view.c2_time_utc_label.setText(format_time(self.model.c2_info.time_utc, time_format))
                self.view.c2_time_local_label.setText(format_time(self.model.c2_info.time_local, time_format))

            if self.model.max_info:
                self.view.max_time_utc_label.setText(format_time(self.model.max_info.time_utc, time_format))
                self.view.max_time_local_label.setText(format_time(self.model.max_info.time_local, time_format))

            if self.model.c3_info:
                self.view.c3_time_utc_label.setText(format_time(self.model.c3_info.time_utc, time_format))
                self.view.c3_time_local_label.setText(format_time(self.model.c3_info.time_local, time_format))

            if self.model.c4_info:
                self.view.c4_time_utc_label.setText(format_time(self.model.c4_info.time_utc, time_format))
                self.view.c4_time_local_label.setText(format_time(self.model.c4_info.time_local, time_format))

            if self.model.sunrise_info:
                self.view.sunrise_time_utc_label.setText(format_time(self.model.sunrise_info.time_utc, time_format))
                self.view.sunrise_time_local_label.setText(format_time(self.model.sunrise_info.time_local, time_format))

            if self.model.sunset_info:
                self.view.sunset_time_utc_label.setText(format_time(self.model.sunset_info.time_utc, time_format))
                self.view.sunset_time_local_label.setText(format_time(self.model.sunset_info.time_local, time_format))

            return

        elif isinstance(changed_object, QCloseEvent):

            if self._live_view_window is not None:
                self._live_view_window.close()
                self._live_view_window = None

            if self.model.camera_overview.camera_overview_dict:
                cameras = self.model.camera_overview.camera_overview_dict.values()

                camera: Camera
                for camera in cameras:
                    camera.exit()

            return

        text = changed_object.text()

        if text == "Location":
            self.location_popup = LocationPopup(self)
            self.location_popup.show()

        elif text == "Date":
            self.eclipse_popup = EclipsePopup(self)
            self.eclipse_popup.show()

        elif text == "Reference moments":
            if self.model.is_location_set and self.model.is_eclipse_date_set:
                # Run reference moments calculation in a background thread and show a
                # modal dialog with progress and a live log view while ephemeris files
                # (de440s/de421) are downloaded. Capture stdout/stderr into the dialog
                # so the user sees progress in the GUI instead of the terminal.
                dialog = QDialog(self.view)
                dialog.setWindowTitle("Downloading")
                dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
                dlg_layout = QVBoxLayout(dialog)

                # Compact dialog: label + indeterminate progress bar
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 0)  # indeterminate
                dlg_layout.addWidget(progress_bar)

                label = QLabel("Loading helper files...")
                dlg_layout.addWidget(label)

                dialog.setLayout(dlg_layout)

                result_container = {}

                class _DevNull:
                    def write(self, s):
                        return

                    def flush(self):
                        return

                def worker():
                    old_out = sys.stdout
                    old_err = sys.stderr
                    sys.stdout = _DevNull()
                    sys.stderr = _DevNull()
                    import logging
                    root_logger = logging.getLogger()
                    old_handlers = list(root_logger.handlers)
                    old_level = root_logger.level
                    try:
                        root_logger.handlers = []
                        rm, mag, typ = self.model.get_reference_moments()
                        result_container["result"] = (rm, mag, typ)
                    except Exception:
                        import traceback

                        result_container["error"] = traceback.format_exc()
                    finally:
                        sys.stdout = old_out
                        sys.stderr = old_err
                        root_logger.handlers = old_handlers
                        root_logger.setLevel(old_level)

                th = threading.Thread(target=worker, daemon=True)

                # Show dialog immediately so it is visible before downloads start.
                try:
                    dialog.show()
                    QApplication.processEvents()
                except Exception:
                    pass

                logging.getLogger(__name__).debug("Starting GUI reference-moments worker thread")

                th.start()

                timer = QTimer(dialog)

                def pump_logs_and_check():
                    if not th.is_alive():
                        timer.stop()
                        dialog.accept()

                timer.timeout.connect(pump_logs_and_check)
                timer.start(100)

                dialog.exec()

                if "error" in result_container:
                    LOGGER.exception("Error while calculating reference moments")
                    QMessageBox.critical(
                        self.view,
                        "Reference moments failed",
                        f"Error calculating reference moments:\n{result_container['error']}"
                    )
                else:
                    rm, mag, typ = result_container["result"]
                    self.view.show_reference_moments(rm, mag, typ)

        elif text == "Camera(s)":
            logging.debug('User requested Camera(s) update')
            try:
                logging.debug('Calling model.camera_overview.update_camera_overview()')
                # Register a callback so sync+check run after cameras are fully loaded
                self.model.camera_overview.on_ready_callback = self._on_cameras_ready
                self.model.camera_overview.update_camera_overview()
                logging.debug('Returned from update_camera_overview()')
            except Exception:
                logging.exception('Exception while updating camera overview')

        elif text == "Simulator":
            self.simulator_popup = SimulatorPopup(self)
            self.simulator_popup.show()

        elif text == "File":
            filename, _ = QFileDialog.getOpenFileName(None, "QFileDialog.getOpenFileName()", "",
                                                      "All Files (*);;Python Files (*.py);;Text Files (*.txt)")

            if not filename:
                return  # user cancelled the dialog

            if not self.model.reference_moments:
                QMessageBox.warning(
                    self.view,
                    "Reference Moments Not Set",
                    "No eclipse reference moments have been calculated yet.\n\n"
                    "Before loading a script, please:\n"
                    "  1. Set the observation location (Location button)\n"
                    "  2. Set the eclipse date (Date button)\n"
                    "  3. Click \"Reference moments\" to compute contact times\n\n"
                    "Then try loading the script again."
                )
                return

            if not os.path.exists(filename):
                QMessageBox.warning(
                    self.view,
                    "File Not Found",
                    f"The selected file does not exist:\n{filename}"
                )
                return

            try:
                from solareclipseworkbench.utils import observe_solar_eclipse
                self.scheduler: BackgroundScheduler \
                    = observe_solar_eclipse(self.model.reference_moments, filename,
                                            self.model.camera_overview.camera_overview_dict, self,
                                            self.sim_reference_moment, self.sim_offset_minutes,
                                            gps_time_offset=self.model.gps_time_offset)

                self.jobs_model = JobsTableModel(self.scheduler, self)
                self.view.jobs_table.setModel(self.jobs_model)
                self.jobs_model.add_observer(self.view.jobs_table)
                self.view.jobs_table.resizeColumnsToContents()

                self.view.camera_action.setDisabled(True)

                n_jobs = len(self.scheduler.get_jobs())
                if n_jobs == 0:
                    cam_keys = list(
                        (self.model.camera_overview.camera_overview_dict or {}).keys()
                    )
                    QMessageBox.warning(
                        self.view,
                        "No Jobs Scheduled",
                        f"The script was loaded but no commands were scheduled.\n\n"
                        f"This usually means the camera name in the script does not match "
                        f"the name of a detected camera.\n\n"
                        f"Detected cameras: {cam_keys or '(none — click Camera(s) first)'}\n\n"
                        f"Check that each camera name in the script exactly matches one of "
                        f"the names shown in the Camera(s) overview table above."
                    )

            except IndexError:
                LOGGER.warning(f"File {filename} does not contain scheduled jobs")

        elif text == "Stop":
            # Ask for confirmation before stopping the scheduler
            if not hasattr(self, 'scheduler') or not self.scheduler or not self.scheduler.get_jobs():
                # No active jobs → no need to confirm
                self._shutdown_scheduler()
                return

            reply = QMessageBox.question(
                self.view,
                "Confirm Stop",
                "Are you sure you want to stop the scheduler?\n\n"
                "All pending jobs will be cancelled.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._shutdown_scheduler()

        elif text == "Datetime format":
            self.settings_popup = SettingsPopup(self)
            self.settings_popup.show()

        elif text == "Save":
            self.view.save_settings()

        elif text == "Live View":
            self._open_live_view()

        elif text == "Refresh Plot":
            self.update_visualization()

    def sync_camera_time(self):
        """ Set the time of all connected cameras to the time of the computer."""

        self.model.sync_camera_time()

    def _on_cameras_ready(self):
        """Called by CameraOverviewTableModel after camera dict is populated.

        Runs sync_camera_time and check_camera_state on the GUI thread so they
        always have access to the fully-populated camera_overview_dict.
        """
        try:
            logging.debug('_on_cameras_ready: syncing camera time')
            self.sync_camera_time()
        except Exception:
            logging.exception('Exception while syncing camera time')
        try:
            logging.debug('_on_cameras_ready: checking camera state')
            warnings = self.model.check_camera_state()
            if warnings:
                QMessageBox.warning(
                    self.view,
                    "Camera Settings Warning",
                    "One or more cameras require attention before shooting:\n\n"
                    + "\n\n".join(f"\u26a0\ufe0f  {w}" for w in warnings)
                )
        except Exception:
            logging.exception('Exception while checking camera state')

    def _open_live_view(self):
        """Open (or bring to front) the live view window.

        When exactly one real camera is connected it is used directly.
        When multiple real cameras are connected a small selection dialog
        is shown so the user can pick which one to preview.
        Shows a warning when no real camera is connected.
        """
        # If window already exists, bring it to the front
        if self._live_view_window is not None and self._live_view_window.isVisible():
            self._live_view_window.activateWindow()
            self._live_view_window.raise_()
            return

        # Collect all real gphoto cameras (deduplicated by object identity).
        # Use cam.name as the display label: when an alias is configured it is
        # set to the primary alias (i.e. the name used in scripts); when no alias
        # is configured it falls back to the gphoto2 model name.
        cam_dict = getattr(self.model.camera_overview, 'camera_overview_dict', None) or {}
        from solareclipseworkbench.camera import GPhotoCameraAdapter, VirtualCamera
        seen_ids: set = set()
        real_cameras: list = []  # list of (display_name, camera) tuples
        for cam in cam_dict.values():
            if isinstance(cam, (GPhotoCameraAdapter, VirtualCamera)) and id(cam) not in seen_ids:
                seen_ids.add(id(cam))
                real_cameras.append((cam.name, cam))

        if not real_cameras:
            QMessageBox.warning(
                self.view,
                "No Camera Connected",
                "Live view requires a connected camera.\n\n"
                "Click the Camera(s) button first to detect connected cameras.\n"
                "In simulator mode the VirtualCamera is also supported."
            )
            return

        if len(real_cameras) == 1:
            camera = real_cameras[0][1]
        else:
            # Ask the user which camera to preview
            names = [name for name, _ in real_cameras]
            chosen, ok = QtWidgets.QInputDialog.getItem(
                self.view,
                "Select Camera for Live View",
                "Camera:",
                names,
                0,
                False,
            )
            if not ok:
                return
            camera = dict(real_cameras)[chosen]

        self._live_view_window = LiveViewWindow(camera, parent=None)
        self._live_view_window.show()

    def load_settings(self):
        """ Load the UI settings.

        These settings are:

            - Date format (always present);
            - Time format (always present);
            - Location (longitude, latitude, altitude);
            - Eclipse date.

        If the location and eclipse date are present in the settings file, the reference moments will be updated
        automatically.
        """

        self.view.settings = QSettings(str(Path.home() / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)

        # Date & time format
        # TODO Requires Python 3.7

        default_date_format, *_ = DATE_FORMATS
        date_format = self.view.settings.value("date_format", default_date_format, type=str)
        default_time_format, *_ = TIME_FORMATS
        time_format = self.view.settings.value("time_format", default_time_format, type=str)
        self.set_datetime_format(date_format, time_format)

        # Location

        is_location_loaded = self.set_location(self.view.settings.value("longitude", None, type=float),
                                               self.view.settings.value("latitude", None, type=float),
                                               self.view.settings.value("altitude", None, type=float))

        # Eclipse date

        is_eclipse_date_loaded = self.set_eclipse_date(self.view.settings.value("eclipse_date", None, type=str),
                                                       date_format)

        # Reference moments

        if is_location_loaded and is_eclipse_date_loaded:
            # Defer reference-moments calculation so the main window can appear
            # before any potential ephemeris downloads. Schedule it on the
            # Qt event loop to run after the UI has been shown.
            try:
                QTimer.singleShot(0, self.set_reference_moments)
            except Exception:
                # Fall back to synchronous call if scheduling fails for any reason
                try:
                    self.set_reference_moments()
                except Exception:
                    pass

    def set_datetime_format(self, date_format: str, time_format: str):
        """ Set the date and time format in the view. """

        self.view.date_format = date_format
        self.view.time_format = time_format

    def set_location(self, longitude: float, latitude: float, altitude: float) -> bool:
        """ Set the observing location in the model and the view.

        Args:
            - longitude: Longitude of the location [degrees]
            - latitude: Latitude of the location [degrees]
            - altitude: Altitude of the location [meters]

        Returns: True if the location was set, false otherwise.
        """


        if longitude and latitude and altitude:
            self.model.set_position(longitude, latitude, altitude)

            self.view.longitude_label.setText(str(longitude))
            self.view.latitude_label.setText(str(latitude))
            self.view.altitude_label.setText(str(altitude))

            self.view.eclipse_visualization.set_location(longitude, latitude, altitude)

            return True

        return False

    def set_eclipse_date(self, eclipse_date: str, date_format: str = None) -> bool:
        """ Set the eclipse date in the model and the view.

        Args:
            - eclipse_date: Eclipse date
            - date_format: Date format for the given eclipse date (if None, the date format is %Y-%m-%d)

        Returns: True if the eclipse date was set, false otherwise.
        """

        if eclipse_date:
            if date_format:
                dt = datetime.datetime.strptime(eclipse_date, DATE_FORMATS[date_format])
                date = datetime.datetime.strftime(dt, "%Y-%m-%d")
                self.view.eclipse_date.setText(eclipse_date)
            else:
                date = datetime.datetime.strptime(eclipse_date, "%Y-%m-%d")
                self.view.eclipse_date.setText(date.strftime(DATE_FORMATS[self.view.date_format]))

            self.model.set_eclipse_date(Time(date))
            return True

        return False

    def set_reference_moments(self):
        """ Set the reference moments of the eclipse in the model and the view."""
        # Run the possibly-slow calculation in a background thread while showing a
        # compact modal dialog so the user sees that helper files are being loaded.
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Loading helper files...")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg_layout = QVBoxLayout(dialog)

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)  # indeterminate
        dlg_layout.addWidget(progress_bar)

        label = QLabel("Loading helper files...")
        dlg_layout.addWidget(label)

        dialog.setLayout(dlg_layout)

        result_container = {}

        class _DevNull:
            def write(self, s):
                return

            def flush(self):
                return

        def worker():
            old_out = sys.stdout
            old_err = sys.stderr
            sys.stdout = _DevNull()
            sys.stderr = _DevNull()
            import logging
            root_logger = logging.getLogger()
            old_handlers = list(root_logger.handlers)
            old_level = root_logger.level
            try:
                # Prevent external libraries from printing to terminal while
                # downloads happen.
                root_logger.handlers = []
                reference_moments, magnitude, eclipse_type = self.model.get_reference_moments()
                result_container["result"] = (reference_moments, magnitude, eclipse_type)
            except Exception:
                import traceback

                result_container["error"] = traceback.format_exc()
            finally:
                sys.stdout = old_out
                sys.stderr = old_err
                root_logger.handlers = old_handlers
                root_logger.setLevel(old_level)

        th = threading.Thread(target=worker, daemon=True)

        # Show dialog immediately so it is visible before downloads start.
        try:
            dialog.show()
            QApplication.processEvents()
        except Exception:
            pass

        LOGGER.debug("Starting reference-moments worker thread (controller)")

        th.start()

        timer = QTimer(dialog)

        def pump_and_close():
            if not th.is_alive():
                timer.stop()
                dialog.accept()

        timer.timeout.connect(pump_and_close)
        timer.start(100)

        dialog.exec()

        if "error" in result_container:
            LOGGER.exception("Error while calculating reference moments")
            QMessageBox.critical(
                self.view,
                "Reference moments failed",
                f"Error calculating reference moments:\n{result_container['error']}"
            )
        else:
            reference_moments, magnitude, eclipse_type = result_container["result"]
            self.view.show_reference_moments(reference_moments, magnitude, eclipse_type)

    def _shutdown_scheduler(self):
        """Safely shut down the scheduler and update UI."""
        try:
            if self.scheduler:
                self.scheduler.shutdown()
                self.jobs_model.clear_jobs_overview()
                self.view.camera_action.setEnabled(True)
                LOGGER.info("Scheduler stopped by user")
        except SchedulerNotRunningError:
            pass  # already stopped
        except Exception:
            logging.exception("Error while shutting down scheduler")


class LocationPopup(QWidget, Observable):
    def __init__(self, observer: SolarEclipseController):
        """ Initialisation of a pop-up window for setting the observing location.

        A pop-up window is shown, in which the user can choose the following information about the observing location:

            - Longitude [degrees];
            - Latitude [degrees];
            - Altitude [meters].

        The window also provides a saved-locations drop-down and an address-search bar (when geopy is installed).  When
        pressing the "Plot" button, the location will be displayed on a world map (as a red dot).  When pressing the
        "OK" button, the controller will be notified.

        If the location had already been set before, the coordinate fields will be pre-filled.

        Args:
            - observer: SolarEclipseController that needs to be notified about the selection of a new location.
        """

        QWidget.__init__(self)
        self.setWindowTitle("Location")
        self.setGeometry(QRect(100, 100, 1000, 800))
        self.add_observer(observer)

        model = observer.model

        layout = QVBoxLayout()

        # Shared location widget: saved-locations drop-down + address search + coordinate fields.
        config_manager = ConfigManager()
        self.location_widget = LocationWidget(config_manager)
        # Only fall back to model coordinates when no saved location was restored
        # by the widget (i.e. the combo is still on "Custom"). If a saved location
        # was restored, its own coordinates should be shown, not the ones from the
        # .SolarEclipseWorkbench.ini file.
        if model.longitude is not None and self.location_widget.location_combo.currentText() == "Custom":
            self.location_widget.set_coordinates(
                model.longitude, model.latitude, model.altitude
            )
        layout.addWidget(self.location_widget)

        self.location_plot = LocationPlot()
        layout.addWidget(self.location_plot)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept_location)
        ok_button.setFixedWidth(100)
        layout.addWidget(ok_button)

        self.setLayout(layout)

        # Auto-plot: debounce coordinate changes so the map refreshes 300 ms
        # after the user stops typing or after a saved/geocoded location is applied.
        self._plot_timer = QTimer(self)
        self._plot_timer.setSingleShot(True)
        self._plot_timer.setInterval(300)
        self._plot_timer.timeout.connect(self.plot_location)

        self.location_widget.longitude_edit.textChanged.connect(self._schedule_auto_plot)
        self.location_widget.latitude_edit.textChanged.connect(self._schedule_auto_plot)

        # Plot whatever coordinates are currently in the fields — covers both the
        # case where the model already had a location and the case where LocationWidget
        # restored the last-used saved location during its own initialisation.
        self.plot_location()

    # ------------------------------------------------------------------
    # Backward-compatible properties so the controller can still do
    #   changed_object.longitude.text() / .latitude.text() / .altitude.text()
    # ------------------------------------------------------------------

    @property
    def longitude(self):
        """Return the longitude QLineEdit from the embedded LocationWidget."""
        return self.location_widget.longitude_edit

    @property
    def latitude(self):
        """Return the latitude QLineEdit from the embedded LocationWidget."""
        return self.location_widget.latitude_edit

    @property
    def altitude(self):
        """Return the altitude QLineEdit from the embedded LocationWidget."""
        return self.location_widget.altitude_edit

    def _schedule_auto_plot(self):
        """Restart the debounce timer whenever a coordinate field changes."""
        self._plot_timer.start()

    def plot_location(self):
        """Plot the selected location on the world map.

        Silently ignored when longitude or latitude are empty or not yet valid numbers.
        """
        try:
            lon = float(self.longitude.text())
            lat = float(self.latitude.text())
        except ValueError:
            return
        self.location_plot.plot_location(longitude=lon, latitude=lat)

    def accept_location(self):
        """ Notify the observer about the selection of a new location and close the pop-up window.

        Check:
            - longitude specified
            - latitude specified
            - altitude specified
        """

        if self.longitude.text() and self.latitude.text() and self.altitude.text():
            self.notify_observers(self)
            self.close()


class EclipsePopup(QWidget, Observable):

    def __init__(self, observer: SolarEclipseController):
        """ Initialisation of a pop-up window for setting the eclipse date.

        A pop-up window is shown, in which the user can choose the date of the eclipse.

        When pressing the "OK" button, the given controller will be notified about this.

        If the eclipse date had already been set before, this will be shown in the combobox.

        Args:
            - observer: SolarEclipseController that needs to be notified about the selection of a new location.
        """

        QWidget.__init__(self)
        self.setWindowTitle("Eclipse date")
        self.setGeometry(QRect(100, 100, 400, 75))
        self.add_observer(observer)

        self.eclipse_combobox = QComboBox()

        date_format = DATE_FORMATS[observer.view.date_format]

        formatted_eclipse_dates = []

        from solareclipseworkbench.utils import calculate_next_solar_eclipses
        for eclipse_date in calculate_next_solar_eclipses(20):
            formatted_eclipse_date = datetime.datetime.strptime(eclipse_date['date'], "%d/%m/%Y").strftime(date_format) + " - " + eclipse_date['type']
            if eclipse_date['type'] == "T" or eclipse_date['type'] == "A" or eclipse_date['type'] == "H":
                # For total, annular, and hybrid eclipses, also show the duration
                duration = eclipse_date["duration"]
                # Convert duration to minutes:seconds
                minutes, seconds = divmod(duration, 60)
                formatted_eclipse_date += f" - {int(minutes)}m {int(seconds):02}s"
                formatted_eclipse_dates.append(formatted_eclipse_date)
            else:
                formatted_eclipse_dates.append(formatted_eclipse_date + " - " + str(int(eclipse_date["magnitude"] * 100)) + "%")

        self.eclipse_combobox.addItems(formatted_eclipse_dates)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.load_eclipse_date)

        layout = QHBoxLayout()

        layout.addWidget(self.eclipse_combobox)
        layout.addWidget(ok_button)
        self.setLayout(layout)

    def load_eclipse_date(self):
        """ Notify the observer about the selection of a new eclipse date and close the pop-up window."""

        self.notify_observers(self)
        self.close()


class SimulatorPopup(QWidget, Observable):
    def __init__(self, observer: SolarEclipseController):
        """ Initialisation of pop-up window to specify the start time of the simulation.

        Args:
            - observer: SolarEclipseController that needs to be notified about the specification of the start time of
                        the simulation
        """

        QWidget.__init__(self)
        self.setWindowTitle("Starting time")
        self.setGeometry(QRect(100, 100, 300, 75))
        self.add_observer(observer)

        # noinspection SpellCheckingInspection
        hbox1 = QHBoxLayout()
        # noinspection SpellCheckingInspection
        hbox2 = QHBoxLayout()

        self.offset_minutes = QLineEdit()
        offset_minutes_validator = QIntValidator()
        self.offset_minutes.setValidator(offset_minutes_validator)

        self.before_after_combobox = QComboBox()
        self.before_after_combobox.addItems(BEFORE_AFTER.keys())

        if observer.sim_offset_minutes:
            self.offset_minutes.setText(str(abs(observer.sim_offset_minutes)))

            if observer.sim_offset_minutes < 0:
                self.before_after_combobox.setCurrentText("after")
            else:
                self.before_after_combobox.setCurrentText("before")

        self.reference_moment_combobox = QComboBox()

        # Populate the reference-moment combobox based on the model's computed reference moments.
        # If a moment is not present in the model (e.g. no C2/C3 for partial eclipses, or no C1/C4/MAX
        # for no-eclipse), it will not be offered as a simulation start point.
        model_ref = getattr(observer.model, 'reference_moments', None)
        if model_ref:
            options = []
            for key in ["C1", "C2", "MAX", "C3", "C4", "sunset", "sunrise"]:
                if key in model_ref:
                    options.append(key)
            # If nothing was detected (defensive), fall back to the full list
            if not options:
                options = list(REFERENCE_MOMENTS)
            self.reference_moment_combobox.addItems(options)
        else:
            # No reference moments computed yet; show full list so the user can pick (or compute moments first)
            self.reference_moment_combobox.addItems(REFERENCE_MOMENTS)

        # Restore previously chosen simulator reference moment if still available, otherwise choose a sensible default
        if observer.sim_reference_moment:
            available = [self.reference_moment_combobox.itemText(i) for i in range(self.reference_moment_combobox.count())]
            if observer.sim_reference_moment in available:
                self.reference_moment_combobox.setCurrentText(observer.sim_reference_moment)
            else:
                if "MAX" in available:
                    self.reference_moment_combobox.setCurrentText("MAX")
                elif available:
                    self.reference_moment_combobox.setCurrentIndex(0)

        layout = QVBoxLayout()

        hbox1.addWidget(self.offset_minutes)
        hbox1.addWidget(QLabel("minute(s)"))
        hbox1.addWidget(self.before_after_combobox)
        hbox1.addWidget(self.reference_moment_combobox)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept_starting_time)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancel_starting_time)

        hbox2.addWidget(ok_button)
        hbox2.addWidget(cancel_button)

        layout.addLayout(hbox1)
        layout.addLayout(hbox2)

        self.setLayout(layout)

    def accept_starting_time(self):
        """ Notify the observer about specification of the starting time of the simulation and close the pop-up window.

        Check:
            - offset specified
        """

        if self.offset_minutes.text():
            self.notify_observers(self)
            self.close()

    def cancel_starting_time(self):
        """ Close the pop-up window. """

        self.close()


class SettingsPopup(QWidget, Observable):

    def __init__(self, observer: SolarEclipseController):
        """ A pop-up window is shown, in which the user can choose the settings.

        When pressing the "OK" button, the given controller will be notified about this.

        If the setting had already been set before, this will be shown in the comboboxes.

        Args:
            - observer: SolarEclipseController that needs to be notified about the settings.
        """

        QWidget.__init__(self)
        self.setWindowTitle("Datetime format")
        self.setGeometry(QRect(100, 100, 300, 75))
        self.add_observer(observer)

        layout = QGridLayout()
        layout.addWidget(QLabel("Date format"), 0, 0)
        self.date_combobox = QComboBox()
        self.date_combobox.addItems(DATE_FORMATS.keys())
        layout.addWidget(self.date_combobox, 0, 1)
        layout.addWidget(QLabel("Time format"), 1, 0)
        self.time_combobox = QComboBox()
        self.time_combobox.addItems(TIME_FORMATS.keys())
        layout.addWidget(self.time_combobox, 1, 1)

        self.date_combobox.setCurrentText(observer.view.date_format)
        self.time_combobox.setCurrentText(observer.view.time_format)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept_settings)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancel_settings)
        layout.addWidget(ok_button, 2, 0)
        layout.addWidget(cancel_button, 2, 1)

        self.setLayout(layout)

    def accept_settings(self):
        """ Notify the observer about the settings changes and close the pop-up window."""

        self.notify_observers(self)
        self.close()

    def cancel_settings(self):
        """ Close the pop-up window without accepting any settings changes."""

        self.close()


class LocationPlot(FigureCanvas):
    """ Display the world with the selected location marked with a red dot."""

    def __init__(self, parent=None, dpi=100):
        """ Plot a world map."""

        self.figure = Figure(dpi=dpi)
        self.ax = self.figure.add_subplot(111, aspect='equal')

        FigureCanvas.__init__(self, self.figure)
        self.setParent(parent)

        FigureCanvas.updateGeometry(self)

        self.location_is_drawn = False
        self.location = None
        self.gdf = None

        # noinspection SpellCheckingInspection
        world = geopandas.read_file(get_path("naturalearth.land"))
        # Crop -> min longitude, min latitude, max longitude, max latitude
        world.clip([-180, -90, 180, 90]).plot(color="white", edgecolor="black", ax=self.ax)

        self.ax.set_aspect("equal")

        self.draw()

    def plot_location(self, longitude: float, latitude: float):
        """ Indicate the given location on the world map with a red dot.

        Args:
            - longitude: Longitude of the location [degrees]
            - latitude: Latitude of the location [degrees]
        """

        if self.location_is_drawn:
            self.gdf.plot(ax=self.ax, color="white")

        df = pd.DataFrame(
            {
                "Latitude": [latitude],
                "Longitude": [longitude],
            }
        )
        self.gdf = geopandas.GeoDataFrame(df, geometry=geopandas.points_from_xy(df.Longitude, df.Latitude),
                                          crs="EPSG:4326")
        self.gdf.plot(ax=self.ax, color="red")

        self.ax.set_aspect("equal")

        self.draw()
        self.location_is_drawn = True



@dataclass(frozen=True)
class Observer:
    latitude: float
    longitude: float
    altitude: float


class EclipsePlotWidget(QtWidgets.QWidget):
    """
    PyQt6 QWidget that plots Sun & Moon discs to scale for a given observer and datetime.

    - Axes are in units of *solar radii* with the Sun drawn as a unit circle centered at (0, 0).
    - By default: North is up, East is right (astronomical convention).
      Set east_left=True to mirror the X axis (East to the left) like many star charts.
    - Call .plot(datetime_obj) to render a frame.
    """

    # Cache ephemerides + timescales across instances to avoid repeated downloads

    CACHED_EPHEMERIDES = None
    CACHED_TIMESCALE = None

    def __init__(
        self,

        east_left: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.offset = datetime.timedelta(minutes=0)

        # Defer loading of Skyfield ephemerides until the plot is actually used.
        # Loading can take time and may download large files; avoid doing that
        # during UI construction so the main window can appear immediately.
        self.sun_ephemeris = None
        self.moon_ephemeris = None

        # --- Matplotlib figure canvas inside this QWidget ---
        self.fig = Figure(figsize=(6.0, 6.2), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)  # single axes

        # UI layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        # Prepare static plot styling (labels, grid, aspect)
        self._init_axes()

        # self.longitude = None
        # self.latitude = None
        # self.altitude = None

        self.observer = None
        self.is_location_set = False

    def set_location(self, longitude, latitude, altitude):

        # self.longitude = longitude
        # self.latitude = latitude
        # self.altitude = altitude
        self.observer = Observer(latitude=latitude, longitude=longitude, altitude=altitude)

        self.is_location_set = True

    def _ensure_ephemerides_loaded(self):
        """Ensure shared Skyfield ephemerides and timescale are loaded.

        This is intentionally called lazily from `plot()` so the GUI can
        appear before any potential downloads start.
        """
        if EclipsePlotWidget.CACHED_TIMESCALE is not None and EclipsePlotWidget.CACHED_EPHEMERIDES is not None:
            # Already loaded
            self.sun_ephemeris = EclipsePlotWidget.CACHED_EPHEMERIDES["sun"]
            self.moon_ephemeris = EclipsePlotWidget.CACHED_EPHEMERIDES["moon"]
            return

        # Show a compact modal dialog while we load ephemerides in background.
        parent = self.window() if self.window() is not None else self
        dialog = QDialog(parent)
        dialog.setWindowTitle("Loading helper files...")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg_layout = QVBoxLayout(dialog)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)
        dlg_layout.addWidget(progress_bar)
        label = QLabel("Loading helper files...")
        dlg_layout.addWidget(label)
        dialog.setLayout(dlg_layout)

        result = {}

        class _DevNull:
            def write(self, s):
                return

            def flush(self):
                return

        def worker():
            old_out = sys.stdout
            old_err = sys.stderr
            sys.stdout = _DevNull()
            sys.stderr = _DevNull()
            import logging
            root_logger = logging.getLogger()
            old_handlers = list(root_logger.handlers)
            old_level = root_logger.level
            try:
                # Temporarily remove handlers to avoid terminal noise
                root_logger.handlers = []
                if EclipsePlotWidget.CACHED_TIMESCALE is None:
                    EclipsePlotWidget.CACHED_TIMESCALE = load.timescale()
                if EclipsePlotWidget.CACHED_EPHEMERIDES is None:
                    EclipsePlotWidget.CACHED_EPHEMERIDES = load("de440s.bsp")
                result['ok'] = True
            except Exception:
                import traceback

                result['error'] = traceback.format_exc()
            finally:
                sys.stdout = old_out
                sys.stderr = old_err
                root_logger.handlers = old_handlers
                root_logger.setLevel(old_level)

        th = threading.Thread(target=worker, daemon=True)

        try:
            dialog.show()
            QApplication.processEvents()
        except Exception:
            pass

        th.start()

        timer = QTimer(dialog)

        def poll():
            if not th.is_alive():
                timer.stop()
                dialog.accept()
                if 'error' in result:
                    raise Exception(result['error'])
                # Populate instance references
                self.sun_ephemeris = EclipsePlotWidget.CACHED_EPHEMERIDES["sun"]
                self.moon_ephemeris = EclipsePlotWidget.CACHED_EPHEMERIDES["moon"]

        timer.timeout.connect(poll)
        timer.start(100)

        dialog.exec()

    # ------------- Public API -------------

    def set_offset(self, offset):
        self.offset = offset

    def plot(self, when: datetime) -> None:
        """
        Render eclipse geometry for the current observer at a given datetime.

        Parameters
        ----------
        when : datetime
            Prefer a timezone-aware datetime (UTC). If naive, it's interpreted as UTC.
        """

        when += self.offset

        # Ensure ephemerides are loaded lazily to avoid blocking UI startup.
        self._ensure_ephemerides_loaded()

        if not self.is_location_set:
            LOGGER.info("Location not set. Please use set_location() first.")
            return

        # Interpret naive datetimes as UTC for robustness
        if when.tzinfo is None:
            when = when.replace(tzinfo=pytz.UTC)

        t = self.CACHED_TIMESCALE.from_datetime(when)



        # Build topocentric observer by attaching a Topos to the Earth body
        # (compose `earth_ephemeris + wgs84.latlon(...)`). The older direct
        # Topos.at(t) path is unreliable across Skyfield versions, so use the
        # earth+Topos site object which consistently supports `.at(t)`.
        earth_ephemeris = self.CACHED_EPHEMERIDES["earth"]
        site = earth_ephemeris + wgs84.latlon(
            self.observer.latitude,
            self.observer.longitude,
            elevation_m=self.observer.altitude,
        )

        sun_app = site.at(t).observe(self.sun_ephemeris).apparent()
        moon_app = site.at(t).observe(self.moon_ephemeris).apparent()

        # Compute topocentric unit direction vectors using local horizontal
        # (alt/az) coordinates and form ENU unit vectors. Then project the
        # difference between Moon and Sun directions onto the tangent plane
        # (East, North) at the observer. This yields small-angle offsets in
        # radians which we scale to solar radii for plotting.

        # Use 3D topocentric unit vectors and project the Moon into the
        # tangent plane perpendicular to the Sun direction. This gives a
        # robust small-angle offset that matches angular separation.

        # Compute small-angle horizontal offsets using alt/az differences so
        # the plotted geometry is in local horizontal coordinates (matching
        # Stellarium). For small separations:
        #   x_east ≈ Δaz * cos(mean_alt)   (radians)
        #   y_north ≈ Δalt                  (radians)
        sun_alt, sun_az, _ = sun_app.altaz()
        moon_alt, moon_az, _ = moon_app.altaz()

        a_s = sun_alt.radians
        A_s = sun_az.radians
        a_m = moon_alt.radians
        A_m = moon_az.radians

        # Wrap Δaz into [-pi, +pi]
        delta_az = (A_m - A_s + math.pi) % (2.0 * math.pi) - math.pi
        mean_alt = 0.5 * (a_s + a_m)

        x_east = float(delta_az * math.cos(mean_alt))
        y_north = float(a_m - a_s)

        # Position Angle (PA): from North through East
        pa_deg = (math.degrees(math.atan2(x_east, y_north)) + 360.0) % 360.0

        # Apparent angular radii (radians)
        sun_distance = sun_app.distance().m     # Distance Earth - Sun [m]
        moon_dist = moon_app.distance().m     # Distance Earth - Moon [m]
        sun_ang_radius = math.asin(SUN_RADIUS / sun_distance)   # Angular radius of the Sun [radians]
        moon_ang_radius = math.asin(MOON_RADIUS / moon_dist)    # Angular radius of the Moon [radians]

        # Normalise to solar radius for plotting
        scale = 1.0 / sun_ang_radius
        xm = x_east * scale
        ym = y_north * scale
        r_moon_scaled = moon_ang_radius * scale

        

        # ---- Draw ----
        self.ax.clear()
        self._init_axes()  # re-apply static styling

        # Sun disk (unit radius)
        sun_disk = self._mpl_circle((0.0, 0.0), 1.0, facecolor="#FDB813", edgecolor="k", alpha=0.85, lw=1.0)
        self.ax.add_patch(sun_disk)

        # Moon disk
        moon_disk = self._mpl_circle((xm, ym), r_moon_scaled, facecolor="k", edgecolor="k", alpha=0.92, lw=1.0)
        self.ax.add_patch(moon_disk)

        # # Cardinal labels on Sun’s rim
        # self._cardinal_marks()

        # # Annotation box
        # txt = (
        #     f"Separation: {math.degrees(sep_rad):.3f}°\n"
            # f"Position angle (Moon from Sun): {pa_deg:.1f}°  (0°=N, 90°=E)\n"
        #     f"R_sun: {math.degrees(R_sun)*60:.2f}′   R_moon: {math.degrees(R_moon)*60:.2f}′"
        # )
        # self.ax.text(
        #     0.02,
        #     0.98,
        #     txt,
        #     transform=self.ax.transAxes,
        #     ha="left",
        #     va="top",
        #     fontsize=9,
        #     bbox=dict(facecolor="white", alpha=0.85, edgecolor="none"),
        # )

        # Title

        title_loc = f"({self.observer.latitude:.4f}°, {self.observer.longitude:.4f}°, {self.observer.altitude:.0f} m)"
        # ISO string in UTC for clarity
        self.ax.set_title(
            f"Solar eclipse geometry",
            fontsize=11,
        )

        # Limits

        # margin = 1.25 * max(1.0, abs(xm) + r_moon_scaled, abs(ym) + r_moon_scaled)
        margin = 1.5
        self.ax.set_xlim(-margin, margin)
        self.ax.set_ylim(-margin, margin)
        
        # Redraw canvas

        self.canvas.draw_idle()

    # ------------- Internals -------------

    def _init_axes(self) -> None:
        """Initialize axes labels, grids, aspect, and crosshair."""
        self.ax.set_aspect("equal", adjustable="box")
        # self.ax.set_xlabel("East (in solar radii)")
        # self.ax.set_ylabel("North (in solar radii)")
        # self.ax.grid(False, alpha=0.25, lw=0.6)

        # Centre crosshair
        # self.ax.axhline(0, color="lightgray", lw=0.6)
        # self.ax.axvline(0, color="lightgray", lw=0.6)

    def _mpl_circle(self, center, radius, **kwargs):
        import matplotlib.patches as mpatches

        return mpatches.Circle(center, radius, **kwargs)

    # def _cardinal_marks(self) -> None:
    #     offs = 1.08
    #     for label, (x, y) in [
    #         ("N", (0, +offs)),
    #         ("E", (+offs if not self.east_left else -offs, 0)),
    #         ("S", (0, -1.12)),
    #         ("W", (-1.12 if not self.east_left else +1.12, 0)),
    #     ]:
    #         self.ax.text(x, y, label, ha="center", va="center", fontsize=10, color="dimgray")


class LiveViewWindow(QWidget):
    """Floating window that shows a live-view preview from a gphoto2 camera.

    A background ``LiveViewThread`` grabs one preview frame per second.  When
    the camera USB lock is held by a scheduled shot the frame is silently
    skipped so timing accuracy is never compromised.

    The window can be:
      - Disabled/re-enabled at any time via the toggle button.
      - Auto-paused between C2 and C3 (totality) by the controller calling
        ``set_totality_paused(True/False)``.
    """

    def __init__(self, camera, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setMinimumSize(480, 400)

        self._camera = camera
        self._thread = None
        self._frame_queue: queue.Queue = queue.Queue(maxsize=1)
        self._user_enabled: bool = True
        self._totality_paused: bool = False

        self.setWindowTitle(f"Live View — {camera.name}")

        # Image display
        self._image_label = QLabel("Waiting for first preview frame…")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(320, 240)

        # Timestamp of last received frame
        self._timestamp_label = QLabel()
        self._timestamp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timestamp_label.setStyleSheet("color: gray; font-size: 11px;")

        # Status line
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Buttons and zoom control
        self._toggle_btn = QPushButton("Disable Live View")
        self._toggle_btn.clicked.connect(self._on_toggle)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        # Zoom control: Fit / 5x / 10x
        self._zoom_combo = QComboBox()
        self._zoom_combo.addItems(["Fit", "5x", "10x"])
        self._zoom_combo.setCurrentIndex(0)
        self._zoom_factor = 1.0
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)

        # Pan controls (hidden until a zoom > 1 is selected)
        self._last_pixmap: Union[QPixmap, None] = None
        self._last_ts: Union[datetime.datetime, None] = None
        self._h_slider = QSlider(Qt.Orientation.Horizontal)
        self._h_slider.setRange(0, 0)
        self._h_slider.setVisible(False)
        self._h_slider.valueChanged.connect(self._on_pan_changed)

        self._v_slider = QSlider(Qt.Orientation.Vertical)
        self._v_slider.setRange(0, 0)
        self._v_slider.setVisible(False)
        self._v_slider.setFixedWidth(18)
        self._v_slider.valueChanged.connect(self._on_pan_changed)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self._toggle_btn)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(QLabel("Zoom:"))
        btn_layout.addWidget(self._zoom_combo)

        # Image area with optional vertical pan slider
        layout = QVBoxLayout()
        image_area = QHBoxLayout()
        image_area.addWidget(self._image_label, stretch=1)
        image_area.addWidget(self._v_slider)
        layout.addLayout(image_area)
        layout.addWidget(self._h_slider)
        layout.addWidget(self._timestamp_label)
        layout.addWidget(self._status_label)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # Poll the frame queue every 500 ms on the GUI thread
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_frame)
        self._poll_timer.start()

        self._start_thread()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_thread(self):
        if self._thread is not None:
            self._thread.stop()
        self._thread = LiveViewThread(
            camera=self._camera,
            frame_callback=self._on_frame,
            interval_s=1.0,
        )
        self._thread.start()
        self._update_status_label()

    def _on_frame(self, jpeg_bytes: bytes):
        """Called from the LiveViewThread; enqueue (frame, timestamp) for GUI thread."""
        try:
            self._frame_queue.put_nowait((jpeg_bytes, datetime.datetime.now()))
        except queue.Full:
            pass  # drop the frame; the previous one hasn't been displayed yet

    def _poll_frame(self):
        """Called on the Qt main thread by the poll timer; updates the image."""
        try:
            jpeg_bytes, ts = self._frame_queue.get_nowait()
        except queue.Empty:
            return
        if isinstance(jpeg_bytes, memoryview):
            jpeg_bytes = jpeg_bytes.tobytes()
        elif isinstance(jpeg_bytes, bytearray):
            jpeg_bytes = bytes(jpeg_bytes)
        elif not isinstance(jpeg_bytes, bytes):
            LOGGER.warning("Live view frame had unsupported type: %s", type(jpeg_bytes).__name__)
            return

        image = QImage.fromData(jpeg_bytes)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        # Store and render using the centralized renderer so pan/zoom UI
        # remains in sync with the latest frame.
        self._render_pixmap(pixmap, ts)

    def _apply_state(self):
        """Push the user+totality state into the thread and refresh the button."""
        if self._thread is None:
            return
        if self._user_enabled and not self._totality_paused:
            self._thread.resume()
            self._toggle_btn.setText("Disable Live View")
        else:
            self._thread.pause()
            self._toggle_btn.setText("Enable Live View")
        self._update_status_label()

    def _update_status_label(self):
        if not self._user_enabled:
            self._status_label.setText("○  Disabled")
            self._status_label.setStyleSheet("color: gray;")
        elif self._totality_paused:
            self._status_label.setText(
                "\u23f8  Paused during totality — script has full USB control"
            )
            self._status_label.setStyleSheet("color: #856404; background: #FFF3CD; padding: 3px; border-radius: 3px;")
        else:
            self._status_label.setText("\u25cf  Active")
            self._status_label.setStyleSheet("color: green;")

    # ------------------------------------------------------------------
    # Public API (called by the controller)
    # ------------------------------------------------------------------

    def set_totality_paused(self, paused: bool):
        """Auto-pause or auto-resume live view around totality."""
        if self._totality_paused == paused:
            return
        self._totality_paused = paused
        self._apply_state()

    # ------------------------------------------------------------------
    # Slots / event handlers
    # ------------------------------------------------------------------

    def _on_toggle(self):
        self._user_enabled = not self._user_enabled
        self._apply_state()

    def _on_zoom_changed(self, index: int):
        """Slot for zoom combo box changes."""
        text = self._zoom_combo.currentText() if hasattr(self, "_zoom_combo") else "Fit"
        if text == "Fit":
            self._zoom_factor = 1.0
        else:
            try:
                # e.g. '5x' -> 5.0
                self._zoom_factor = float(text.rstrip('x'))
            except Exception:
                self._zoom_factor = 1.0
        # Re-render the last frame with the new zoom (if any)
        if getattr(self, "_last_pixmap", None) is not None:
            self._render_pixmap(self._last_pixmap, getattr(self, "_last_ts", datetime.datetime.now()))

    def _on_pan_changed(self, _value: int):
        """Called when either pan slider moves; re-render using last pixmap."""
        if getattr(self, "_last_pixmap", None) is not None:
            self._render_pixmap(self._last_pixmap, getattr(self, "_last_ts", datetime.datetime.now()))

    def _render_pixmap(self, pixmap: QPixmap, ts: datetime.datetime):
        """Render the given QPixmap into the image label respecting zoom and pan.

        Stores the last pixmap/timestamp so slider updates can trigger re-renders.
        """
        self._last_pixmap = pixmap
        self._last_ts = ts

        zoom = getattr(self, "_zoom_factor", 1.0)
        ow, oh = pixmap.width(), pixmap.height()

        if zoom and zoom > 1.0 and ow > 0 and oh > 0:
            crop_w = max(1, int(ow / zoom))
            crop_h = max(1, int(oh / zoom))
            max_x = max(0, ow - crop_w)
            max_y = max(0, oh - crop_h)

            # Update slider ranges and make visible
            self._h_slider.blockSignals(True)
            self._v_slider.blockSignals(True)
            self._h_slider.setRange(0, max_x)
            self._h_slider.setPageStep(max(1, crop_w))
            self._v_slider.setRange(0, max_y)
            self._v_slider.setPageStep(max(1, crop_h))

            # If sliders were previously hidden, default to centred view
            if not self._h_slider.isVisible():
                self._h_slider.setValue(max_x // 2)
            if not self._v_slider.isVisible():
                self._v_slider.setValue(max_y // 2)

            self._h_slider.setVisible(True)
            self._v_slider.setVisible(True)
            self._h_slider.blockSignals(False)
            self._v_slider.blockSignals(False)

            x0 = min(self._h_slider.value(), max_x) if max_x > 0 else 0
            y0 = min(self._v_slider.value(), max_y) if max_y > 0 else 0

            try:
                crop = pixmap.copy(x0, y0, crop_w, crop_h)
            except Exception:
                crop = pixmap

            disp = crop.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            # Hide pan controls when not zoomed
            self._h_slider.setVisible(False)
            self._v_slider.setVisible(False)
            disp = pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        # Draw blue crosshair at the centre of the displayed pixmap
        w, h = disp.width(), disp.height()
        painter = QPainter(disp)
        pen = QPen(QColor(0, 120, 255))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(0, h // 2, w, h // 2)  # horizontal
        painter.drawLine(w // 2, 0, w // 2, h)  # vertical
        painter.end()

        self._image_label.setPixmap(disp)
        self._timestamp_label.setText("Last frame: " + ts.strftime("%Y-%m-%d  %H:%M:%S"))

    def closeEvent(self, event):
        self._poll_timer.stop()
        if self._thread is not None:
            self._thread.stop()
            self._thread = None
        event.accept()


def format_countdown(countdown: datetime.timedelta):
    """ Format the given countdown.

    Args:
        - countdown: Countdown as datetime

    Returns: Formatted countdown, with the days (if any), hours (if any), minutes, and seconds.
    """

    formatted_countdown = ""
    days = countdown.days

    if days > 0:
        formatted_countdown += f" {days}d "

    hours = countdown.seconds // 3600
    if days > 0 or hours > 0:
        formatted_countdown += f"{hours:02d}:"

    minutes, seconds = (countdown.seconds // 60) % 60, countdown.seconds % 60
    formatted_countdown += f"{minutes:02d}:{seconds:02d}"

    return formatted_countdown


def format_time(time: datetime.datetime, time_format: str) -> str:
    """ Format the given time according to the given time format.

    Args:
        - time: Time as datetime

    Returns: Formatted time, according to the given time format.
    """

    suffix = ""
    if time_format == "12 hours":
        suffix = " am" if time.hour < 12 else " pm"

    return f"{datetime.datetime.strftime(time, TIME_FORMATS[time_format])}{suffix}"


class CameraOverviewTableColumnNames(Enum):
    """ Enumeration of the column names for the table with the camera overview table. """

    CAMERA = "Camera name"
    BATTERY_LEVEL = "Battery level [%]"
    FREE_MEMORY_GB = "Free memory [GB]"
    FREE_MEMORY_PERCENTAGE = "Free memory [%]"


class CameraOverviewTableModel(QAbstractTableModel):

    def __init__(self):
        """ Initialisation of the model for the table with the camera overview. """

        super().__init__()

        self.camera_overview_dict: Union[dict, None] = None
        # Optional callable invoked on the GUI thread after camera data is applied.
        # Set by the controller before calling update_camera_overview() so that
        # sync_camera_time / check_camera_state run only once the dict is ready.
        self.on_ready_callback = None

        self._data = pd.DataFrame(columns=[CameraOverviewTableColumnNames.CAMERA.value,
                                           CameraOverviewTableColumnNames.BATTERY_LEVEL.value,
                                           CameraOverviewTableColumnNames.FREE_MEMORY_GB.value,
                                           CameraOverviewTableColumnNames.FREE_MEMORY_PERCENTAGE.value])
        # signal for async worker
        try:
            self.data_ready = pyqtSignal(object)
            self.data_ready.connect(self._on_data_ready)
        except Exception:
            # fallback for environments without Qt signal support during tests
            self.data_ready = None

    def rowCount(self, index):
        return self._data.shape[0]

    def columnCount(self, index):
        return self._data.shape[1]

    def headerData(self, section, orientation, role):
        # section is the index of the column/row.
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return str(self._data.columns[section])

            if orientation == Qt.Orientation.Vertical:
                return str(self._data.index[section])

    def data(self, index: QModelIndex, role):
        """ Formatting of the data to display. """

        if role == Qt.ItemDataRole.DisplayRole:

            value = self._data.loc[index.row()].iat[index.column()]
            return value

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() == 0:
                return Qt.AlignmentFlag.AlignLeft
            else:
                return Qt.AlignmentFlag.AlignRight

    def update_camera_overview(self):
        """ Update the camera overview. """
        logging.debug('CameraOverviewTableModel.update_camera_overview(): start (scheduling worker)')
        try:
            LOGGER.info("CameraOverview: scheduling worker to probe cameras")
        except Exception:
            pass

        # clear current data quickly on UI thread
        self._data = pd.DataFrame(columns=self._data.columns)
        self.beginResetModel()
        self.endResetModel()

        # start background worker to probe cameras
        # prepare a slot for pending data written by the worker
        self._pending_data = None

        worker = threading.Thread(target=self._gather_camera_info, daemon=True)
        worker.start()

        # start a short polling timer on the main thread to apply data when available
        QTimer.singleShot(200, self._try_apply_pending)

    def _gather_camera_info(self):
        max_retries = 2
        attempt = 0

        while attempt < max_retries:
            try:
                is_sim = getattr(self.view, 'is_simulator', False) and getattr(self.view, 'virtual_camera_enabled', False)
                vc_fps = getattr(self.view, 'virtual_camera_fps', 1)

                # Reuse existing camera objects if available to avoid opening a new USB
                # connection while a previous connection (e.g. from take_picture) is still held.
                existing_map = getattr(self, 'camera_overview_dict', None)
                force_refresh = getattr(self, '_force_camera_refresh', False)

                if force_refresh or not existing_map or not all(v is not None for v in existing_map.values()):
                    if force_refresh:
                        logging.info(f"CameraOverview: forcing fresh detection (attempt {attempt+1})")
                        self._force_camera_refresh = False

                    alias_map = ConfigManager().get_camera_aliases() or None
                    camera_dict = get_camera_dict(is_simulator=is_sim, alias_map=alias_map)
                    logging.debug('CameraOverview: fresh camera detection performed')
                else:
                    camera_dict = existing_map
                    logging.debug('CameraOverview: reusing %d existing camera object(s)', len(camera_dict))

                data = []
                seen_camera_ids: set = set()
                needs_refresh = False

                for camera_name, camera in camera_dict.items():
                    # Skip bare-key aliases that point to the same physical camera object
                    # already added under its full gphoto2 name (e.g. "Sony Alpha-A7r II"
                    # is a duplicate of "Sony Alpha-A7r II (Control)").
                    cam_id = id(camera)
                    if cam_id in seen_camera_ids:
                        logging.debug('Worker: skipping duplicate alias "%s" (same camera object)', camera_name)
                        continue
                    seen_camera_ids.add(cam_id)
                    try:
                        logging.debug('Worker: processing camera %s', camera_name)
                        battery_level = get_battery_level(camera).rstrip('%')
                        free_space_gb = get_free_space(camera)
                        total_space = get_space(camera)
                        if free_space_gb < 0 or total_space <= 0:
                            free_space_gb_str = 'N/A'
                            free_space_pct_str = 'N/A'
                        else:
                            free_space_gb_str = str(free_space_gb)
                            free_space_pct_str = str(int(free_space_gb / total_space * 100))
                        data.append([camera_name, str(battery_level), free_space_gb_str, free_space_pct_str])
                    except Exception as e:
                        error_str = str(e).lower()
                        if any(x in error_str for x in ['-52', '-2', 'could not find the requested device', 'bad parameters']):
                            logging.warning(f"Stale camera connection detected on {camera_name} ({e})")
                            needs_refresh = True
                            self._force_camera_refresh = True
                        # Preserve the camera row with N/A values when probing fails so
                        # the camera does not disappear from the UI.
                        try:
                            data.append([camera_name, 'N/A', 'N/A', 'N/A'])
                        except Exception:
                            pass
                        continue

                # If we hit critical errors, retry once with fresh objects
                if needs_refresh and attempt == 0:
                    logging.info("Critical USB errors detected - resetting camera_overview_dict and retrying...")
                    self.camera_overview_dict = None
                    attempt += 1
                    continue

                # schedule UI update on main thread
                try:
                    LOGGER.info("Worker: gathered camera overview data: " + data)
                except Exception:
                    pass
                # write pending data and the camera objects for the main thread poll to pick up
                try:
                    self._pending_data = data
                    # keep the mapping of camera name -> camera object for later actions
                    self._pending_camera_map = camera_dict
                except Exception:
                    logging.exception('Worker: could not set pending data')
                break
            except Exception:
                logging.exception('Worker: failed to gather camera info')
                attempt += 1
                if attempt >= max_retries:
                    break

    def _on_data_ready(self, data):
        try:
            LOGGER.info("CameraOverview: on_data_ready called with " + data)
        except Exception:
            pass
        # Update internal dict for other parts of the app (store camera objects if available)
        try:
            # prefer the actual camera objects if the worker provided them
            pending_map = getattr(self, '_pending_camera_map', None)
            if pending_map:
                self.camera_overview_dict = pending_map
            else:
                # fallback: create a name->None map
                dmap = {}
                for row in data:
                    name = row[0]
                    dmap[name] = None
                self.camera_overview_dict = dmap
            # clear pending map
            try:
                self._pending_camera_map = None
            except Exception:
                pass
        except Exception:
            self.camera_overview_dict = None

        # Merge incoming data with previous data to avoid dropping cameras when
        # a probe fails or the worker returns partial/empty results.
        try:
            # Map new data by camera name for quick lookup
            new_map = {row[0]: list(row) for row in data}

            # Build a map of previous rows (camera_name -> row values)
            prev_map = {}
            try:
                for i in range(self._data.shape[0]):
                    prev_row = list(self._data.iloc[i].values)
                    prev_map[str(prev_row[0])] = prev_row
            except Exception:
                prev_map = {}

            # Determine the canonical ordering: prefer pending camera_map keys if available
            pending_map = getattr(self, '_pending_camera_map', None)
            if pending_map:
                order = list(pending_map.keys())
            elif data:
                order = [row[0] for row in data]
            else:
                order = list(prev_map.keys())

            # If there's no new order and we have previous data, keep previous table
            if not order and self._data is not None and not self._data.empty:
                return

            merged_rows = []
            for name in order:
                if name in new_map:
                    merged_rows.append(new_map[name])
                elif name in prev_map:
                    merged_rows.append(prev_map[name])
                else:
                    merged_rows.append([name, 'N/A', 'N/A', 'N/A'])

            self.beginResetModel()
            self._data = pd.DataFrame(merged_rows, columns=self._data.columns)
            self.endResetModel()
        except Exception:
            logging.exception('Could not merge camera overview data')
            # Fallback to previous behaviour
            try:
                self.beginResetModel()
                self._data = pd.DataFrame(data, columns=self._data.columns)
                self.endResetModel()
            except Exception:
                logging.exception('Fallback: could not set camera overview data')

        # Ensure the view updates and columns are sized to the new data
        try:
            if hasattr(self, 'view') and getattr(self.view, 'camera_overview', None):
                self.view.camera_overview.setModel(self)
                self.view.camera_overview.resizeColumnsToContents()
                try:
                    self.view.camera_overview.selectRow(0)
                except Exception:
                    pass
                self.view.camera_overview.repaint()
                LOGGER.info("CameraOverview: view updated")
        except Exception:
            logging.exception('Could not update camera overview view after data ready')

        # Notify controller that cameras are ready (fires sync_camera_time + check_camera_state)
        cb = getattr(self, 'on_ready_callback', None)
        if cb is not None:
            try:
                cb()
            except Exception:
                logging.exception('on_ready_callback raised an exception')
            finally:
                self.on_ready_callback = None

        # Check if a Sony camera is present. Use vendor attribute when available,
        # else fall back to camera name containing 'sony'.
        try:
            sony_present = False
            pm = getattr(self, 'camera_overview_dict', None)
            if pm:
                for cam in pm.values():
                    if cam is not None and _is_sony_camera_instance(cam):
                        sony_present = True
                        break
        except Exception:
            logging.debug('Could not check the presence of a Sony camera', exc_info=True)

        # If we have actual camera objects, start the Sony background downloader
        # automatically only when the camera reports PC-Only save destination.
        # Also, show an informational banner about the relevant settings.
        try:
            if pm and sony_present:
                for cam in pm.values():
                    try:
                        if cam is None:
                            continue
                        if getattr(cam, 'vendor', None) != 'Sony':
                            # ensure any previously running downloader is stopped
                            try:
                                cam.stop_background_downloader()
                            except Exception:
                                pass
                            continue
                        dest = get_sony_save_destination(cam)
                        image_quality = get_sony_image_quality(cam)
                        # Start downloader only when destination clearly says
                        # PC-only. If destination is unavailable (common with
                        # localized camera menus), avoid downloading to protect
                        # shot timing.
                        camera_model = getattr(cam, 'name', None)
                        sony_banner_label_visibility = True
                        if dest == "sdram":
                            sony_banner_label_text = camera_model + ": currently saving photos to PC. We recommend testing if 'PC+Camera' mode is faster for you or not."
                            if image_quality != "RAW":
                                sony_banner_label_text += " Also, 'File Format' is set to ''" + image_quality + "'. Please set it to 'RAW'!"
                            try:
                                cam.start_background_downloader()
                            except Exception:
                                logging.exception('Failed to start downloader for: ' + camera_model)
                        elif dest == "card+sdram":
                            sony_banner_label_text = camera_model + ": currently in 'PC+Camera' mode. We recommend testing if 'PC' mode is faster for you or not."
                            if not image_quality.startswith("RAW+JPEG"):
                                sony_banner_label_text += " Also, 'File Format' is set to ''" + image_quality + "'. Please set it to 'RAW+JPEG' and in 'PC Remote Settings' please choose 'JPEG Only' for 'RAW+J PC Save Img' option!"
                            try:
                                cam.stop_background_downloader()
                            except Exception:
                                pass
                        elif dest == "card":
                            if image_quality != "RAW":
                                sony_banner_label_text = camera_model + ": 'File Format' is set to ''" + image_quality + "'. Please set it to 'RAW'!"
                            else:
                                sony_banner_label_visibility = False
                            try:
                                cam.stop_background_downloader()
                            except Exception:
                                pass
                        else:
                            if image_quality != "RAW":
                                sony_banner_label_text = camera_model + ": 'Quality' is set to ''" + image_quality + "'. Please set it to 'RAW'!"
                            else:
                                sony_banner_label_visibility = False
                            try:
                                cam.start_background_downloader()
                            except Exception:
                                logging.exception('Failed to start downloader for: ' + camera_model)
                        if hasattr(self, 'view') and getattr(self.view, 'sony_banner_label', None) is not None:
                            if sony_banner_label_visibility:
                                full_text = f"{sony_banner_label_text} If this info is wrong or you want to re-check after an update to the settings - just press again the 'Camera(s)' button!"
                                self.view.sony_banner_label.setText(full_text)
                                self.view.sony_banner_label.setVisible(True)
                            else:
                                # Hide it cleanly without touching inner text properties
                                self.view.sony_banner_label.setVisible(False)
                    except Exception:
                        logging.debug('Error while checking Sony save destination', exc_info=True)
        except Exception:
            logging.debug('Could not auto-start Sony downloader and update Sony banner visibility', exc_info=True)

    def _try_apply_pending(self):
        """Poll for pending data written by the background worker and apply it on the GUI thread."""
        try:
            data = getattr(self, '_pending_data', None)
            if data:
                # clear pending before applying to avoid races
                self._pending_data = None
                self._on_data_ready(data)
            else:
                # not ready yet — try again shortly
                QTimer.singleShot(200, self._try_apply_pending)
        except Exception:
            logging.exception('Error while polling for pending camera overview data')


class JobsTableColumnNames(Enum):
    """ Enumeration of the column names for the table with the scheduled jobs. """

    EXEC_TIME_UTC = "Execution time (UTC)"
    EXEC_TIME_LOCAL = "Execution time (local)"
    COUNTDOWN = "Countdown"
    COMMAND = "Command"
    DESCRIPTION = "Description"


class JobsTableModel(QAbstractTableModel, Observable):
    def __init__(self, scheduler: BackgroundScheduler, controller: SolarEclipseController):
        """ Initialisation of the model for the table with the scheduled jobs.

        Args:
            - scheduler: Background scheduler
            - model: Model for the Solar Eclipse Workbench UI
        """

        super().__init__()
        self.controller = controller
        self.time_format = self.controller.view.time_format

        from solareclipseworkbench.reference_moments import _find_timezone
        timezone = pytz.timezone(_find_timezone(self.controller.model.longitude, self.controller.model.latitude))

        now_utc = datetime.datetime.now().astimezone(tz=datetime.timezone.utc)
        data = []

        self.execution_times_utc_as_datetime = []
        self.execution_times_local_as_datetime = []

        job: Job
        for job in scheduler.get_jobs():

            execution_time_utc: datetime.datetime = job.next_run_time
            if execution_time_utc:
                execution_time_local = execution_time_utc.astimezone(timezone)

                countdown = "-"
                if now_utc <= execution_time_utc:
                    countdown = format_countdown(execution_time_utc - now_utc)
                description: str = job.name

                job_string = ""

                if job.func.__name__ == "take_picture":
                    camera_settings: CameraSettings = job.args[1]
                    camera_name = camera_settings.camera_name
                    shutter_speed = camera_settings.shutter_speed
                    aperture = camera_settings.aperture
                    iso = camera_settings.iso

                    job_string = f"take_picture(\"{camera_name}\", {shutter_speed}, {aperture}, {iso})"

                elif job.func.__name__ == "take_burst":
                    camera_settings: CameraSettings = job.args[1]
                    camera_name = camera_settings.camera_name
                    shutter_speed = camera_settings.shutter_speed
                    aperture = camera_settings.aperture
                    iso = camera_settings.iso
                    duration = job.args[2]

                    job_string = f"take_burst(\"{camera_name}\", {shutter_speed}, {aperture}, {iso}, {duration})"

                elif job.func.__name__ == "take_bracket":
                    camera_settings: CameraSettings = job.args[1]
                    camera_name = camera_settings.camera_name
                    shutter_speed = camera_settings.shutter_speed
                    aperture = camera_settings.aperture
                    iso = camera_settings.iso
                    step = job.args[2]

                    job_string = f"take_bracket(\"{camera_name}\", {shutter_speed}, {aperture}, {iso}, {step})"

                elif job.func.__name__ == "take_hdr":
                    camera_settings: CameraSettings = job.args[1]
                    camera_name = camera_settings.camera_name
                    shutter_speed = camera_settings.shutter_speed
                    aperture = camera_settings.aperture
                    iso = camera_settings.iso
                    stops = job.args[2]

                    job_string = f"take_hdr(\"{camera_name}\", {shutter_speed}, {aperture}, {iso}, {stops} stops)"

                elif job.func.__name__ == "sync_cameras":
                    job_string = f"sync_cameras()"

                elif job.func.__name__ == "voice_prompt":
                    job_string = f"{job.func.__name__}({', '.join(job.args).strip()})"

                elif job.func.__name__ == "execute_command":
                    job_string = f"command({', '.join(job.args).strip()})"

                self.execution_times_utc_as_datetime.append(execution_time_utc)
                formatted_execution_time_utc = format_time(execution_time_utc, self.time_format)

                self.execution_times_local_as_datetime.append(execution_time_local)
                formatted_execution_time_local = format_time(execution_time_local, self.time_format)

                data.append([countdown, formatted_execution_time_local, formatted_execution_time_utc, job_string,
                             description])

        self._data = pd.DataFrame(data, columns=[JobsTableColumnNames.COUNTDOWN.value,
                                                 JobsTableColumnNames.EXEC_TIME_LOCAL.value,
                                                 JobsTableColumnNames.EXEC_TIME_UTC.value,
                                                 JobsTableColumnNames.COMMAND.value,
                                                 JobsTableColumnNames.DESCRIPTION.value])

    def update_countdown(self):
        """ Update the countdown until execution time."""

        if self._data.shape[0] > 0:

            self.beginResetModel()
            now_utc = datetime.datetime.now().astimezone(tz=datetime.timezone.utc)
            time_format = self.controller.view.time_format
            for row in range(len(self.execution_times_local_as_datetime)):

                new_countdown = self.execution_times_utc_as_datetime[row] - now_utc
                if new_countdown.total_seconds() >= 0:
                    if int(new_countdown.total_seconds()) == 0:
                        self.notify_observers(row)
                    new_countdown = format_countdown(new_countdown)
                else:
                    new_countdown = "-"
                self._data.loc[row, JobsTableColumnNames.COUNTDOWN.value] = new_countdown

                if self.time_format != time_format:
                    self._data.loc[row, JobsTableColumnNames.EXEC_TIME_UTC.value] \
                        = format_time(self.execution_times_utc_as_datetime[row], time_format)
                    self._data.loc[row, JobsTableColumnNames.EXEC_TIME_LOCAL.value] \
                        = format_time(self.execution_times_local_as_datetime[row], time_format)

            self.time_format = time_format

            self.endResetModel()

    def clear_jobs_overview(self):
        """ Clear the scheduled jobs overview. """

        self.beginResetModel()
        self._data = pd.DataFrame(columns=self._data.columns)
        self.endResetModel()

    def rowCount(self, index):
        return self._data.shape[0]

    def columnCount(self, index):
        return self._data.shape[1]

    def headerData(self, section, orientation, role):
        # section is the index of the column/row.
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return str(self._data.columns[section])

            if orientation == Qt.Orientation.Vertical:
                return str(self._data.index[section])

    def data(self, index: QModelIndex, role):
        """ Formatting of the data to display. """

        if role == Qt.ItemDataRole.DisplayRole:

            value = self._data.loc[index.row()].iat[index.column()]

            # Perform per-type checks and render accordingly.
            if isinstance(value, datetime.datetime):
                return format_time(value, self.controller.view.time_format)
            return value

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() == 0:
                return Qt.AlignmentFlag.AlignRight
            elif index.column() <= 2:
                return Qt.AlignmentFlag.AlignHCenter
            else:
                return Qt.AlignmentFlag.AlignLeft


class QJobsTableView(QTableView):

    def __init__(self):
        super().__init__()

    def update(self, row: int):
        """ Scroll to the jobs that are up next.

        Args:
            - row: Row index of the first job that will be executed next.
        """

        index: QModelIndex = self.model().index(min(row + 5, self.model().rowCount(None) - 1), 0)
        self.setCurrentIndex(index)

    def do(self, actions):
        pass


def main():
    time_string = time.strftime("%Y%m%d-%H%M%S")
    logging.basicConfig(filename=f'{time_string}.log', level=logging.DEBUG, format='%(asctime)s %(message)s')
    # Also log to stdout so users see debug output in terminal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(console_handler)
    LOGGER.info("Starting up Solar Eclipse Workbench")

    parser = argparse.ArgumentParser(description="Solar Eclipse Workbench")
    parser.add_argument(
        "-s",
        "--sim",
        help="Start up in simulator mode",
        default=False,
        action='store_true'
    )
    parser.add_argument(
        "--virtual-camera",
        help="Enable virtual camera (when starting GUI in simulator mode)",
        action='store_true',
        default=False,
    )
    parser.add_argument(
        "-lon",
        "--longitude",
        help="longitude of the location where to watch the solar eclipse (W is negative)",
        default=False,
        type=float
    )

    parser.add_argument(
        "-lat",
        "--latitude",
        help="latitude of the location where to watch the solar eclipse (N is positive)",
        default=False,
        type=float
    )

    parser.add_argument(
        "-alt",
        "--altitude",
        help="altitude of the location where to watch the solar eclipse (in metres)",
        default=False,
        type=float
    )

    parser.add_argument(
        "-d",
        "--date",
        help="date of the solar eclipse (in YYYY-MM-DD format)",
        default=False,
    )

    parser.add_argument(
        "-lc",
        "--low-cpu",
        help="Disable the eclipse visualization plot auto-update",
        action='store_true',
        default=False,
    )

    parser.add_argument(
        "-scm",
        "--sony-cont-mode",
        help="Specify continuous mode name for Sony cameras"
    )

    args = parser.parse_args()
    configuration.SONY_CONTINUOUS_MODE = args.sony_cont_mode
    # args[1:1] = ["-stylesheet", str(styles_location)]
    app = QApplication(list(sys.argv))
    apply_system_color_scheme(app)
    app.setWindowIcon(QIcon(str(ICON_PATH / "logo-small.svg")))
    app.setApplicationName("Solar Eclipse Workbench")

    model = SolarEclipseModel()
    view = SolarEclipseView(is_simulator=args.sim,low_cpu_mode=args.low_cpu)
    # Attach virtual camera defaults to the view so other parts can query them
    view.virtual_camera_enabled = args.virtual_camera

    controller = SolarEclipseController(
        model,
        view,
        is_simulator=args.sim,
        low_cpu_mode=args.low_cpu
    )

    # Make the view available to the camera overview model so it can read simulator flags
    model.camera_overview.view = view

    if args.longitude and args.latitude and args.altitude:
        controller.set_location(args.longitude, args.latitude, args.altitude)

    if args.date:
        controller.set_eclipse_date(args.date, date_format=None)

    # Show the main window first, then schedule reference-moments calculation so
    # the loading dialog is shown on top of the visible GUI if helper files
    # need to be downloaded.
    view.show()

    if args.longitude and args.latitude and args.altitude and args.date:
        # Schedule after the event loop starts so the main window is painted.
        QTimer.singleShot(0, controller.set_reference_moments)

    return app.exec()


def sync_cameras(controller: SolarEclipseController):
    """ Synchronise the cameras for the given controller.

    This consists of the following steps:

        - Update the camera overview in the model and the view of the given controller;
        - Set the time of all connected cameras to the time of the computer;
        - Check whether the focus mode and shooting mode of all connected cameras is set to 'Manual'.

    Args:
        - controller: Controller of the Solar Eclipse Workbench UI
    """

    controller.model.camera_overview.update_camera_overview()


if __name__ == "__main__":

    sys.exit(main())
