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

import numpy as np
import pandas as pd
import pytz
from PyQt6.QtCore import (QTimer, QRect, Qt, QAbstractTableModel, QModelIndex,
                         QSettings, QSignalBlocker, pyqtSignal)
from PyQt6.QtGui import QIcon, QAction, QIntValidator, QCloseEvent, QPixmap, QImage, QPainter, QPen, QColor, \
    QFontMetrics
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, \
QGridLayout, QGroupBox, QComboBox, QPushButton, QLineEdit, QFileDialog, QScrollArea, QSlider, QTableView, \
QMessageBox, QDialog, QPlainTextEdit, QProgressBar, QToolButton, QSplitter, QCheckBox, QSizePolicy, QStyle, \
QDoubleSpinBox
from PyQt6 import QtWidgets
from apscheduler.job import Job
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from astropy.time import Time
from gphoto2 import GPhoto2Error, Camera
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from skyfield.api import load, wgs84

import threading

from solareclipseworkbench.camera import get_camera_dict, get_battery_level, get_free_space, get_space, \
    get_shooting_mode, get_focus_mode, set_time, CameraSettings, LiveViewThread, \
    get_sony_save_destination, get_sony_image_quality, CameraKeepAliveThread, get_auto_power_off, \
    MIN_AUTO_POWER_OFF_S, get_live_view_sizes, set_live_view_size, get_exposure_compensation, \
    set_exposure_compensation, compensated_shutter_speed, EXPOSURE_COMPENSATION_STEP_EV, \
    MAX_EXPOSURE_COMPENSATION_EV
from solareclipseworkbench import hardware_problems
from solareclipseworkbench.limb_ui import BeadsPanel, beads_icon
from solareclipseworkbench.logging_setup import setup_logging, file_handlers_only, camera_log
from solareclipseworkbench.limb_correction import (is_enabled as limb_correction_is_enabled,
                                                   set_enabled as set_limb_correction_enabled,
                                                   ensure_limb_profile)
from solareclipseworkbench.observer import Observer, Observable
from solareclipseworkbench.qt_utils import apply_system_color_scheme
from solareclipseworkbench.reference_moments import calculate_reference_moments, ReferenceMomentInfo
from solareclipseworkbench.location_ui import ConfigManager, LocationWidget, SiteMapWidget
from solareclipseworkbench.path_map_ui import EclipsePathWidget, eclipse_choices
from solareclipseworkbench.constants import MOON_RADIUS
from solareclipseworkbench import solar_radius
from solareclipseworkbench import configuration

ICON_PATH = Path(__file__).parent.resolve() / "img"

TIME_FORMATS = {
    "24 hours": "%H:%M:%S.%f",
    "12 hours": "%I:%M:%S.%f"
}

LIMB_CORRECTION_TOOLTIP = (
    "Use the Moon's topography to apply the Maestro-style contact-point "
    "correction to C2/C3. A separate whole-arc photographic capture window "
    "is available when the configured illuminated-arc criterion can be solved."
)
SOLAR_RADIUS_TOOLTIP = (
    'The solar radius sets the duration of totality: a larger Sun shortens it, by about '
    '1 s per 100 s for the 0.32" between the two values, and more near the path limits.\n'
    '959.95" (default): Quaglia et al. 2021, measured from eclipse contacts, which is '
    'what contact times need.\n'
    '959.63": Auwers 1891, the convention of published predictions (Espenak, '
    'Solar Eclipse Maestro, eclipse-chaser-log); choose it to compare with those.'
)
SOLAR_RADIUS_LOCKED_TOOLTIP = (
    "The solar radius cannot be changed while a script has pending jobs. "
    "Stop the scheduler first, then change the radius and reload the script."
)
LIMB_CORRECTION_LOCKED_TOOLTIP = (
    "The lunar limb correction cannot be changed while a script has pending "
    "jobs. Stop the scheduler first, then change the correction and reload the script."
)

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

SAVE_MESSAGE_TIMEOUT = 10000  # How long the outcome of `Save` stays in the status bar [ms]

