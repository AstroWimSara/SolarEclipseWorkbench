""" Solar Eclipse Workbench GUI, implemented according to the MVC pattern:

    - Model: SolarEclipseModel
    - View: SolarEclipseView
    - Controller: SolarEclipseController
"""

import datetime
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Union

import geopandas
import pandas as pd
import pytz
from PyQt6.QtCore import QTimer, QRect, Qt, QAbstractTableModel, QModelIndex
from PyQt6.QtGui import QIcon, QAction, QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, QGridLayout, \
    QGroupBox, QComboBox, QPushButton, QLineEdit, QFileDialog, QScrollArea, QTableView
from apscheduler.job import Job
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from astropy.time import Time
from geodatasets import get_path
from gphoto2 import GPhoto2Error
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from timezonefinder import TimezoneFinder

from solareclipseworkbench.camera import get_camera_dict, get_battery_level, get_free_space, get_space, \
    get_shooting_mode, get_focus_mode, set_time, CameraSettings
from solareclipseworkbench.observer import Observer, Observable
from solareclipseworkbench.reference_moments import calculate_reference_moments, ReferenceMomentInfo

ICON_PATH = Path(__file__).parent.resolve() / ".." / ".." / "img"

ECLIPSE_DATES = ["08/04/2024", "02/10/2024", "29/03/2025", "21/09/2025", "17/02/2026", "12/08/2026", "06/02/2027",
                 "02/08/2027", "26/01/2028", "22/07/2028", "14/01/2029", "12/06/2029", "11/07/2029", "05/12/2029",
                 "01/06/2030", "25/11/2030", "21/05/2031", "14/11/2031", "09/05/2032", "03/11/2033", "30/03/2033",
                 "23/09/2033", "20/03/2034", "12/09/2034", "09/03/2035", "02/09/2035", "27/02/2036", "23/07/2036",
                 "21/08/2036", "16/01/2037", "13/07/2037", "05/01/2038", "02/07/2038", "26/12/2038", "21/06/2039",
                 "15/12/2039", "11/05/2040", "04/11/2040", "30/04/2041", "25/10/2041", "20/04/2042", "14/10/2042",
                 "09/04/2043", "03/10/2043", "28/02/2044", "23/08/2044", "16/02/2045", "12/08/2045"]

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

        self.camera_overview: dict = None

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

    def set_camera_overview(self, camera_overview: dict):
        """ Set the camera overview to the given dictionary.

        Args:
            - camera_overview: Dictionary containing the camera overview
        """

        self.camera_overview = camera_overview

    def sync_camera_time(self):
        """ Set the time of all connected cameras to the time of the computer."""

        for camera_name, camera in self.camera_overview.items():

            logging.info(f"Syncing time for camera {camera_name}")
            set_time(camera)

    def check_camera_state(self):
        """ Check whether the focus mode and shooting mode of all connected cameras is set to 'Manual'.

        For the camera(s) for which the focus mode and/or shooting mode is not set to 'Manual', a warning message is
        logged.
        """

        for camera_name, camera in self.camera_overview.items():

            # Focus mode

            focus_mode = get_focus_mode(camera)
            if focus_mode.lower() != "manual":
                logging.warning(f"The focus mode for camera {camera_name} should be set to 'Manual' "
                                f"(is '{focus_mode}')")

            # Shooting mode

            shooting_mode = get_shooting_mode(camera_name, camera)
            if shooting_mode.lower() != "manual":
                logging.warning(f"The shooting mode for camera {camera_name} should be set to 'Manual' "
                                f"(is '{shooting_mode}')")


