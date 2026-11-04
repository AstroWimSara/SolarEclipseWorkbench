"""
Solar Eclipse Workbench Configuration Wizard

A PyQt6-based wizard to generate eclipse photography scripts interactively.
"""
import sys
import math
import json
import time
import requests
import logging
import threading
import queue
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal, QTimer, QEventLoop, QObject
from PyQt6.QtGui import QDoubleValidator, QIntValidator, QFont
from PyQt6.QtWidgets import (
    QApplication, QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QLineEdit, QComboBox, QCheckBox, QRadioButton,
    QSpinBox, QDoubleSpinBox, QGroupBox, QButtonGroup, QTextEdit,
    QFileDialog, QPushButton, QMessageBox, QProgressDialog, QDialog, QPlainTextEdit, QProgressBar, QWidget, QScrollArea
)

from solareclipseworkbench.location_ui import ConfigManager, GeocodingWorker, GEOPY_AVAILABLE, LocationWidget
from solareclipseworkbench.qt_utils import apply_system_color_scheme, _is_dark_mode_preferred, _build_dark_palette, dark_lineedit_style, apply_dark_to_lineedit

# Import eclipse-specific modules
from astropy.time import Time
from solareclipseworkbench.exposure_calculator import (
    calculate_eclipse_exposures, 
    format_shutter_speed,
    parse_shutter_speed,
    calculate_sun_altitudes_at_time,
    calculate_exposure,
    get_exposure_bracket,
    round_to_camera_shutter_speed
)
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.logging_setup import setup_logging, file_handlers_only
from solareclipseworkbench.camera_check import ExposureLimits, adapt_script_lines
from solareclipseworkbench.bracketing import (
    HDR_ONE_WAY, HDR_ROUND_TRIP, STANDARD_FRAMES, STANDARD_STEPS, format_ev, hdr_offsets, parse_bracket,
)
from solareclipseworkbench.command_timing import (
    DEFAULT_PROFILE,
    CONTACT_BUFFER_S,
    contact_burst_plan,
    mode_switch_s,
    vendor_from_name,
    picture_duration_s,
    hdr_duration_s,
    bracket_planning_s,
    timing_directive,
)
from datetime import timedelta
from solareclipseworkbench.contact_visibility import DEFAULT_PIXEL_SIZE_UM, MAX_STEP_S, contact_step_s


# Wizard page IDs
PAGE_INTRO = 0
PAGE_ECLIPSE_CONFIG = 1
PAGE_EQUIPMENT = 2
PAGE_PHENOMENA = 3
PAGE_SUMMARY = 4


# ConfigManager, GeocodingWorker, and LocationWidget are imported from location_ui.



def camera_profile_for(wizard, config_manager, camera_name):
    """The camera test result for camera_name: from this session, else the saved one, else None."""
    from solareclipseworkbench.camera_check import CameraProfile
    profiles = getattr(wizard, 'camera_profiles', None) or {}
    if camera_name in profiles:
        return profiles[camera_name]
    if config_manager is not None:
        return CameraProfile.from_dict(config_manager.get_camera_profile(camera_name))
    return None


def store_camera_profile(wizard, config_manager, camera_name, profile):
    """Keep a camera test result for this session, and with the saved camera if there is one."""
    if wizard is not None:
        if getattr(wizard, 'camera_profiles', None) is None:
            wizard.camera_profiles = {}
        wizard.camera_profiles[camera_name] = profile
    if config_manager is not None:
        config_manager.set_camera_profile(camera_name, profile.to_dict())