LOGGER = logging.getLogger("Solar Eclipse Workbench UI")


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

        # Set when the user closes the banner, so that automatic refreshes (e.g. a scheduled `sync_cameras`)
        # do not bring it back.  Only a refresh requested by the user (the `Camera(s)` button) clears it.
        self.dismissed = False

        # Explicitly hide the root frame (self) when clicked
        self.close_btn.clicked.connect(self.dismiss)

        layout.addWidget(self.label, 1)
        layout.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)

    def setText(self, text: str):
        self.label.setText(text)

    def dismiss(self):
        """ Hide the banner and remember that the user closed it. """
        self.dismissed = True
        self.hide()

    def show_message(self, text: str, user_requested: bool = False):
        """ Show the given text, unless the user already closed the banner while it showed this same text.

        Args:
            - text: Text to show.  An empty text hides the banner.
            - user_requested: Whether the user asked to see the camera state again (`Camera(s)` button), which
                              also brings back a closed banner.
        """
        if not text:
            self.setVisible(False)
            return
        if user_requested or text != self.label.text():
            self.dismissed = False
        self.setText(text)
        self.setVisible(not self.dismissed)


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
            camera_log(camera_name).info("syncing time")
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

            # Auto power off: once asleep, the camera cannot be woken over USB

            try:
                auto_power_off = get_auto_power_off(camera)
                if auto_power_off is not None:
                    label, value, delay_s = auto_power_off
                    if delay_s is not None and delay_s < MIN_AUTO_POWER_OFF_S:
                        msg = (f"{label} for {camera_name} is set to '{value}'.\n"
                               f"Disable it, or set it to at least {int(MIN_AUTO_POWER_OFF_S // 60)} minutes, "
                               f"so the camera does not fall asleep before the eclipse.")
                        LOGGER.warning(msg)
                        warnings.append(msg)
            except Exception:
                LOGGER.debug("Could not read auto power off for %s", camera_name, exc_info=True)

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
        self.beads_action = QAction("Baily's beads", self)
        self.timeline_action = QAction("Timeline", self)
        self.run_report_action = QAction("Run report", self)
        self.compare_sites_action = QAction("Compare sites", self)

        self.place_time_frame = QFrame()

        self.eclipse_date_widget = QWidget()
        self.eclipse_date_label = QLabel(f"Eclipse date [{self.date_format}]")
        self.eclipse_date = QLabel("")

        self.reference_moments_widget = QWidget()

        # A contact burst is aimed at the bead window rather than at the contact,
        # so the window is worth reading directly.
        self.beads_c2_label = QLabel()
        self.beads_c2_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.beads_c3_label = QLabel()
        self.beads_c3_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.limb_correction_checkbox = QCheckBox(
            "Apply the lunar limb correction to the contact times")
        # The controller replaces this with whatever was remembered.
        self.limb_correction_checkbox.setChecked(True)
        self.limb_correction_checkbox.setToolTip(LIMB_CORRECTION_TOOLTIP)

        # The controller selects whatever was remembered
        self.solar_radius_combo = QComboBox()
        for key, (value, description) in solar_radius.PRESETS.items():
            self.solar_radius_combo.addItem(f'{value:.2f}"  {description}', key)
        self.solar_radius_combo.addItem("Custom value", "custom")
        self.solar_radius_combo.setToolTip(SOLAR_RADIUS_TOOLTIP)
        self.solar_radius_spinbox = QDoubleSpinBox()
        self.solar_radius_spinbox.setRange(solar_radius.MIN_ARCSEC, solar_radius.MAX_ARCSEC)
        self.solar_radius_spinbox.setDecimals(2)
        self.solar_radius_spinbox.setSingleStep(0.01)
        self.solar_radius_spinbox.setSuffix('"')
        # Recompute when the value is entered, not on every keystroke
        self.solar_radius_spinbox.setKeyboardTracking(False)
        self.solar_radius_spinbox.setValue(solar_radius.DEFAULT_ARCSEC)
        self.solar_radius_spinbox.setEnabled(False)
        self.solar_radius_spinbox.setToolTip(SOLAR_RADIUS_TOOLTIP)

        self.c1_time_local_label = QLabel()
        self.c1_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c2_time_local_label = QLabel()
        self.c2_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.max_time_local_label = QLabel()
        self.max_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c3_time_local_label = QLabel()
        self.c3_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c4_time_local_label = QLabel()
        self.c4_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sunrise_time_local_label = QLabel()
        self.sunrise_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sunset_time_local_label = QLabel()
        self.sunset_time_local_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c1_time_utc_label = QLabel()
        self.c1_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c2_time_utc_label = QLabel()
        self.c2_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.max_time_utc_label = QLabel()
        self.max_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c3_time_utc_label = QLabel()
        self.c3_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c4_time_utc_label = QLabel()
        self.c4_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sunrise_time_utc_label = QLabel()
        self.sunrise_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sunset_time_utc_label = QLabel()
        self.sunset_time_utc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c1_countdown_label = QLabel()
        self.c1_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c2_countdown_label = QLabel()
        self.c2_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.max_countdown_label = QLabel()
        self.max_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c3_countdown_label = QLabel()
        self.c3_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c4_countdown_label = QLabel()
        self.c4_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sunrise_countdown_label = QLabel()
        self.sunrise_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sunset_countdown_label = QLabel()
        self.sunset_countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c1_azimuth_label = QLabel()
        self.c1_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c2_azimuth_label = QLabel()
        self.c2_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.max_azimuth_label = QLabel()
        self.max_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c3_azimuth_label = QLabel()
        self.c3_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c4_azimuth_label = QLabel()
        self.c4_azimuth_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c1_altitude_label = QLabel()
        self.c1_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c2_altitude_label = QLabel()
        self.c2_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.max_altitude_label = QLabel()
        self.max_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c3_altitude_label = QLabel()
        self.c3_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.c4_altitude_label = QLabel()
        self.c4_altitude_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.date_label = QLabel(f"Date [{self.date_format}]")
        self.date_label_local = QLabel()
        self.date_label_local.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time_label_local = QLabel()
        self.time_label_local.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time_label_local.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.date_label_utc = QLabel()
        self.date_label_utc.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time_label_utc = QLabel()
        self.time_label_utc.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

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

        # Exposure compensation for all following shots (clouds, haze, dust)
        self.exposure_darker_button = QPushButton(f"\u2212{EXPOSURE_COMPENSATION_STEP_EV} EV")
        self.exposure_darker_button.setToolTip(
            f"Take all following pictures {EXPOSURE_COMPENSATION_STEP_EV} stop darker (shorter shutter speed)")
        self.exposure_brighter_button = QPushButton(f"+{EXPOSURE_COMPENSATION_STEP_EV} EV")
        self.exposure_brighter_button.setToolTip(
            f"Take all following pictures {EXPOSURE_COMPENSATION_STEP_EV} stop brighter (longer shutter speed), "
            f"e.g. for clouds or dust")
        self.exposure_reset_button = QPushButton("Reset exposure")
        self.exposure_reset_button.setToolTip("Take all following pictures with the exposure from the script")
        self.exposure_compensation_label = QLabel()
        self.show_exposure_compensation(get_exposure_compensation())

        # Banner with camera settings to check (hidden by default; shown for Sony and Nikon cameras)
        self.camera_banner = BannerNotification()
        self.camera_banner.setVisible(False)

        self.init_ui()

    def save_settings(self):
        """ Save the settings.

        The settings that are saved are:

            - Longitude [degrees];
            - Latitude [degrees];
            - Altitude [m];
            - Eclipse date;
            - Date format;
            - Time format;
            - Position of the splitter between the eclipse plot and the jobs table.

        The outcome is shown in the status bar and logged (Issue #181).

        Returns: True if the settings were written to disk, False otherwise.
        """

        # Location

        longitude = self.longitude_label.text()
        latitude = self.latitude_label.text()
        altitude = self.altitude_label.text()

        missing = [name for name, value in (("longitude", longitude), ("latitude", latitude),
                                            ("altitude", altitude)) if not value]
        if not missing:
            self.settings.setValue("longitude", float(longitude))
            self.settings.setValue("latitude", float(latitude))
            self.settings.setValue("altitude", float(altitude))

        # Eclipse date

        self.settings.setValue("eclipse_date", self.eclipse_date.text())

        # Date & time format

        self.settings.setValue("date_format", self.date_format)
        self.settings.setValue("time_format", self.time_format)

        # Layout

        self.save_layout_settings()

        # Write to disk now, so a failure can be reported

        self.settings.sync()
        filename = self.settings.fileName()

        if self.settings.status() != QSettings.Status.NoError:
            message = f"Could not save the settings to {filename}"
            LOGGER.error(message)
            self.statusBar().showMessage(message, SAVE_MESSAGE_TIMEOUT)
            return False

        if missing:
            message = (f"Settings saved to {filename}, without the location "
                       f"({', '.join(missing)} not set)")
            LOGGER.warning(message)
        else:
            message = f"Settings saved to {filename}"
            LOGGER.info(message)
        self.statusBar().showMessage(message, SAVE_MESSAGE_TIMEOUT)
        return True

    def save_layout_settings(self):
        """ Save the position of the splitter between the eclipse plot and the jobs table. """

        settings = getattr(self, "settings", None)
        if settings is not None:
            settings.setValue("output_splitter_state", self.output_splitter.saveState())

    def restore_layout_settings(self):
        """ Restore the position of the splitter between the eclipse plot and the jobs table. """

        settings = getattr(self, "settings", None)
        if settings is None:
            return
        state = settings.value("output_splitter_state", None)
        if state is not None:
            self.output_splitter.restoreState(state)

    def init_ui(self):
        """ Add all components to the UI. """

        app_frame = QFrame()
        app_frame.setObjectName("AppFrame")

        self.add_toolbar()

        vbox_left = QVBoxLayout()

        place_time_group_box = QGroupBox()
        place_time_grid_layout = QGridLayout()

        place_time_grid_layout.addWidget(QLabel("Local", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 1)
        place_time_grid_layout.addWidget(QLabel("UTC", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 2)

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
        reference_moments_grid_layout.addWidget(QLabel("Time (local)", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 1)
        reference_moments_grid_layout.addWidget(self.c1_time_local_label, 1, 1)
        reference_moments_grid_layout.addWidget(self.c2_time_local_label, 2, 1)
        reference_moments_grid_layout.addWidget(self.max_time_local_label, 3, 1)
        reference_moments_grid_layout.addWidget(self.c3_time_local_label, 4, 1)
        reference_moments_grid_layout.addWidget(self.c4_time_local_label, 5, 1)
        reference_moments_grid_layout.addWidget(self.sunrise_time_local_label, 6, 1)
        reference_moments_grid_layout.addWidget(self.sunset_time_local_label, 7, 1)
        reference_moments_grid_layout.addWidget(QLabel("Time (UTC)", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 2)
        reference_moments_grid_layout.addWidget(self.c1_time_utc_label, 1, 2)
        reference_moments_grid_layout.addWidget(self.c2_time_utc_label, 2, 2)
        reference_moments_grid_layout.addWidget(self.max_time_utc_label, 3, 2)
        reference_moments_grid_layout.addWidget(self.c3_time_utc_label, 4, 2)
        reference_moments_grid_layout.addWidget(self.c4_time_utc_label, 5, 2)
        reference_moments_grid_layout.addWidget(self.sunrise_time_utc_label, 6, 2)
        reference_moments_grid_layout.addWidget(self.sunset_time_utc_label, 7, 2)
        reference_moments_grid_layout.addWidget(QLabel("Countdown", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 3)
        reference_moments_grid_layout.addWidget(self.c1_countdown_label, 1, 3)
        reference_moments_grid_layout.addWidget(self.c2_countdown_label, 2, 3)
        reference_moments_grid_layout.addWidget(self.max_countdown_label, 3, 3)
        reference_moments_grid_layout.addWidget(self.c3_countdown_label, 4, 3)
        reference_moments_grid_layout.addWidget(self.c4_countdown_label, 5, 3)
        reference_moments_grid_layout.addWidget(self.sunrise_countdown_label, 6, 3)
        reference_moments_grid_layout.addWidget(self.sunset_countdown_label, 7, 3)
        reference_moments_grid_layout.addWidget(QLabel("Azimuth [°]", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 4)
        reference_moments_grid_layout.addWidget(self.c1_azimuth_label, 1, 4)
        reference_moments_grid_layout.addWidget(self.c2_azimuth_label, 2, 4)
        reference_moments_grid_layout.addWidget(self.max_azimuth_label, 3, 4)
        reference_moments_grid_layout.addWidget(self.c3_azimuth_label, 4, 4)
        reference_moments_grid_layout.addWidget(self.c4_azimuth_label, 5, 4)
        reference_moments_grid_layout.addWidget(QLabel("Altitude [°]", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), 0, 5)
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
        # The bead window spans all value columns: over the two time columns
        # alone it is wider than they are, and widens them at the expense of the
        # row titles
        reference_moments_grid_layout.addWidget(QLabel("Baily's beads (C2)"), 8, 0)
        reference_moments_grid_layout.addWidget(self.beads_c2_label, 8, 1, 1, 5)
        reference_moments_grid_layout.addWidget(QLabel("Baily's beads (C3)"), 9, 0)
        reference_moments_grid_layout.addWidget(self.beads_c3_label, 9, 1, 1, 5)
        # The switch sits with the times it changes: turning it off moves C2 and
        # C3 by seconds, which is more than a bead burst is long.
        reference_moments_grid_layout.addWidget(self.limb_correction_checkbox, 10, 0, 1, 6)
        # Like the limb correction, it changes C2 and C3 (by up to about half a second)
        solar_radius_label = QLabel("Solar radius")
        solar_radius_label.setToolTip(SOLAR_RADIUS_TOOLTIP)
        reference_moments_grid_layout.addWidget(solar_radius_label, 11, 0)
        reference_moments_grid_layout.addWidget(self.solar_radius_combo, 11, 1, 1, 4)
        reference_moments_grid_layout.addWidget(self.solar_radius_spinbox, 11, 5)
        reference_moments_group_box.setLayout(reference_moments_grid_layout)
        # At least 600 pixels, but wider when a larger font needs it, so the row
        # titles are never cut off.  The countdown column is sized for its widest
        # value, so the box does not change width while counting down.
        countdown_width = QFontMetrics(self.c1_countdown_label.font()).horizontalAdvance("000d 00:00:00")
        for countdown_label in (self.c1_countdown_label, self.c2_countdown_label, self.max_countdown_label,
                                self.c3_countdown_label, self.c4_countdown_label, self.sunrise_countdown_label,
                                self.sunset_countdown_label):
            countdown_label.setMinimumWidth(countdown_width)
        reference_moments_group_box.setMinimumWidth(600)
        reference_moments_group_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        # noinspection SpellCheckingInspection
        input_hbox = QHBoxLayout()
        input_hbox.addLayout(vbox_left)
        input_hbox.addWidget(reference_moments_group_box)

        self.camera_overview.setFixedHeight(300)
        input_hbox.addWidget(self.camera_overview)

        # Plot and jobs table share a user-resizable splitter, so the plot can be shrunk to give the scheduler
        # more room (e.g. on widescreen displays).  Neither side can be collapsed completely.
        self.output_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.output_splitter.addWidget(self.eclipse_visualization)
        # The exposure compensation sits right above the jobs it changes
        exposure_hbox = QHBoxLayout()
        exposure_hbox.setContentsMargins(0, 0, 0, 0)
        exposure_hbox.addWidget(QLabel("Exposure of all following shots:"))
        exposure_hbox.addWidget(self.exposure_darker_button)
        exposure_hbox.addWidget(self.exposure_compensation_label)
        exposure_hbox.addWidget(self.exposure_brighter_button)
        exposure_hbox.addWidget(self.exposure_reset_button)
        exposure_hbox.addStretch(1)
        for button in (self.exposure_darker_button, self.exposure_brighter_button, self.exposure_reset_button):
            button.clicked.connect(self.on_toolbar_button_click)
        jobs_vbox = QVBoxLayout()
        jobs_vbox.setContentsMargins(0, 0, 0, 0)
        jobs_vbox.addLayout(exposure_hbox)
        jobs_vbox.addWidget(self.jobs_table, 1)
        jobs_widget = QWidget()
        jobs_widget.setLayout(jobs_vbox)
        self.output_splitter.addWidget(jobs_widget)
        self.output_splitter.setChildrenCollapsible(False)
        self.output_splitter.setStretchFactor(0, 1)
        self.output_splitter.setStretchFactor(1, 2)

        global_layout = QVBoxLayout()
        # show reminder banner at top
        global_layout.addWidget(self.camera_banner)
        global_layout.addLayout(input_hbox)

        global_layout.addWidget(self.output_splitter, 1)

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
        self.live_view_action.setIcon(QIcon(str(ICON_PATH / "live.png")))
        self.live_view_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.live_view_action)

        # Baily's beads

        self.beads_action.setStatusTip("Show the Baily's beads at second and third contact for this location")
        self.beads_action.setIcon(beads_icon(32))
        self.beads_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.beads_action)

        # Script timeline

        self.timeline_action.setStatusTip("Show the script per camera: which commands start late or are dropped")
        self.timeline_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView))
        self.timeline_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.timeline_action)

        # Run report

        self.run_report_action.setStatusTip("Show what became of every command of a run, from its log file")
        self.run_report_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.run_report_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.run_report_action)

        # Compare candidate sites

        self.compare_sites_action.setStatusTip("Compare candidate sites: totality, Sun altitude, Baily's beads "
                                               "and cloud forecast side by side")
        self.compare_sites_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        self.compare_sites_action.triggered.connect(self.on_toolbar_button_click)
        self.toolbar.addAction(self.compare_sites_action)

        # Refresh Plot
        if self.low_cpu_mode:
            self.refresh_plot_action = QAction("Refresh Plot", self)
            self.refresh_plot_action.setStatusTip("Manually update the eclipse geometry plot")
            self.refresh_plot_action.setIcon(QIcon(str(ICON_PATH / "refresh.png")))
            self.refresh_plot_action.triggered.connect(self.on_toolbar_button_click)
            self.toolbar.addAction(self.refresh_plot_action)

    def show_exposure_compensation(self, ev: int):
        """ Show the exposure compensation applied to all following shots.

        Args:
            - ev: Exposure compensation [EV]; positive is brighter
        """

        self.exposure_compensation_label.setText(f"{ev:+d} EV" if ev else "as scripted")
        self.exposure_compensation_label.setStyleSheet("font-weight: bold; color: #d35400;" if ev else "")
        self.exposure_darker_button.setEnabled(ev > -MAX_EXPOSURE_COMPENSATION_EV)
        self.exposure_brighter_button.setEnabled(ev < MAX_EXPOSURE_COMPENSATION_EV)
        self.exposure_reset_button.setEnabled(ev != 0)

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
            self.c1_altitude_label.setText(str(round(c1_info.apparent_altitude)))
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
            self.c2_altitude_label.setText(str(round(c2_info.apparent_altitude)))
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
            self.max_altitude_label.setText(str(round(max_info.apparent_altitude)))
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
            self.c3_altitude_label.setText(str(round(c3_info.apparent_altitude)))
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
            self.c4_altitude_label.setText(str(round(c4_info.apparent_altitude)))
        else:
            self.c4_time_utc_label.setText("")
            self.c4_time_local_label.setText("")
            self.c4_azimuth_label.setText("")
            self.c4_altitude_label.setText("")

        # Bead windows

        for contact, label in (("C2", self.beads_c2_label), ("C3", self.beads_c3_label)):
            start = reference_moments.get(f"BEADS_{contact}_START")
            end = reference_moments.get(f"BEADS_{contact}_END")
            if start is None or end is None:
                status = reference_moments.get(f"BEADS_{contact}_STATUS")
                if status == "unresolved":
                    label.setText("capture window unresolved")
                else:
                    # Name the reason: a blank cell reads like a solve that failed.
                    label.setText("correction off" if not limb_correction_is_enabled()
                                  else "no limb profile")
                continue
            seconds = (end.time_utc - start.time_utc).total_seconds()
            label.setText("%s - %s  (%.2f s)" % (format_time(start.time_utc, self.time_format),
                                                 format_time(end.time_utc, self.time_format),
                                                 seconds))

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
            self.save_layout_settings()
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

        # Camera problems are raised on worker threads, which cannot open a
        # dialog, so they are queued and collected here on the UI thread.
        self._problem_timer = QTimer()
        self._problem_timer.timeout.connect(self._show_camera_problems)
        self._problem_timer.setInterval(2000)
        self._problem_timer.start()

        # Update the eclipse visualization less frequently to save CPU/battery.
        # The main time display remains at 1 Hz; the plot updates every 5 seconds.
        self.visualization_timer = QTimer()
        self.visualization_timer.timeout.connect(self.update_visualization)
        self.visualization_timer.setInterval(5000)

        if not low_cpu_mode:
            self.visualization_timer.start()

        self._live_view_window: Union[LiveViewWindow, None] = None
        self._beads_window: Union[BeadsPanel, None] = None
        self._timeline_window = None
        self._run_report_window = None
        self._sites_window = None
        # The script loaded last, for the timeline
        self.script_filename: Union[str, None] = None

        # Keeps idle cameras from going to sleep before the script starts.
        # Started once the cameras are connected; update_time() pauses it
        # around totality and just before scheduled commands.
        self._keep_alive_thread: Union[CameraKeepAliveThread, None] = None
        self._keep_alive_allowed = threading.Event()

        self.load_settings()

        # After load_settings: it creates view.settings, and it schedules the
        # reference moments onto the event loop, which has not run yet — so the
        # correction is in place before they are first computed.  Restored before
        # the signal is connected, so start-up triggers no recalculation.
        remembered = self.view.settings.value("limb_correction", True, type=bool)
        self.view.limb_correction_checkbox.setChecked(remembered)
        set_limb_correction_enabled(remembered)
        self.view.limb_correction_checkbox.toggled.connect(self.on_limb_correction_toggled)

        # The radius itself was loaded at start-up (main), before anything was computed
        self._show_solar_radius()
        self.view.solar_radius_combo.currentIndexChanged.connect(self.on_solar_radius_choice_changed)
        self.view.solar_radius_spinbox.valueChanged.connect(self.on_solar_radius_value_changed)

    def _show_solar_radius(self):
        """Show the solar radius in use, without triggering a recalculation."""
        value = solar_radius.get_radius_arcsec()
        key = solar_radius.preset_for(value) or "custom"
        combo_blocker = QSignalBlocker(self.view.solar_radius_combo)
        spinbox_blocker = QSignalBlocker(self.view.solar_radius_spinbox)
        self.view.solar_radius_combo.setCurrentIndex(self.view.solar_radius_combo.findData(key))
        self.view.solar_radius_spinbox.setValue(value)
        self.view.solar_radius_spinbox.setEnabled(key == "custom" and not self._run_in_progress())
        del combo_blocker, spinbox_blocker

    def on_solar_radius_choice_changed(self, index: int):
        """A preset was chosen, or 'Custom value' (then the value is typed in the spin box)."""
        key = self.view.solar_radius_combo.itemData(index)
        if key == "custom":
            self.view.solar_radius_spinbox.setEnabled(True)
            self._apply_solar_radius(self.view.solar_radius_spinbox.value())
        else:
            self.view.solar_radius_spinbox.setEnabled(False)
            value, _ = solar_radius.PRESETS[key]
            blocker = QSignalBlocker(self.view.solar_radius_spinbox)
            self.view.solar_radius_spinbox.setValue(value)
            del blocker
            self._apply_solar_radius(value)

    def on_solar_radius_value_changed(self, value: float):
        """A custom radius was entered."""
        if self.view.solar_radius_combo.currentData() == "custom":
            self._apply_solar_radius(value)

    def _apply_solar_radius(self, value: float):
        """Use this solar radius, remember it and redo the contact times."""
        if abs(value - solar_radius.get_radius_arcsec()) < 1e-9:
            return
        if self._run_in_progress():
            # Same reason as for the limb correction: the absolute triggers of
            # the loaded jobs were computed with the radius in use.
            self._show_solar_radius()
            logging.warning("Stop the scheduler before changing the solar radius")
            return
        try:
            solar_radius.set_radius_arcsec(value)
        except ValueError as exc:
            logging.warning("%s", exc)
            self._show_solar_radius()
            return
        self.view.settings.setValue(solar_radius.SETTINGS_KEY, solar_radius.get_radius_arcsec())
        logging.info("Solar radius: %s", solar_radius.describe())

        if self.model.is_location_set and self.model.is_eclipse_date_set:
            self.set_reference_moments()
        if self._beads_window is not None:
            self._beads_window.refresh()

    def on_limb_correction_toggled(self, enabled: bool):
        """Apply or drop the lunar limb correction and redo the contact times.

        The times on screen answer the question this checkbox asks, so they are
        recomputed rather than left stale.
        """
        if self._run_in_progress():
            # Defensive even though the checkbox is disabled when jobs are
            # loaded: programmatic changes must not make displayed contacts
            # disagree with already-created absolute DateTriggers.
            blocker = QSignalBlocker(self.view.limb_correction_checkbox)
            self.view.limb_correction_checkbox.setChecked(limb_correction_is_enabled())
            del blocker
            logging.warning("Stop the scheduler before changing the lunar limb correction")
            return

        set_limb_correction_enabled(enabled)
        self.view.settings.setValue("limb_correction", enabled)
        logging.info('Lunar limb correction %s', 'on' if enabled else 'off')

        if self.model.is_location_set and self.model.is_eclipse_date_set:
            self.set_reference_moments()
        if self._beads_window is not None:
            self._beads_window.refresh()

    def _set_limb_correction_locked(self, locked: bool):
        """Keep contact settings immutable while absolute jobs are pending."""
        self.view.limb_correction_checkbox.setEnabled(not locked)
        self.view.limb_correction_checkbox.setToolTip(
            LIMB_CORRECTION_LOCKED_TOOLTIP if locked else LIMB_CORRECTION_TOOLTIP)
        self.view.solar_radius_combo.setEnabled(not locked)
        self.view.solar_radius_spinbox.setEnabled(
            not locked and self.view.solar_radius_combo.currentData() == "custom")
        for widget in (self.view.solar_radius_combo, self.view.solar_radius_spinbox):
            widget.setToolTip(SOLAR_RADIUS_LOCKED_TOOLTIP if locked else SOLAR_RADIUS_TOOLTIP)

    def _run_in_progress(self) -> bool:
        """True while a schedule is loaded and running."""
        try:
            return bool(self.scheduler and self.scheduler.get_jobs())
        except Exception:
            return False

    def _show_camera_problems(self, script_loaded: bool = False):
        """Show queued camera problems, without ever interrupting a run.

        Before the run a dialog is right: that is when a camera that failed to
        respond can still be replugged or swapped.  Once the schedule is
        running a modal dialog is worse than the problem it reports, because it
        blocks the UI thread while frames are being taken, so the count goes in
        the window title instead and the detail stays in the log.

        Loading a script starts its schedule, but the problems found while
        loading it (a bad bracket, commands already past) are shown right away
        (script_loaded): that is the moment the script can still be fixed.
        """
        try:
            if hardware_problems.count() == 0:
                return

            if self._run_in_progress() and not script_loaded:
                pending = hardware_problems.peek()
                worst = "error" if any(p.severity == "error" for p in pending) else "warning"
                marker = "\u26d4" if worst == "error" else "\u26a0"
                self.view.setWindowTitle(
                    f"{marker} {len(pending)} camera problem(s) - Solar Eclipse Workbench"
                )
                return

            problems = hardware_problems.drain()
            summary = hardware_problems.summarise(problems)
            has_error = any(p.severity == "error" for p in problems)
            box = QMessageBox.critical if has_error else QMessageBox.warning
            kind = "Script" if all(p.source == "Script" for p in problems) else "Camera"
            box(
                self.view,
                f"{kind} problem" if len(problems) == 1 else f"{kind} problems",
                summary + "\n\nDetails are in the log file.",
            )
        except Exception:
            LOGGER.exception("Could not display camera problems")

    def update_time(self):
        """ Update the displayed current time and countdown clocks."""

        # Show GPS time when a USB GPS fix has measured the computer clock error, so the
        # countdowns agree with the (equally corrected) scheduled commands.
        gps_time_offset = self.model.gps_time_offset
        current_time_local = datetime.datetime.now() + gps_time_offset
        current_time_utc = datetime.datetime.now(tz=datetime.timezone.utc) + gps_time_offset

        self.model.local_time = current_time_local
        self.model.utc_time = current_time_utc

        # When simulating, the scheduler has moved every command so that the chosen reference
        # moment happens now-ish.  The countdowns must follow that same shift, otherwise they
        # keep showing the real time to the eclipse (days away) while the commands fire.  This
        # is the offset the eclipse visualization already applies in plot(); zero when not
        # simulating, so the normal case is unaffected.
        offset = getattr(self.view.eclipse_visualization, 'offset', datetime.timedelta(0))
        reference_now = current_time_utc + offset

        countdown_c1 = self.model.c1_info.time_utc - reference_now if self.model.c1_info else None
        countdown_c2 = self.model.c2_info.time_utc - reference_now if self.model.c2_info else None
        countdown_max = self.model.max_info.time_utc - reference_now if self.model.max_info else None
        countdown_c3 = self.model.c3_info.time_utc - reference_now if self.model.c3_info else None
        countdown_c4 = self.model.c4_info.time_utc - reference_now if self.model.c4_info else None
        countdown_sunrise = self.model.sunrise_info.time_utc - reference_now if self.model.sunrise_info else None
        countdown_sunset = self.model.sunset_info.time_utc - reference_now if self.model.sunset_info else None

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
                and (c2.time_utc - _MARGIN) <= reference_now <= (c3.time_utc + _MARGIN)
            )
            self._live_view_window.set_totality_paused(in_totality)

        if self._beads_window is not None and self._beads_window.isVisible():
            self._beads_window.set_current_time(reference_now)

        self._update_keep_alive_allowed(reference_now)

        # self.view.eclipse_visualization.plot(current_time_utc)    FIXME

        self.update_jobs_countdown()

    def _update_keep_alive_allowed(self, reference_now: datetime.datetime):
        """Allow keep-alive pings only when they cannot get in the way of a shot.

        Pings are suspended from 15 s before C2 until 15 s after C3 (same window
        as live view), and whenever a scheduled command fires within the next
        few seconds, so a scheduled shot never has to wait for the USB lock.
        """
        margin = datetime.timedelta(seconds=15)
        c2 = self.model.c2_info
        c3 = self.model.c3_info
        allowed = not (
            c2 is not None
            and c3 is not None
            and (c2.time_utc - margin) <= reference_now <= (c3.time_utc + margin)
        )

        if allowed and self.scheduler:
            try:
                # next_run_time is on the computer clock (already GPS-corrected), so no offset here
                horizon = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(seconds=5)
                allowed = not any(
                    job.next_run_time is not None and job.next_run_time <= horizon
                    for job in self.scheduler.get_jobs()
                )
            except Exception:
                allowed = False

        if allowed:
            self._keep_alive_allowed.set()
        else:
            self._keep_alive_allowed.clear()

    def _start_keep_alive(self):
        """Start the camera keep-alive thread once; it follows camera refreshes by itself."""
        if self._keep_alive_thread is not None and self._keep_alive_thread.is_alive():
            return

        def cameras():
            return list((self.model.camera_overview.camera_overview_dict or {}).values())

        self._keep_alive_thread = CameraKeepAliveThread(cameras, should_ping=self._keep_alive_allowed.is_set)
        self._keep_alive_thread.start()
        logging.info('Camera keep-alive started (cameras are pinged while idle so they do not fall asleep)')

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

            # The eclipse may have been changed on the map in the location window.
            selected = changed_object.location_plot.selected_eclipse_date()
            if selected and selected != changed_object.initial_eclipse_date:
                eclipse_date = datetime.datetime.strptime(selected, "%Y-%m-%d")
                self.model.set_eclipse_date(Time(eclipse_date))
                self.view.eclipse_date.setText(eclipse_date.strftime(DATE_FORMATS[self.view.date_format]))

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

            if self._keep_alive_thread is not None:
                self._keep_alive_thread.stop()
                self._keep_alive_thread = None

            if self._live_view_window is not None:
                self._live_view_window.close()
                self._live_view_window = None

            if self._beads_window is not None:
                self._beads_window.close()
                self._beads_window = None

            for window in (self._timeline_window, self._run_report_window, self._sites_window):
                if window is not None:
                    window.close()
            self._timeline_window = self._run_report_window = self._sites_window = None

            if self.model.camera_overview.camera_overview_dict:
                cameras = self.model.camera_overview.camera_overview_dict.values()

                camera: Camera
                for camera in cameras:
                    # Close every camera even if one refuses.  Without this, the
                    # first camera to raise aborts the loop and leaves the rest
                    # open, still holding their USB devices, so the next run
                    # cannot claim them and fails with a device-busy error.
                    try:
                        camera.exit()
                    except Exception:
                        LOGGER.exception("Could not close camera %s",
                                         getattr(camera, "name", camera))

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
                self.set_reference_moments()

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

            # Loading a script always starts a *new* scheduler, so any scheduler from a
            # previously loaded script must be stopped first — otherwise both stay alive and
            # every command fires twice.
            if self.scheduler:
                LOGGER.info("Replacing the previously loaded script")
                self._shutdown_scheduler()

            try:
                from solareclipseworkbench.utils import observe_solar_eclipse, get_continuous_mode_commands
                self.scheduler: BackgroundScheduler
                self.scheduler, unknown_moments \
                    = observe_solar_eclipse(self.model.reference_moments, filename,
                                            self.model.camera_overview.camera_overview_dict, self,
                                            self.sim_reference_moment, self.sim_offset_minutes,
                                            gps_time_offset=self.model.gps_time_offset)

                self.script_filename = filename
                if self._timeline_window is not None:
                    self._timeline_window.set_script(filename)

                # Remind Nikon users to set the release-mode dial for the bursts / brackets in this script
                self.model.camera_overview.set_continuous_mode_commands(
                    get_continuous_mode_commands(self.scheduler, self.model.camera_overview.camera_overview_dict))

                # Loading is the last moment this can be fixed: afterwards the names are
                # resolved and the missing lines are simply gone.  The bead windows
                # (BEADS_C2, BEADS_C3 and their _START/_END) exist only when the
                # correction is on and the lunar limb profile is installed.
                for name, count in unknown_moments.items():
                    LOGGER.warning("Script schedules against %s, which does not exist: %d line(s) "
                                   "were not scheduled.  Available: %s", name, count,
                                   ", ".join(sorted(self.model.reference_moments)))

                # Problems found while loading (a bad bracket, commands already past) are shown
                # now, while the script can still be fixed, not after the run
                self._show_camera_problems(script_loaded=True)

                self.jobs_model = JobsTableModel(self.scheduler, self)
                self.view.jobs_table.setModel(self.jobs_model)
                self.jobs_model.add_observer(self.view.jobs_table)
                self.view.jobs_table.resizeColumnsToContents()

                self.view.camera_action.setDisabled(True)

                n_jobs = len(self.scheduler.get_jobs())
                self._set_limb_correction_locked(n_jobs > 0)
                if n_jobs > 0 and self._beads_window is not None:
                    # From now on, show what is happening rather than the last second scrubbed to
                    self._beads_window.follow_live()
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

        elif changed_object in (self.view.exposure_darker_button, self.view.exposure_brighter_button,
                                self.view.exposure_reset_button):
            if changed_object is self.view.exposure_reset_button:
                ev = 0
            elif changed_object is self.view.exposure_brighter_button:
                ev = get_exposure_compensation() + EXPOSURE_COMPENSATION_STEP_EV
            else:
                ev = get_exposure_compensation() - EXPOSURE_COMPENSATION_STEP_EV
            ev = set_exposure_compensation(ev)
            self.view.show_exposure_compensation(ev)
            if self.jobs_model:
                self.jobs_model.update_commands()

        elif text == "Datetime format":
            self.settings_popup = SettingsPopup(self)
            self.settings_popup.show()

        elif text == "Save":
            self.view.save_settings()

        elif text == "Live View":
            self._open_live_view()

        elif text == "Baily's beads":
            self._open_beads_window()

        elif text == "Timeline":
            self._open_timeline_window()

        elif text == "Run report":
            self._open_run_report_window()

        elif text == "Compare sites":
            self._open_sites_window()

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
            self._start_keep_alive()
        except Exception:
            logging.exception('Could not start the camera keep-alive')
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

    def _open_timeline_window(self):
        """Open (or bring to front) the script timeline, on the script loaded last."""
        from solareclipseworkbench.report_ui import TimelineWindow
        if self._timeline_window is None:
            self._timeline_window = TimelineWindow(
                lambda: (self.model.reference_moments, self.model.camera_overview.camera_overview_dict))
        if self._timeline_window.filename is None and self.script_filename is None:
            self._timeline_window.choose_script()
        else:
            self._timeline_window.set_script(self.script_filename if self._timeline_window.filename is None
                                             else None)
        self._timeline_window.show()
        self._timeline_window.activateWindow()
        self._timeline_window.raise_()

    def _open_run_report_window(self):
        """Open (or bring to front) the run report, on the newest log with a loaded script."""
        from solareclipseworkbench.report_ui import RunReportWindow
        if self._run_report_window is None:
            self._run_report_window = RunReportWindow()
        else:
            self._run_report_window.fill_logs()
        self._run_report_window.show()
        self._run_report_window.activateWindow()
        self._run_report_window.raise_()

    def _sites_context(self):
        """The eclipse date (YYYY-MM-DD) and the location of the main window, for the Compare sites window."""
        from solareclipseworkbench.site_comparison import Site
        date = None
        if self.model.is_eclipse_date_set:
            day = self.model.eclipse_date.datetime
            date = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        site = None
        if self.model.is_location_set:
            site = Site("Current location", self.model.longitude, self.model.latitude, self.model.altitude)
        return date, site

    def _use_site(self, site):
        """Make a site of the Compare sites window the observing location, and recompute the contacts."""
        self.set_location(site.longitude, site.latitude, site.altitude)
        LOGGER.info("Location set to %s (%s, %s, %s m) from Compare sites", site.name, site.longitude,
                    site.latitude, site.altitude)
        if self.model.is_eclipse_date_set:
            self.set_reference_moments()

    def _open_sites_window(self):
        """Open (or bring to front) the Compare sites window."""
        from solareclipseworkbench.sites_ui import SiteComparisonWindow
        if self._sites_window is None:
            self._sites_window = SiteComparisonWindow(self._sites_context, self._use_site)
        else:
            self._sites_window.fill_saved_locations()
            self._sites_window.refresh_context()
        self._sites_window.show()
        self._sites_window.activateWindow()
        self._sites_window.raise_()

    def _open_beads_window(self):
        """Open (or bring to front) the Baily's beads window."""
        if self._beads_window is None:
            self._beads_window = BeadsPanel()
        self._refresh_beads_window()
        self._beads_window.show()
        self._beads_window.activateWindow()
        self._beads_window.raise_()

    def _refresh_beads_window(self):
        """Point the Baily's beads window at the current location and eclipse, if both are set.

        Solving the limb costs a couple of seconds, so the window only redoes it
        when the place or the date actually changes.
        """
        if self._beads_window is None:
            return
        if not (self.model.is_location_set and self.model.is_eclipse_date_set):
            self._beads_window.summary.setText("Set a location and an eclipse date first")
            return
        day = self.model.eclipse_date.datetime
        date = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        self._beads_window.set_context(date, self.model.longitude, self.model.latitude, self.model.altitude)

    def load_settings(self):
        """ Load the UI settings.

        These settings are:

            - Date format (always present);
            - Time format (always present);
            - Location (longitude, latitude, altitude);
            - Eclipse date;
            - Position of the splitter between the eclipse plot and the jobs table.

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

        # Layout

        self.view.restore_layout_settings()

        # Location

        # A missing key is read as 0.0 when type=float is given, so check that the key exists first

        longitude, latitude, altitude = (self.view.settings.value(key, type=float)
                                         if self.view.settings.contains(key) else None
                                         for key in ("longitude", "latitude", "altitude"))
        is_location_loaded = self.set_location(longitude, latitude, altitude)

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


        # 0 is a valid coordinate (e.g. an altitude at sea level)

        if longitude is not None and latitude is not None and altitude is not None:
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
        download_progress = {}

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
                root_logger.handlers = file_handlers_only(old_handlers)
                if limb_correction_is_enabled():
                    # The first time, the lunar limb profile is downloaded (72 MB)
                    ensure_limb_profile(progress=lambda received, total: download_progress.update(
                        received=received, total=total))
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
            elif download_progress:
                received, total = download_progress["received"], download_progress["total"]
                label.setText(f"Downloading the lunar limb profile "
                              f"({received // 1_000_000} of {total // 1_000_000} MB)...")
                progress_bar.setRange(0, total)
                progress_bar.setValue(received)

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
            self._refresh_beads_window()

    def _shutdown_scheduler(self):
        """Safely shut down the scheduler and update UI."""
        try:
            if self.scheduler:
                self.scheduler.shutdown()
                if self.jobs_model:
                    self.jobs_model.clear_jobs_overview()
                self.view.camera_action.setEnabled(True)
                LOGGER.info("Scheduler stopped by user")
                self.model.camera_overview.set_continuous_mode_commands(None)
        except SchedulerNotRunningError:
            pass  # already stopped
        except Exception:
            logging.exception("Error while shutting down scheduler")
        finally:
            self._set_limb_correction_locked(False)


class LocationPopup(QWidget, Observable):
    def __init__(self, observer: SolarEclipseController):
        """ Initialisation of a pop-up window for setting the observing location.

        A pop-up window is shown, in which the user can choose the following information about the observing location:

            - Longitude [degrees];
            - Latitude [degrees];
            - Altitude [meters].

        The window also provides a saved-locations drop-down and an address-search bar (when geopy is installed).  When
        coordinates change, the location is shown on a map (as a red dot) together with the path of totality or
        annularity of the selected eclipse, and the distance from the centre line.  The eclipse can be changed in
        the drop-down above the map.  When pressing the "OK" button, the controller will be notified (and takes over
        a changed eclipse as the eclipse date).  A street map next to it shows the site in detail; double-clicking it
        moves the site there (after confirmation).

        If the location had already been set before, the coordinate fields will be pre-filled.

        Args:
            - observer: SolarEclipseController that needs to be notified about the selection of a new location.
        """

        QWidget.__init__(self)
        self.setWindowTitle("Location")
        self.setGeometry(QRect(100, 100, 1300, 800))
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

        # Detailed street map of the site, next to the map with the path of the selected eclipse.  The eclipse
        # can be changed above the path map; pressing OK then also makes it the eclipse date of the main window.
        self.site_map = SiteMapWidget(self.location_widget)
        self.location_plot = EclipsePathWidget(date_format=DATE_FORMATS[observer.view.date_format])
        self.initial_eclipse_date = model.eclipse_date.strftime("%Y-%m-%d") if model.eclipse_date is not None \
            else None
        self.location_plot.set_eclipse_date(self.initial_eclipse_date)

        maps_layout = QHBoxLayout()
        maps_layout.addWidget(self.site_map, stretch=1)
        maps_layout.addWidget(self.location_plot, stretch=1)
        layout.addLayout(maps_layout, stretch=1)

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
        self.location_widget.altitude_edit.textChanged.connect(self._schedule_auto_plot)

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
        """Plot the selected location on the map and say where it is relative to the eclipse path.

        Silently ignored when longitude or latitude are empty or not yet valid numbers.
        """
        try:
            lon = float(self.longitude.text())
            lat = float(self.latitude.text())
        except ValueError:
            return
        try:
            alt = float(self.altitude.text())
        except ValueError:
            alt = 0.0
        self.location_plot.plot_location(longitude=lon, latitude=lat, altitude=alt)

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

        # "<date> - <type> - <duration for central eclipses, magnitude for partial ones>"
        self.eclipse_combobox.addItems([label for label, _ in eclipse_choices(20, date_format)])

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
                root_logger.handlers = file_handlers_only(old_handlers)
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
        sun_ang_radius = math.asin(solar_radius.get_radius_m() / sun_distance)   # Angular radius of the Sun [radians]
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


CAMERA_DEFAULT_SIZE = "Camera default"


def live_view_size_items(current: str, choices: list) -> tuple:
    """Items of the preview size box, and the one to select first.

    Some cameras report a size they do not offer (an EOS 80D reports 'val 0'
    next to Large, Medium and Small) and do not accept it back: the box then
    starts at "Camera default", which is never sent to the camera.
    """
    if current in choices:
        return list(choices), current
    return [CAMERA_DEFAULT_SIZE] + list(choices), CAMERA_DEFAULT_SIZE


class LiveViewWindow(QWidget):
    """Floating window that shows a live-view preview from a gphoto2 camera.

    A background ``LiveViewThread`` grabs one preview frame per second.  When
    the camera USB lock is held by a scheduled shot the frame is silently
    skipped so timing accuracy is never compromised.

    The window can be:
      - Disabled/re-enabled at any time via the toggle button.
      - Auto-paused between C2 and C3 (totality) by the controller calling
        ``set_totality_paused(True/False)``.

    The preview uses the live-view size set on the camera.  When the camera
    lets it be changed (Canon EOS, recent Nikon bodies), ``Preview size``
    selects another one for as long as the window is open; the camera's own
    setting is restored when the window closes.
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

        # Preview size: only offered when the camera lets it be changed
        self._size_combo = QComboBox()
        self._original_size: Union[str, None] = None
        sizes = get_live_view_sizes(camera)
        if sizes is None:
            self._size_combo.addItem(CAMERA_DEFAULT_SIZE)
            self._size_combo.setEnabled(False)
            self._size_combo.setToolTip("This camera does not let SEW change the size of the live-view frames")
        else:
            items, self._original_size = live_view_size_items(*sizes)
            self._size_combo.addItems(items)
            self._size_combo.setCurrentText(self._original_size)
            if self._original_size == CAMERA_DEFAULT_SIZE:
                restored = ("The camera does not report its own setting, so a size chosen here stays on the "
                            "camera after this window closes.")
            else:
                restored = f"The camera setting ({self._original_size}) is restored when this window closes."
            self._size_combo.setToolTip(
                "Size of the live-view frames.  Larger frames show more detail but take longer to transfer: "
                "a scheduled shot that fires during a transfer waits for it.\n" + restored
            )
        self._size_combo.currentTextChanged.connect(self._on_size_changed)

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
        btn_layout.addWidget(QLabel("Preview size:"))
        btn_layout.addWidget(self._size_combo)
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
        # No preview size changes around totality: each one is a USB round-trip
        self._size_combo.setEnabled(self._original_size is not None and not self._totality_paused)
        if self._user_enabled and not self._totality_paused:
            self._thread.resume()
            self._toggle_btn.setText("Disable Live View")
        else:
            self._thread.pause()
            # Actually exit live view on the camera (Nikon D610 etc.)
            self._thread.exit_live_view()
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

    def _on_size_changed(self, size: str):
        """Slot for preview size combo box changes."""
        if self._original_size is None or self._totality_paused or size == CAMERA_DEFAULT_SIZE:
            return
        if not set_live_view_size(self._camera, size):
            QMessageBox.warning(self, "Preview size", f"The camera did not accept preview size {size}.")

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
        self._timestamp_label.setText("Last frame: " + ts.strftime("%Y-%m-%d  %H:%M:%S")
                                      + f"  ({pixmap.width()}\u00d7{pixmap.height()})")

    def closeEvent(self, event):
        self._poll_timer.stop()
        if self._thread is not None:
            self._thread.stop()
            self._thread = None
        # Give the camera its own preview size back, unless that would cost a
        # USB round-trip during totality
        if self._original_size is not None and self._size_combo.currentText() != self._original_size:
            if self._totality_paused:
                camera_log(self._camera).warning('live view size left at %s (window closed during totality)',
                                                 self._size_combo.currentText())
            elif self._original_size == CAMERA_DEFAULT_SIZE:
                camera_log(self._camera).info('live view size left at %s (the camera did not report its own '
                                              'size)', self._size_combo.currentText())
            else:
                set_live_view_size(self._camera, self._original_size)
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
    """Format the given time according to the given time format."""

    # Format with standard strftime (includes 6 digits of microseconds)
    formatted = time.strftime(TIME_FORMATS[time_format])

    # Slice off the last 5 digits of %f, leaving 1 decimal place (.f)
    formatted = formatted[:-5]

    suffix = ""
    if time_format == "12 hours":
        suffix = " am" if time.hour < 12 else " pm"

    return f"{formatted}{suffix}"


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
        # Whether the pending update was requested by the user (`Camera(s)` button).  Only then does a closed
        # Sony banner reappear.
        self._user_requested = False
        # Banner lines about the Sony settings, kept so that the banner can be rebuilt without probing the cameras
        self._sony_banner_lines = []
        # Per camera name, which of take_burst / take_bracket the loaded script uses for it (None when
        # no script has been loaded).  Nikon cameras may need their release-mode dial set to Continuous for these.
        self.continuous_mode_commands: Union[dict, None] = None

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

    def update_camera_overview(self, user_requested: bool = True):
        """ Update the camera overview.

        Args:
            - user_requested: Whether the user asked for this update (`Camera(s)` button).  An automatic update
                              (`sync_cameras`) does not show the Sony banner again once the user closed it.
        """
        # Sticky until the data is applied, so an automatic update in between does not cancel the user's request
        self._user_requested = self._user_requested or user_requested
        logging.debug('CameraOverviewTableModel.update_camera_overview(): start (scheduling worker)')
        try:
            LOGGER.debug("CameraOverview: scheduling worker to probe cameras")
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
                        logging.info('CameraOverview: forcing fresh detection (attempt %d)', attempt + 1)
                        seen = set()
                        for camera_name, camera in (existing_map or {}).items():
                            if camera is None or id(camera) in seen:
                                continue
                            seen.add(id(camera))
                            try:
                                camera.disconnect()
                            except Exception:
                                camera_log(camera_name).debug('Worker: disconnect raised (non-fatal)')
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
                        camera_log(camera_name).debug('Worker: processing camera')
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
                    except Exception as exc:
                        error_str = str(exc).lower()
                        if any(x in error_str for x in ['-52', '-2', 'could not find the requested device', 'bad parameters']):
                            camera_log(camera_name).warning('Stale camera connection detected (%s)', exc)
                            hardware_problems.report(
                                str(camera_name),
                                'Lost the USB connection to this camera',
                                detail=str(exc),
                            )
                            needs_refresh = True
                            self._force_camera_refresh = True
                            break
                        camera_log(camera_name).exception('Worker: exception while processing camera')
                        # The row survives with N/A values, which on its own looks
                        # like the camera is simply idle.  Say why.
                        hardware_problems.report(
                            str(camera_name),
                            'Could not read battery and free space from this camera',
                            detail=str(exc),
                            severity='warning',
                        )
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
                LOGGER.debug('Worker: gathered camera overview data: %s', data)
                # write pending data and the camera objects for the main thread poll to pick up
                try:
                    self._pending_data = data
                    # keep the mapping of camera name -> camera object for later actions
                    self._pending_camera_map = camera_dict
                except Exception:
                    logging.exception('Worker: could not set pending data')
                break
            except Exception as exc:
                logging.exception('Worker: failed to gather camera info')
                attempt += 1
                if attempt >= max_retries:
                    hardware_problems.report(
                        'Cameras',
                        'Could not read the connected cameras',
                        detail=str(exc),
                    )
                    break

    def _on_data_ready(self, data):
        try:
            LOGGER.debug("CameraOverview: on_data_ready called with " + data)
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
                LOGGER.debug("CameraOverview: view updated")
        except Exception:
            logging.exception('Could not update camera overview view after data ready')

        # If we have actual camera objects, start the Sony background downloader
        # automatically only when the camera reports PC-Only save destination.
        # Also, show an informational banner about the relevant settings.
        try:
            pm = getattr(self, 'camera_overview_dict', None)

            if pm:
                seen = set()
                banner_lines = []

                for cam in pm.values():
                    camera_vendor = getattr(cam, 'vendor', None)

                    if camera_vendor == "Sony":
                        try:
                            if cam is None:
                                continue
                            if id(cam) in seen:
                                continue
                            seen.add(id(cam))

                            dest = get_sony_save_destination(cam)
                            image_quality = get_sony_image_quality(cam)
                            camera_model = getattr(cam, 'name', 'Unknown Sony')

                            # Decide action + message for this camera
                            if dest == "sdram":
                                text = (f"{camera_model}: currently saving photos to PC. "
                                        f"We recommend testing if 'PC+Camera' mode is faster.")
                                if image_quality != "RAW":
                                    text += f" Also, 'File Format' is set to '{image_quality}'. Please set it to 'RAW'!"
                                try:
                                    cam.start_background_downloader()
                                except Exception:
                                    camera_log(camera_model).warning('failed to start Background Downloader')

                                banner_lines.append(text)

                            elif dest == "card+sdram":
                                text = (f"{camera_model}: currently in 'PC+Camera' mode. "
                                        f"We recommend testing if 'PC' mode is faster.")
                                if not image_quality.startswith("RAW+JPEG"):
                                    text += (" Also, 'File Format' is set to '{}'."
                                            " Please set it to 'RAW+JPEG' and choose 'JPEG Only' "
                                            "for 'RAW+J PC Save Img'.").format(image_quality)
                                try:
                                    cam.stop_background_downloader()
                                except Exception:
                                    pass

                                banner_lines.append(text)

                            elif dest == "card":
                                if image_quality != "RAW":
                                    text = f"{camera_model}: 'File Format' is set to '{image_quality}'. Please set it to 'RAW'!"
                                    banner_lines.append(text)
                                else:
                                    # No banner needed for good RAW + Card-only config
                                    try:
                                        cam.stop_background_downloader()
                                    except Exception:
                                        pass
                            else:
                                # Unknown / unavailable destination
                                if image_quality != "RAW":
                                    text = f"{camera_model}: 'Quality' is set to '{image_quality}'. Please set it to 'RAW'!"
                                    banner_lines.append(text)
                                else:
                                    try:
                                        cam.start_background_downloader()
                                    except Exception:
                                        logging.warning(
                                            '%s: failed to start Background Downlaoder', camera_model)

                        except Exception:
                            logging.debug('Error while checking Sony save destination for a camera', exc_info=True)

                self._sony_banner_lines = banner_lines
            else:
                self._sony_banner_lines = []
        except Exception:
            logging.exception("Error checking Sony settings / background downloaders")

        self.update_camera_banner(user_requested=self._user_requested)
        self._user_requested = False

        # Notify controller that cameras are ready (fires sync_camera_time + check_camera_state)
        cb = getattr(self, 'on_ready_callback', None)
        if cb is not None:
            try:
                cb()
            except Exception:
                logging.exception('on_ready_callback raised an exception')
            finally:
                self.on_ready_callback = None

    def _nikon_banner_lines(self) -> list:
        """ Return the banner lines that remind to set the release-mode dial of the Nikon cameras to Continuous.

        On Nikon bodies with a physical release-mode dial, the app cannot change the release mode, and take_burst
        and take_bracket need a Continuous mode (take_picture and take_hdr work in any mode).  Once a script has been
        loaded, only the Nikon cameras for which it uses one of these commands get a line.

        Returns: List with one line per Nikon camera that needs the reminder.
        """
        lines = []
        seen = set()
        for name, cam in (self.camera_overview_dict or {}).items():
            if cam is None or getattr(cam, 'vendor', None) != "Nikon" or id(cam) in seen:
                continue
            seen.add(id(cam))
            camera_model = getattr(cam, 'name', name)

            if self.continuous_mode_commands is None:
                lines.append(f"{camera_model}: if you use take_burst or take_bracket and this camera has "
                             f"a release-mode dial, set the dial to a Continuous mode.")
            else:
                commands = self.continuous_mode_commands.get(name)
                if commands:
                    lines.append(f"{camera_model}: the script uses {', '.join(sorted(commands))}.  If this camera "
                                 f"has a release-mode dial, set the dial to a Continuous mode.")
        return lines

    def update_camera_banner(self, user_requested: bool = False):
        """ Show the settings to check for the connected Sony and Nikon cameras in the banner (or hide it).

        Args:
            - user_requested: Whether the user asked to see the camera state again (`Camera(s)` button), which also
                              brings back a closed banner.
        """
        banner = getattr(getattr(self, 'view', None), 'camera_banner', None)
        if banner is None:
            return

        lines = list(self._sony_banner_lines)
        if lines:
            lines.append("If this info is wrong or you changed settings - press 'Camera(s)' again!")
        lines += self._nikon_banner_lines()

        full_text = "\n".join(lines)
        banner.show_message(full_text, user_requested=user_requested)
        if full_text:
            logging.info("Camera banner updated to:\n%s", full_text)

    def set_continuous_mode_commands(self, continuous_mode_commands: Union[dict, None]):
        """ Remember which cameras the loaded script drives with take_burst / take_bracket.

        Args:
            - continuous_mode_commands: Per camera name, the set of these commands the script uses for it.  None
                                        when no script is loaded.
        """
        self.continuous_mode_commands = continuous_mode_commands
        self.update_camera_banner()

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