class SolarEclipseView(QMainWindow, Observable):
    """ View for the Solar Eclipse Workbench UI in the MVC pattern. """

    def __init__(self, is_simulator: bool = False):
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

        self.setGeometry(300, 300, 1500, 1000)
        self.setWindowTitle("Solar Eclipse Workbench")

        self.date_format = list(DATE_FORMATS.keys())[0]
        self.time_format = list(TIME_FORMATS.keys())[0]

        self.toolbar = None

        self.place_time_frame = QFrame()

        self.eclipse_date_widget = QWidget()
        self.eclipse_date_label = QLabel(f"Eclipse date [{self.date_format}]")
        self.eclipse_date = QLabel(f"")

        self.reference_moments_widget = QWidget()
        self.c1_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c2_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.max_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c3_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c4_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.sunrise_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.sunset_time_local_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c1_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c2_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.max_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c3_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c4_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.sunrise_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.sunset_time_utc_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c1_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c2_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.max_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c3_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c4_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.sunrise_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.sunset_countdown_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c1_azimuth_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c2_azimuth_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.max_azimuth_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c3_azimuth_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c4_azimuth_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c1_altitude_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c2_altitude_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.max_altitude_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c3_altitude_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.c4_altitude_label = QLabel(alignment=Qt.AlignmentFlag.AlignRight)

        self.date_label = QLabel(f"Date [{self.date_format}]")
        self.date_label_local = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.time_label_local = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.time_label_local.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_label_utc = QLabel(alignment=Qt.AlignmentFlag.AlignRight)
        self.time_label_utc = QLabel(alignment=Qt.AlignmentFlag.AlignRight)

        self.longitude_label = QLabel()
        self.longitude_label.setToolTip(
            "Positive values: East of Greenwich meridian; Negative values: West of Greenwich meridian")
        self.latitude_label = QLabel()
        self.latitude_label.setToolTip("Positive values: Northern hemisphere; Negative values: Southern hemisphere")
        self.altitude_label = QLabel()

        self.eclipse_type = QLabel()

        self.camera_overview_grid_layout = QGridLayout()
        self.camera_overview_grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.jobs_table = QTableView()

        self.init_ui()

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

        camera_overview_group_box = QGroupBox()
        self.camera_overview_grid_layout.addWidget(QLabel("Camera"), 0, 0)
        self.camera_overview_grid_layout.addWidget(QLabel("Battery level [%]"), 0, 1)
        self.camera_overview_grid_layout.addWidget(QLabel("Free memory [GB]"), 0, 2)
        self.camera_overview_grid_layout.addWidget(QLabel("Free memory [%]"), 0, 3)
        camera_overview_group_box.setLayout(self.camera_overview_grid_layout)
        camera_overview_group_box.setFixedWidth(600)

        hbox = QHBoxLayout()
        hbox.addLayout(vbox_left)
        hbox.addWidget(reference_moments_group_box)
        hbox.addWidget(camera_overview_group_box)

        scroll = QScrollArea()
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)

        scroll.setWidget(self.jobs_table)

        global_layout = QVBoxLayout()
        global_layout.addLayout(hbox)

        global_layout.addWidget(scroll)

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

        location_action = QAction("Location", self)
        location_action.setStatusTip("Location")
        location_action.setIcon(QIcon(str(ICON_PATH / "location.png")))
        location_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(location_action)

        # Date

        date_action = QAction("Date", self)
        date_action.setStatusTip("Date")
        date_action.setIcon(QIcon(str(ICON_PATH / "calendar.png")))
        date_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(date_action)

        # Reference moments

        reference_moments_action = QAction("Reference moments", self)
        reference_moments_action.setStatusTip("Reference moments")
        reference_moments_action.setIcon(QIcon(str(ICON_PATH / "clock.png")))
        reference_moments_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(reference_moments_action)

        # Camera(s)

        camera_action = QAction("Camera(s)", self)
        camera_action.setStatusTip("Camera(s)")
        camera_action.setIcon(QIcon(str(ICON_PATH / "camera.png")))
        camera_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(camera_action)

        if self.is_simulator:
            simulator_action = QAction("Simulator", self)
            simulator_action.setStatusTip("Configure simulator")
            simulator_action.setIcon(QIcon(str(ICON_PATH / "simulator.png")))
            simulator_action.triggered.connect(self.on_toolbar_button_click)
            self.toolbar.addAction(simulator_action)

        # Configuration file

        file_action = QAction("File", self)
        file_action.setStatusTip("File")
        file_action.setIcon(QIcon(str(ICON_PATH / "folder.png")))
        file_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(file_action)

        # Shutdown scheduler

        shutdown_scheduler_action = QAction("Stop", self)
        shutdown_scheduler_action.setStatusTip("Shut down scheduler")
        shutdown_scheduler_action.setIcon(QIcon(str(ICON_PATH / "stop.png")))
        shutdown_scheduler_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(shutdown_scheduler_action)

        # Settings

        settings_action = QAction("Settings", self)
        settings_action.setStatusTip("Settings")
        settings_action.setIcon(QIcon(str(ICON_PATH / "settings.png")))
        settings_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(settings_action)

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
        self.date_label_local.setText(datetime.datetime.strftime(current_time_local, DATE_FORMATS[self.date_format])) # "%d/%m/%Y"))
        self.date_label_utc.setText(datetime.datetime.strftime(current_time_utc, DATE_FORMATS[self.date_format]))

        suffix = ""
        if self.time_format == "12 hours":
            suffix = " am" if current_time_utc.hour < 12 else " pm"

        self.time_label_local.setText(
            f"{datetime.datetime.strftime(current_time_local, TIME_FORMATS[self.time_format])}{suffix}")
        self.time_label_utc.setText(
            f"{datetime.datetime.strftime(current_time_utc, TIME_FORMATS[self.time_format])}{suffix}")

        if countdown_c1:
            self.c1_countdown_label.setText(str(format_countdown(countdown_c1)))
        else:
            self.c1_countdown_label.setText("")
        if countdown_c2:
            self.c2_countdown_label.setText(str(format_countdown(countdown_c2)))
        else:
            self.c2_countdown_label.setText("")
        if countdown_max:
            self.max_countdown_label.setText(str(format_countdown(countdown_max)))
        else:
            self.max_countdown_label.setText("")
        if countdown_c3:
            self.c3_countdown_label.setText(str(format_countdown(countdown_c3)))
        else:
            self.c3_countdown_label.setText("")
        if countdown_c4:
            self.c4_countdown_label.setText(str(format_countdown(countdown_c4)))
        else:
            self.c4_countdown_label.setText("")
        if countdown_sunrise:
            self.sunrise_countdown_label.setText(str(format_countdown(countdown_sunrise)))
        else:
            self.sunrise_countdown_label.setText("")
        if countdown_sunset:
            self.sunset_countdown_label.setText(str(format_countdown(countdown_sunset)))
        else:
            self.sunset_countdown_label.setText("")

    def show_reference_moments(self, reference_moments: dict, magnitude: float, eclipse_type: str):
        """ Display the given reference moments, magnitude, and eclipse type.

        Args:
            - reference_moments: Dictionary with the reference moments (C1, C2, maximum eclipse, C3, C4, sunrise, and
                                 sunset)
            - magnitude: Eclipse magnitude (0: no eclipse, 1: total eclipse)
            - eclipse_type: Eclipse type (total / annular / partial / no eclispe)
        """

        if eclipse_type == "Partial" or eclipse_type == "Annular":
            self.eclipse_type.setText(eclipse_type + f" eclipse (magnitude: {round(magnitude, 2)})")
        elif eclipse_type == "No eclipse":
            self.eclipse_type.setText(eclipse_type)
        else:
            minutes, seconds = divmod(reference_moments["duration"].seconds, 60)
            self.eclipse_type.setText(f"{eclipse_type} eclipse ({minutes}:{seconds:02})")

        suffix = ""

        # First contact

        if "C1" in reference_moments:
            c1_info: ReferenceMomentInfo = reference_moments["C1"]
            label_text_utc, label_text_local \
                = format_reference_moment_labels(c1_info.time_utc, c1_info.time_local, self.time_format)
            self.c1_time_utc_label.setText(label_text_utc)
            self.c1_time_local_label.setText(label_text_local)
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
            label_text_utc, label_text_local \
                = format_reference_moment_labels(c2_info.time_utc, c2_info.time_local, self.time_format)
            self.c2_time_utc_label.setText(label_text_utc)
            self.c2_countdown_label.setText(label_text_local)
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
            label_text_utc, label_text_local \
                = format_reference_moment_labels(max_info.time_utc, max_info.time_local, self.time_format)
            self.max_time_utc_label.setText(label_text_utc)
            self.max_countdown_label.setText(label_text_local)
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
            label_text_utc, label_text_local \
                = format_reference_moment_labels(c3_info.time_utc, c3_info.time_local, self.time_format)
            self.c3_time_utc_label.setText(label_text_utc)
            self.c3_countdown_label.setText(label_text_local)
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
            label_text_utc, label_text_local \
                = format_reference_moment_labels(c4_info.time_utc, c4_info.time_local, self.time_format)
            self.c4_time_utc_label.setText(label_text_utc)
            self.c4_countdown_label.setText(label_text_local)
            self.c4_azimuth_label.setText(str(int(c4_info.azimuth)))
            self.c4_altitude_label.setText(str(int(c4_info.altitude)))
        else:
            self.c4_time_utc_label.setText("")
            self.c4_time_local_label.setText("")
            self.c4_azimuth_label.setText("")
            self.c4_altitude_label.setText("")

        # Sunrise

        sunrise_info: ReferenceMomentInfo = reference_moments["sunrise"]
        label_text_utc, label_text_local \
            = format_reference_moment_labels(sunrise_info.time_utc, sunrise_info.time_local, self.time_format)
        self.sunrise_time_utc_label.setText(label_text_utc)
        self.sunrise_countdown_label.setText(label_text_local)

        # Sunset

        sunset_info: ReferenceMomentInfo = reference_moments["sunset"]

    def show_camera_overview(self, camera_overview: dict):
        """ Display the overview of connected cameras.

        Args:
            - camera_overview: Dictionary with an overview of the connected cameras
        """

        # Clear the widget

        for widget_index in reversed(range(self.camera_overview_grid_layout.count())):
            # if not widget_index % 3:
            self.camera_overview_grid_layout.itemAt(widget_index).widget().setParent(None)

        self.camera_overview_grid_layout.addWidget(QLabel("Camera"), 0, 0)
        self.camera_overview_grid_layout.addWidget(QLabel("Battery level [%]"), 0, 1)
        self.camera_overview_grid_layout.addWidget(QLabel("Free memory [GB]"), 0, 2)
        self.camera_overview_grid_layout.addWidget(QLabel("Free memory [%]"), 0, 3)

        camera_index = 1
        for camera_name, camera in camera_overview.items():

            try:
                battery_level = get_battery_level(camera).rstrip("%")
                free_space_gb = get_free_space(camera)
                total_space = get_space(camera)

                free_space_percentage = int(free_space_gb / total_space * 100)

                self.camera_overview_grid_layout.addWidget(QLabel(camera_name), camera_index, 0)
                self.camera_overview_grid_layout.addWidget(
                    QLabel(str(battery_level), alignment=Qt.AlignmentFlag.AlignRight), camera_index, 1)
                self.camera_overview_grid_layout.addWidget(
                    QLabel(str(free_space_gb), alignment=Qt.AlignmentFlag.AlignRight), camera_index, 2)
                self.camera_overview_grid_layout.addWidget(
                    QLabel(str(free_space_percentage), alignment=Qt.AlignmentFlag.AlignRight), camera_index, 3)
            except GPhoto2Error:
                self.camera_overview_grid_layout.addWidget(QLabel(camera_name), camera_index, 0)
                self.camera_overview_grid_layout.addWidget(
                    QLabel("N.A.", alignment=Qt.AlignmentFlag.AlignRight), camera_index, 1)
                self.camera_overview_grid_layout.addWidget(
                    QLabel("N.A.", alignment=Qt.AlignmentFlag.AlignRight), camera_index, 2)
                self.camera_overview_grid_layout.addWidget(
                    QLabel("N.A.", alignment=Qt.AlignmentFlag.AlignRight), camera_index, 3)

            camera_index += 1