def run_with_progress(parent, title, text, func):
    """Run func in a background thread behind a modal progress dialog; return its result or raise."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog_layout = QVBoxLayout(dialog)
    bar = QProgressBar()
    bar.setRange(0, 0)
    dialog_layout.addWidget(bar)
    dialog_layout.addWidget(QLabel(text))

    result = {}

    def worker():
        try:
            result['value'] = func()
        except Exception as e:
            logging.exception("%s failed", title)
            result['error'] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    timer = QTimer(dialog)
    timer.timeout.connect(lambda: dialog.accept() if not thread.is_alive() else None)
    timer.start(100)
    dialog.exec()
    thread.join()
    if 'error' in result:
        raise result['error']
    return result.get('value')


def show_test_report(parent, title, report, footer=None):
    """Show a camera test report (camera_check.TestReport) as a list with a mark per item."""
    from html import escape
    symbols = {
        'ok': ('&#10004;', '#2e7d32'),
        'info': ('&#8505;', '#1565c0'),
        'warning': ('&#9888;', '#ef6c00'),
        'error': ('&#10006;', '#c62828'),
    }
    headline = {
        'ok': "Everything is in order.",
        'info': "Everything is in order; see the notes below.",
        'warning': "Check the warnings below.",
        'error': "Problems found: fix the items marked with a cross before the eclipse.",
    }[report.worst]
    rows = []
    for item in report.items:
        symbol, colour = symbols.get(item.status, ('&#8226;', '#000000'))
        detail = f"<br><span style='font-size:small'>{escape(item.detail)}</span>" if item.detail else ""
        rows.append(f"<tr><td style='color:{colour}; font-size:large; padding-right:8px' valign='top'>"
                    f"{symbol}</td><td><b>{escape(item.title)}</b>{detail}</td></tr>")
    if footer:
        rows.append(f"<tr><td></td><td><i>{escape(footer)}</i></td></tr>")

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(640, 560)
    dialog_layout = QVBoxLayout(dialog)
    browser = QTextEdit()
    browser.setReadOnly(True)
    browser.setHtml(f"<p><b>{escape(headline)}</b></p><table cellspacing='4'>{''.join(rows)}</table>")
    dialog_layout.addWidget(browser)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    dialog_layout.addWidget(close_button)
    dialog.exec()


def ask_test_level(parent, title, text, full_text):
    """Ask whether to only read the settings or run the full test.  Returns None (cancel), False or True."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setInformativeText(
        "Check Settings: reads the camera settings.  Nothing is changed on the camera.\n\n"
        "Full Test: " + full_text + "  The test pictures are saved on the memory card.")
    settings_button = box.addButton("Check Settings", QMessageBox.ButtonRole.AcceptRole)
    full_button = box.addButton("Full Test", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(full_button)
    box.exec()
    if box.clickedButton() is full_button:
        return True
    if box.clickedButton() is settings_button:
        return False
    return None


def _sun_above_horizon(timings, time_utc):
    """Whether (part of) the sun is visible above the horizon at the given time.

    Uses the sunrise and sunset of the reference moments, so shots are kept while the sun is partly below the
    horizon, up to the moment its (refracted) upper limb sets, exactly as the sunset shown in the GUI.
    """
    sunrise = timings.get('sunrise') if timings else None
    sunset = timings.get('sunset') if timings else None
    if sunrise is not None and time_utc < sunrise.time_utc:
        return False
    if sunset is not None and time_utc > sunset.time_utc:
        return False
    return True


class IntroPage(QWizardPage):
    """Introduction page for the wizard."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Welcome to Solar Eclipse Workbench Configuration Wizard")
        self.setSubTitle("This wizard will help you create a photography script for your eclipse observation.")
        
        layout = QVBoxLayout()
        
        intro_text = QLabel(
            "This wizard will guide you through the process of creating a customized "
            "photography script for the Solar Eclipse Workbench.\n\n"
            "You will configure:\n"
            "• Eclipse date and location information\n"
            "• Camera and equipment settings\n"
            "• Phenomena to photograph during the eclipse\n"
            "• Voice prompt options\n\n"
            "Click 'Next' to begin."
        )
        intro_text.setWordWrap(True)
        layout.addWidget(intro_text)
        layout.addStretch()
        
        self.setLayout(layout)


class EclipseConfigPage(QWizardPage):
    """Eclipse configuration page - date, location, type."""
    
    # Predefined locations (name: (longitude, latitude, altitude))
    LOCATIONS = {
        "Custom": (None, None, None),
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Eclipse Configuration")
        self.setSubTitle("Select the eclipse you will observe and your location.")
        
        # Get config manager from wizard
        self.config_manager = parent.config_manager if hasattr(parent, 'config_manager') else ConfigManager()
        
        layout = QVBoxLayout()
        
        # Eclipse selection group
        eclipse_group = QGroupBox("Eclipse Selection")
        eclipse_layout = QVBoxLayout()
        
        eclipse_select_layout = QHBoxLayout()
        eclipse_select_layout.addWidget(QLabel("Select Eclipse:"))
        self.eclipse_combo = QComboBox()
        self.eclipse_combo.currentIndexChanged.connect(self._on_eclipse_changed)
        eclipse_select_layout.addWidget(self.eclipse_combo, 1)
        eclipse_layout.addLayout(eclipse_select_layout)
        
        # Eclipse details (read-only info)
        details_layout = QGridLayout()
        details_layout.addWidget(QLabel("Date:"), 0, 0)
        self.eclipse_date_label = QLabel("-")
        details_layout.addWidget(self.eclipse_date_label, 0, 1)
        
        details_layout.addWidget(QLabel("Type:"), 1, 0)
        self.eclipse_type_label = QLabel("-")
        details_layout.addWidget(self.eclipse_type_label, 1, 1)
        
        details_layout.addWidget(QLabel("Magnitude:"), 2, 0)
        self.eclipse_magnitude_label = QLabel("-")
        details_layout.addWidget(self.eclipse_magnitude_label, 2, 1)
        
        eclipse_layout.addLayout(details_layout)
        eclipse_group.setLayout(eclipse_layout)
        layout.addWidget(eclipse_group)
        
        # Location selection group
        location_group = QGroupBox("Observation Location")
        location_layout = QVBoxLayout()

        self.location_widget = LocationWidget(self.config_manager)
        location_layout.addWidget(self.location_widget)

        location_group.setLayout(location_layout)
        layout.addWidget(location_group)
        
        layout.addStretch()
        _content = QWidget()
        _content.setLayout(layout)
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _scroll.setWidget(_content)
        _page_layout = QVBoxLayout()
        _page_layout.setContentsMargins(0, 0, 0, 0)
        _page_layout.addWidget(_scroll)
        self.setLayout(_page_layout)
        
        # Hidden fields for registration
        self.eclipse_date_field = QLineEdit()
        self.eclipse_date_field.setVisible(False)
        self.eclipse_type_field = QLineEdit()
        self.eclipse_type_field.setVisible(False)
        self.eclipse_name_field = QLineEdit()
        self.eclipse_name_field.setVisible(False)
        self.location_name_field = QLineEdit()
        self.location_name_field.setVisible(False)
        
        # Register fields
        self.registerField("eclipse_name*", self.eclipse_name_field)
        self.registerField("eclipse_date*", self.eclipse_date_field)
        self.registerField("eclipse_type", self.eclipse_type_field)
        self.registerField("location", self.location_name_field)
        self.registerField("longitude", self.location_widget.longitude_edit)
        self.registerField("latitude", self.location_widget.latitude_edit)
        self.registerField("altitude", self.location_widget.altitude_edit)
        
        # Initialize - populate eclipses after all UI elements are created
        self._populate_eclipses()
    
    def initializePage(self):
        """Called when the page is shown - ensure eclipse data is loaded."""
        super().initializePage()
        # Re-apply dark stylesheets: QWizard.initializePage() overwrites any
        # stylesheet set on registered field widgets during construction.
        _s = dark_lineedit_style()
        if _s:
            lw = self.location_widget
            for edit in (lw.longitude_edit, lw.latitude_edit, lw.altitude_edit,
                         lw.location_name_edit):
                edit.setStyleSheet(_s)
            if lw.address_search_edit is not None:
                lw.address_search_edit.setStyleSheet(_s)
        # Ensure the first eclipse is selected and fields are populated
        if self.eclipse_combo.count() > 0 and self.eclipse_combo.currentIndex() >= 0:
            # Trigger the change handler to populate hidden fields
            self._on_eclipse_changed(self.eclipse_combo.currentIndex())
    
    def _populate_eclipses(self):
        """Populate the eclipse dropdown with upcoming eclipses."""
        try:
            from solareclipseworkbench.utils import calculate_next_solar_eclipses
            eclipses = calculate_next_solar_eclipses(20)
            
            self.eclipse_data = []
            for eclipse in eclipses:
                eclipse_type = eclipse['type']
                # Convert type codes to full names
                type_map = {
                    'T': 'Total',
                    'A': 'Annular',
                    'H': 'Hybrid',
                    'P': 'Partial'
                }
                type_name = type_map.get(eclipse_type, eclipse_type)
                
                # Format display text
                display_text = f"{eclipse['date']} - {type_name}"
                if eclipse_type in ['T', 'A', 'H']:
                    duration = eclipse['duration']
                    minutes, seconds = divmod(int(duration), 60)
                    display_text += f" - {minutes}m {seconds:02}s"
                else:
                    magnitude_pct = int(eclipse['magnitude'] * 100)
                    display_text += f" - {magnitude_pct}%"
                
                self.eclipse_combo.addItem(display_text)
                self.eclipse_data.append({
                    'date': eclipse['date'],
                    'type': type_name,
                    'magnitude': eclipse['magnitude'],
                    'duration': eclipse['duration']
                })
            
            # Set the first eclipse as selected (this will trigger the signal)
            if self.eclipse_data:
                self.eclipse_combo.setCurrentIndex(0)
                
        except Exception as e:
            # Fallback if eclipse calculation fails
            self.eclipse_combo.addItem("Custom Eclipse")
            self.eclipse_data = []
    
    def _on_eclipse_changed(self, index):
        """Update eclipse details when selection changes."""
        if not hasattr(self, 'eclipse_data') or not self.eclipse_data:
            return
            
        if 0 <= index < len(self.eclipse_data):
            eclipse = self.eclipse_data[index]
            
            # Update display labels
            self.eclipse_date_label.setText(eclipse['date'])
            self.eclipse_type_label.setText(eclipse['type'])
            self.eclipse_magnitude_label.setText(f"{eclipse['magnitude']:.3f}")
            
            # Update hidden fields for registration
            # Convert DD/MM/YYYY to YYYY-MM-DD
            date_parts = eclipse['date'].split('/')
            if len(date_parts) == 3:
                iso_date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
                self.eclipse_date_field.setText(iso_date)
            
            self.eclipse_type_field.setText(eclipse['type'])
            
            # Create eclipse name
            eclipse_name = f"{eclipse['type']} Solar Eclipse {date_parts[2]}"
            self.eclipse_name_field.setText(eclipse_name)
    
    def validatePage(self):
        """Validate page before moving to next."""
        # Check that location coordinates are provided
        if (not self.location_widget.longitude_edit.text()
                or not self.location_widget.latitude_edit.text()
                or not self.location_widget.altitude_edit.text()):
            QMessageBox.warning(
                self,
                "Missing Location Data",
                "Please provide longitude, latitude, and altitude for your observation location."
            )
            return False

        # Update the hidden location field for page registration
        location_name = self.location_widget.location_combo.currentText()
        if location_name.endswith(" (Saved)"):
            location_name = location_name[:-len(" (Saved)")]
        self.location_name_field.setText(location_name)
        if location_name != "Custom":
            self.config_manager.set_last_used_location(location_name)

        return True


class EquipmentPage(QWizardPage):
    """Equipment configuration page - camera and filter settings."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Equipment Configuration")
        self.setSubTitle("Configure your camera and filter settings.")
        
        # Get config manager from wizard
        self.config_manager = parent.config_manager if hasattr(parent, 'config_manager') else ConfigManager()
        
        layout = QVBoxLayout()
        
        # Camera selection
        camera_select_group = QGroupBox("Camera Selection")
        camera_select_layout = QVBoxLayout()
        
        camera_select_h_layout = QHBoxLayout()
        camera_select_h_layout.addWidget(QLabel("Select Camera:"))
        self.camera_select_combo = QComboBox()
        self.camera_select_combo.addItem("New Camera...")
        # Add saved cameras
        for camera in self.config_manager.get_cameras():
            self.camera_select_combo.addItem(camera["name"])
        
        camera_select_h_layout.addWidget(self.camera_select_combo)

        self.delete_camera_btn = QPushButton("Delete Camera")
        self.delete_camera_btn.clicked.connect(self._delete_camera)
        self.delete_camera_btn.setToolTip("Permanently delete this camera from saved configurations")
        self.delete_camera_btn.setEnabled(False)  # Disabled until a saved camera is selected
        camera_select_h_layout.addWidget(self.delete_camera_btn)

        camera_select_layout.addLayout(camera_select_h_layout)
        
        camera_select_group.setLayout(camera_select_layout)
        layout.addWidget(camera_select_group)
        
        # Camera details group
        camera_details_group = QGroupBox("Camera Details")
        camera_details_layout = QVBoxLayout()
        
        # Camera name
        camera_name_layout = QHBoxLayout()
        camera_name_layout.addWidget(QLabel("Camera Name:"))
        self.camera_name_edit = QLineEdit()
        self.camera_name_edit.setPlaceholderText("e.g., Canon EOS 80D, Nikon D850, Sony Alpha A7")
        apply_dark_to_lineedit(self.camera_name_edit)
        # Connect textChanged to update page completeness
        self.camera_name_edit.textChanged.connect(lambda: self.completeChanged.emit())
        self.camera_name_edit.textChanged.connect(self._on_camera_name_changed)
        camera_name_layout.addWidget(self.camera_name_edit)
        
        # Save camera button
        self.save_camera_btn = QPushButton("Save Camera")
        self.save_camera_btn.clicked.connect(self._save_camera)
        self.save_camera_btn.setToolTip("Save this camera configuration for future use")
        camera_name_layout.addWidget(self.save_camera_btn)
        
        camera_details_layout.addLayout(camera_name_layout)

        # Camera ID detection row
        detect_id_layout = QHBoxLayout()
        self.detect_camera_btn = QPushButton("Detect Connected Camera")
        self.detect_camera_btn.setToolTip(
            "Connect a physical camera via USB, then click this button to read its unique "
            "serial number and map it to the camera name above.\n\n"
            "This is required when you use two cameras of the same brand and model "
            "(e.g. two Canon EOS 80D) so that each can be addressed by its own name "
            "in the script.\n\n"
            "If only one camera of each model is used, you can skip this step."
        )
        self.detect_camera_btn.clicked.connect(self._detect_camera_id)
        detect_id_layout.addWidget(self.detect_camera_btn)

        self.camera_id_label = QLabel("")
        self.camera_id_label.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")
        self.camera_id_label.setWordWrap(True)
        detect_id_layout.addWidget(self.camera_id_label, 1)
        camera_details_layout.addLayout(detect_id_layout)

        # Camera test: what the camera offers and how fast it is, used to fit the script
        test_layout = QHBoxLayout()
        self.test_camera_btn = QPushButton("Test Camera...")
        self.test_camera_btn.setToolTip(
            "Connect the camera (with the lens you will use) via USB and click this button.\n\n"
            "The wizard reads the shutter speeds, ISO values and apertures the camera offers and, in the "
            "full test, measures how long a picture and a burst take and checks that the camera clock can "
            "be set.  The generated script is then fitted to this camera.  The result is saved with the "
            "camera configuration, so this is only needed once per camera and lens."
        )
        self.test_camera_btn.clicked.connect(self._test_camera)
        test_layout.addWidget(self.test_camera_btn)
        self.camera_test_label = QLabel("")
        self.camera_test_label.setWordWrap(True)
        test_layout.addWidget(self.camera_test_label, 1)
        camera_details_layout.addLayout(test_layout)

        camera_details_group.setLayout(camera_details_layout)
        layout.addWidget(camera_details_group)
        
        # Lens configuration
        lens_group = QGroupBox("Lens / Telescope Configuration")
        lens_layout = QGridLayout()
        
        lens_info = QLabel(
            "Lens specifications are used to calculate optimal camera settings for different eclipse phases, "
            "especially for corona photography."
        )
        lens_info.setWordWrap(True)
        lens_info.setStyleSheet("QLabel { color: #555; font-style: italic; }")
        lens_layout.addWidget(lens_info, 0, 0, 1, 3)
        
        # Focal length
        lens_layout.addWidget(QLabel("Focal Length:"), 1, 0)
        self.focal_length_spin = QSpinBox()
        self.focal_length_spin.setRange(10, 5000)
        self.focal_length_spin.setValue(400)
        self.focal_length_spin.setSuffix(" mm")
        self.focal_length_spin.setToolTip("Focal length of your lens or telescope (e.g., 400mm, 800mm)")
        lens_layout.addWidget(self.focal_length_spin, 1, 1)
        
        # Aperture range
        lens_layout.addWidget(QLabel("Aperture Range:"), 2, 0)
        
        aperture_range_layout = QHBoxLayout()
        aperture_range_layout.addWidget(QLabel("f/"))
        self.aperture_min_spin = QDoubleSpinBox()
        self.aperture_min_spin.setRange(1.0, 64.0)
        self.aperture_min_spin.setValue(5.6)
        self.aperture_min_spin.setSingleStep(0.1)
        self.aperture_min_spin.setDecimals(1)
        self.aperture_min_spin.setToolTip("Minimum f-number (widest aperture, e.g., f/2.8)")
        aperture_range_layout.addWidget(self.aperture_min_spin)
        
        aperture_range_layout.addWidget(QLabel("to f/"))
        self.aperture_max_spin = QDoubleSpinBox()
        self.aperture_max_spin.setRange(1.0, 64.0)
        self.aperture_max_spin.setValue(8.0)
        self.aperture_max_spin.setSingleStep(0.1)
        self.aperture_max_spin.setDecimals(1)
        self.aperture_max_spin.setToolTip("Maximum f-number (smallest aperture, e.g., f/22)")
        aperture_range_layout.addWidget(self.aperture_max_spin)
        aperture_range_layout.addStretch()
        
        aperture_range_widget = QWidget()
        aperture_range_widget.setLayout(aperture_range_layout)
        lens_layout.addWidget(aperture_range_widget, 2, 1)

        # Pixel size: with the focal length, it sets how soon the Moon's bite shows after C1
        lens_layout.addWidget(QLabel("Pixel Size:"), 3, 0)
        self.pixel_size_spin = QDoubleSpinBox()
        self.pixel_size_spin.setRange(1.0, 20.0)
        self.pixel_size_spin.setValue(DEFAULT_PIXEL_SIZE_UM)
        self.pixel_size_spin.setSingleStep(0.1)
        self.pixel_size_spin.setDecimals(2)
        self.pixel_size_spin.setSuffix(" µm")
        self.pixel_size_spin.setToolTip(
            "Size of one pixel on the camera sensor: the sensor width in mm divided by the image width in "
            "pixels, times 1000 (e.g. 35.9 mm / 7952 px = 4.5 µm for a Sony A7R III).  Typical values: "
            "4.4-6 µm for full frame, 3.7-4.3 µm for APS-C.  Used with the focal length to time the first "
            "and fourth contact shots.")
        lens_layout.addWidget(self.pixel_size_spin, 3, 1)
        
        lens_note = QLabel("Note: For telescopes, min and max aperture are often the same (e.g., f/6).")
        lens_note.setWordWrap(True)
        lens_note.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")
        lens_layout.addWidget(lens_note, 4, 0, 1, 3)
        
        lens_group.setLayout(lens_layout)
        layout.addWidget(lens_group)
        
        # ISO settings
        iso_group = QGroupBox("ISO Settings")
        iso_layout = QGridLayout()
        
        iso_info = QLabel(
            "ISO settings affect the camera sensor sensitivity and influence optimal shutter speeds. "
            "The wizard will calculate appropriate exposures based on your preferred ISO value."
        )
        iso_info.setWordWrap(True)
        iso_info.setStyleSheet("QLabel { color: #555; font-style: italic; }")
        iso_layout.addWidget(iso_info, 0, 0, 1, 3)
        
        # Preferred ISO
        iso_layout.addWidget(QLabel("Preferred ISO:"), 1, 0)
        self.preferred_iso_combo = QComboBox()
        self.preferred_iso_combo.addItems(["100", "200", "400", "800", "1600", "3200", "6400"])
        self.preferred_iso_combo.setCurrentText("400")
        self.preferred_iso_combo.setToolTip("Your preferred ISO value for eclipse photography")
        iso_layout.addWidget(self.preferred_iso_combo, 1, 1)
        
        # ISO range for bracketing
        iso_layout.addWidget(QLabel("ISO Range (for bracketing):"), 2, 0)
        
        iso_range_layout = QHBoxLayout()
        iso_range_layout.addWidget(QLabel("From ISO"))
        self.iso_min_combo = QComboBox()
        self.iso_min_combo.addItems(["100", "200", "400", "800", "1600", "3200", "6400"])
        self.iso_min_combo.setCurrentText("100")
        self.iso_min_combo.setToolTip("Minimum ISO for exposure bracketing")
        iso_range_layout.addWidget(self.iso_min_combo)
        
        iso_range_layout.addWidget(QLabel("to ISO"))
        self.iso_max_combo = QComboBox()
        self.iso_max_combo.addItems(["100", "200", "400", "800", "1600", "3200", "6400"])
        self.iso_max_combo.setCurrentText("1600")
        self.iso_max_combo.setToolTip("Maximum ISO for exposure bracketing")
        iso_range_layout.addWidget(self.iso_max_combo)
        iso_range_layout.addStretch()
        
        iso_range_widget = QWidget()
        iso_range_widget.setLayout(iso_range_layout)
        iso_layout.addWidget(iso_range_widget, 2, 1)
        
        iso_note = QLabel("Note: Bracketing range is used for suggestions; preferred ISO is used for calculations.")
        iso_note.setWordWrap(True)
        iso_note.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")
        iso_layout.addWidget(iso_note, 3, 0, 1, 3)
        
        iso_group.setLayout(iso_layout)
        layout.addWidget(iso_group)
        
        # Camera sync
        sync_group = QGroupBox("Camera Synchronization")
        sync_layout = QVBoxLayout()
        
        self.sync_enabled_check = QCheckBox("Enable periodic camera synchronization")
        self.sync_enabled_check.stateChanged.connect(self._on_sync_enabled_changed)
        sync_layout.addWidget(self.sync_enabled_check)
        
        # Info text
        sync_info = QLabel(
            "Camera synchronization checks battery level and available disk space. "
            "Sync commands are scheduled during gaps between other commands (when there "
            "is at least 10 seconds of free time)."
        )
        sync_info.setWordWrap(True)
        sync_info.setStyleSheet("QLabel { color: #555; font-style: italic; margin-left: 20px; }")
        sync_layout.addWidget(sync_info)
        
        # Sync interval
        sync_interval_widget = QWidget()
        sync_interval_layout = QHBoxLayout()
        sync_interval_layout.setContentsMargins(20, 5, 0, 0)
        
        sync_interval_layout.addWidget(QLabel("Sync interval:"))
        self.sync_interval_combo = QComboBox()
        self.sync_interval_combo.addItems(["5 minutes", "15 minutes", "30 minutes"])
        self.sync_interval_combo.setCurrentIndex(1)  # Default to 15 minutes
        self.sync_interval_combo.setEnabled(False)
        sync_interval_layout.addWidget(self.sync_interval_combo)
        sync_interval_layout.addStretch()
        
        sync_interval_widget.setLayout(sync_interval_layout)
        sync_layout.addWidget(sync_interval_widget)
        
        sync_group.setLayout(sync_layout)
        layout.addWidget(sync_group)
        
        layout.addStretch()
        _content = QWidget()
        _content.setLayout(layout)
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _scroll.setWidget(_content)
        _page_layout = QVBoxLayout()
        _page_layout.setContentsMargins(0, 0, 0, 0)
        _page_layout.addWidget(_scroll)
        self.setLayout(_page_layout)
        
        # Register fields
        self.registerField("camera_name*", self.camera_name_edit)
        self.registerField("focal_length", self.focal_length_spin, "value")
        self.registerField("pixel_size", self.pixel_size_spin, "value")
        self.registerField("aperture_min", self.aperture_min_spin, "value")
        self.registerField("aperture_max", self.aperture_max_spin, "value")
        self.registerField("preferred_iso", self.preferred_iso_combo, "currentText")
        self.registerField("iso_min", self.iso_min_combo, "currentText")
        self.registerField("iso_max", self.iso_max_combo, "currentText")
        self.registerField("sync_enabled", self.sync_enabled_check)
        self.registerField("sync_interval", self.sync_interval_combo, "currentText")
        
        # NOW connect signal and set initial value (after all widgets exist)
        self.camera_select_combo.currentTextChanged.connect(self._on_camera_selected)
        
        # Select last used camera if available
        last_camera = self.config_manager.get_last_used_camera()
        if last_camera:
            index = self.camera_select_combo.findText(last_camera)
            if index >= 0:
                self.camera_select_combo.setCurrentIndex(index)
    
    def _on_camera_selected(self, camera_name):
        """Load selected camera configuration."""
        is_saved = camera_name != "New Camera..."
        self.delete_camera_btn.setEnabled(is_saved)

        if camera_name == "New Camera...":
            # Clear all fields
            self.camera_name_edit.clear()
            self.focal_length_spin.setValue(400)
            self.pixel_size_spin.setValue(DEFAULT_PIXEL_SIZE_UM)
            self.aperture_min_spin.setValue(5.6)
            self.aperture_max_spin.setValue(8.0)
            self.preferred_iso_combo.setCurrentText("400")
            self.iso_min_combo.setCurrentText("100")
            self.iso_max_combo.setCurrentText("1600")
            self.camera_name_edit.setReadOnly(False)
            self.camera_name_edit.setStyleSheet("")
        else:
            # Load camera configuration
            camera = self.config_manager.get_camera(camera_name)
            if camera:
                self.camera_name_edit.setText(camera["name"])
                self.focal_length_spin.setValue(camera["focal_length"])
                # Entered on this page, or else found by Test Camera
                self.pixel_size_spin.setValue(camera.get("pixel_size")
                                              or (camera.get("profile") or {}).get("pixel_size_um")
                                              or DEFAULT_PIXEL_SIZE_UM)
                self.aperture_min_spin.setValue(camera["aperture_min"])
                self.aperture_max_spin.setValue(camera["aperture_max"])
                
                # Set ISO values (with defaults for backward compatibility)
                self.preferred_iso_combo.setCurrentText(str(camera.get("preferred_iso", 400)))
                self.iso_min_combo.setCurrentText(str(camera.get("iso_min", 100)))
                self.iso_max_combo.setCurrentText(str(camera.get("iso_max", 1600)))
                
                # Make camera name read-only for saved cameras (not disabled, so validation works)
                self.camera_name_edit.setReadOnly(True)
                self.camera_name_edit.setStyleSheet("QLineEdit:read-only { background-color: #f0f0f0; }")
        
        # Refresh camera-ID and camera test status labels
        self._refresh_camera_id_label(self.camera_name_edit.text().strip())
        self._refresh_camera_test_label(self.camera_name_edit.text().strip())
        # Emit signal to re-validate page completeness
        self.completeChanged.emit()
    
    def _save_camera(self):
        """Save current camera configuration."""
        camera_name = self.camera_name_edit.text().strip()
        if not camera_name:
            QMessageBox.warning(self, "Invalid Camera Name", "Please enter a camera name.")
            return
        
        # Save camera (filter is now on phenomena page, use default 5.0 for backward compatibility)
        self.config_manager.add_camera(
            name=camera_name,
            focal_length=self.focal_length_spin.value(),
            pixel_size=self.pixel_size_spin.value(),
            aperture_min=self.aperture_min_spin.value(),
            aperture_max=self.aperture_max_spin.value(),
            filter_nd="5.0",  # Default value for backward compatibility
            preferred_iso=int(self.preferred_iso_combo.currentText()),
            iso_min=int(self.iso_min_combo.currentText()),
            iso_max=int(self.iso_max_combo.currentText())
        )
        
        # Update combo box if this is a new camera
        if self.camera_select_combo.findText(camera_name) < 0:
            self.camera_select_combo.addItem(camera_name)
            self.camera_select_combo.setCurrentText(camera_name)
        
        # Keep a camera test result that was obtained before the camera was saved
        profile = camera_profile_for(self.wizard(), self.config_manager, camera_name)
        if profile is not None:
            self.config_manager.set_camera_profile(camera_name, profile.to_dict())

        # Set as last used
        self.config_manager.set_last_used_camera(camera_name)
        
        QMessageBox.information(self, "Camera Saved", f"Camera '{camera_name}' has been saved.")
        
        # Make camera name read-only after saving (not disabled, so validation works)
        self.camera_name_edit.setReadOnly(True)
        self.camera_name_edit.setStyleSheet("QLineEdit:read-only { background-color: #f0f0f0; }")

    def _delete_camera(self):
        """Delete the currently selected camera from saved configurations."""
        camera_name = self.camera_select_combo.currentText()
        if camera_name == "New Camera...":
            return

        reply = QMessageBox.question(
            self,
            "Delete Camera",
            f"Are you sure you want to delete '{camera_name}'?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.config_manager.delete_camera(camera_name):
            index = self.camera_select_combo.findText(camera_name)
            if index >= 0:
                self.camera_select_combo.removeItem(index)
            # Reset to "New Camera..."
            self.camera_select_combo.setCurrentIndex(0)

    def _on_camera_name_changed(self, text: str):
        """Update the camera-ID status label whenever the camera name changes."""
        self._refresh_camera_id_label(text.strip())
        self._refresh_camera_test_label(text.strip())

    def _refresh_camera_test_label(self, camera_name: str):
        """Show whether the camera has been tested, and what the test found."""
        profile = camera_profile_for(self.wizard(), self.config_manager, camera_name) if camera_name else None
        if profile is None:
            self.camera_test_label.setText(
                "Not tested: the script will use standard shutter speeds and estimated timing.  "
                "Connect the camera and click 'Test Camera...' to fit the script to it.")
            self.camera_test_label.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")
        else:
            self.camera_test_label.setText(f"Tested ✓ on {profile.summary()}")
            self.camera_test_label.setStyleSheet("QLabel { color: #4a8; font-size: 9pt; }")

    def _test_camera(self):
        """Test the connected camera and keep the result for generating the script."""
        from solareclipseworkbench.camera_check import WARNING, check_camera

        try:
            from solareclipseworkbench.camera import detect_cameras, get_camera_by_port
            detected = detect_cameras()
        except Exception as exc:
            QMessageBox.critical(self, "Detection Failed", f"Could not detect cameras via gphoto2:\n{exc}")
            return
        if not detected:
            QMessageBox.information(self, "No Camera Found",
                                    "No camera was detected.  Connect the camera via USB, switch it on and try "
                                    "again.  Close Solar Eclipse Workbench if it is running.")
            return
        if len(detected) > 1:
            model_list = "\n".join(f"  • {m} ({p})" for m, p in detected)
            QMessageBox.warning(self, "Multiple Cameras Connected",
                                f"More than one camera was detected:\n{model_list}\n\n"
                                "Disconnect all cameras except the one to test, then try again.")
            return
        model_name, port = detected[0]
        camera_name = self.camera_name_edit.text().strip() or model_name

        full = ask_test_level(
            self, "Test Camera",
            f"Test the connected {model_name} for '{camera_name}'?  Mount the lens you will use: "
            "the available apertures depend on it.",
            "also sets the camera clock and checks the result, and takes one test picture and one test "
            "burst to measure how long the camera needs for them.")
        if full is None:
            return

        def run():
            cam = get_camera_by_port(model_name, port)
            try:
                return check_camera(cam, full=full)
            finally:
                try:
                    cam.disconnect()
                except Exception:
                    pass

        self.test_camera_btn.setEnabled(False)
        try:
            report, profile = run_with_progress(
                self, "Testing Camera",
                "Running the full test (test picture and burst)..." if full else "Reading the camera settings...",
                run)
        except Exception as e:
            QMessageBox.critical(self, "Camera Test Failed",
                                 f"The camera could not be tested:\n{e}\n\nCheck that it is switched on and that "
                                 "no other program (such as Solar Eclipse Workbench) is using it.")
            return
        finally:
            self.test_camera_btn.setEnabled(True)

        # Compare the limits entered on this page with what the camera and lens offer.
        if profile.apertures:
            low, high = profile.apertures[0], profile.apertures[-1]
            if self.aperture_min_spin.value() < low - 0.05 or self.aperture_max_spin.value() > high + 0.05:
                report.add(WARNING, "The aperture range on this page is outside the lens range",
                           f"This page says f/{self.aperture_min_spin.value():g}–f/{self.aperture_max_spin.value():g}, "
                           f"the lens offers f/{low:g}–f/{high:g}.  The script uses the nearest available aperture.")
        if profile.isos:
            iso_min, iso_max = int(self.iso_min_combo.currentText()), int(self.iso_max_combo.currentText())
            if iso_min < min(profile.isos) or iso_max > max(profile.isos):
                report.add(WARNING, "The ISO range on this page is outside the camera range",
                           f"This page says ISO {iso_min}–{iso_max}, the camera offers ISO "
                           f"{min(profile.isos)}–{max(profile.isos)}.")

        if profile.pixel_size_um is not None:
            self.pixel_size_spin.setValue(profile.pixel_size_um)

        if not self.camera_name_edit.text().strip():
            self.camera_name_edit.setText(camera_name)
        store_camera_profile(self.wizard(), self.config_manager, camera_name, profile)
        self._refresh_camera_test_label(camera_name)
        footer = ("The script will be fitted to this camera.  Save the camera to keep this result."
                  if self.config_manager.get_camera(camera_name) is None
                  else "The script will be fitted to this camera; the result is saved with the camera.")
        show_test_report(self, f"Camera Test: {camera_name}", report, footer)

    def _refresh_camera_id_label(self, camera_name: str):
        """Show whether *camera_name* already has a serial number mapped to it."""
        if not camera_name:
            self.camera_id_label.setText("")
            return
        serial = self.config_manager.get_serial_for_alias(camera_name)
        if serial:
            self.camera_id_label.setText(f"Camera ID mapped ✓  (serial: {serial})")
            self.camera_id_label.setStyleSheet("QLabel { color: #4a8; font-size: 9pt; }")
        else:
            self.camera_id_label.setText(
                "No camera ID mapped yet — only needed when two cameras of the same model are used,"
                " or when the same camera is saved under multiple configuration names."
            )
            self.camera_id_label.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")

    def _detect_camera_id(self):
        """Read the serial number of a connected camera and link it to the current camera name.

        When no camera name has been entered yet (i.e. the user is on 'New Camera...'),
        detection still runs and the detected model name is used to auto-populate the
        camera-name field.  Serial mapping is skipped in that case — the user can click
        'Detect Connected Camera' again (after optionally renaming) if they want to map
        the serial (only needed when two cameras of the same model are used simultaneously).
        """
        from PyQt6.QtWidgets import QApplication

        camera_name = self.camera_name_edit.text().strip()
        # NOTE: we intentionally do NOT bail out early when camera_name is empty —
        # detection must work for 'New Camera...' so the user can discover what is
        # connected and have the name field auto-populated.

        # Give visual feedback while detecting
        self.detect_camera_btn.setEnabled(False)
        self.detect_camera_btn.setText("Detecting…")
        QApplication.processEvents()

        try:
            from solareclipseworkbench.camera import detect_cameras, get_camera_by_port, get_serial_number
            detected = detect_cameras()
        except Exception as exc:
            self.detect_camera_btn.setEnabled(True)
            self.detect_camera_btn.setText("Detect Connected Camera")
            QMessageBox.critical(
                self, "Detection Failed",
                f"Could not detect cameras via gphoto2:\n{exc}\n\n"
                "Make sure your camera is connected and gphoto2 is installed."
            )
            return
        finally:
            self.detect_camera_btn.setEnabled(True)
            self.detect_camera_btn.setText("Detect Connected Camera")

        if not detected:
            msg = (
                "No cameras were detected.\n\n"
                f"Please connect the camera you want to map to '{camera_name}' and try again."
                if camera_name else
                "No cameras were detected.\n\n"
                "Please connect your camera via USB and try again."
            )
            QMessageBox.information(self, "No Camera Found", msg)
            return

        if len(detected) > 1:
            # Ask the user to disconnect all but one camera
            model_list = "\n".join(f"  • {m} ({p})" for m, p in detected)
            target_hint = (
                f"the one you want to map to '{camera_name}'"
                if camera_name else
                "the one you want to use"
            )
            QMessageBox.warning(
                self, "Multiple Cameras Connected",
                f"More than one camera was detected:\n{model_list}\n\n"
                f"Please disconnect all cameras except {target_hint}, "
                "then click 'Detect Connected Camera' again."
            )
            return

        # Exactly one camera connected.
        model_name, port = detected[0]

        # --- No camera name yet: auto-populate from model and return early ---
        if not camera_name:
            self.camera_name_edit.setText(model_name)
            self.camera_name_edit.setReadOnly(False)
            self.camera_name_edit.setStyleSheet("")
            self._refresh_camera_id_label(model_name)
            QMessageBox.information(
                self, "Camera Detected",
                f"Detected camera:  {model_name}\n\n"
                "The camera name has been set to the detected model name.\n"
                "You can rename it in the 'Camera Name' field above.\n\n"
                "If you use two cameras of the same model at the same time, "
                "enter a unique name for this camera and click "
                "'Detect Connected Camera' again to map its serial number."
            )
            return

        # --- Camera name already set: proceed with serial-number mapping ---
        self.detect_camera_btn.setEnabled(False)
        self.detect_camera_btn.setText("Reading serial…")
        QApplication.processEvents()

        try:
            cam = get_camera_by_port(model_name, port)
            serial = get_serial_number(cam)
            try:
                cam.disconnect()
            except Exception:
                pass
        except Exception as exc:
            self.detect_camera_btn.setEnabled(True)
            self.detect_camera_btn.setText("Detect Connected Camera")
            QMessageBox.critical(
                self, "Connection Failed",
                f"Could not open the camera '{model_name}':\n{exc}"
            )
            return
        finally:
            self.detect_camera_btn.setEnabled(True)
            self.detect_camera_btn.setText("Detect Connected Camera")

        if not serial:
            QMessageBox.warning(
                self, "Serial Number Unavailable",
                f"The camera '{model_name}' was detected, but its serial number "
                "could not be read via gphoto2.\n\n"
                "Without a serial number, duplicate cameras of the same model cannot "
                "be distinguished automatically.  The camera name will still be used "
                "as-is (existing behaviour)."
            )
            return

        # Confirm with the user before storing the mapping
        reply = QMessageBox.question(
            self,
            "Map Camera ID",
            f"Detected:  {model_name}\n"
            f"Serial:    {serial}\n\n"
            f"Map this camera to the name '{camera_name}'?\n\n"
            "When SEW starts, it will look up this serial number on the connected "
            "cameras and use '{camera_name}' as the key — matching what is written "
            "in your script.".format(camera_name=camera_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.config_manager.set_camera_alias(serial, camera_name)
        self._refresh_camera_id_label(camera_name)
        QMessageBox.information(
            self, "Camera ID Saved",
            f"Camera '{camera_name}' is now linked to serial number {serial}.\n\n"
            "When SEW starts with this camera connected, it will be recognised as "
            f"'{camera_name}' — matching the name used in your script.\n\n"
            "You can register the same camera body under additional names "
            "(e.g. for different equipment setups like telescope vs. lens) by "
            "entering the next name and clicking 'Detect Connected Camera' again."
        )

    def _on_sync_enabled_changed(self, state):
        """Enable/disable camera sync interval selection."""
        enabled = state == Qt.CheckState.Checked.value
        self.sync_interval_combo.setEnabled(enabled)
    
    def initializePage(self):
        """Called when the page is shown - ensure camera data is loaded."""
        super().initializePage()
        # Re-apply dark stylesheet: QWizard overwrites it on registered fields.
        self.camera_name_edit.setStyleSheet(dark_lineedit_style())
        # If a camera is selected, trigger the selection handler to ensure fields are populated
        current_camera = self.camera_select_combo.currentText()
        if current_camera and current_camera != "New Camera...":
            self._on_camera_selected(current_camera)
    
    def isComplete(self):
        """Override to check if page is complete - handle read-only camera name field."""
        # Check if camera name field has text (required field)
        camera_name = self.camera_name_edit.text().strip()
        return len(camera_name) > 0
    
    def validatePage(self):
        """Validate page and save last used camera."""
        # Save last used camera if not "New Camera..."
        camera_name = self.camera_select_combo.currentText()
        if camera_name != "New Camera...":
            self.config_manager.set_last_used_camera(camera_name)
        
        return True


class PhenomenaPage(QWizardPage):
    """Phenomena selection page - what to photograph during eclipse."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Select Phenomena to Photograph")
        self.setSubTitle("Choose which eclipse phenomena you want to photograph.")
        
        layout = QVBoxLayout()
        
        phenomena_group = QGroupBox("Phenomena Selection")
        phenomena_layout = QVBoxLayout()
        
        # First and Fourth contacts
        self.c1_c4_check = QCheckBox("First (C1) and Fourth (C4) contacts")
        self.c1_c4_check.setChecked(True)
        phenomena_layout.addWidget(self.c1_c4_check)

        # Step of the contact shots: C1 - step, C1, C1 + step (and the same around C4)
        contact_step_layout = QHBoxLayout()
        contact_step_layout.setContentsMargins(20, 0, 0, 0)
        contact_step_layout.addWidget(QLabel("Shots at C1/C4 ± step:"))
        self.contact_step_auto_check = QCheckBox("Automatic")
        self.contact_step_auto_check.setChecked(True)
        self.contact_step_auto_check.setToolTip(
            "Nothing is visible at C1 itself: the Moon's bite shows once it is a couple of pixels deep.  "
            "Automatic works out when that is from the focal length and pixel size on the equipment page "
            "(tens of seconds with a short lens, a few seconds with a telescope).  The shot after C1 (and "
            "before C4) then shows the first (last) bite, the shot before C1 (after C4) the whole Sun.")
        contact_step_layout.addWidget(self.contact_step_auto_check)
        self.contact_step_spin = QSpinBox()
        self.contact_step_spin.setRange(2, MAX_STEP_S)
        self.contact_step_spin.setValue(30)
        self.contact_step_spin.setSuffix(" s")
        self.contact_step_spin.setToolTip("Seconds between the contact shots, when not automatic")
        contact_step_layout.addWidget(self.contact_step_spin)
        contact_step_layout.addStretch()
        phenomena_layout.addLayout(contact_step_layout)

        def _update_contact_step():
            enabled = self.c1_c4_check.isChecked()
            self.contact_step_auto_check.setEnabled(enabled)
            self.contact_step_spin.setEnabled(enabled and not self.contact_step_auto_check.isChecked())
        self.c1_c4_check.toggled.connect(_update_contact_step)
        self.contact_step_auto_check.toggled.connect(_update_contact_step)
        _update_contact_step()
        
        # Equispaced filter
        self.equispaced_check = QCheckBox("Equispaced shots during partial phases with filter")
        self.equispaced_check.setChecked(True)
        phenomena_layout.addWidget(self.equispaced_check)
        
        # Diamond rings
        self.diamond_check = QCheckBox("Diamond rings (C2 and C3)")
        self.diamond_check.setChecked(True)
        phenomena_layout.addWidget(self.diamond_check)
        
        # Baily's beads
        self.bailys_check = QCheckBox("Baily's beads")
        self.bailys_check.setChecked(True)
        phenomena_layout.addWidget(self.bailys_check)
        
        # Chromosphere
        self.chromosphere_check = QCheckBox("Chromosphere")
        self.chromosphere_check.setChecked(True)
        phenomena_layout.addWidget(self.chromosphere_check)
        
        # Prominences
        self.prominences_check = QCheckBox("Prominences")
        self.prominences_check.setChecked(True)
        phenomena_layout.addWidget(self.prominences_check)
        
        # Earthshine (moon's dark surface)
        self.earthshine_check = QCheckBox("Earthshine (visible during totality)")
        self.earthshine_check.setChecked(False)
        phenomena_layout.addWidget(self.earthshine_check)
        
        # Corona
        self.corona_check = QCheckBox("Solar corona series (inner/outer corona, auto-scheduled throughout totality)")
        self.corona_check.setChecked(True)
        self.corona_check.stateChanged.connect(self._on_bracket_changed)
        phenomena_layout.addWidget(self.corona_check)

        # Bracket each corona exposure (take_bracket)
        self.bracket_check = QCheckBox("Bracket each corona exposure (take_bracket)")
        self.bracket_check.setChecked(False)
        self.bracket_check.stateChanged.connect(self._on_bracket_changed)
        phenomena_layout.addWidget(self.bracket_check)

        bracket_widget = QWidget()
        bracket_layout = QHBoxLayout()
        bracket_layout.setContentsMargins(20, 0, 0, 0)
        bracket_layout.addWidget(QLabel("Step:"))
        self.bracket_step_combo = QComboBox()
        self.bracket_step_combo.setToolTip("Exposure difference between successive frames of the bracket")
        self.bracket_step_combo.currentTextChanged.connect(self._on_bracket_step_changed)
        bracket_layout.addWidget(self.bracket_step_combo)
        bracket_layout.addWidget(QLabel("EV"))
        bracket_layout.addSpacing(12)
        bracket_layout.addWidget(QLabel("Frames:"))
        self.bracket_frames_combo = QComboBox()
        self.bracket_frames_combo.setToolTip("Number of frames, centred on the corona exposure")
        self.bracket_frames_combo.currentTextChanged.connect(self._refresh_bracket_note)
        bracket_layout.addWidget(self.bracket_frames_combo)
        bracket_layout.addStretch()
        bracket_widget.setLayout(bracket_layout)
        phenomena_layout.addWidget(bracket_widget)

        self.bracket_note = QLabel()
        self.bracket_note.setWordWrap(True)
        self.bracket_note.setContentsMargins(20, 0, 0, 0)
        self.bracket_note.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")
        phenomena_layout.addWidget(self.bracket_note)
        self._bracket_options = {}      # step label -> numbers of frames
        self._bracket_source = None     # CameraProfile the options were read from, or None

        # HDR burst at maximum eclipse
        self.hdr_check = QCheckBox("HDR burst at maximum eclipse (take_hdr)")
        self.hdr_check.setChecked(False)
        self.hdr_check.stateChanged.connect(self._on_hdr_changed)
        phenomena_layout.addWidget(self.hdr_check)

        hdr_stops_widget = QWidget()
        hdr_stops_layout = QHBoxLayout()
        hdr_stops_layout.setContentsMargins(20, 0, 0, 0)
        hdr_stops_layout.addWidget(QLabel("Number of stops to ramp:"))
        self.hdr_stops_spin = QSpinBox()
        self.hdr_stops_spin.setRange(2, 16)
        self.hdr_stops_spin.setValue(7)
        self.hdr_stops_spin.setSuffix(" stops")
        self.hdr_stops_spin.setEnabled(False)
        hdr_stops_layout.addWidget(self.hdr_stops_spin)
        hdr_stops_layout.addStretch()
        hdr_stops_widget.setLayout(hdr_stops_layout)
        phenomena_layout.addWidget(hdr_stops_widget)

        # HDR sequence: up and back down again, or only up (fewer shots)
        hdr_sequence_widget = QWidget()
        hdr_sequence_layout = QHBoxLayout()
        hdr_sequence_layout.setContentsMargins(20, 0, 0, 0)
        hdr_sequence_layout.addWidget(QLabel("Sequence:"))
        self.hdr_round_trip_radio = QRadioButton("Round trip (short → long → short)")
        self.hdr_one_way_radio = QRadioButton("One way (short → long, fewer shots)")
        self.hdr_round_trip_radio.setToolTip("2 × stops + 1 shots; the longest exposure is taken once")
        self.hdr_one_way_radio.setToolTip("stops + 1 shots, faster for a short totality.  A Sony takes it with its "
                                          "own bracketing when it has a 1 EV mode with that many frames.")
        self.hdr_round_trip_radio.setChecked(True)
        self.hdr_round_trip_radio.setEnabled(False)
        self.hdr_one_way_radio.setEnabled(False)
        self.hdr_sequence_button_group = QButtonGroup(self)
        self.hdr_sequence_button_group.addButton(self.hdr_round_trip_radio)
        self.hdr_sequence_button_group.addButton(self.hdr_one_way_radio)
        hdr_sequence_layout.addWidget(self.hdr_round_trip_radio)
        hdr_sequence_layout.addWidget(self.hdr_one_way_radio)
        hdr_sequence_layout.addStretch()
        hdr_sequence_widget.setLayout(hdr_sequence_layout)
        phenomena_layout.addWidget(hdr_sequence_widget)

        # HDR starting shutter speed (auto-calculate or manual)
        hdr_start_widget = QWidget()
        hdr_start_layout = QHBoxLayout()
        hdr_start_layout.setContentsMargins(20, 0, 0, 0)
        hdr_start_layout.addWidget(QLabel("Starting shutter speed:"))
        self.hdr_start_auto_radio = QRadioButton("Auto-calculate")
        self.hdr_start_manual_radio = QRadioButton("Manual:")
        self.hdr_start_auto_radio.setChecked(True)
        self.hdr_start_auto_radio.setEnabled(False)
        self.hdr_start_manual_radio.setEnabled(False)
        self.hdr_start_button_group = QButtonGroup(self)
        self.hdr_start_button_group.addButton(self.hdr_start_auto_radio)
        self.hdr_start_button_group.addButton(self.hdr_start_manual_radio)
        hdr_start_layout.addWidget(self.hdr_start_auto_radio)
        hdr_start_layout.addWidget(self.hdr_start_manual_radio)
        self.hdr_start_speed_combo = QComboBox()
        self.hdr_start_speed_combo.addItems([
            "1/8000", "1/6400", "1/5000", "1/4000", "1/3200", "1/2500", "1/2000",
            "1/1600", "1/1250", "1/1000", "1/800", "1/640", "1/500", "1/400",
            "1/320", "1/250", "1/200", "1/160", "1/125", "1/100", "1/80", "1/60",
            "1/50", "1/40", "1/30", "1/25", "1/20", "1/15", "1/13", "1/10",
            "1/8", "1/6", "1/5", "1/4",
        ])
        self.hdr_start_speed_combo.setCurrentText("1/1000")
        self.hdr_start_speed_combo.setEnabled(False)
        hdr_start_layout.addWidget(self.hdr_start_speed_combo)
        hdr_start_layout.addStretch()
        hdr_start_widget.setLayout(hdr_start_layout)
        phenomena_layout.addWidget(hdr_start_widget)
        self.hdr_start_auto_radio.toggled.connect(self._on_hdr_start_changed)

        # HDR ISO (auto-calculate or manual)
        hdr_iso_widget = QWidget()
        hdr_iso_layout = QHBoxLayout()
        hdr_iso_layout.setContentsMargins(20, 0, 0, 0)
        hdr_iso_layout.addWidget(QLabel("ISO:"))
        self.hdr_iso_auto_radio = QRadioButton("Auto-calculate")
        self.hdr_iso_manual_radio = QRadioButton("Manual:")
        self.hdr_iso_auto_radio.setChecked(True)
        self.hdr_iso_auto_radio.setEnabled(False)
        self.hdr_iso_manual_radio.setEnabled(False)
        self.hdr_iso_button_group = QButtonGroup(self)
        self.hdr_iso_button_group.addButton(self.hdr_iso_auto_radio)
        self.hdr_iso_button_group.addButton(self.hdr_iso_manual_radio)
        hdr_iso_layout.addWidget(self.hdr_iso_auto_radio)
        hdr_iso_layout.addWidget(self.hdr_iso_manual_radio)
        self.hdr_iso_combo = QComboBox()
        self.hdr_iso_combo.addItems(["100", "200", "400", "800", "1600", "3200", "6400"])
        self.hdr_iso_combo.setCurrentText("400")
        self.hdr_iso_combo.setEnabled(False)
        hdr_iso_layout.addWidget(self.hdr_iso_combo)
        hdr_iso_layout.addStretch()
        hdr_iso_widget.setLayout(hdr_iso_layout)
        phenomena_layout.addWidget(hdr_iso_widget)
        self.hdr_iso_auto_radio.toggled.connect(self._on_hdr_iso_changed)

        phenomena_group.setLayout(phenomena_layout)
        layout.addWidget(phenomena_group)
        
        # Partial eclipse settings
        partial_group = QGroupBox("Partial Eclipse Interval")
        partial_layout = QVBoxLayout()
        
        partial_info = QLabel("Set the interval for taking photos during partial phases:")
        partial_layout.addWidget(partial_info)
        
        # Magnitude option
        mag_layout = QHBoxLayout()
        self.partial_magnitude_radio = QRadioButton("Every")
        self.partial_magnitude_radio.setChecked(True)
        mag_layout.addWidget(self.partial_magnitude_radio)
        self.magnitude_spin = QDoubleSpinBox()
        self.magnitude_spin.setRange(0.1, 100.0)
        self.magnitude_spin.setValue(2.0)
        self.magnitude_spin.setSingleStep(0.1)
        self.magnitude_spin.setDecimals(1)
        self.magnitude_spin.setSuffix(" % of magnitude")
        mag_layout.addWidget(self.magnitude_spin)
        mag_layout.addStretch()
        partial_layout.addLayout(mag_layout)
        
        # Seconds option
        sec_layout = QHBoxLayout()
        self.partial_seconds_radio = QRadioButton("Every")
        sec_layout.addWidget(self.partial_seconds_radio)
        self.seconds_spin = QSpinBox()
        self.seconds_spin.setRange(1, 3600)
        self.seconds_spin.setValue(10)
        self.seconds_spin.setSuffix(" seconds")
        sec_layout.addWidget(self.seconds_spin)
        sec_layout.addStretch()
        partial_layout.addLayout(sec_layout)
        
        partial_group.setLayout(partial_layout)
        layout.addWidget(partial_group)
        
        # Full aperture filter ND value
        filter_group = QGroupBox("Full Aperture Solar Filter")
        filter_layout = QVBoxLayout()
        
        filter_info = QLabel("Select the ND (Neutral Density) value of your solar filter:")
        filter_info.setWordWrap(True)
        filter_layout.addWidget(filter_info)
        
        filter_value_layout = QHBoxLayout()
        filter_value_layout.addWidget(QLabel("ND Value:"))
        self.filter_value_combo = QComboBox()
        self.filter_value_combo.addItems(["5.0", "3.8", "Manual"])
        self.filter_value_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_value_layout.addWidget(self.filter_value_combo)
        
        self.filter_manual_spin = QDoubleSpinBox()
        self.filter_manual_spin.setRange(0.0, 10.0)
        self.filter_manual_spin.setSingleStep(0.1)
        self.filter_manual_spin.setValue(5.0)
        self.filter_manual_spin.setDecimals(1)
        self.filter_manual_spin.setEnabled(False)
        filter_value_layout.addWidget(self.filter_manual_spin)
        filter_value_layout.addStretch()
        
        filter_layout.addLayout(filter_value_layout)
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # Voice prompts
        voice_group = QGroupBox("Voice Prompts")
        voice_layout = QVBoxLayout()
        
        self.voice_enabled_check = QCheckBox("Enable voice prompts")
        self.voice_enabled_check.stateChanged.connect(self._on_voice_enabled_changed)
        voice_layout.addWidget(self.voice_enabled_check)
        
        voice_type_widget = QWidget()
        voice_type_layout = QHBoxLayout()
        voice_type_layout.setContentsMargins(20, 0, 0, 0)
        
        self.voice_basic_radio = QRadioButton("Basic voice prompts")
        self.voice_extended_radio = QRadioButton("Extended voice prompts")
        self.voice_basic_radio.setChecked(True)
        self.voice_basic_radio.setEnabled(False)
        self.voice_extended_radio.setEnabled(False)
        
        voice_type_layout.addWidget(self.voice_basic_radio)
        voice_type_layout.addWidget(self.voice_extended_radio)
        voice_type_layout.addStretch()
        voice_type_widget.setLayout(voice_type_layout)
        
        voice_layout.addWidget(voice_type_widget)
        voice_group.setLayout(voice_layout)
        layout.addWidget(voice_group)
        
        layout.addStretch()
        _content = QWidget()
        _content.setLayout(layout)
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _scroll.setWidget(_content)
        _page_layout = QVBoxLayout()
        _page_layout.setContentsMargins(0, 0, 0, 0)
        _page_layout.addWidget(_scroll)
        self.setLayout(_page_layout)
        
        # Register fields
        self.registerField("c1_c4", self.c1_c4_check)
        self.registerField("contact_step_auto", self.contact_step_auto_check)
        self.registerField("contact_step", self.contact_step_spin, "value")
        self.registerField("equispaced", self.equispaced_check)
        self.registerField("diamond", self.diamond_check)
        self.registerField("bailys", self.bailys_check)
        self.registerField("chromosphere", self.chromosphere_check)
        self.registerField("prominences", self.prominences_check)
        self.registerField("earthshine", self.earthshine_check)
        self.registerField("corona", self.corona_check)
        self.registerField("partial_magnitude", self.partial_magnitude_radio)
        self.registerField("magnitude_value", self.magnitude_spin, "value")
        self.registerField("seconds_value", self.seconds_spin, "value")
        self.registerField("filter_value", self.filter_value_combo, "currentText")
        self.registerField("filter_manual", self.filter_manual_spin, "value")
        self.registerField("voice_enabled", self.voice_enabled_check)
        self.registerField("voice_basic", self.voice_basic_radio)
        self.registerField("hdr_burst", self.hdr_check)
        self.registerField("hdr_stops", self.hdr_stops_spin, "value")
        self.registerField("hdr_one_way", self.hdr_one_way_radio)
        self.registerField("hdr_start_auto", self.hdr_start_auto_radio)
        self.registerField("hdr_start_speed", self.hdr_start_speed_combo, "currentText")
        self.registerField("hdr_iso_auto", self.hdr_iso_auto_radio)
        self.registerField("hdr_iso_manual", self.hdr_iso_combo, "currentText")
        self.registerField("corona_bracket", self.bracket_check)
        self.registerField("bracket_step", self.bracket_step_combo, "currentText")
        self.registerField("bracket_frames", self.bracket_frames_combo, "currentText")
        self._fill_bracket_options()

    def initializePage(self):
        """Offer the brackets of the camera chosen on the Equipment page."""
        self._fill_bracket_options()

    def _fill_bracket_options(self):
        """Fill the step and frame lists: the camera's own brackets when it was tested, else standard values."""
        wizard = self.wizard()
        camera_name = (wizard.field('camera_name') or '').strip() if wizard else ''
        profile = camera_profile_for(wizard, getattr(wizard, 'config_manager', None), camera_name) \
            if camera_name else None

        options = {}
        for bracket in (profile.brackets if profile else []):
            try:
                spec = parse_bracket(bracket)
            except ValueError:
                continue
            options.setdefault(spec.ev_step, set()).add(spec.frames)
        if not options:
            options = {ev: set(STANDARD_FRAMES) for ev in STANDARD_STEPS}
        self._bracket_options = {format_ev(ev): sorted(frames) for ev, frames in sorted(options.items())}
        self._bracket_source = profile

        previous_step = self.bracket_step_combo.currentText() or "1"
        self.bracket_step_combo.blockSignals(True)
        self.bracket_step_combo.clear()
        self.bracket_step_combo.addItems(list(self._bracket_options))
        self.bracket_step_combo.blockSignals(False)
        if previous_step in self._bracket_options:
            self.bracket_step_combo.setCurrentText(previous_step)
        self._on_bracket_step_changed(self.bracket_step_combo.currentText())
        self._on_bracket_changed()

    def _on_bracket_step_changed(self, step):
        """Offer the numbers of frames the camera takes with this step."""
        previous = self.bracket_frames_combo.currentText() or "3"
        frames = [str(n) for n in self._bracket_options.get(step, [])]
        self.bracket_frames_combo.blockSignals(True)
        self.bracket_frames_combo.clear()
        self.bracket_frames_combo.addItems(frames)
        if previous in frames:
            self.bracket_frames_combo.setCurrentText(previous)
        self.bracket_frames_combo.blockSignals(False)
        self._refresh_bracket_note()

    def _refresh_bracket_note(self, *_):
        """Explain where the bracket options come from, and what to set on a Canon."""
        profile = self._bracket_source
        if profile is None:
            text = ("Camera not tested: standard values.  A bracket the camera does not offer is taken in "
                    "software, one picture per frame (slower).  'Test Camera...' on the Equipment page lists "
                    "the brackets the camera takes itself.")
        elif not profile.brackets:
            text = ("The camera offers no bracketing over USB: the frames are taken in software, one picture "
                    "per frame (slower).")
        else:
            text = "Brackets the camera takes itself (read by 'Test Camera...')."
            if profile.vendor == "Canon":
                text += (f"  Set 'Number of bracketed shots' in the camera menu to "
                         f"{self.bracket_frames_combo.currentText()}: it cannot be set over USB.")
        self.bracket_note.setText(text)

    def _on_bracket_changed(self, *_):
        """Bracket options only apply to the corona series."""
        corona = self.corona_check.isChecked()
        self.bracket_check.setEnabled(corona)
        enabled = corona and self.bracket_check.isChecked()
        self.bracket_step_combo.setEnabled(enabled)
        self.bracket_frames_combo.setEnabled(enabled)
        self.bracket_note.setVisible(enabled)
    
    def _on_filter_changed(self, text):
        """Enable/disable manual entry based on filter selection."""
        self.filter_manual_spin.setEnabled(text == "Manual")
    
    def _on_voice_enabled_changed(self, state):
        """Enable/disable voice prompt type selection."""
        enabled = state == Qt.CheckState.Checked.value
        self.voice_basic_radio.setEnabled(enabled)
        self.voice_extended_radio.setEnabled(enabled)

    def _on_hdr_changed(self, state):
        """Enable/disable HDR stops, starting-speed, and ISO controls."""
        enabled = state == Qt.CheckState.Checked.value
        self.hdr_stops_spin.setEnabled(enabled)
        self.hdr_round_trip_radio.setEnabled(enabled)
        self.hdr_one_way_radio.setEnabled(enabled)
        self.hdr_start_auto_radio.setEnabled(enabled)
        self.hdr_start_manual_radio.setEnabled(enabled)
        self.hdr_start_speed_combo.setEnabled(enabled and self.hdr_start_manual_radio.isChecked())
        self.hdr_iso_auto_radio.setEnabled(enabled)
        self.hdr_iso_manual_radio.setEnabled(enabled)
        self.hdr_iso_combo.setEnabled(enabled and self.hdr_iso_manual_radio.isChecked())

    def _on_hdr_start_changed(self, auto_checked):
        """Enable/disable manual shutter speed combo based on auto/manual selection."""
        self.hdr_start_speed_combo.setEnabled(
            not auto_checked and self.hdr_check.isChecked()
        )

    def _on_hdr_iso_changed(self, auto_checked):
        """Enable/disable manual ISO combo based on auto/manual selection."""
        self.hdr_iso_combo.setEnabled(
            not auto_checked and self.hdr_check.isChecked()
        )


class SummaryPage(QWizardPage):
    """Summary page - review configuration and generate script."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Summary and Script Generation")
        self.setSubTitle("Review your configuration and generate the photography script.")
        
        layout = QVBoxLayout()
        
        # Summary text
        summary_label = QLabel("Configuration Summary:")
        summary_label.setFont(QFont("", 10, QFont.Weight.Bold))
        layout.addWidget(summary_label)
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(80)
        self.summary_text.setMaximumHeight(120)
        layout.addWidget(self.summary_text)
        
        # Preview label
        preview_label = QLabel("Script Preview:")
        preview_label.setFont(QFont("", 10, QFont.Weight.Bold))
        layout.addWidget(preview_label)
        
        # Script preview
        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFont(QFont("Monospace", 9))
        layout.addWidget(self.script_preview)
        
        # Save location
        save_layout = QHBoxLayout()
        save_layout.addWidget(QLabel("Save to:"))
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("Click Browse to select save location...")
        apply_dark_to_lineedit(self.save_path_edit)
        save_layout.addWidget(self.save_path_edit)
        
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_save_location)
        save_layout.addWidget(self.browse_button)
        layout.addLayout(save_layout)

        # Camera test
        test_layout = QHBoxLayout()
        self.test_camera_button = QPushButton("Verify with Camera...")
        self.test_camera_button.setToolTip(
            "Connect the camera of this script and check that it can run the script: settings, "
            "camera state, clock and timing")
        self.test_camera_button.clicked.connect(self._test_with_camera)
        test_layout.addWidget(self.test_camera_button)
        test_layout.addStretch()
        layout.addLayout(test_layout)
        
        self.setLayout(layout)
        
        # Register field
        self.registerField("save_path*", self.save_path_edit)
    
    def initializePage(self):
        """Called when page is displayed - update summary and preview."""
        # Re-apply dark stylesheet: QWizard overwrites it on registered fields.
        self.save_path_edit.setStyleSheet(dark_lineedit_style())
        wizard = self.wizard()
        if not wizard:
            return
        
        # Build summary
        summary = []
        summary.append(f"Eclipse: {wizard.field('eclipse_name')}")
        summary.append(f"Date: {wizard.field('eclipse_date')}")
        summary.append(f"Type: {wizard.field('eclipse_type')}")
        summary.append(f"Location: {wizard.field('location')}")
        
        # Add coordinates
        lon = wizard.field('longitude')
        lat = wizard.field('latitude')
        alt = wizard.field('altitude')
        summary.append(f"Coordinates: {lat}° N, {lon}° E, {alt} m")
        
        summary.append(f"Camera: {wizard.field('camera_name')}")
        
        # Lens configuration
        focal_length = wizard.field('focal_length')
        aperture_min = wizard.field('aperture_min')
        aperture_max = wizard.field('aperture_max')
        summary.append(f"Lens: {focal_length}mm, f/{aperture_min}-{aperture_max}")
        if wizard.field('pixel_size'):
            summary.append(f"Pixel Size: {float(wizard.field('pixel_size')):.2f} µm")
        if wizard.field('c1_c4'):
            if wizard.field('contact_step_auto') is False:
                summary.append(f"C1/C4 Shots: ± {wizard.field('contact_step')} s")
            else:
                summary.append("C1/C4 Shots: ± automatic (when the Moon's bite shows)")
        
        # ISO settings
        preferred_iso = wizard.field('preferred_iso')
        iso_min = wizard.field('iso_min')
        iso_max = wizard.field('iso_max')
        summary.append(f"ISO: {preferred_iso} (bracket range: {iso_min}-{iso_max})")
        
        filter_val = wizard.field('filter_value')
        if filter_val == "Manual":
            filter_val = f"{wizard.field('filter_manual')}"
        summary.append(f"Solar Filter ND: {filter_val}")

        if wizard.field('hdr_burst'):
            summary.append(f"HDR: {wizard.field('hdr_stops')} stops, "
                           f"{'one way' if wizard.field('hdr_one_way') else 'round trip'}")

        if wizard.field('corona') and wizard.field('corona_bracket'):
            summary.append(f"Corona Bracket: {wizard.field('bracket_frames')} frames, "
                           f"{wizard.field('bracket_step')} EV apart")

        if wizard.field('voice_enabled'):
            voice_type = "Basic" if wizard.field('voice_basic') else "Extended"
            summary.append(f"Voice Prompts: {voice_type}")
        else:
            summary.append("Voice Prompts: Disabled")
        
        if wizard.field('sync_enabled'):
            sync_interval = wizard.field('sync_interval')
            summary.append(f"Camera Sync: Every {sync_interval}")
        else:
            summary.append("Camera Sync: Disabled")
        
        self.summary_text.setPlainText("\n".join(summary))
        
        # Generate script preview
        script = self._generate_script()
        self.script_preview.setPlainText(script)
        self.summary_text.append(self._script_check_text(script))
        
        # Set default save path
        if not self.save_path_edit.text():
            eclipse_name = wizard.field('eclipse_name').replace(' ', '_')
            default_name = f"{eclipse_name}_{datetime.now().strftime('%Y%m%d')}.txt"
            self.save_path_edit.setText(str(Path.home() / default_name))
    
    def _browse_save_location(self):
        """Open file dialog to select save location."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Script File",
            str(Path.home()),
            "Script Files (*.txt);;All Files (*)"
        )
        if filename:
            self.save_path_edit.setText(filename)

    def _script_check_text(self, script):
        """Summary lines on the camera fitting and the timing of the generated script."""
        from solareclipseworkbench.camera_check import ERROR, TestReport, check_timing, load_commands
        lines = []
        profile = getattr(self, '_camera_profile', None)
        adaptation = getattr(self, '_adaptation', None)
        if profile is None:
            lines.append("Camera test: not tested (use 'Test Camera...' on the Equipment page to fit the script)")
        else:
            lines.append(f"Camera test: {profile.summary()}")
            if adaptation is not None:
                text = f"Fitted to the camera: {adaptation.changed} commands adjusted"
                if adaptation.off_limit:
                    text += f", {len(adaptation.off_limit)} cannot be exposed as planned (camera limit)"
                lines.append(text)
        timings = getattr(self, '_last_timings', None)
        if timings:
            try:
                report = TestReport()
                camera_name = self.wizard().field('camera_name')
                commands = [c for c in load_commands(script, timings) if c.camera == camera_name]
                check_timing(commands, timings, None, report,
                             profile.timing_profile() if profile else DEFAULT_PROFILE, measured=bool(
                                 profile and profile.full_test))
                worst = next((i for i in report.items if i.status == ERROR), None) or report.items[-1]
                lines.append(f"Timing check: {worst.title}")
            except Exception as e:
                logging.warning("Timing check of the generated script failed: %s", e)
        return "\n".join(lines)

    def _test_with_camera(self):
        """Check the generated script against the connected camera and show a report."""
        wizard = self.wizard()
        if not wizard:
            return
        camera_name = wizard.field('camera_name')
        script = self.script_preview.toPlainText()
        timings = getattr(self, '_last_timings', None)
        if not timings:
            QMessageBox.warning(
                self, "Camera Test",
                "The contact times for this location could not be calculated, so the script cannot be tested.")
            return

        full = ask_test_level(
            self, "Verify with Camera",
            f"Connect '{camera_name}' with USB and switch it on.  Close Solar Eclipse Workbench "
            "if it is running: only one program can use the camera.",
            "also sets the camera clock and checks the result, and takes one test picture and one test burst "
            "with the settings of the script to measure how long they take.")
        if full is None:
            return

        def run():
            from solareclipseworkbench.camera import get_camera_dict
            from solareclipseworkbench.camera_check import check_script_with_cameras
            config_manager = getattr(wizard, 'config_manager', None) or ConfigManager()
            cameras = get_camera_dict(alias_map=config_manager.get_camera_aliases() or None)
            try:
                return check_script_with_cameras(script, timings, cameras, camera_name, full=full)
            finally:
                for cam in {id(c): c for c in cameras.values()}.values():
                    try:
                        cam.disconnect()
                    except Exception:
                        pass

        self.test_camera_button.setEnabled(False)
        try:
            report = run_with_progress(self, "Testing Camera",
                                             "Running the full test (test picture and burst)..." if full
                                             else "Reading the camera settings...", run)
        except Exception as e:
            QMessageBox.critical(
                self, "Camera Test Failed",
                f"The camera could not be tested:\n{e}\n\n"
                "Check that the camera is connected and switched on, and that no other program "
                "(such as Solar Eclipse Workbench) is using it.")
            return
        finally:
            self.test_camera_button.setEnabled(True)
        show_test_report(self, f"Camera Test: {camera_name}", report,
                         None if full else "The clock and the timing with this camera were not tested: "
                                           "run the full test for that.")

    def _calculate_reference_moments_with_progress(self, longitude, latitude, altitude, eclipse_time):
        """Run calculate_reference_moments in a background thread and show a modal dialog
        with an indeterminate progress bar and a live log view that captures stdout/stderr.

        Returns: (timings, magnitude, type) or raises exception on error.
        """
        # Dialog with progress and log
        dialog = QDialog(self)
        dialog.setWindowTitle("Downloading")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)

        # Compact UI: a short label and indeterminate progress bar
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)  # indeterminate
        layout.addWidget(progress_bar)

        label = QLabel("Loading helper files...")
        layout.addWidget(label)

        dialog.setLayout(layout)

        result = {}

        class _DevNull:
            def write(self, s):
                return

            def flush(self):
                return

        def worker():
            # Redirect stdout/stderr to devnull and temporarily silence root logging
            old_out = sys.stdout
            old_err = sys.stderr
            sys.stdout = _DevNull()
            sys.stderr = _DevNull()
            import logging
            root_logger = logging.getLogger()
            old_handlers = list(root_logger.handlers)
            old_level = root_logger.level
            try:
                # Remove handlers so external libraries don't print to terminal
                root_logger.handlers = file_handlers_only(old_handlers)
                # Run the actual computation
                res = calculate_reference_moments(longitude, latitude, altitude, eclipse_time)
                result['res'] = res
            except Exception:
                import traceback

                result['error'] = traceback.format_exc()
            finally:
                # Restore stdout/stderr and logging handlers
                sys.stdout = old_out
                sys.stderr = old_err
                root_logger.handlers = old_handlers
                root_logger.setLevel(old_level)

        th = threading.Thread(target=worker, daemon=True)

        # Show dialog immediately so the user sees the busy UI before downloads start.
        try:
            dialog.show()
            QApplication.processEvents()
        except Exception:
            pass

        logging = __import__('logging')
        logging.getLogger(__name__).debug("Starting reference-moments worker thread")

        th.start()

        timer = QTimer(dialog)

        def pump_logs_and_check():
            if not th.is_alive():
                timer.stop()
                dialog.accept()

        timer.timeout.connect(pump_logs_and_check)
        timer.start(100)

        dialog.exec()

        if 'error' in result:
            raise Exception(result['error'])
        return result.get('res', (None, None, None))
    
    def _generate_script(self):
        """Generate the photography script based on configuration."""
        wizard = self.wizard()
        if not wizard:
            return "# Error: Could not access wizard"
        lines = []
        timings = None
        
        # Header
        lines.append(f"# Solar Eclipse Photography Script")
        lines.append(f"# Generated by SEW Wizard on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"#")
        lines.append(f"# Eclipse: {wizard.field('eclipse_name')}")
        lines.append(f"# Date: {wizard.field('eclipse_date')}")
        lines.append(f"# Type: {wizard.field('eclipse_type')}")
        lines.append(f"# Location: {wizard.field('location')}")
        lines.append(f"# Coordinates: {wizard.field('latitude')}° N, {wizard.field('longitude')}° E, {wizard.field('altitude')} m")
        lines.append(f"# Camera: {wizard.field('camera_name')}")
        lines.append(f"# Lens: {wizard.field('focal_length')}mm, f/{wizard.field('aperture_min')}-{wizard.field('aperture_max')}")
        
        # Get camera settings for exposure calculation
        preferred_iso = int(wizard.field('preferred_iso'))
        iso_max = int(wizard.field('iso_max'))
        aperture = wizard.field('aperture_min')  # Use widest aperture for calculations
        aperture_max = wizard.field('aperture_max')  # Narrowest aperture (highest f-number)
        filter_val = wizard.field('filter_value')
        if filter_val == "Manual":
            nd_filter = wizard.field('filter_manual')
        else:
            nd_filter = float(filter_val)
        
        lines.append(f"# ISO: {preferred_iso} (max: {iso_max}), Aperture: f/{aperture}-f/{aperture_max}, ND Filter: {nd_filter}")
        
        # Add sync info to header
        if wizard.field('sync_enabled'):
            sync_interval = wizard.field('sync_interval')
            lines.append(f"# Camera Sync: Every ~{sync_interval} (during gaps between commands)")
        
        lines.append(f"#")
        
        # Calculate exposures based on eclipse circumstances
        exposures = {}
        try:
            # Parse eclipse date
            eclipse_date_str = wizard.field('eclipse_date')
            # Try to parse the date - it should be in format like "August 12, 2026"
            from dateutil import parser
            parsed_date = parser.parse(eclipse_date_str)
            eclipse_time = Time(parsed_date)

            # Get location
            longitude = float(wizard.field('longitude'))
            latitude = float(wizard.field('latitude'))
            altitude = float(wizard.field('altitude'))

            # Pre-compute reference moments first (shows modal dialog and captures download output)
            timings = None
            try:
                timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)
            except Exception:
                # If precomputation fails, leave timings as None and fallback to calculate inside exposures
                timings = None

            # Calculate all exposures; pass precomputed timings when available to avoid re-downloading ephemerides
            exposures = calculate_eclipse_exposures(
                eclipse_time, longitude, latitude, altitude,
                preferred_iso, aperture, nd_filter, timings=timings
            )
            
            # Add exposure summary to header
            lines.append(f"#")
            lines.append(f"# Calculated Exposures (ISO {preferred_iso}, f/{aperture}):")
            lines.append(f"# ------------------------------------------------")
            for name, data in exposures.items():
                sun_alt = data.get('sun_apparent_altitude', data['sun_altitude'])
                shutter = data['shutter']
                lines.append(f"#   {name:25s}: {shutter:>10s}  (sun alt: {sun_alt:5.1f}°)")
            lines.append(f"#")
            
        except Exception as e:
            lines.append(f"# Warning: Could not calculate exposures: {str(e)}")
            lines.append(f"# Using default placeholder values instead.")
            lines.append(f"#")
        
        lines.append("")
        
        camera_name = wizard.field('camera_name')
        eclipse_type = wizard.field('eclipse_type')

        # Pre-compute reference moments to determine whether the observer's location
        # actually experiences totality/annularity.  This differs from eclipse_type,
        # which is the *global* eclipse type: an observer in the partial zone of a
        # "Total" eclipse has no C2/C3 at their location.
        has_totality = False
        try:
            if timings is None:
                timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)
            if timings:
                has_totality = 'C2' in timings and 'C3' in timings
        except Exception:
            # Fallback: assume totality only for globally total/annular/hybrid eclipses
            timings = None
            has_totality = eclipse_type in ["Total", "Annular", "Hybrid"]

        # Voice prompts - load from file if enabled
        if wizard.field('voice_enabled'):
            voice_type = "basic" if wizard.field('voice_basic') else "extended"
            prompt_file = f"voice_prompts_{voice_type}.txt" if voice_type == "basic" else "voice_prompts.txt"
            
            # Load voice prompts from file
            from pathlib import Path
            voice_file_path = Path(__file__).parent / 'example_scripts' / prompt_file
            if voice_file_path.exists():
                lines.append(f"# Voice prompts from {prompt_file}")
                voice_lines = voice_file_path.read_text().strip().split('\n')
                for voice_line in voice_lines:
                    if voice_line.strip() and not voice_line.startswith('#'):
                        lines.append(voice_line)
                lines.append("")
            else:
                lines.append(f"# Voice prompts: {prompt_file} (file not found)")
                lines.append("")
        
        # Helper function to get shutter speed for a phenomenon
        def get_shutter(phenom_key, default="1/1000"):
            if phenom_key in exposures:
                return exposures[phenom_key]['shutter'].replace('s', '')
            return default
        
        def get_adjusted_exposure(phenom_key, default_shutter, base_iso, base_aperture, max_exposure=5.0, max_iso=6400, min_aperture=2.8):
            """
            Get exposure settings, adjusting aperture/ISO if exposure would exceed max_exposure.
            Priority: Open aperture first, then increase ISO (respecting max_iso limit).
            
            Args:
                phenom_key: Phenomenon key (e.g., 'corona_outer_8R')
                default_shutter: Default shutter speed if not in exposures
                base_iso: Preferred ISO value
                base_aperture: Preferred aperture value (widest, smallest f-number)
                max_exposure: Maximum acceptable exposure in seconds (default 5.0)
                max_iso: Maximum allowed ISO value (from settings)
                min_aperture: Minimum f-number (widest aperture, e.g., 2.8)
            
            Returns:
                Tuple of (shutter_speed_str, iso, aperture)
            """
            shutter = get_shutter(phenom_key, default_shutter)
            exposure_seconds = parse_shutter_speed(shutter)
            
            # If exposure is within limits, return as-is
            if exposure_seconds <= max_exposure:
                return (shutter, base_iso, base_aperture)
            
            # Calculate how much we need to reduce exposure
            adjusted_aperture = base_aperture
            adjusted_iso = base_iso
            
            # STEP 1: Try opening aperture first (if possible)
            # Common aperture stops (sorted from widest to narrowest)
            aperture_options = [1.4, 2.0, 2.8, 4.0, 5.6, 8.0, 11.0, 16.0, 22.0]
            
            # Find apertures wider than current base_aperture and >= min_aperture
            available_apertures = [ap for ap in aperture_options if ap >= min_aperture and ap < base_aperture]
            available_apertures.sort()  # Widest first
            
            for ap in available_apertures:
                # Calculate exposure at this wider aperture
                aperture_factor = (ap / base_aperture) ** 2
                new_exposure = exposure_seconds * aperture_factor
                
                if new_exposure <= max_exposure:
                    adjusted_aperture = ap
                    exposure_seconds = new_exposure
                    break
            
            # STEP 2: If still too long, increase ISO (but don't exceed max_iso)
            if exposure_seconds > max_exposure:
                iso_options = [100, 200, 400, 800, 1600, 3200, 6400]
                
                # Find current ISO position
                try:
                    iso_index = iso_options.index(base_iso)
                except ValueError:
                    iso_index = 2  # Default to 400 if not found
                
                # Calculate current exposure with any aperture adjustments
                current_aperture_factor = (adjusted_aperture / base_aperture) ** 2
                
                # Increase ISO to reduce exposure (but don't exceed max_iso)
                while exposure_seconds > max_exposure and iso_index < len(iso_options) - 1:
                    next_iso = iso_options[iso_index + 1]
                    
                    # Don't exceed max_iso
                    if next_iso > max_iso:
                        break
                    
                    iso_index += 1
                    adjusted_iso = next_iso
                    
                    # Each ISO doubling halves the exposure
                    iso_factor = base_iso / adjusted_iso
                    exposure_seconds = parse_shutter_speed(shutter) * current_aperture_factor * iso_factor
                    
                    if exposure_seconds <= max_exposure:
                        break
            
            # Recalculate final shutter speed with adjustments
            final_shutter = format_shutter_speed(exposure_seconds)
            
            return (final_shutter, adjusted_iso, adjusted_aperture)

        # Timing of the diamond ring and Baily's beads bursts around C2 and C3,
        # and of the partial and totality shots next to them.  A burst keeps the
        # camera busy far longer than the shutter is held, and a command that
        # has to wait more than 1.5 s for the camera is dropped, so everything
        # is spaced by the estimated burst duration (see command_timing).
        contact_bursts = bool(wizard.field('diamond') or wizard.field('bailys'))
        # A tested camera brings its own shutter speeds, ISO values, apertures
        # and measured durations; otherwise standard values and estimates are used.
        camera_profile = camera_profile_for(wizard, getattr(wizard, 'config_manager', None), camera_name)
        timing = camera_profile.timing_profile() if camera_profile else DEFAULT_PROFILE
        vendor = (camera_profile.vendor if camera_profile else None) or vendor_from_name(camera_name)
        # With the lunar limb profile, the beads bursts are centred on the Baily's beads
        # windows.  They are still written relative to C2 and C3, so a script run
        # without the limb profile keeps all its lines (timed against the mean limb).
        bead_windows = {}
        for contact in ("C2", "C3"):
            if timings and contact in timings and all(f"BEADS_{contact}_{edge}" in timings
                                                      for edge in ("START", "END")):
                at = timings[contact].time_utc
                bead_windows[contact] = tuple((timings[f"BEADS_{contact}_{edge}"].time_utc - at).total_seconds()
                                              for edge in ("START", "END"))
        plan = contact_burst_plan(vendor, contact_bursts, timing,
                                  beads_c2=bead_windows.get("C2"), beads_c3=bead_windows.get("C3"))
        contact_burst_param = plan.burst_param
        contact_burst_s = plan.burst_s
        c2_diamond_start, c2_beads_start = plan.c2_diamond_start, plan.c2_beads_start
        c3_beads_start, c3_diamond_start = plan.c3_beads_start, plan.c3_diamond_start
        c2_buffer, c3_buffer = plan.c2_buffer, plan.c3_buffer
        totality_first_shot = plan.totality_first_shot
        buffer_seconds = CONTACT_BUFFER_S

        def _offset_str(seconds):
            seconds = int(seconds)
            return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}.0"

        def _contact_offset(reference, seconds_after):
            """'<reference>, <sign>, <offset>' of a command this many seconds (to 0.1 s) after a contact."""
            tenths = round(abs(seconds_after) * 10)
            sign = "-" if seconds_after < 0 else "+"
            return (f"{reference}, {sign}, {tenths // 36000}:{(tenths // 600) % 60:02d}:"
                    f"{(tenths // 10) % 60:02d}.{tenths % 10}")

        def _relative(reference, seconds_after):
            """'C2-0.5s' / 'C3+1.0s', for comments."""
            return f"{reference}{round(seconds_after, 1) + 0.0:+.1f}s"

        def _beads_comment(shooting_s, busy_s):
            """How long a beads burst shoots and keeps the camera busy."""
            frames = (f" ({round(shooting_s * timing.nikon_burst_fps)} frames at {timing.nikon_burst_fps:g} "
                      "frames per second)" if vendor == "Nikon" else "")
            return (f"# The beads burst shoots for {shooting_s:.1f}s{frames} and keeps the camera busy "
                    f"for ~{busy_s:.0f}s.")

        def _window_comment(contact):
            start, end = bead_windows[contact]
            return (f"# Baily's beads window ({contact}): {_relative(contact, start)} to "
                    f"{_relative(contact, end)} ({end - start:.1f}s, from the lunar limb profile)")

        # Bracket of every corona exposure ('<EV step> <frames>'), or None for single pictures
        corona_bracket = None
        if wizard.field('corona_bracket'):
            corona_bracket = f"{wizard.field('bracket_step')} {wizard.field('bracket_frames')}"
            try:
                parse_bracket(corona_bracket)
            except ValueError:
                corona_bracket = None

        # A camera that is slow to change drive mode (Sony) takes this much longer
        # for the first shot after one in another mode: single picture, burst, or
        # bracket (see command_timing.MODE_SWITCH_S).
        switch_s = mode_switch_s(vendor)
        corona_mode = "bracket" if corona_bracket else "single"
        # Extra time of a single picture taken among bracketed corona shots
        single_among_corona_s = switch_s if wizard.field('corona') and corona_bracket else 0.0

        # The chromosphere shot before C3 has to have released the camera when
        # the beads burst starts, which can be before C3 with the beads timed
        chromosphere_shutter = get_shutter('chromosphere_c3', '1/250')
        chromosphere_before_c3 = 2.0
        if contact_bursts:
            chromosphere_before_c3 = max(chromosphere_before_c3,
                                         math.ceil((picture_duration_s(chromosphere_shutter, timing)
                                                    + single_among_corona_s - plan.c3_first_start) * 10) / 10)
        # Seconds before C3 by which the corona sequence has finished
        totality_end_buffer = max(10, math.ceil(chromosphere_before_c3) if wizard.field('chromosphere') else 0,
                                  math.ceil(-plan.c3_first_start) if contact_bursts else 0)

        hdr_sequence = HDR_ONE_WAY if wizard.field('hdr_one_way') else HDR_ROUND_TRIP


        def corona_shot_s(shutter):
            """Busy time of one corona exposure: a picture, or a bracket."""
            if corona_bracket:
                return bracket_planning_s(shutter, corona_bracket, timing)
            return picture_duration_s(shutter, timing)

        def corona_command(ref, sign, offset, shutter, ap, iso, description):
            """Script line of one corona exposure: take_picture, or take_bracket around it."""
            if corona_bracket:
                return (f'take_bracket, {ref}, {sign}, {offset}, {camera_name}, {shutter}, {ap}, {iso}, '
                        f'"{corona_bracket}", "{description}"')
            return f'take_picture, {ref}, {sign}, {offset}, {camera_name}, {shutter}, {ap}, {iso}, "{description}"'

        def corona_maximum_lines(corona_middle_shutter):
            """Fallback corona at MAX: one bracket, or 5 pictures 1 EV apart."""
            if corona_bracket:
                return [corona_command('MAX', '+', '0:00:00.0', corona_middle_shutter, aperture, preferred_iso,
                                       "Corona maximum")]
            result = []
            bracket_exposures = get_exposure_bracket(parse_shutter_speed(corona_middle_shutter), stops=2, step=1.0)
            offset_seconds = 0.0
            for i, exp in enumerate(bracket_exposures):
                rounded_exp = round_to_camera_shutter_speed(exp)
                shutter = format_shutter_speed(rounded_exp)
                result.append(f'take_picture, MAX, +, {_offset_str(offset_seconds)}, {camera_name}, {shutter}, '
                              f'{aperture}, {preferred_iso}, "Corona maximum ({i - 2:+d} EV)"')
                offset_seconds += rounded_exp + 2.0
            return result

        def earthshine_plan():
            """(shutter, iso, aperture, busy seconds) of the earthshine shots at C2+30 s and C3-30 s,
            or None when they are not taken (not selected, or totality too short for them)."""
            if not wizard.field('earthshine') or not timings or 'C2' not in timings or 'C3' not in timings:
                return None
            es_shutter, es_iso, es_aperture = get_adjusted_exposure(
                'earthshine', '7', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
            duration = (timings['C3'].time_utc - timings['C2'].time_utc).total_seconds()
            if duration < 60 + 2 * parse_shutter_speed(es_shutter) + 20:
                return None
            return es_shutter, es_iso, es_aperture, picture_duration_s(es_shutter, timing)

        def hdr_start_after_c2(hdr_duration):
            """Start of take_hdr in whole seconds after C2: centred on MAX, but not before the first
            earthshine shot is done.  None when the contact times are unknown."""
            if not timings or 'C2' not in timings or 'MAX' not in timings:
                return None
            start = (timings['MAX'].time_utc - timings['C2'].time_utc).total_seconds() - hdr_duration / 2
            earthshine = earthshine_plan()
            if earthshine is not None:
                start = max(start, 30 + earthshine[3])
            return math.ceil(start)

        # Step of the C1 and C4 shots: C1 - step (whole Sun), C1, C1 + step (first bite), and
        # C4 - step (last bite), C4, C4 + step.  Automatic: when the bite is deep enough to
        # show with this focal length and pixel size (see contact_visibility).
        c1_shutter = get_shutter('partial_c1', '1/800')
        c4_shutter = get_shutter('partial_c4', '1/800')
        contact_steps = {"C1": max(2, math.ceil(picture_duration_s(c1_shutter, timing))),
                         "C4": max(2, math.ceil(picture_duration_s(c4_shutter, timing)))}
        contact_step_note = None
        if wizard.field('c1_c4'):
            if wizard.field('contact_step_auto') is False:
                manual_step = int(wizard.field('contact_step') or 0)
                contact_steps = {contact: max(minimum, manual_step) for contact, minimum in contact_steps.items()}
                contact_step_note = "set in the wizard"
            else:
                focal_length = float(wizard.field('focal_length') or 0)
                pixel_size = float(wizard.field('pixel_size') or DEFAULT_PIXEL_SIZE_UM)
                try:
                    visible = contact_step_s(str(eclipse_time).split(' ')[0], latitude, longitude, altitude,
                                             focal_length, pixel_size)
                except Exception as e:
                    logging.warning("Could not work out when the Moon's bite shows at C1/C4: %s", e)
                    visible = None
                if visible is not None:
                    contact_steps = {contact: max(minimum, visible[contact])
                                     for contact, minimum in contact_steps.items()}
                    contact_step_note = (f"when the Moon's bite is visible at {focal_length:.0f} mm with "
                                         f"{pixel_size:.2f} µm pixels")
        # Partial-phase shots start after the C1 + step shot and end before the C4 - step shot
        c1_clear_s = buffer_seconds
        c4_clear_s = buffer_seconds
        if wizard.field('c1_c4'):
            c1_clear_s = max(buffer_seconds, contact_steps["C1"] + math.ceil(picture_duration_s(c1_shutter, timing)))
            c4_clear_s = max(buffer_seconds, contact_steps["C4"] + math.ceil(picture_duration_s("1", timing)))

        # C1 and C4 contacts
        if wizard.field('c1_c4'):
            # Check if sun is above horizon at C1
            try:
                if timings is None:
                    timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)
                if timings and 'C1' in timings:
                    c1_time = timings['C1'].time_utc
                    _, c1_sun_alt = calculate_sun_altitudes_at_time(
                        c1_time, eclipse_time, longitude, latitude, altitude
                    )
                    
                    # Only add C1 shots if sun is above horizon
                    if _sun_above_horizon(timings, c1_time):
                        lines.append("# First contact (C1) - with solar filter")
                        step = contact_steps["C1"]
                        if contact_step_note:
                            lines.append(f"# Shots {step}s apart: {contact_step_note}")
                        lines.append(f'take_picture, C1, -, {_offset_str(step)}, {camera_name}, {c1_shutter}, {aperture}, {preferred_iso}, "First contact (C1-{step}s)"')
                        lines.append(f'take_picture, C1, +, 0:00:00.0, {camera_name}, {c1_shutter}, {aperture}, {preferred_iso}, "First contact (C1)"')
                        lines.append(f'take_picture, C1, +, {_offset_str(step)}, {camera_name}, {c1_shutter}, {aperture}, {preferred_iso}, "First contact (C1+{step}s)"')
                        lines.append("")
                    else:
                        lines.append(f"# First contact (C1) skipped - sun below horizon (altitude: {c1_sun_alt:.1f}°)")
                        lines.append("")
            except Exception as e:
                # If we can't calculate, skip the shots
                lines.append(f"# First contact (C1) skipped - could not calculate sun position")
                lines.append("")
        
        # Partial phase - equispaced shots with filter
        if wizard.field('equispaced'):
            try:
                # Get reference moments for detailed partial phase planning (reuse cached result when available)
                if timings is None:
                    timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)

                if timings and has_totality and 'C1' in timings and 'C2' in timings and 'C3' in timings and 'C4' in timings:
                    c1_time = timings['C1'].time_utc
                    c2_time = timings['C2'].time_utc
                    c3_time = timings['C3'].time_utc
                    c4_time = timings['C4'].time_utc
                    
                    # Generate C1 to C2 partial phase shots
                    lines.append("# Partial phase (C1 to C2) - with solar filter")
                    
                    if wizard.field('partial_magnitude'):
                        magnitude_interval = wizard.field('magnitude_value')
                        lines.append(f"# Shots every {magnitude_interval}% of magnitude change")
                    else:
                        seconds_interval = wizard.field('seconds_value')
                        lines.append(f"# Shots every {seconds_interval} seconds")
                    
                    lines.append("#")
                    
                    # Calculate interval in seconds for C1-C2 phase
                    # Add buffer times to avoid conflicts with contact pictures
                    # (c2_buffer leaves room for the bursts before C2)
                    c1_c2_duration = (c2_time - c1_time).total_seconds() - c1_clear_s - c2_buffer
                    c1_start_time = c1_time + timedelta(seconds=c1_clear_s)
                    c2_end_time = c2_time - timedelta(seconds=c2_buffer)
                    
                    if wizard.field('partial_magnitude'):
                        # For magnitude-based, we'll use time intervals
                        # A rough approximation: take shots proportional to eclipse progress
                        magnitude_interval = wizard.field('magnitude_value')
                        if magnitude_interval is None or magnitude_interval <= 0:
                            magnitude_interval = 2.0  # Default fallback
                        # Estimate number of shots: 100% / interval
                        num_shots = max(3, int(100 / magnitude_interval))
                        time_interval = c1_c2_duration / num_shots
                    else:
                        seconds_interval = wizard.field('seconds_value')
                        if seconds_interval is None or seconds_interval <= 0:
                            seconds_interval = 60  # Default fallback
                        time_interval = seconds_interval
                        num_shots = int(c1_c2_duration / time_interval)
                    
                    # Generate shots from C1 to C2 (with buffers)
                    partial_shots_c1_c2 = []
                    for i in range(num_shots):
                        shot_time = c1_start_time + timedelta(seconds=i * time_interval)
                        if shot_time >= c2_end_time:
                            break
                        
                        # Calculate sun altitude at this time
                        sun_alt, sun_apparent_alt = calculate_sun_altitudes_at_time(
                            shot_time, eclipse_time, longitude, latitude, altitude
                        )
                        
                        # Calculate exposure with current ISO
                        exposure = calculate_exposure(
                            "partial", sun_alt, altitude, preferred_iso, aperture, nd_filter
                        )
                        
                        # Auto-adjust ISO if exposure is too slow
                        adjusted_iso = preferred_iso
                        max_iso = int(wizard.field('iso_max'))
                        
                        # If exposure > 1/30s (hand-held limit), increase ISO
                        while exposure > 1/30 and adjusted_iso < max_iso:
                            adjusted_iso *= 2
                            if adjusted_iso > max_iso:
                                adjusted_iso = max_iso
                                break
                            exposure = calculate_exposure(
                                "partial", sun_alt, altitude, adjusted_iso, aperture, nd_filter
                            )
                        
                        shutter = format_shutter_speed(exposure)
                        
                        # Calculate time offset back from C2 (so partial shots don't clash with totality sequence)
                        offset_seconds = (c2_time - shot_time).total_seconds()
                        offset_str = f"{int(offset_seconds // 3600)}:{int((offset_seconds % 3600) // 60):02d}:{int(offset_seconds % 60):02d}.0"
                        
                        partial_shots_c1_c2.append((offset_str, shutter, adjusted_iso, shot_time, sun_apparent_alt))
                    
                    # Filter out shots below horizon and add sync commands
                    sync_interval_minutes = 0
                    if wizard.field('sync_enabled'):
                        sync_interval = wizard.field('sync_interval')
                        sync_interval_minutes = int(sync_interval.split()[0])
                    
                    shot_count = 0
                    for idx, (offset, shutter, iso, shot_time, sun_apparent_alt) in enumerate(partial_shots_c1_c2):
                        # Skip shots when the sun has not risen yet or has set
                        if not _sun_above_horizon(timings, shot_time):
                            continue
                        
                        shot_count += 1
                        time_str = shot_time.strftime('%H:%M:%S')
                        iso_note = f" (ISO {iso})" if iso != preferred_iso else ""
                        lines.append(f'take_picture, C2, -, {offset}, {camera_name}, {shutter}, {aperture}, {iso}, "Partial C1-C2 #{shot_count} @ {time_str}, sun {sun_apparent_alt:.1f}°{iso_note}"')
                        
                        # Add sync_cameras periodically if enabled
                        if sync_interval_minutes > 0 and idx > 0:
                            c1_offset_seconds = (shot_time - c1_time).total_seconds()
                            # Add sync every N minutes, avoiding conflicts with shots
                            if c1_offset_seconds % (sync_interval_minutes * 60) < time_interval and c1_offset_seconds > sync_interval_minutes * 60:
                                # Sync 5 seconds before the shot; express as C2-relative offset
                                sync_time = shot_time - timedelta(seconds=5)
                                sync_c2_offset = int((c2_time - sync_time).total_seconds())
                                sync_offset_str = f"{int(sync_c2_offset // 3600)}:{int((sync_c2_offset % 3600) // 60):02d}:{int(sync_c2_offset % 60):02d}.0"
                                lines.append(f'sync_cameras, C2, -, {sync_offset_str}, "Camera sync @ {sync_time.strftime("%H:%M:%S")}"')
                    
                    lines.append("")
                    
                    # Generate C3 to C4 partial phase shots
                    lines.append("# Partial phase (C3 to C4) - with solar filter")
                    lines.append("# REMEMBER TO REPLACE SOLAR FILTER after C3!")
                    lines.append("#")
                    
                    # c3_buffer leaves room for the bursts after C3
                    c3_c4_duration = (c4_time - c3_time).total_seconds() - c3_buffer - c4_clear_s
                    c3_start_time = c3_time + timedelta(seconds=c3_buffer)
                    c4_end_time = c4_time - timedelta(seconds=c4_clear_s)
                    
                    if wizard.field('partial_magnitude'):
                        magnitude_interval = wizard.field('magnitude_value')
                        if magnitude_interval is None or magnitude_interval <= 0:
                            magnitude_interval = 2.0  # Default fallback
                        num_shots = max(3, int(100 / magnitude_interval))
                        time_interval = c3_c4_duration / num_shots
                    else:
                        seconds_interval = wizard.field('seconds_value')
                        if seconds_interval is None or seconds_interval <= 0:
                            seconds_interval = 60  # Default fallback
                        time_interval = seconds_interval
                        num_shots = int(c3_c4_duration / time_interval)
                    
                    # Generate shots from C3 to C4 (with buffers)
                    partial_shots_c3_c4 = []
                    for i in range(num_shots):
                        shot_time = c3_start_time + timedelta(seconds=i * time_interval)
                        if shot_time >= c4_end_time:
                            break
                        
                        # Calculate sun altitude at this time
                        sun_alt, sun_apparent_alt = calculate_sun_altitudes_at_time(
                            shot_time, eclipse_time, longitude, latitude, altitude
                        )
                        
                        # Calculate exposure with current ISO
                        exposure = calculate_exposure(
                            "partial", sun_alt, altitude, preferred_iso, aperture, nd_filter
                        )
                        
                        # Auto-adjust ISO if exposure is too slow
                        adjusted_iso = preferred_iso
                        max_iso = int(wizard.field('iso_max'))
                        
                        while exposure > 1/30 and adjusted_iso < max_iso:
                            adjusted_iso *= 2
                            if adjusted_iso > max_iso:
                                adjusted_iso = max_iso
                                break
                            exposure = calculate_exposure(
                                "partial", sun_alt, altitude, adjusted_iso, aperture, nd_filter
                            )
                        
                        shutter = format_shutter_speed(exposure)
                        
                        # Calculate time offset from C3
                        offset_seconds = (shot_time - c3_time).total_seconds()
                        offset_str = f"{int(offset_seconds // 3600)}:{int((offset_seconds % 3600) // 60):02d}:{int(offset_seconds % 60):02d}.0"
                        
                        partial_shots_c3_c4.append((offset_str, shutter, adjusted_iso, shot_time, sun_apparent_alt))
                    
                    # Filter out shots below horizon
                    shot_count = 0
                    for idx, (offset, shutter, iso, shot_time, sun_apparent_alt) in enumerate(partial_shots_c3_c4):
                        # Skip shots when the sun has not risen yet or has set
                        if not _sun_above_horizon(timings, shot_time):
                            continue
                        
                        shot_count += 1
                        time_str = shot_time.strftime('%H:%M:%S')
                        iso_note = f" (ISO {iso})" if iso != preferred_iso else ""
                        lines.append(f'take_picture, C3, +, {offset}, {camera_name}, {shutter}, {aperture}, {iso}, "Partial C3-C4 #{shot_count} @ {time_str}, sun {sun_apparent_alt:.1f}°{iso_note}"')
                        
                        # Add sync_cameras periodically if enabled
                        if sync_interval_minutes > 0 and idx > 0:
                            offset_seconds = (shot_time - c3_time).total_seconds()
                            # Add sync every N minutes, avoiding conflicts with shots
                            if offset_seconds % (sync_interval_minutes * 60) < time_interval and offset_seconds > sync_interval_minutes * 60:
                                sync_offset = int(offset_seconds - 5)  # 5 seconds before the shot
                                sync_offset_str = f"{int(sync_offset // 3600)}:{int((sync_offset % 3600) // 60):02d}:{int(sync_offset % 60):02d}.0"
                                lines.append(f'sync_cameras, C3, +, {sync_offset_str}, "Camera sync @ {(c3_time + timedelta(seconds=sync_offset)).strftime("%H:%M:%S")}"')

                elif 'C1' in timings and 'C4' in timings:
                    # Partial-only eclipse at this location (no totality/annularity)
                    c1_time = timings['C1'].time_utc
                    c4_time = timings['C4'].time_utc

                    lines.append("# Partial phase (C1 to C4) - with solar filter")

                    if wizard.field('partial_magnitude'):
                        magnitude_interval = wizard.field('magnitude_value')
                        lines.append(f"# Shots every {magnitude_interval}% of magnitude change")
                    else:
                        seconds_interval = wizard.field('seconds_value')
                        lines.append(f"# Shots every {seconds_interval} seconds")
                    lines.append("#")

                    c1_c4_duration = (c4_time - c1_time).total_seconds() - c1_clear_s - c4_clear_s
                    c1_start_time = c1_time + timedelta(seconds=c1_clear_s)
                    c4_end_time = c4_time - timedelta(seconds=c4_clear_s)

                    if wizard.field('partial_magnitude'):
                        magnitude_interval = wizard.field('magnitude_value')
                        if magnitude_interval is None or magnitude_interval <= 0:
                            magnitude_interval = 2.0
                        num_shots = max(3, int(100 / magnitude_interval))
                        time_interval = c1_c4_duration / num_shots
                    else:
                        seconds_interval = wizard.field('seconds_value')
                        if seconds_interval is None or seconds_interval <= 0:
                            seconds_interval = 60
                        time_interval = seconds_interval
                        num_shots = int(c1_c4_duration / time_interval)

                    partial_shots_c1_c4 = []
                    for i in range(num_shots):
                        shot_time = c1_start_time + timedelta(seconds=i * time_interval)
                        if shot_time >= c4_end_time:
                            break

                        sun_alt, sun_apparent_alt = calculate_sun_altitudes_at_time(
                            shot_time, eclipse_time, longitude, latitude, altitude
                        )

                        exposure = calculate_exposure(
                            "partial", sun_alt, altitude, preferred_iso, aperture, nd_filter
                        )

                        adjusted_iso = preferred_iso
                        max_iso = int(wizard.field('iso_max'))

                        while exposure > 1/30 and adjusted_iso < max_iso:
                            adjusted_iso *= 2
                            if adjusted_iso > max_iso:
                                adjusted_iso = max_iso
                                break
                            exposure = calculate_exposure(
                                "partial", sun_alt, altitude, adjusted_iso, aperture, nd_filter
                            )

                        shutter = format_shutter_speed(exposure)
                        offset_seconds = (shot_time - c1_time).total_seconds()
                        offset_str = f"{int(offset_seconds // 3600)}:{int((offset_seconds % 3600) // 60):02d}:{int(offset_seconds % 60):02d}.0"
                        partial_shots_c1_c4.append((offset_str, shutter, adjusted_iso, shot_time, sun_apparent_alt))

                    sync_interval_minutes = 0
                    if wizard.field('sync_enabled'):
                        sync_interval = wizard.field('sync_interval')
                        sync_interval_minutes = int(sync_interval.split()[0])

                    shot_count = 0
                    for idx, (offset, shutter, iso, shot_time, sun_apparent_alt) in enumerate(partial_shots_c1_c4):
                        # Skip shots when the sun has not risen yet or has set
                        if not _sun_above_horizon(timings, shot_time):
                            continue
                        shot_count += 1
                        time_str = shot_time.strftime('%H:%M:%S')
                        iso_note = f" (ISO {iso})" if iso != preferred_iso else ""
                        lines.append(f'take_picture, C1, +, {offset}, {camera_name}, {shutter}, {aperture}, {iso}, "Partial #{shot_count} @ {time_str}, sun {sun_apparent_alt:.1f}°{iso_note}"')

                        if sync_interval_minutes > 0 and idx > 0:
                            offset_seconds_val = (shot_time - c1_time).total_seconds()
                            if offset_seconds_val % (sync_interval_minutes * 60) < time_interval and offset_seconds_val > sync_interval_minutes * 60:
                                sync_offset = int(offset_seconds_val - 5)
                                sync_offset_str = f"{int(sync_offset // 3600)}:{int((sync_offset % 3600) // 60):02d}:{int(sync_offset % 60):02d}.0"
                                lines.append(f'sync_cameras, C1, +, {sync_offset_str}, "Camera sync @ {(c1_time + timedelta(seconds=sync_offset)).strftime("%H:%M:%S")}"')
                    lines.append("")

            except Exception as e:
                # Fallback to simple examples if calculation fails
                lines.append("# Partial phase shots (with solar filter)")
                lines.append(f"# Warning: Could not calculate detailed partial phase: {str(e)}")
                lines.append("# Using example shots - adjust timing based on your eclipse duration")

                if wizard.field('partial_magnitude'):
                    lines.append(f"# Interval: Every {wizard.field('magnitude_value')}% of magnitude")
                else:
                    lines.append(f"# Interval: Every {wizard.field('seconds_value')} seconds")

                partial_shutter = get_shutter('partial_c1', '1/800')
                if has_totality:
                    lines.append(f'take_picture, C2, -, 0:10:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial C1-C2 (10 min before C2)"')
                    lines.append(f'take_picture, C2, -, 0:05:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial C1-C2 (5 min before C2)"')
                    lines.append(f'take_picture, C2, -, 0:01:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial C1-C2 (1 min before C2)"')
                else:
                    lines.append(f'take_picture, C1, +, 0:10:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial phase (C1 + 10 min)"')
                    lines.append(f'take_picture, MAX, -, 0:05:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial phase (5 min before MAX)"')
                    lines.append(f'take_picture, MAX, +, 0:00:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial phase (MAX)"')
                    lines.append(f'take_picture, MAX, +, 0:05:00.0, {camera_name}, {partial_shutter}, {aperture}, {preferred_iso}, "Partial phase (5 min after MAX)"')
                lines.append("")
        
        # Diamond rings, Baily's beads, Chromosphere (only for locations with totality/annularity)
        if has_totality:
            if wizard.field('diamond') or wizard.field('bailys'):
                lines.append("# Diamond ring and Baily's beads (C2) - REMOVE SOLAR FILTER!")
                if plan.beads_timed:
                    lines.append(_window_comment("C2"))
                    lines.append("# The beads burst is centred on that window.")
                lines.append(f"# The diamond ring burst keeps the camera busy for ~{contact_burst_s:.0f}s, so it starts at "
                             f"{_relative('C2', -c2_diamond_start)} and the beads burst at "
                             f"{_relative('C2', -c2_beads_start)}.")
                lines.append(_beads_comment(plan.c2_beads_shooting_s, plan.c2_beads_s))
                beads_shutter = get_shutter('bailys_beads_c2', '1/500')
                diamond_shutter = get_shutter('diamond_ring_c2', '1/250')

                if plan.c2_prepare_start is not None:
                    lines.append(f"# The camera needs ~{plan.switch_s:.0f}s to switch from single pictures to continuous "
                                 f"shooting, so it is set up at {_relative('C2', -plan.c2_prepare_start)}.")
                    lines.append(f'prepare_camera, {_contact_offset("C2", -plan.c2_prepare_start)}, {camera_name}, {diamond_shutter}, {aperture}, {preferred_iso}, burst, "Prepare for C2 diamond ring"')
                lines.append(f'take_burst, {_contact_offset("C2", -c2_diamond_start)}, {camera_name}, {diamond_shutter}, {aperture}, {preferred_iso}, {contact_burst_param:g}, "C2 diamond ring"')
                lines.append(f'take_burst, {_contact_offset("C2", -c2_beads_start)}, {camera_name}, {beads_shutter}, {aperture}, {preferred_iso}, {plan.c2_beads_param:g}, "C2 beads"')
                lines.append("")
            
            # Totality/Annularity - Corona
            if wizard.field('corona'):
                try:
                    # Get totality duration to fill it optimally (reuse cached result when available)
                    if timings is None:
                        timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)

                    if timings and 'C2' in timings and 'C3' in timings:
                        totality_c2 = timings['C2'].time_utc
                        totality_c3 = timings['C3'].time_utc
                        totality_duration = (totality_c3 - totality_c2).total_seconds()
                        
                        lines.append("# Totality - Solar Corona")
                        
                        # Use calculated exposures for different corona layers
                        # Get adjusted exposures (limiting to 5 seconds max)
                        # Returns: (shutter, iso, aperture) tuples
                        corona_inner_02r = get_adjusted_exposure('corona_inner_0.2R', '1/10', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_inner_05r = get_adjusted_exposure('corona_inner_0.5R', '1/4', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_lower = get_adjusted_exposure('corona_lower', '1/60', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_middle = get_adjusted_exposure('corona_middle', '1/15', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_upper = get_adjusted_exposure('corona_upper', '1/4', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_outer_3r = get_adjusted_exposure('corona_outer_3R', '2', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_outer_4r = get_adjusted_exposure('corona_outer_4R', '4', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        corona_outer_8r = get_adjusted_exposure('corona_outer_8R', '68', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        
                        # Start: Prominences and inner corona (first ~10s), once
                        # the beads burst before C2 has released the camera
                        early_time = totality_first_shot
                        # Drive mode of the shot before (the beads burst, or the last partial)
                        mode_before = "burst" if contact_bursts else "single"
                        if wizard.field('prominences'):
                            prominences_shutter = get_shutter('prominences', '1/125')
                            lines.append(f'# Early totality - prominences and inner corona')
                            lines.append(f'take_picture, C2, +, {_offset_str(early_time)}, {camera_name}, {prominences_shutter}, {aperture}, {preferred_iso}, "Prominences"')
                            prominences_s = picture_duration_s(prominences_shutter, timing)
                            if mode_before != "single":
                                prominences_s += switch_s
                            early_time += max(3, math.ceil(prominences_s))
                            mode_before = "single"
                        else:
                            lines.append(f'# Early totality - inner corona')
                        lines.append(corona_command('C2', '+', _offset_str(early_time), corona_lower[0], corona_lower[2],
                                                    corona_lower[1], "Corona inner"))
                        early_end = early_time + corona_shot_s(corona_lower[0])
                        if mode_before != corona_mode:
                            early_end += switch_s
                        lines.append("")
                        
                        # Determine corona coverage based on totality duration
                        # Short (<90s): Basic coverage (lower, middle, upper)
                        # Medium (90-180s): Add 3R outer
                        # Long (180-300s): Add 4R outer  
                        # Very long (>300s): Add 8R outer (if exposure time permits)
                        if totality_duration < 90:
                            corona_pattern = ['lower', 'middle', 'upper']
                            coverage_desc = "basic (inner/middle/outer corona)"
                        elif totality_duration < 180:
                            corona_pattern = ['lower', '0.2R', 'middle', 'upper', '3R']
                            coverage_desc = "extended (inner to 3 solar radii)"
                        elif totality_duration < 300:
                            corona_pattern = ['lower', '0.2R', '0.5R', 'middle', 'upper', '3R', '4R']
                            coverage_desc = "comprehensive (inner to 4 solar radii)"
                        else:
                            # For very long totalities, include 8R
                            corona_pattern = ['lower', '0.2R', '0.5R', 'middle', 'upper', '3R', '4R', '8R']
                            coverage_desc = "full (inner to 8 solar radii)"
                        
                        lines.append(f'# Corona sequence throughout totality - {coverage_desc}')
                        lines.append(f'# Pattern cycles: {" → ".join(corona_pattern)}')
                        lines.append(f'# Note: Exposures >5s are automatically adjusted (increased ISO/wider aperture)')
                        if corona_bracket:
                            lines.append(f'# Every corona exposure is bracketed: "{corona_bracket}" (EV step, frames)')
                        
                        # Calculate earthshine shot times if earthshine is enabled
                        earthshine_times = []
                        earthshine = earthshine_plan()
                        if earthshine is not None:
                            # Earthshine shots at C2+30s and C3-30s, each keeping the camera busy
                            # for its exposure plus the time a picture takes
                            earthshine_busy = earthshine[3] + single_among_corona_s
                            earthshine_times = [
                                (30.0, 30.0 + earthshine_busy),  # C2+30s shot
                                (totality_duration - 30.0, totality_duration - 30.0 + earthshine_busy)  # C3-30s shot
                            ]

                        # Calculate HDR burst exclusion window if HDR is enabled (fired at MAX-10s)
                        hdr_times = []
                        if wizard.field('hdr_burst'):
                            hdr_stops_val = wizard.field('hdr_stops')
                            if wizard.field('hdr_start_auto'):
                                hdr_excl_speed_str = corona_lower[0]
                            else:
                                hdr_excl_speed_str = wizard.field('hdr_start_speed')
                            # Shutter-open times of the ramp down and back up, plus USB overhead
                            hdr_duration = hdr_duration_s(hdr_excl_speed_str, hdr_stops_val, hdr_sequence, timing)
                            # Same start as the take_hdr line written below
                            hdr_start = hdr_start_after_c2(hdr_duration)
                            if hdr_start is None:
                                hdr_start = totality_duration / 2 - hdr_duration / 2  # centre on MAX
                            hdr_times = [(hdr_start, hdr_start + hdr_duration + single_among_corona_s)]

                        # Merge all blocked windows and sort by start time for conflict detection
                        blocked_windows = sorted(earthshine_times + hdr_times)
                        
                        # Generate shots from C2+10s (or later, after the early totality
                        # shots) to C3-10s, tracking cumulative time to avoid overlaps
                        start_offset = max(10, early_end)
                        end_buffer = totality_end_buffer
                        usable_duration = totality_duration - start_offset - end_buffer
                        
                        if usable_duration > 0:
                            # Map pattern names to exposure tuples
                            layer_map = {
                                'lower': (corona_lower, 'inner'),
                                '0.2R': (corona_inner_02r, '0.2R'),
                                '0.5R': (corona_inner_05r, '0.5R'),
                                'middle': (corona_middle, 'middle'),
                                'upper': (corona_upper, 'upper'),
                                '3R': (corona_outer_3r, '3R'),
                                '4R': (corona_outer_4r, '4R'),
                                '8R': (corona_outer_8r, '8R')
                            }
                            
                            corona_shot_count = 0
                            current_time = start_offset  # Track cumulative time from C2
                            pattern_index = 0
                            # A bracket after an earthshine or HDR picture switches drive mode
                            after_blocked_window = False
                            
                            # Keep adding shots until we run out of time
                            while current_time < totality_duration - end_buffer:
                                # Cycle through the corona pattern
                                layer_type = corona_pattern[pattern_index % len(corona_pattern)]
                                exposure_tuple, layer_desc = layer_map[layer_type]
                                shutter, iso, ap = exposure_tuple
                                
                                # Offsets are written in whole seconds: round up first, so the
                                # end time (and the next shot) follow from the written start
                                current_time = math.ceil(current_time)
                                shot_end_time = current_time + corona_shot_s(shutter)
                                if after_blocked_window:
                                    shot_end_time += single_among_corona_s
                                
                                # Check if this shot would exceed totality
                                if shot_end_time > totality_duration - end_buffer:
                                    break
                                
                                # Check if this corona shot conflicts with any blocked window
                                # (earthshine shots or HDR burst)
                                conflicts = False
                                conflict_end = None
                                if blocked_windows:
                                    for bw_start, bw_end in blocked_windows:
                                        if not (shot_end_time <= bw_start or current_time >= bw_end):
                                            conflicts = True
                                            conflict_end = bw_end
                                            break
                                
                                # If no conflict, add the shot
                                if not conflicts:
                                    # Ceil to whole second so truncation never schedules earlier than intended
                                    written_time = math.ceil(current_time)
                                    offset_str = f"{int(written_time // 3600)}:{int((written_time % 3600) // 60):02d}:{int(written_time % 60):02d}.0"
                                    corona_shot_count += 1
                                    
                                    # Note if ISO or aperture was adjusted from preferred
                                    settings_note = ""
                                    if iso != preferred_iso or ap != aperture:
                                        settings_note = f" (adjusted: ISO {iso}, f/{ap})"
                                    
                                    lines.append(corona_command('C2', '+', offset_str, shutter, ap, iso,
                                                                f"Corona {layer_desc} #{corona_shot_count}{settings_note}"))
                                    
                                    # Move to next available time slot (after current shot completes)
                                    current_time = shot_end_time
                                    after_blocked_window = False
                                else:
                                    # Skip past the conflicting window
                                    if conflict_end is not None and conflict_end < totality_duration - end_buffer:
                                        current_time = conflict_end
                                        after_blocked_window = True
                                    else:
                                        current_time += 2.0
                                
                                pattern_index += 1
                        
                        lines.append("")
                    else:
                        # Fallback if timing calculation fails
                        lines.append("# Totality - Solar Corona (fallback timing)")
                        
                        corona_middle_shutter = get_shutter('corona_middle', '1/15')
                        
                        if wizard.field('prominences'):
                            prominences_shutter = get_shutter('prominences', '1/125')
                            lines.append(f'take_picture, C2, +, 0:00:03.0, {camera_name}, {prominences_shutter}, {aperture}, {preferred_iso}, "Prominences"')
                        
                        lines.extend(corona_maximum_lines(corona_middle_shutter))
                        
                        lines.append("")
                        
                except Exception as e:
                    # Fallback if timing calculation fails
                    lines.append("# Totality - Solar Corona (error in timing)")
                    lines.append(f"# Warning: {str(e)}")
                    corona_middle_shutter = get_shutter('corona_middle', '1/15')
                    
                    lines.extend(corona_maximum_lines(corona_middle_shutter))
                    
                    lines.append("")
            
            # Chromosphere
            if wizard.field('chromosphere'):
                lines.append("# Chromosphere")
                lines.append(f'take_picture, {_contact_offset("C3", -chromosphere_before_c3)}, {camera_name}, {chromosphere_shutter}, {aperture}, {preferred_iso}, "Chromosphere pre-C3"')
                lines.append("")
            
            # Earthshine (if requested and feasible)
            if wizard.field('earthshine'):
                # Check if earthshine fits within totality
                try:
                    # Get reference moments to calculate totality duration (reuse cached result when available)
                    if timings is None:
                        timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)

                    if timings and 'C2' in timings and 'C3' in timings:
                        totality_c2 = timings['C2'].time_utc
                        totality_c3 = timings['C3'].time_utc
                        totality_duration = (totality_c3 - totality_c2).total_seconds()
                        
                        # Get adjusted earthshine exposure (limit to 5 seconds)
                        earthshine_shutter, earthshine_iso, earthshine_aperture = get_adjusted_exposure('earthshine', '7', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                        earthshine_exposure = parse_shutter_speed(earthshine_shutter)
                        
                        # Calculate required time:
                        # - First shot at C2+30s takes earthshine_exposure seconds
                        # - Second shot at C3-30s takes earthshine_exposure seconds
                        # - Need buffer between shots and other activities (at least 20s)
                        required_time = 60 + (2 * earthshine_exposure) + 20  # 60s for buffers, 20s safety margin
                        
                        if totality_duration >= required_time:
                            lines.append("# Earthshine (moon's dark surface)")
                            lines.append("# Note: Some corona shots are automatically skipped to avoid conflicts with these long exposures")
                            
                            # Add note if settings were adjusted
                            if earthshine_iso != preferred_iso or earthshine_aperture != aperture:
                                lines.append(f"# Exposure adjusted to {earthshine_shutter} (ISO {earthshine_iso}, f/{earthshine_aperture}) to keep within 5s limit")
                            
                            lines.append(f'take_picture, C2, +, 0:00:30.0, {camera_name}, {earthshine_shutter}, {earthshine_aperture}, {earthshine_iso}, "Earthshine early totality"')
                            lines.append(f'take_picture, C3, -, 0:00:30.0, {camera_name}, {earthshine_shutter}, {earthshine_aperture}, {earthshine_iso}, "Earthshine late totality"')
                            lines.append("")
                        else:
                            lines.append("# Earthshine skipped - totality too short for long exposures")
                            lines.append(f"# (Totality: {int(totality_duration)}s, Required: {int(required_time)}s for {earthshine_shutter} exposures)")
                            lines.append("")
                    else:
                        # No totality data available
                        lines.append("# Earthshine skipped - could not determine totality duration")
                        lines.append("")
                except Exception as e:
                    # If we can't calculate, skip earthshine to be safe
                    lines.append("# Earthshine skipped - could not verify timing")
                    lines.append("")
            
            # HDR burst at maximum eclipse
            if wizard.field('hdr_burst'):
                hdr_stops = wizard.field('hdr_stops')
                if wizard.field('hdr_start_auto'):
                    hdr_adj = get_adjusted_exposure('corona_lower', '1/60', preferred_iso, aperture,
                                                    max_iso=iso_max, min_aperture=aperture)
                    hdr_start_speed = hdr_adj[0]
                    hdr_iso_auto = hdr_adj[1]
                else:
                    hdr_start_speed = wizard.field('hdr_start_speed')
                    hdr_iso_auto = preferred_iso
                hdr_iso = int(wizard.field('hdr_iso_manual')) if not wizard.field('hdr_iso_auto') else hdr_iso_auto
                n_shots = len(hdr_offsets(hdr_stops, hdr_sequence))
                hdr_duration = hdr_duration_s(hdr_start_speed, hdr_stops, hdr_sequence, timing)
                # The default round trip is left out, so the line reads as before
                hdr_sequence_field = f" {hdr_sequence}," if hdr_sequence == HDR_ONE_WAY else ""
                lines.append("# HDR burst at maximum eclipse")
                if hdr_sequence == HDR_ONE_WAY:
                    lines.append(f"# Fires {n_shots} shots ({hdr_stops} stops longer than {hdr_start_speed}, one way)")
                else:
                    lines.append(f"# Fires {n_shots} shots ({hdr_stops} stops longer than {hdr_start_speed} and back)")
                hdr_start = hdr_start_after_c2(hdr_duration)
                if hdr_start is not None:
                    # Relative to C2, so it lines up exactly with the other totality shots
                    lines.append(f"# Estimated duration: {hdr_duration:.1f}s, starting at C2+{hdr_start}s "
                                 "(centred on MAX, after the first earthshine shot)")
                    lines.append(f'take_hdr, C2, +, {_offset_str(hdr_start)}, {camera_name}, {hdr_start_speed}, {aperture}, {hdr_iso}, {hdr_stops},{hdr_sequence_field} "HDR at maximum eclipse"')
                else:
                    offset_s = math.ceil(hdr_duration / 2)
                    lines.append(f"# Estimated duration: {hdr_duration:.1f}s, starting at MAX-{offset_s}s")
                    lines.append(f'take_hdr, MAX, -, {_offset_str(offset_s)}, {camera_name}, {hdr_start_speed}, {aperture}, {hdr_iso}, {hdr_stops},{hdr_sequence_field} "HDR at maximum eclipse"')
                lines.append("")

            # C3 - Diamond ring and Baily's beads
            if wizard.field('diamond') or wizard.field('bailys'):
                lines.append("# Diamond ring and Baily's beads (C3)")
                if plan.beads_timed:
                    lines.append(_window_comment("C3"))
                    lines.append("# The beads burst is centred on that window.")
                lines.append(_beads_comment(plan.c3_beads_shooting_s, plan.c3_beads_s))
                lines.append(f"# The beads burst starts at {_relative('C3', c3_beads_start)} and the diamond ring burst "
                             f"at {_relative('C3', c3_diamond_start)}.")
                diamond_c3_shutter = get_shutter('diamond_ring_c3', '1/250')
                beads_c3_shutter = get_shutter('bailys_beads_c3', '1/500')

                if plan.c3_prepare_start is not None:
                    lines.append(f"# The camera needs ~{plan.switch_s:.0f}s to switch to continuous shooting after the "
                                 f"totality shots, so it is set up at {_relative('C3', plan.c3_prepare_start)}.")
                    lines.append(f'prepare_camera, {_contact_offset("C3", plan.c3_prepare_start)}, {camera_name}, {beads_c3_shutter}, {aperture}, {preferred_iso}, burst, "Prepare for C3 beads"')
                lines.append(f'take_burst, {_contact_offset("C3", c3_beads_start)}, {camera_name}, {beads_c3_shutter}, {aperture}, {preferred_iso}, {plan.c3_beads_param:g}, "C3 beads"')
                lines.append(f'take_burst, {_contact_offset("C3", c3_diamond_start)}, {camera_name}, {diamond_c3_shutter}, {aperture}, {preferred_iso}, {contact_burst_param:g}, "C3 diamond ring"')
                lines.append("# REPLACE SOLAR FILTER after C3!")
                lines.append("")
        
        # C4 - Fourth contact
        if wizard.field('c1_c4'):
            # Check if sun is above horizon at C4
            try:
                if timings is None:
                    timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)
                if timings and 'C4' in timings:
                    c4_time = timings['C4'].time_utc
                    _, c4_sun_alt = calculate_sun_altitudes_at_time(
                        c4_time, eclipse_time, longitude, latitude, altitude
                    )
                    
                    # Only add C4 shots if sun is above horizon
                    if _sun_above_horizon(timings, c4_time):
                        lines.append("# Fourth contact (C4) - with solar filter")
                        step = contact_steps["C4"]
                        if contact_step_note:
                            lines.append(f"# Shots {step}s apart: {contact_step_note}")
                        lines.append(f'take_picture, C4, -, {_offset_str(step)}, {camera_name}, {c4_shutter}, {aperture}, {preferred_iso}, "Fourth contact (C4-{step}s)"')
                        lines.append(f'take_picture, C4, +, 0:00:00.0, {camera_name}, {c4_shutter}, {aperture}, {preferred_iso}, "Fourth contact (C4)"')
                        lines.append(f'take_picture, C4, +, {_offset_str(step)}, {camera_name}, {c4_shutter}, {aperture}, {preferred_iso}, "Fourth contact (C4+{step}s)"')
                        lines.append("")
                    else:
                        lines.append(f"# Fourth contact (C4) skipped - sun below horizon (altitude: {c4_sun_alt:.1f}°)")
                        lines.append("")
            except Exception as e:
                # If we can't calculate, skip the shots
                lines.append(f"# Fourth contact (C4) skipped - could not calculate sun position")
                lines.append("")
        
        lines.append("# End of script")

        # Fit every exposure to the settings the tested camera really offers.
        header_end = lines.index("") if "" in lines else len(lines)
        separator = [] if header_end and lines[header_end - 1] == "#" else ["#"]
        self._adaptation = None
        if camera_profile is not None and camera_profile.shutter_speeds:
            limits = ExposureLimits(int(wizard.field('iso_min')), int(wizard.field('iso_max')),
                                    float(wizard.field('aperture_min')), float(wizard.field('aperture_max')))
            lines, self._adaptation = adapt_script_lines(lines, camera_name, camera_profile, limits)
            header = self._adaptation.header_lines(camera_profile)
        else:
            header = ["# Camera not tested: standard shutter speeds and estimated timing are used.",
                      "# Use 'Test Camera...' in the wizard to fit the script to the camera."]
        if camera_profile is not None and camera_profile.full_test:
            # SEW checks the script against the timing it was planned with
            header.append(timing_directive(camera_name, timing))
        lines[header_end:header_end] = separator + header

        # Kept for the camera test, which needs the contact times.
        self._last_timings = timings
        self._camera_profile = camera_profile
        return "\n".join(lines)
    
    def validatePage(self):
        """Validate and save the script when Finish is clicked."""
        save_path = self.save_path_edit.text()
        if not save_path:
            QMessageBox.warning(self, "No Save Path", "Please select a location to save the script.")
            return False
        
        try:
            script_content = self._generate_script()
            Path(save_path).write_text(script_content, encoding='utf-8')
            
            QMessageBox.information(
                self,
                "Script Generated",
                f"Photography script has been successfully saved to:\n{save_path}\n\n"
                "You can now load this script in the Solar Eclipse Workbench main application."
            )
            return True
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving Script",
                f"An error occurred while saving the script:\n{str(e)}"
            )
            return False


class SEWConfigWizard(QWizard):
    """Main wizard window for Solar Eclipse Workbench configuration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        try:
            _version = version("solareclipseworkbench")
        except PackageNotFoundError:
            _version = "unknown"
        self.setWindowTitle(f"Solar Eclipse Workbench Configuration Wizard v{_version}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.HaveHelpButton, False)
        self.setMinimumSize(900, 620)
        self.resize(950, 850)
        
        # Initialize configuration manager
        self.config_manager = ConfigManager()
        # Camera test results of this session (camera name -> camera_check.CameraProfile)
        self.camera_profiles = {}
        
        # Apply modern styling
        self._apply_modern_style()
        
        # Add pages
        self.setPage(PAGE_INTRO, IntroPage(self))
        self.setPage(PAGE_ECLIPSE_CONFIG, EclipseConfigPage(self))
        self.setPage(PAGE_EQUIPMENT, EquipmentPage(self))
        self.setPage(PAGE_PHENOMENA, PhenomenaPage(self))
        self.setPage(PAGE_SUMMARY, SummaryPage(self))
        
        self.setStartId(PAGE_INTRO)
        
        # Load settings
        self._load_settings()
        
        # Connect finished signal
        self.finished.connect(self._save_settings)
    
    def _apply_modern_style(self):
        """Apply modern styling to the wizard."""
        # Use Fusion style for modern cross-platform look
        QApplication.setStyle("Fusion")
        # setStyle() resets the application palette to the style's default
        # (light). Re-apply the dark palette immediately so that all palette-
        # driven painting (e.g. QLineEdit Base role) stays dark.
        if _is_dark_mode_preferred():
            QApplication.instance().setPalette(_build_dark_palette())

        if _is_dark_mode_preferred():
            window_bg    = "#1e1e1e"
            page_bg      = "#2b2b2b"
            input_bg     = "#3c3f41"
            input_fg     = "#eeeeee"
            input_border = "#555555"
            label_fg     = "#eeeeee"
            disabled_fg  = "#888888"
        else:
            window_bg    = "#f5f5f5"
            page_bg      = "white"
            input_bg     = "white"
            input_fg     = "#000000"
            input_border = "#bdc3c7"
            label_fg     = "#000000"
            disabled_fg  = "#888888"

        # Custom stylesheet (f-string: literal braces must be doubled)
        stylesheet = f"""
        QWizard {{
            background-color: {window_bg};
        }}
        QWizardPage {{
            background-color: {page_bg};
        }}
        QLabel {{
            color: {label_fg};
        }}
        QGroupBox {{
            font-weight: bold;
            border: 2px solid #3498db;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
            color: {label_fg};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }}
        QPushButton {{
            background-color: #3498db;
            color: white;
            border: none;
            padding: 5px 15px;
            border-radius: 3px;
            min-width: 80px;
        }}
        QPushButton:hover {{
            background-color: #2980b9;
        }}
        QPushButton:pressed {{
            background-color: #21618c;
        }}
        QPushButton:disabled {{
            background-color: #555555;
            color: {disabled_fg};
        }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {input_bg};
            color: {input_fg};
            padding: 5px;
            border: 1px solid {input_border};
            border-radius: 3px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 2px solid #3498db;
        }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            color: {disabled_fg};
        }}
        QTextEdit {{
            background-color: {input_bg};
            color: {input_fg};
            border: 1px solid {input_border};
            border-radius: 3px;
        }}
        QCheckBox, QRadioButton {{
            color: {label_fg};
            spacing: 5px;
        }}
        QCheckBox:disabled, QRadioButton:disabled {{
            color: {disabled_fg};
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 18px;
            height: 18px;
        }}
        """
        self.setStyleSheet(stylesheet)
    
    def _load_settings(self):
        """Load previous wizard settings."""
        settings = QSettings("SolarEclipseWorkbench", "ConfigWizard")
        # Could load previous values here if desired
        pass
    
    def _save_settings(self):
        """Save wizard settings for next time."""
        settings = QSettings("SolarEclipseWorkbench", "ConfigWizard")
        # Could save values here if desired
        pass


def main():
    """Main entry point for the wizard application."""
    setup_logging("sew_wizard")
    app = QApplication(sys.argv)
    app.setApplicationName("Solar Eclipse Workbench Configuration Wizard")
    apply_system_color_scheme(app)

    wizard = SEWConfigWizard()
    wizard.show()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
