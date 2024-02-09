""" Solar Eclipse Workbench GUI, implemented according to the MVC pattern:

    - Model: SolarEclipseModel
    - View: SolarEclipseView
    - Controller: SolarEclipseController
"""
import datetime
import sys
from pathlib import Path

import geopandas
import pandas as pd
from PyQt6.QtCore import QTimer, QRect
from PyQt6.QtGui import QIcon, QAction, QDoubleValidator
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, QGridLayout, \
    QGroupBox, QComboBox, QPushButton, QLineEdit
from astropy.time import Time
from geodatasets import get_path
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from solareclipseworkbench.camera import get_camera_overview, set_time
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


class SolarEclipseModel:

    def __init__(self):

        # Location

        self.is_location_set = False
        self.longitude: float = None
        self.latitude: float = None
        self.altitude: float = None

        # Eclipse date

        self.is_eclipse_date_set = False
        self.eclipse_date:Time = None

        # Time

        self.local_time: datetime.datetime = None
        self.utc_time: datetime.datetime = None

        # Reference moments

        self.c1_info: ReferenceMomentInfo = None
        self.c2_info: ReferenceMomentInfo = None
        self.max_info: ReferenceMomentInfo = None
        self.c3_info: ReferenceMomentInfo = None
        self.c4_info: ReferenceMomentInfo = None
        self.sunrise_info: ReferenceMomentInfo = None
        self.sunset_info: ReferenceMomentInfo = None

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

        reference_moments, magnitude, eclipse_type = calculate_reference_moments(self.longitude, self.latitude,
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
            self.c1_info = reference_moments["C1"]
            self.c2_info = None
            self.max_info = reference_moments["MAX"]
            self.c3_info = None
            self.c4_info = reference_moments["C4"]

        # Total eclipse

        else:
            self.c1_info = reference_moments["C1"]
            self.c2_info = reference_moments["C2"]
            self.max_info = reference_moments["MAX"]
            self.c3_info = reference_moments["C3"]
            self.c4_info = reference_moments["C4"]

        self.sunrise_info = reference_moments["sunrise"]
        self.sunset_info = reference_moments["sunset"]

        return reference_moments, magnitude, eclipse_type

    def set_camera_overview(self, camera_overview: dict):

        self.camera_overview = camera_overview


class SolarEclipseView(QMainWindow, Observable):

    def __init__(self):

        super().__init__()

        self.controller = None

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
        self.c1_time_local_label = QLabel()
        self.c2_time_local_label = QLabel()
        self.max_time_local_label = QLabel()
        self.c3_time_local_label = QLabel()
        self.c4_time_local_label = QLabel()
        self.sunrise_time_local_label = QLabel()
        self.sunset_time_local_label = QLabel()
        self.c1_time_utc_label = QLabel()
        self.c2_time_utc_label = QLabel()
        self.max_time_utc_label = QLabel()
        self.c3_time_utc_label = QLabel()
        self.c4_time_utc_label = QLabel()
        self.sunrise_time_utc_label = QLabel()
        self.sunset_time_utc_label = QLabel()
        self.c1_countdown_label = QLabel()
        self.c2_countdown_label = QLabel()
        self.max_countdown_label = QLabel()
        self.c3_countdown_label = QLabel()
        self.c4_countdown_label = QLabel()
        self.sunrise_countdown_label = QLabel()
        self.sunset_countdown_label = QLabel()
        self.c1_azimuth_label = QLabel()
        self.c2_azimuth_label = QLabel()
        self.max_azimuth_label = QLabel()
        self.c3_azimuth_label = QLabel()
        self.c4_azimuth_label = QLabel()
        self.c1_altitude_label = QLabel()
        self.c2_altitude_label = QLabel()
        self.max_altitude_label = QLabel()
        self.c3_altitude_label = QLabel()
        self.c4_altitude_label = QLabel()

        self.date_label = QLabel(f"Date [{self.date_format}]")
        self.date_label_local = QLabel()
        self.time_label_local = QLabel()
        self.date_label_utc = QLabel()
        self.time_label_utc = QLabel()

        self.longitude_label = QLabel()
        self.longitude_label.setToolTip(
            "Positive values: East of Greenwich meridian; Negative values: West of Greenwich meridian")
        self.latitude_label = QLabel()
        self.latitude_label.setToolTip("Positive values: Northern hemisphere; Negative values: Southern hemisphere")
        self.altitude_label = QLabel()

        self.eclipse_type = QLabel()

        self.init_ui()

    def init_ui(self):

        app_frame = QFrame()
        app_frame.setObjectName("AppFrame")

        self.add_toolbar()

        vbox_left = QVBoxLayout()

        place_time_group_box = QGroupBox()
        place_time_grid_layout = QGridLayout()

        place_time_grid_layout.addWidget(QLabel("Local"), 0, 1)
        place_time_grid_layout.addWidget(QLabel("UTC"), 0, 2)

        place_time_grid_layout.addWidget(self.date_label, 1, 0)
        place_time_grid_layout.addWidget(self.date_label_local, 1, 1)
        place_time_grid_layout.addWidget(self.date_label_utc, 1, 2)

        place_time_grid_layout.addWidget(QLabel("Time"), 2, 0)
        place_time_grid_layout.addWidget(self.time_label_local, 2, 1)
        place_time_grid_layout.addWidget(self.time_label_utc, 2, 2)

        place_time_group_box.setLayout(place_time_grid_layout)
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
        vbox_left.addWidget(location_group_box)

        eclipse_date_group_box = QGroupBox()
        eclipse_date_grid_layout = QGridLayout()
        eclipse_date_grid_layout.addWidget(self.eclipse_date_label, 0, 0)
        eclipse_date_grid_layout.addWidget(self.eclipse_date, 0, 1)
        eclipse_date_grid_layout.addWidget(QLabel("Eclipse type"), 1, 0)
        eclipse_date_grid_layout.addWidget(self.eclipse_type, 1, 1)

        eclipse_date_group_box.setLayout(eclipse_date_grid_layout)
        vbox_left.addWidget(eclipse_date_group_box)

        reference_moments_group_box = QGroupBox()
        reference_moments_grid_layout = QGridLayout()
        reference_moments_grid_layout.addWidget(QLabel("Time (local)"), 0, 1)
        reference_moments_grid_layout.addWidget(self.c1_time_local_label, 1, 1)
        reference_moments_grid_layout.addWidget(self.c2_time_local_label, 2, 1)
        reference_moments_grid_layout.addWidget(self.max_time_local_label, 3, 1)
        reference_moments_grid_layout.addWidget(self.c3_time_local_label, 4, 1)
        reference_moments_grid_layout.addWidget(self.c4_time_local_label, 5, 1)
        reference_moments_grid_layout.addWidget(self.sunrise_time_local_label, 6, 1)
        reference_moments_grid_layout.addWidget(self.sunset_time_local_label, 7, 1)
        reference_moments_grid_layout.addWidget(QLabel("Time (UTC)"), 0, 2)
        reference_moments_grid_layout.addWidget(self.c1_time_utc_label, 1, 2)
        reference_moments_grid_layout.addWidget(self.c2_time_utc_label, 2, 2)
        reference_moments_grid_layout.addWidget(self.max_time_utc_label, 3, 2)
        reference_moments_grid_layout.addWidget(self.c3_time_utc_label, 4, 2)
        reference_moments_grid_layout.addWidget(self.c4_time_utc_label, 5, 2)
        reference_moments_grid_layout.addWidget(self.sunrise_time_utc_label, 6, 2)
        reference_moments_grid_layout.addWidget(self.sunset_time_utc_label, 7, 2)
        reference_moments_grid_layout.addWidget(QLabel("Countdown"), 0, 3)
        reference_moments_grid_layout.addWidget(self.c1_countdown_label, 1, 3)
        reference_moments_grid_layout.addWidget(self.c2_countdown_label, 2, 3)
        reference_moments_grid_layout.addWidget(self.max_countdown_label, 3, 3)
        reference_moments_grid_layout.addWidget(self.c3_countdown_label, 4, 3)
        reference_moments_grid_layout.addWidget(self.c4_countdown_label, 5, 3)
        reference_moments_grid_layout.addWidget(self.sunrise_countdown_label, 6, 3)
        reference_moments_grid_layout.addWidget(self.sunset_countdown_label, 7, 3)
        reference_moments_grid_layout.addWidget(QLabel("Azimuth [°]"), 0, 4)
        reference_moments_grid_layout.addWidget(self.c1_azimuth_label, 1, 4)
        reference_moments_grid_layout.addWidget(self.c2_azimuth_label, 2, 4)
        reference_moments_grid_layout.addWidget(self.max_azimuth_label, 3, 4)
        reference_moments_grid_layout.addWidget(self.c3_azimuth_label, 4, 4)
        reference_moments_grid_layout.addWidget(self.c4_azimuth_label, 5, 4)
        reference_moments_grid_layout.addWidget(QLabel("Altitude [°]"), 0, 5)
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

        camera_overview_group_box = QGroupBox()
        # camera_overview_grid_layout.addWidget(QLabel("No camera connected/detected yet \nPress the camera icon in the toolbox to update"))
        self.camera_overview_grid_layout.addWidget(QLabel("Camera"), 0, 0)
        self.camera_overview_grid_layout.addWidget(QLabel("Battery level [%]"), 0, 1)
        self.camera_overview_grid_layout.addWidget(QLabel("Free memory [GB]"), 0, 2)
        self.camera_overview_grid_layout.addWidget(QLabel("Free memory [%]"), 0, 3)
        camera_overview_group_box.setLayout(self.camera_overview_grid_layout)

        hbox = QHBoxLayout()
        hbox.addLayout(vbox_left)
        hbox.addWidget(reference_moments_group_box)
        hbox.addWidget(camera_overview_group_box)

        app_frame.setLayout(hbox)

        self.setCentralWidget(app_frame)

    def add_toolbar(self):

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
            self.eclipse_type.setText(eclipse_type + " eclipse")

        suffix = ""

        # First contact

        if "C1" in reference_moments:
            c1_info: ReferenceMomentInfo = reference_moments["C1"]
            if self.time_format == "12 hours":
                suffix = " am" if c1_info.time_utc.hour < 12 else " pm"
            self.c1_time_utc_label.setText(f"{datetime.datetime.strftime(c1_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
            if self.time_format == "12 hours":
                suffix = " am" if c1_info.time_local.hour < 12 else " pm"
            self.c1_time_local_label.setText(
                f"{datetime.datetime.strftime(c1_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")
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
            if self.time_format == "12 hours":
                suffix = " am" if c2_info.time_utc.hour < 12 else " pm"
            self.c2_time_utc_label.setText(
                f"{datetime.datetime.strftime(c2_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
            if self.time_format == "12 hours":
                suffix = " am" if c2_info.time_local.hour < 12 else " pm"
            self.c2_time_local_label.setText(
                f"{datetime.datetime.strftime(c2_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")
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
            if self.time_format == "12 hours":
                suffix = " am" if max_info.time_utc.hour < 12 else " pm"
            self.max_time_utc_label.setText(
                f"{datetime.datetime.strftime(max_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
            if self.time_format == "12 hours":
                suffix = " am" if max_info.time_local.hour < 12 else " pm"
            self.max_time_local_label.setText(
                f"{datetime.datetime.strftime(max_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")
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
            if self.time_format == "12 hours":
                suffix = " am" if c3_info.time_utc.hour < 12 else " pm"
            self.c3_time_utc_label.setText(f"{datetime.datetime.strftime(c3_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
            if self.time_format == "12 hours":
                suffix = " am" if c3_info.time_local.hour < 12 else " pm"
            self.c3_time_local_label.setText(
                f"{datetime.datetime.strftime(c3_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")
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
            if self.time_format == "12 hours":
                suffix = " am" if c4_info.time_utc.hour < 12 else " pm"
            self.c4_time_utc_label.setText(
                f"{datetime.datetime.strftime(c4_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
            if self.time_format == "12 hours":
                suffix = " am" if c4_info.time_local.hour < 12 else " pm"
            self.c4_time_local_label.setText(
                f"{datetime.datetime.strftime(c4_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")
            self.c4_azimuth_label.setText(str(int(c4_info.azimuth)))
            self.c4_altitude_label.setText(str(int(c4_info.altitude)))
        else:
            self.c4_time_utc_label.setText("")
            self.c4_time_local_label.setText("")
            self.c4_azimuth_label.setText("")
            self.c4_altitude_label.setText("")

        # Sunrise

        sunrise_info: ReferenceMomentInfo = reference_moments["sunrise"]
        if self.time_format == "12 hours":
            suffix = " am" if sunrise_info.time_utc.hour < 12 else " pm"
        self.sunrise_time_utc_label.setText(
            f"{datetime.datetime.strftime(sunrise_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
        if self.time_format == "12 hours":
            suffix = " am" if sunrise_info.time_local.hour < 12 else " pm"
        self.sunrise_time_local_label.setText(
            f"{datetime.datetime.strftime(sunrise_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")

        # Sunset

        sunset_info: ReferenceMomentInfo = reference_moments["sunset"]
        if self.time_format == "12 hours":
            suffix = " am" if sunset_info.time_utc.hour < 12 else " pm"
        self.sunset_time_utc_label.setText(
            f"{datetime.datetime.strftime(sunset_info.time_utc, TIME_FORMATS[self.time_format])}{suffix}")
        if self.time_format == "12 hours":
            suffix = " am" if sunset_info.time_local.hour < 12 else " pm"
        self.sunset_time_local_label.setText(
            f"{datetime.datetime.strftime(sunset_info.time_local, TIME_FORMATS[self.time_format])}{suffix}")

    def show_camera_overview(self, camera_overview: dict):
        raise NotImplementedError


        Args:
            - camera_overview: Dictionary with an overview of the connected cameras
        """
        raise NotImplementedError


class SolarEclipseController(Observer):

    def __init__(self, model: SolarEclipseModel, view: SolarEclipseView):

        self.model = model

        self.view = view
        self.view.add_observer(self)

        self.location_popup: LocationPopup = None
        self.eclipse_popup: EclipsePopup = None
        self.camera_popup: CameraPopup = None
        self.settings_popup: SettingsPopup = None

        self.time_display_timer = QTimer()
        self.time_display_timer.timeout.connect(self.update_time)
        self.time_display_timer.setInterval(1000)
        self.time_display_timer.start()

    def update_time(self):

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

    def do(self, actions):
        pass

    def update(self, changed_object):

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

        elif isinstance(changed_object, CameraPopup):
            camera_overview = changed_object.camera_overview
            self.model.set_camera_overview(camera_overview)
            return

        elif isinstance(changed_object, SettingsPopup):
            date_format = changed_object.date_combobox.currentText()
            self.view.date_format = date_format
            if self.model.eclipse_date:
                self.view.eclipse_date.setText(self.model.eclipse_date.strftime(DATE_FORMATS[date_format]))

            time_format = changed_object.time_combobox.currentText()
            self.view.time_format = time_format

            if self.model.c1_info:
                c1_time_utc = self.model.c1_info.time_utc
                c1_time_local = self.model.c1_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if c1_time_utc.hour < 12 else " pm"
                self.view.c1_time_utc_label.setText(
                    f"{datetime.datetime.strftime(c1_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c1_time_local.hour < 12 else " pm"
                self.view.c1_time_local_label.setText(
                    f"{datetime.datetime.strftime(c1_time_local, TIME_FORMATS[time_format])}{suffix}")

            if self.model.c2_info:
                c2_time_utc = self.model.c2_info.time_utc
                c2_time_local = self.model.c2_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if c2_time_utc.hour < 12 else " pm"
                self.view.c2_time_utc_label.setText(
                    f"{datetime.datetime.strftime(c2_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c2_time_local.hour < 12 else " pm"
                self.view.c2_time_local_label.setText(
                    f"{datetime.datetime.strftime(c2_time_local, TIME_FORMATS[time_format])}{suffix}")

            if self.model.max_info:
                max_time_utc = self.model.max_info.time_utc
                max_time_local = self.model.max_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if max_time_utc.hour < 12 else " pm"
                self.view.max_time_utc_label.setText(
                    f"{datetime.datetime.strftime(max_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c1_time_local.hour < 12 else " pm"
                self.view.max_time_local_label.setText(
                    f"{datetime.datetime.strftime(max_time_local, TIME_FORMATS[time_format])}{suffix}")

            if self.model.c3_info:
                c3_time_utc = self.model.c3_info.time_utc
                c3_time_local = self.model.c3_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if c3_time_utc.hour < 12 else " pm"
                self.view.c3_time_utc_label.setText(
                    f"{datetime.datetime.strftime(c3_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c1_time_local.hour < 12 else " pm"
                self.view.c3_time_local_label.setText(
                    f"{datetime.datetime.strftime(c3_time_local, TIME_FORMATS[time_format])}{suffix}")

            if self.model.c4_info:
                c4_time_utc = self.model.c4_info.time_utc
                c4_time_local = self.model.c4_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if c4_time_utc.hour < 12 else " pm"
                self.view.c4_time_utc_label.setText(
                    f"{datetime.datetime.strftime(c4_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c1_time_local.hour < 12 else " pm"
                self.view.c4_time_local_label.setText(
                    f"{datetime.datetime.strftime(c4_time_local, TIME_FORMATS[time_format])}{suffix}")

            if self.model.sunrise_info:
                sunrise_time_utc = self.model.sunrise_info.time_utc
                sunrise_time_local = self.model.sunrise_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if sunrise_time_utc.hour < 12 else " pm"
                self.view.sunrise_time_utc_label.setText(
                    f"{datetime.datetime.strftime(sunrise_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c1_time_local.hour < 12 else " pm"
                self.view.sunrise_time_local_label.setText(
                    f"{datetime.datetime.strftime(sunrise_time_local, TIME_FORMATS[time_format])}{suffix}")

            if self.model.sunset_info:
                sunset_time_utc = self.model.sunset_info.time_utc
                sunset_time_local = self.model.sunset_info.time_local
                suffix = ""
                if time_format == "12 hours":
                    suffix = " am" if sunset_time_utc.hour < 12 else " pm"
                self.view.sunset_time_utc_label.setText(
                    f"{datetime.datetime.strftime(sunset_time_utc, TIME_FORMATS[time_format])}{suffix}")
                if time_format == "12 hours":
                    suffix = " am" if c1_time_local.hour < 12 else " pm"
                self.view.sunset_time_local_label.setText(
                    f"{datetime.datetime.strftime(sunset_time_local, TIME_FORMATS[time_format])}{suffix}")

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
            # TODO
            print("Camera(s)")
            self.camera_popup = CameraPopup(self)
            self.camera_popup.show()

        elif text == "Settings":
            self.settings_popup = SettingsPopup(self)
            self.settings_popup.show()


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
        latitude_validator.setRange(-90, 90, 5)
        self.latitude.setValidator(latitude_validator)
        self.latitude.setToolTip("Positive values: Northern hemisphere; Negative values: Southern hemisphere")
        if model.latitude:
            self.latitude.setText(str(model.latitude))
        grid_layout.addWidget(self.latitude, 1, 1)

        grid_layout.addWidget(QLabel("Altitude [m]"), 2, 0)
        self.altitude = QLineEdit()
        altitude_validator = QDoubleValidator()
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
        """ Plot the selected location on the world map."""

        self.location_plot.plot_location(longitude=float(self.longitude.text()), latitude=float(self.latitude.text()))

    def accept_location(self):
        """ Notify the observer about the selection of a new location and close the pop-up window."""

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


class CameraPopup(QWidget, Observable):

    def __init__(self, observer: SolarEclipseController):
        QWidget.__init__(self)
        self.setWindowTitle("Camera(s)")
        self.setGeometry(QRect(100, 100, 300, 75))
        self.add_observer(observer)

        self.camera_overview = get_camera_overview()

        layout = QHBoxLayout()

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_camera_overview)

        sync_button = QPushButton("Synchronise")
        sync_button.clicked.connect(self.sync)

        ok_button = QPushButton("OK")
        sync_button.clicked.connect(self.close)

        layout.addWidget(refresh_button)
        layout.addWidget(sync_button)
        layout.addWidget(ok_button)

        self.setLayout(layout)

    def refresh_camera_overview(self):
        print("Refresh camera overview")

        self.camera_overview: dict = get_camera_overview()
        self.notify_observers(self)

        self.close()

    def sync(self):
        print("Sync camera overview")
        # TODO model -> sync_camera_time
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


def main():

    args = list(sys.argv)
    # args[1:1] = ["-stylesheet", str(styles_location)]
    app = QApplication(args)
    app.setWindowIcon(QIcon(str(ICON_PATH / "logo-small.svg")))
    app.setApplicationName("Solar Eclipse Workbench")

    model = SolarEclipseModel()
    view = SolarEclipseView()
    controller = SolarEclipseController(model, view)

    view.show()

    return app.exec()


if __name__ == "__main__":

    sys.exit(main())