class SolarEclipseController(Observer):
    """ Controller for the Solar Eclipse Workbench UI in the MVC pattern. """

    def __init__(self, model: SolarEclipseModel, view: SolarEclipseView, is_simulator: bool):
        """ Initialisation of the controller of the Solar Eclipse Workbench UI.

        Args:
            - model: Model for the Solar Eclipse Workbench UI
            - view: View for the Solar Eclipse Workbench UI
            - is_simulator: Indicates whether the UI should be started in simulator mode
        """

        self.model = model
        self.jobs_model: Union[JobsTableModel, None] = None

        self.view: SolarEclipseView = view
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

        self.update_jobs_countdown()

    def update_jobs_countdown(self):
        """ Update the countdown of the scheduled jobs. """

        if self.jobs_model:
            self.jobs_model.update_countdown()

    def do(self, actions):
        pass

    def update(self, changed_object):
        """ Take action when a notification is received from an observable.

        The following notifications can be received:

            - Change in location at which the solar eclipse will be observed;
            - Change in date at which the solar eclipse will be observed;
            - Change in date and/or time format;
            - One of the buttons in the toolbar of the view is clicked.

        Args:
            - changed_object: Object from which the update was requested
        """

        if isinstance(changed_object, LocationPopup):
            longitude = float(changed_object.longitude.text())
            latitude = float(changed_object.latitude.text())
            altitude = float(changed_object.altitude.text())

            self.model.set_position(longitude, latitude, altitude)

            self.view.longitude_label.setText(str(longitude))
            self.view.latitude_label.setText(str(latitude))
            self.view.altitude_label.setText(str(altitude))
            return

        elif isinstance(changed_object, EclipsePopup):
            eclipse_date = changed_object.eclipse_combobox.currentText()
            self.model.set_eclipse_date(Time(datetime.datetime.strptime(eclipse_date, DATE_FORMATS[self.view.date_format])))

            self.view.eclipse_date.setText(changed_object.eclipse_combobox.currentText())
            return

        elif isinstance(changed_object, SimulatorPopup):
            self.sim_reference_moment = changed_object.reference_moment_combobox.currentText()
            self.sim_offset_minutes = int(changed_object.offset_minutes.text()) * BEFORE_AFTER[changed_object.before_after_combobox.currentText()]
            return

        elif isinstance(changed_object, SettingsPopup):
            date_format = changed_object.date_combobox.currentText()
            self.view.date_format = date_format
            if self.model.eclipse_date:
                self.view.eclipse_date.setText(self.model.eclipse_date.strftime(DATE_FORMATS[date_format]))

            time_format = changed_object.time_combobox.currentText()
            self.view.time_format = time_format

            if self.model.c1_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.c1_info.time_utc, self.model.c1_info.time_local, time_format)
                self.view.c1_time_utc_label.setText(label_text_utc)
                self.view.c1_time_local_label.setText(label_text_local)

            if self.model.c2_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.c2_info.time_utc, self.model.c2_info.time_local, time_format)
                self.view.c2_time_utc_label.setText(label_text_utc)
                self.view.c2_time_local_label.setText(label_text_local)

            if self.model.max_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.max_info.time_utc, self.model.max_info.time_local, time_format)
                self.view.max_time_utc_label.setText(label_text_utc)
                self.view.max_time_local_label.setText(label_text_local)

            if self.model.c3_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.c3_info.time_utc, self.model.c3_info.time_local, time_format)
                self.view.c3_time_utc_label.setText(label_text_utc)
                self.view.c3_time_local_label.setText(label_text_local)

            if self.model.c4_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.c4_info.time_utc, self.model.c4_info.time_local, time_format)
                self.view.c4_time_utc_label.setText(label_text_utc)
                self.view.c4_time_local_label.setText(label_text_local)

            if self.model.sunrise_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.sunrise_info.time_utc, self.model.sunrise_info.time_local, time_format)
                self.view.sunrise_time_utc_label.setText(label_text_utc)
                self.view.sunrise_time_local_label.setText(label_text_local)

            if self.model.sunset_info:
                label_text_utc, label_text_local = format_reference_moment_labels(
                    self.model.sunset_info.time_utc, self.model.sunset_info.time_local, time_format)
                self.view.sunset_time_utc_label.setText(label_text_utc)
                self.view.sunset_time_local_label.setText(label_text_local)

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
                reference_moments, magnitude, eclipse_type = self.model.get_reference_moments()
                self.view.show_reference_moments(reference_moments, magnitude, eclipse_type)

        elif text == "Camera(s)":
            self.update_camera_overview()
            self.sync_camera_time()
            self.check_camera_state()

        elif text == "Simulator":
            self.simulator_popup = SimulatorPopup(self)
            self.simulator_popup.show()

        elif text == "File":
            filename, _ = QFileDialog.getOpenFileName(None, "QFileDialog.getOpenFileName()", "",
                                                      "All Files (*);;Python Files (*.py);;Text Files (*.txt)")

            if self.model.reference_moments:
                from solareclipseworkbench.utils import observe_solar_eclipse
                self.scheduler: BackgroundScheduler = observe_solar_eclipse(self.model.reference_moments, filename,
                                                                            self.model.camera_overview, self,
                                                                            self.sim_reference_moment,
                                                                            self.sim_offset_minutes)

                self.jobs_model = JobsTableModel(self.scheduler, self)
                self.view.jobs_table.setModel(self.jobs_model)
                self.view.jobs_table.resizeColumnsToContents()
                self.view.jobs_table.setColumnWidth(4, 250)

        elif text == "Stop":
            try:
                if self.scheduler:
                    self.scheduler.shutdown()
                    self.jobs_model.clear_jobs_overview()
            except SchedulerNotRunningError:
                # Scheduler not running
                pass

        elif text == "Settings":
            self.settings_popup = SettingsPopup(self)
            self.settings_popup.show()

    def update_camera_overview(self):
        """ Update the camera overview in the model and the view."""

        camera_overview: dict = get_camera_dict()

        self.model.set_camera_overview(camera_overview)
        self.view.show_camera_overview(camera_overview)

    def sync_camera_time(self):
        """ Set the time of all connected cameras to the time of the computer."""

        self.model.sync_camera_time()

    def check_camera_state(self):
        """ Check whether the focus mode and shooting mode of all connected cameras is set to 'Manual'.

        For the camera(s) for which the focus mode and/or shooting mode is not set to 'Manual', a warning message is
        logged.
        """

        self.model.check_camera_state()