def _shutter_speed_string(shutter_speed: str) -> str:
    """ Return the shutter speed for the jobs table, with the exposure compensation when one is set.

    E.g. "1/1000 → 1/500" at +1 EV.
    """

    compensated = compensated_shutter_speed(shutter_speed)
    if compensated == shutter_speed:
        return shutter_speed
    return f"{shutter_speed} \u2192 {compensated}"


def job_command_string(job: Job) -> str:
    """ Return the command of a scheduled job as shown in the jobs table.

    Args:
        - job: Scheduled job
    """

    name = job.func.__name__

    if name in ("take_picture", "take_burst", "take_bracket", "prepare_camera", "take_hdr"):
        camera_settings: CameraSettings = job.args[1]
        settings = (f"\"{camera_settings.camera_name}\", {_shutter_speed_string(camera_settings.shutter_speed)}, "
                    f"{camera_settings.aperture}, {camera_settings.iso}")
        if name == "take_picture":
            return f"take_picture({settings})"
        if name == "take_hdr":
            return f"take_hdr({settings}, {job.args[2]} stops)"
        return f"{name}({settings}, {job.args[2]})"

    if name == "sync_cameras":
        return "sync_cameras()"

    if name == "voice_prompt":
        return f"{name}({', '.join(job.args).strip()})"

    if name == "execute_command":
        return f"command({', '.join(job.args).strip()})"

    return ""


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

        # The jobs were scheduled on the computer clock, shifted by this GPS–computer offset.
        # Adding it back shows the true (GPS) UTC execution times.  It is captured here, not
        # read live, because it must match the offset the scheduler used for these jobs.
        self.gps_time_offset: datetime.timedelta = self.controller.model.gps_time_offset

        from solareclipseworkbench.reference_moments import _find_timezone
        timezone = pytz.timezone(_find_timezone(self.controller.model.longitude, self.controller.model.latitude))

        now_utc = datetime.datetime.now(tz=datetime.timezone.utc) + self.gps_time_offset
        data = []

        self.execution_times_utc_as_datetime = []
        self.execution_times_local_as_datetime = []
        self.jobs: list[Job] = []

        job: Job
        for job in scheduler.get_jobs():

            execution_time_utc: datetime.datetime = job.next_run_time
            if execution_time_utc:
                execution_time_utc = execution_time_utc + self.gps_time_offset
                execution_time_local = execution_time_utc.astimezone(timezone)

                countdown = "-"
                if now_utc <= execution_time_utc:
                    countdown = format_countdown(execution_time_utc - now_utc)
                description: str = job.name

                job_string = job_command_string(job)
                self.jobs.append(job)

                self.execution_times_utc_as_datetime.append(execution_time_utc)
                formatted_execution_time_utc = format_time(execution_time_utc, self.time_format)

                self.execution_times_local_as_datetime.append(execution_time_local)
                formatted_execution_time_local = format_time(execution_time_local, self.time_format)

                data.append([countdown, formatted_execution_time_local, formatted_execution_time_utc,
                             job_string, description])

        self._data = pd.DataFrame(data, columns=[JobsTableColumnNames.COUNTDOWN.value,
                                                 JobsTableColumnNames.EXEC_TIME_LOCAL.value,
                                                 JobsTableColumnNames.EXEC_TIME_UTC.value,
                                                 JobsTableColumnNames.COMMAND.value,
                                                 JobsTableColumnNames.DESCRIPTION.value])

    def update_countdown(self):
        """ Update the countdown until execution time."""

        if self._data.shape[0] > 0:

            self.beginResetModel()
            now_utc = datetime.datetime.now(tz=datetime.timezone.utc) + self.gps_time_offset
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

    def update_commands(self):
        """ Show the shutter speeds with the current exposure compensation. """

        self.beginResetModel()
        for row, job in enumerate(self.jobs):
            self._data.loc[row, JobsTableColumnNames.COMMAND.value] = job_command_string(job)
        self.endResetModel()

    def clear_jobs_overview(self):
        """ Clear the scheduled jobs overview. """

        self.beginResetModel()
        self._data = pd.DataFrame(columns=self._data.columns)
        self.jobs = []
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

        index: QModelIndex = self.model().index(min(row + 3, self.model().rowCount(None) - 1), 0)
        self.setCurrentIndex(index)

    def do(self, actions):
        pass