class LocationPopup(QWidget, Observable):
    def __init__(self, observer: SolarEclipseController):
        """ Initialisation of a pop-up window for setting the observing location.

        A pop-up window is shown, in which the user can choose the following information about the observing location:

            - Longitude [degrees];
            - Latitude [degrees];
            - Altitude [meters].

        When pressing the "Plot" button, this location will be displayed on a world map (as a red dot). When pressing
        the "OK" button, the given controller will be notified about this.

        If the location had already been set before, this will be shown in the text boxes.

        Args:
            - observer: SolarEclipseController that needs to be notified about the selection of a new location.
        """

        QWidget.__init__(self)
        self.setWindowTitle("Location")
        self.setGeometry(QRect(100, 100, 1000, 800))
        self.add_observer(observer)

        model = observer.model

        layout = QVBoxLayout()

        grid_layout = QGridLayout()
        grid_layout.addWidget(QLabel("Longitude [°]"), 0, 0)
        self.longitude = QLineEdit()
        longitude_validator = QDoubleValidator()
        longitude_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        longitude_validator.setRange(-180, 180, 5)
        self.longitude.setValidator(longitude_validator)
        self.longitude.setToolTip("Positive values: East of Greenwich meridian; "
                                  "Negative values: West of Greenwich meridian")
        if model.longitude:
            self.longitude.setText(str(model.longitude))
        grid_layout.addWidget(self.longitude, 0, 1)

        grid_layout.addWidget(QLabel("Latitude [°]"), 1, 0)
        self.latitude = QLineEdit()
        latitude_validator = QDoubleValidator()
        latitude_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        latitude_validator.setRange(-90, 90, 5)
        self.latitude.setValidator(latitude_validator)
        self.latitude.setToolTip("Positive values: Northern hemisphere; Negative values: Southern hemisphere")
        if model.latitude:
            self.latitude.setText(str(model.latitude))
        grid_layout.addWidget(self.latitude, 1, 1)

        grid_layout.addWidget(QLabel("Altitude [m]"), 2, 0)
        self.altitude = QLineEdit()
        altitude_validator = QDoubleValidator()
        altitude_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.altitude.setValidator(altitude_validator)
        grid_layout.addWidget(self.altitude, 2, 1)
        if model.altitude:
            self.altitude.setText(str(model.altitude))
        layout.addLayout(grid_layout)

        plot_button = QPushButton("Plot")
        plot_button.clicked.connect(self.plot_location)
        plot_button.setFixedWidth(100)
        layout.addWidget(plot_button)

        self.location_plot = LocationPlot()
        layout.addWidget(self.location_plot)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept_location)
        ok_button.setFixedWidth(100)
        layout.addWidget(ok_button)

        self.setLayout(layout)

    def plot_location(self):
        """ Plot the selected location on the world map.

        Check:
            - longitude specified
            - latitude specified
        """

        if self.longitude.text() and self.latitude.text():
            self.location_plot.plot_location(
                longitude=float(self.longitude.text()), latitude=float(self.latitude.text()))

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

        for eclipse_date in ECLIPSE_DATES:
            formatted_eclipse_date = datetime.datetime.strptime(eclipse_date, "%d/%m/%Y").strftime(date_format)
            formatted_eclipse_dates.append(formatted_eclipse_date)

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

        hbox1 = QHBoxLayout()
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
        self.reference_moment_combobox.addItems(REFERENCE_MOMENTS)

        if observer.sim_reference_moment:
            self.reference_moment_combobox.setCurrentText(observer.sim_reference_moment)

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
        """ Notify the observer about the specification of the starting time of the simulation and close the pop-up window.

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
        self.setWindowTitle("Settings")
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
        ok_button.clicked.connect(self.cancel_settings)
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
    """ Display the world with the selected location overplotted in red."""

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
        self.gdf = geopandas.GeoDataFrame(df, geometry=geopandas.points_from_xy(df.Longitude, df.Latitude), crs="EPSG:4326")
        self.gdf.plot(ax=self.ax, color="red")

        self.ax.set_aspect("equal")

        self.draw()
        self.location_is_drawn = True


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


class JobsTableColumnNames(Enum):
    """ Enumeration of the column names for the table with the scheduled jobs. """

    EXEC_TIME_UTC = "Execution time (UTC)"
    EXEC_TIME_LOCAL = "Execution time (local)"
    COUNTDOWN = "Countdown"
    COMMAND = "Command"
    DESCRIPTION = "Description"


class JobsTableModel(QAbstractTableModel):
    def __init__(self, scheduler: BackgroundScheduler, controller: SolarEclipseController):
        """ Initialisation of the model for the table with the scheduled jobs.

        Args:
            - scheduler: Background scheduler
            - model: Model for the Solar Eclipse Workbench UI
        """

        super().__init__()
        self.controller = controller
        self.time_format = self.controller.view.time_format

        tf = TimezoneFinder()
        timezone = pytz.timezone(tf.timezone_at(lng=self.controller.model.longitude, lat=self.controller.model.latitude))

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

                elif job.func.__name__ == "sync_cameras":
                    job_string = f"sync_cameras()"

                elif job.func.__name__ == "voice_prompt":
                    job_string = f"{job.func.__name__}({', '.join(job.args)})"

                self.execution_times_utc_as_datetime.append(execution_time_utc)
                suffix = ""
                if self.time_format == "12 hours":
                    suffix = " am" if execution_time_utc.hour < 12 else " pm"
                formatted_execution_time_utc = \
                    f"{datetime.datetime.strftime(execution_time_utc, TIME_FORMATS[self.time_format])}{suffix}"

                self.execution_times_local_as_datetime.append(execution_time_local)
                suffix = ""
                if self.time_format == "12 hours":
                    suffix = " am" if execution_time_local.hour < 12 else " pm"
                formatted_execution_time_local = \
                    f"{datetime.datetime.strftime(execution_time_local, TIME_FORMATS[self.time_format])}{suffix}"

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
                if new_countdown.total_seconds() > 0:
                    new_countdown = format_countdown(new_countdown)
                else:
                    new_countdown = "-"
                self._data.loc[row, JobsTableColumnNames.COUNTDOWN.value] = new_countdown

                if self.time_format != time_format:
                    suffix = ""
                    execution_time_utc = self.execution_times_utc_as_datetime[row]
                    if time_format == "12 hours":
                        suffix = " am" if execution_time_utc.hour < 12 else " pm"
                    self._data.loc[row, JobsTableColumnNames.EXEC_TIME_UTC.value] = \
                        f"{datetime.datetime.strftime(execution_time_utc, TIME_FORMATS[time_format])}{suffix}"

                    suffix = ""
                    execution_time_local = self.execution_times_local_as_datetime[row]
                    if time_format == "12 hours":
                        suffix = " am" if execution_time_local.hour < 12 else " pm"
                    self._data.loc[row, JobsTableColumnNames.EXEC_TIME_LOCAL.value] = \
                        f"{datetime.datetime.strftime(execution_time_local, TIME_FORMATS[time_format])}{suffix}"

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

                suffix = ""
                if self.time_format == "12 hours":
                    suffix = " am" if value.hour < 12 else " pm"
                return datetime.datetime.strftime(value, f"{TIME_FORMATS[self.controller.view.time_format]}{suffix}")

            return value

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() == 0:
                return Qt.AlignmentFlag.AlignRight
            elif index.column() <= 2:
                return Qt.AlignmentFlag.AlignHCenter
            else:
                return Qt.AlignmentFlag.AlignLeft


def format_reference_moment_labels(time_utc, time_local, time_format):
    """ Format text for the labels with the timing of the reference moments.

    Args:
        - time_utc: Time in UTC timezone
        - time_local: Time in local timezone
        - time_format: Time format (12/24 hours)

    Returns:
        - Formatted time in UTC timezone
        - Formatted time in local timezone
    """

    suffix = ""
    if time_format == "12 hours":
        suffix = " am" if time_utc.hour < 12 else " pm"

    if time_format == "12 hours":
        suffix = " am" if time_local.hour < 12 else " pm"

    return (f"{datetime.datetime.strftime(time_utc, TIME_FORMATS[time_format])}{suffix}",
            f"{datetime.datetime.strftime(time_local, TIME_FORMATS[time_format])}{suffix}")


def main():

    args = list(sys.argv)
    is_simulator = "--sim" in args or "--simulator" in args
    # args[1:1] = ["-stylesheet", str(styles_location)]
    app = QApplication(args)
    app.setWindowIcon(QIcon(str(ICON_PATH / "logo-small.svg")))
    app.setApplicationName("Solar Eclipse Workbench")

    model = SolarEclipseModel()
    view = SolarEclipseView(is_simulator=is_simulator)
    controller = SolarEclipseController(model, view, is_simulator=is_simulator)

    view.show()

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

    controller.update_camera_overview()
    controller.sync_camera_time()
    controller.check_camera_state()


if __name__ == "__main__":

    sys.exit(main())