def main():
    parser = argparse.ArgumentParser(description="Solar Eclipse Workbench")
    parser.add_argument(
        "-s",
        "--sim",
        help="Start up in simulator mode",
        default=False,
        action='store_true'
    )
    parser.add_argument(
        "-vc",
        "--virtual-camera",
        help="Enable virtual camera (when starting GUI in simulator mode)",
        action='store_true',
        default=False,
    )
    parser.add_argument(
        "-lon",
        "--longitude",
        help="longitude of the location where to watch the solar eclipse (W is negative)",
        default=None,
        type=float
    )

    parser.add_argument(
        "-lat",
        "--latitude",
        help="latitude of the location where to watch the solar eclipse (N is positive)",
        default=None,
        type=float
    )

    parser.add_argument(
        "-alt",
        "--altitude",
        help="altitude of the location where to watch the solar eclipse (in metres)",
        default=None,
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

    parser.add_argument(
        "--check",
        metavar="SCRIPT",
        help="print the timeline of a script per camera, with the commands that start late or are dropped, "
             "and exit (needs --longitude, --latitude, --altitude and --date)",
    )

    parser.add_argument(
        "--plot",
        metavar="PNG",
        help="with --check: also draw the timeline around totality to this image file",
    )

    parser.add_argument(
        "--report",
        metavar="LOG",
        nargs="?",
        const="",
        help="print what became of every command of the last run in a log file and exit "
             "(default: the newest log in which a script was loaded)",
    )

    parser.add_argument(
        "--compare",
        metavar="LOCATION",
        nargs="*",
        help="compare candidate sites for the eclipse of --date and exit: the named saved locations, or the "
             "shortlist of the Compare sites window when none are named (plus --longitude/--latitude/--altitude "
             "when given)",
    )

    parser.add_argument(
        "--forecast",
        action="store_true",
        help="with --compare: also fetch the cloud cover at maximum eclipse from Open-Meteo",
    )

    args = parser.parse_args()

    if args.report is not None:
        return report_main(args.report)

    # --check prints its own result; the log file still gets everything
    setup_logging("sew", console_level=logging.WARNING if args.check or args.compare is not None else logging.INFO)
    LOGGER.info("Starting up Solar Eclipse Workbench")
    # Before any contact time is computed, also for --check and --compare
    solar_radius.load_saved()
    LOGGER.info("Solar radius: %s", solar_radius.describe())

    if args.check:
        return check_main(args)

    if args.compare is not None:
        return compare_main(args)

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

    is_location_given = args.longitude is not None and args.latitude is not None and args.altitude is not None
    if is_location_given:
        controller.set_location(args.longitude, args.latitude, args.altitude)

    if args.date:
        controller.set_eclipse_date(args.date, date_format=None)

    # Show the main window first, then schedule reference-moments calculation so
    # the loading dialog is shown on top of the visible GUI if helper files
    # need to be downloaded.
    view.show()

    if is_location_given and args.date:
        # Schedule after the event loop starts so the main window is painted.
        QTimer.singleShot(0, controller.set_reference_moments)

    return app.exec()


def check_main(args) -> int:
    """sew --check: print the timeline of a script and exit; 1 when a command will be dropped."""
    from solareclipseworkbench.script_timeline import build_timeline, draw_timeline, format_timeline

    if args.longitude is None or args.latitude is None or args.altitude is None or not args.date:
        print("--check needs the location and the date: --longitude, --latitude, --altitude and --date")
        return 2
    reference_moments, _, eclipse_type = calculate_reference_moments(args.longitude, args.latitude, args.altitude,
                                                                     Time(args.date))
    timeline = build_timeline(args.check, reference_moments)
    print(f"Script {args.check}, {eclipse_type} eclipse of {args.date} at {args.longitude}, {args.latitude}, "
          f"{args.altitude} m\n")
    print(format_timeline(timeline))
    if args.plot:
        from matplotlib.figure import Figure
        figure = Figure(figsize=(14, 2 + 0.6 * max(1, len(timeline.cameras))))
        draw_timeline(figure, timeline)
        figure.savefig(args.plot, dpi=120)
        print(f"Timeline drawn to {args.plot}")
    return 1 if timeline.dropped or timeline.unknown_moments else 0


def compare_main(args) -> int:
    """sew --compare: print the candidate sites side by side and exit."""
    from solareclipseworkbench import site_comparison
    from solareclipseworkbench.site_comparison import Site

    if not args.date:
        print("--compare needs the date of the eclipse: --date YYYY-MM-DD")
        return 2
    config = ConfigManager()
    sites = []
    if args.compare:
        for name in args.compare:
            location = config.get_location(name)
            if location is None:
                saved = ", ".join(loc["name"] for loc in config.get_locations()) or "none"
                print(f"No saved location called {name!r} (saved: {saved})")
                return 2
            sites.append(Site(location["name"], float(location["longitude"]), float(location["latitude"]),
                              float(location.get("altitude", 0.0))))
    else:
        for data in config.get_candidate_sites():
            try:
                sites.append(Site.from_dict(data))
            except (KeyError, TypeError, ValueError):
                continue
    if args.longitude is not None and args.latitude is not None:
        sites.append(Site("Command line location", args.longitude, args.latitude, args.altitude or 0.0))
    if not sites:
        print("No sites to compare: name saved locations, add sites in the Compare sites window, "
              "or give --longitude, --latitude and --altitude")
        return 2

    results = site_comparison.compare_sites(sites, args.date)
    forecasts = [site_comparison.fetch_cloud_cover_for(r) for r in results] if args.forecast else None
    print(site_comparison.format_comparison(results, args.date, forecasts))
    return 1 if all(r.error for r in results) else 0


def report_main(log: str) -> int:
    """sew --report: print the report of the last run in a log file and exit."""
    from solareclipseworkbench import run_report

    if log:
        path = Path(log)
    else:
        logs = run_report.run_logs()
        if not logs:
            print(f"No log with a loaded script in {run_report.LOG_DIR}")
            return 1
        path = logs[0]
    try:
        runs = run_report.read_log(path)
    except OSError as e:
        print(f"Could not read {path}: {e}")
        return 1
    if not runs:
        print(f"No script was loaded in {path}")
        return 1
    if len(runs) > 1:
        print(f"{len(runs)} scripts were loaded in this log; this is the last one.\n")
    print(run_report.format_report(runs[-1], path))
    return 0


def sync_cameras(controller: SolarEclipseController):
    """ Synchronise the cameras for the given controller.

    This consists of the following steps:

        - Update the camera overview in the model and the view of the given controller;
        - Set the time of all connected cameras to the time of the computer;
        - Check whether the focus mode and shooting mode of all connected cameras is set to 'Manual'.

    Args:
        - controller: Controller of the Solar Eclipse Workbench UI
    """

    controller.model.camera_overview.update_camera_overview(user_requested=False)


if __name__ == "__main__":

    sys.exit(main())
