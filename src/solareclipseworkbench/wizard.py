"""
Solar Eclipse Workbench Configuration Wizard

A PyQt6-based wizard to generate eclipse photography scripts interactively.
"""
import sys
import math
import json
import time
import requests
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
    calculate_sun_altitude_at_time,
    calculate_exposure,
    get_exposure_bracket,
    round_to_camera_shutter_speed
)
from solareclipseworkbench.reference_moments import calculate_reference_moments
from datetime import timedelta


# Wizard page IDs
PAGE_INTRO = 0
PAGE_ECLIPSE_CONFIG = 1
PAGE_EQUIPMENT = 2
PAGE_PHENOMENA = 3
PAGE_SUMMARY = 4


# ConfigManager, GeocodingWorker, and LocationWidget are imported from location_ui.


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
        
        lens_note = QLabel("Note: For telescopes, min and max aperture are often the same (e.g., f/6).")
        lens_note.setWordWrap(True)
        lens_note.setStyleSheet("QLabel { color: #888; font-size: 9pt; font-style: italic; }")
        lens_layout.addWidget(lens_note, 3, 0, 1, 3)
        
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
                self.aperture_min_spin.setValue(camera["aperture_min"])
                self.aperture_max_spin.setValue(camera["aperture_max"])
                
                # Set ISO values (with defaults for backward compatibility)
                self.preferred_iso_combo.setCurrentText(str(camera.get("preferred_iso", 400)))
                self.iso_min_combo.setCurrentText(str(camera.get("iso_min", 100)))
                self.iso_max_combo.setCurrentText(str(camera.get("iso_max", 1600)))
                
                # Make camera name read-only for saved cameras (not disabled, so validation works)
                self.camera_name_edit.setReadOnly(True)
                self.camera_name_edit.setStyleSheet("QLineEdit:read-only { background-color: #f0f0f0; }")
        
        # Refresh camera-ID status label
        self._refresh_camera_id_label(self.camera_name_edit.text().strip())
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
            from solareclipseworkbench.camera import get_cameras, get_camera_by_port, get_serial_number
            detected = get_cameras()
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
        phenomena_layout.addWidget(self.corona_check)

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
        self.registerField("hdr_start_auto", self.hdr_start_auto_radio)
        self.registerField("hdr_start_speed", self.hdr_start_speed_combo, "currentText")
        self.registerField("hdr_iso_auto", self.hdr_iso_auto_radio)
        self.registerField("hdr_iso_manual", self.hdr_iso_combo, "currentText")
    
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
        
        # ISO settings
        preferred_iso = wizard.field('preferred_iso')
        iso_min = wizard.field('iso_min')
        iso_max = wizard.field('iso_max')
        summary.append(f"ISO: {preferred_iso} (bracket range: {iso_min}-{iso_max})")
        
        filter_val = wizard.field('filter_value')
        if filter_val == "Manual":
            filter_val = f"{wizard.field('filter_manual')}"
        summary.append(f"Solar Filter ND: {filter_val}")
        
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
                root_logger.handlers = []
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
                sun_alt = data['sun_altitude']
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
        
        # C1 and C4 contacts
        if wizard.field('c1_c4'):
            # Check if sun is above horizon at C1
            try:
                if timings is None:
                    timings, _, _ = self._calculate_reference_moments_with_progress(longitude, latitude, altitude, eclipse_time)
                if timings and 'C1' in timings:
                    c1_time = timings['C1'].time_utc
                    c1_sun_alt = calculate_sun_altitude_at_time(
                        c1_time, eclipse_time, longitude, latitude, altitude
                    )
                    
                    # Only add C1 shots if sun is above horizon
                    if c1_sun_alt >= 0:
                        lines.append("# First contact (C1) - with solar filter")
                        c1_shutter = get_shutter('partial_c1', '1/800')
                        lines.append(f'take_picture, C1, -, 0:00:02.0, {camera_name}, {c1_shutter}, {aperture}, {preferred_iso}, "First contact (C1-2s)"')
                        lines.append(f'take_picture, C1, +, 0:00:00.0, {camera_name}, {c1_shutter}, {aperture}, {preferred_iso}, "First contact (C1)"')
                        lines.append(f'take_picture, C1, +, 0:00:02.0, {camera_name}, {c1_shutter}, {aperture}, {preferred_iso}, "First contact (C1+2s)"')
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
                    buffer_seconds = 10  # Buffer after C1 and before C2
                    c1_c2_duration = (c2_time - c1_time).total_seconds() - 2 * buffer_seconds
                    c1_start_time = c1_time + timedelta(seconds=buffer_seconds)
                    c2_end_time = c2_time - timedelta(seconds=buffer_seconds)
                    
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
                        sun_alt = calculate_sun_altitude_at_time(
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
                        
                        partial_shots_c1_c2.append((offset_str, shutter, adjusted_iso, shot_time, sun_alt))
                    
                    # Filter out shots below horizon and add sync commands
                    sync_interval_minutes = 0
                    if wizard.field('sync_enabled'):
                        sync_interval = wizard.field('sync_interval')
                        sync_interval_minutes = int(sync_interval.split()[0])
                    
                    shot_count = 0
                    for idx, (offset, shutter, iso, shot_time, sun_alt) in enumerate(partial_shots_c1_c2):
                        # Skip shots when sun is below horizon
                        if sun_alt < 0:
                            continue
                        
                        shot_count += 1
                        time_str = shot_time.strftime('%H:%M:%S')
                        iso_note = f" (ISO {iso})" if iso != preferred_iso else ""
                        lines.append(f'take_picture, C2, -, {offset}, {camera_name}, {shutter}, {aperture}, {iso}, "Partial C1-C2 #{shot_count} @ {time_str}, sun {sun_alt:.1f}°{iso_note}"')
                        
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
                    
                    c3_c4_duration = (c4_time - c3_time).total_seconds() - 2 * buffer_seconds
                    c3_start_time = c3_time + timedelta(seconds=buffer_seconds)
                    c4_end_time = c4_time - timedelta(seconds=buffer_seconds)
                    
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
                        sun_alt = calculate_sun_altitude_at_time(
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
                        
                        partial_shots_c3_c4.append((offset_str, shutter, adjusted_iso, shot_time, sun_alt))
                    
                    # Filter out shots below horizon
                    shot_count = 0
                    for idx, (offset, shutter, iso, shot_time, sun_alt) in enumerate(partial_shots_c3_c4):
                        # Skip shots when sun is below horizon
                        if sun_alt < 0:
                            continue
                        
                        shot_count += 1
                        time_str = shot_time.strftime('%H:%M:%S')
                        iso_note = f" (ISO {iso})" if iso != preferred_iso else ""
                        lines.append(f'take_picture, C3, +, {offset}, {camera_name}, {shutter}, {aperture}, {iso}, "Partial C3-C4 #{shot_count} @ {time_str}, sun {sun_alt:.1f}°{iso_note}"')
                        
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

                    buffer_seconds = 10
                    c1_c4_duration = (c4_time - c1_time).total_seconds() - 2 * buffer_seconds
                    c1_start_time = c1_time + timedelta(seconds=buffer_seconds)
                    c4_end_time = c4_time - timedelta(seconds=buffer_seconds)

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

                        sun_alt = calculate_sun_altitude_at_time(
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
                        partial_shots_c1_c4.append((offset_str, shutter, adjusted_iso, shot_time, sun_alt))

                    sync_interval_minutes = 0
                    if wizard.field('sync_enabled'):
                        sync_interval = wizard.field('sync_interval')
                        sync_interval_minutes = int(sync_interval.split()[0])

                    shot_count = 0
                    for idx, (offset, shutter, iso, shot_time, sun_alt) in enumerate(partial_shots_c1_c4):
                        if sun_alt < 0:
                            continue
                        shot_count += 1
                        time_str = shot_time.strftime('%H:%M:%S')
                        iso_note = f" (ISO {iso})" if iso != preferred_iso else ""
                        lines.append(f'take_picture, C1, +, {offset}, {camera_name}, {shutter}, {aperture}, {iso}, "Partial #{shot_count} @ {time_str}, sun {sun_alt:.1f}°{iso_note}"')

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
                beads_shutter = get_shutter('bailys_beads_c2', '1/500')
                diamond_shutter = get_shutter('diamond_ring_c2', '1/250')
                
                # Determine burst parameter based on camera brand:
                # Sony and Nikon use number of frames; Canon uses duration in seconds.
                is_nikon_or_sony = 'nikon' in camera_name.lower() or 'sony' in camera_name.lower()
                beads_burst_param = 30 if is_nikon_or_sony else 2  # Nikon/Sony: 30 pictures, Canon: 2 seconds
                diamond_burst_param = 30 if is_nikon_or_sony else 2
                
                # Start beads burst 1s earlier, diamond ring 1s later to avoid overlap (each burst ~2s + 3s gap)
                lines.append(f'take_burst, C2, -, 0:00:08.0, {camera_name}, {beads_shutter}, {aperture}, {preferred_iso}, {beads_burst_param}, "Pre-C2 beads"')
                lines.append(f'take_burst, C2, -, 0:00:02.0, {camera_name}, {diamond_shutter}, {aperture}, {preferred_iso}, {diamond_burst_param}, "C2 diamond ring"')
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
                        
                        # Start: Prominences and inner corona (first 10s)
                        if wizard.field('prominences'):
                            prominences_shutter = get_shutter('prominences', '1/125')
                            lines.append(f'# Early totality - prominences and inner corona')
                            lines.append(f'take_picture, C2, +, 0:00:03.0, {camera_name}, {prominences_shutter}, {aperture}, {preferred_iso}, "Prominences"')
                            lines.append(f'take_picture, C2, +, 0:00:06.0, {camera_name}, {corona_lower[0]}, {corona_lower[2]}, {corona_lower[1]}, "Corona inner"')
                        else:
                            lines.append(f'# Early totality - inner corona')
                            lines.append(f'take_picture, C2, +, 0:00:03.0, {camera_name}, {corona_lower[0]}, {corona_lower[2]}, {corona_lower[1]}, "Corona inner"')
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
                        
                        # Calculate earthshine shot times if earthshine is enabled
                        earthshine_times = []
                        if wizard.field('earthshine'):
                            earthshine_shutter, earthshine_iso, earthshine_aperture = get_adjusted_exposure('earthshine', '7', preferred_iso, aperture, max_iso=iso_max, min_aperture=aperture)
                            earthshine_exposure = parse_shutter_speed(earthshine_shutter)
                            # Earthshine shots at C2+30s and C3-30s
                            # Each occupies: start_time to start_time + exposure + 2s buffer
                            earthshine_times = [
                                (30.0, 30.0 + earthshine_exposure + 2.0),  # C2+30s shot
                                (totality_duration - 30.0, totality_duration - 30.0 + earthshine_exposure + 2.0)  # C3-30s shot
                            ]

                        # Calculate HDR burst exclusion window if HDR is enabled (fired at MAX-10s)
                        hdr_times = []
                        if wizard.field('hdr_burst'):
                            hdr_stops_val = wizard.field('hdr_stops')
                            if wizard.field('hdr_start_auto'):
                                hdr_excl_speed_str = corona_lower[0]
                            else:
                                hdr_excl_speed_str = wizard.field('hdr_start_speed')
                            hdr_start_speed_s = parse_shutter_speed(hdr_excl_speed_str)
                            # Sum actual shutter-open times: ramp down (start→slowest) then up
                            ramp_down = sum(hdr_start_speed_s * (2 ** k) for k in range(hdr_stops_val + 1))
                            ramp_up = sum(hdr_start_speed_s * (2 ** k) for k in range(hdr_stops_val - 1, -1, -1))
                            n_shots = 2 * hdr_stops_val + 1
                            # Per-shot USB overhead ~1.5 s (set_config + trigger + wait_capture_complete)
                            hdr_duration = ramp_down + ramp_up + n_shots * 1.5 + 2.0
                            hdr_start = totality_duration / 2 - hdr_duration / 2  # centre on MAX
                            hdr_times = [(hdr_start, hdr_start + hdr_duration)]

                        # Merge all blocked windows and sort by start time for conflict detection
                        blocked_windows = sorted(earthshine_times + hdr_times)
                        
                        # Generate shots from C2+10s to C3-10s, tracking cumulative time to avoid overlaps
                        start_offset = 10
                        end_buffer = 10
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
                            
                            # Keep adding shots until we run out of time
                            while current_time < totality_duration - end_buffer:
                                # Cycle through the corona pattern
                                layer_type = corona_pattern[pattern_index % len(corona_pattern)]
                                exposure_tuple, layer_desc = layer_map[layer_type]
                                shutter, iso, ap = exposure_tuple
                                
                                corona_exposure = parse_shutter_speed(shutter)
                                shot_end_time = current_time + corona_exposure + 2.0  # +2s buffer
                                
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
                                    
                                    lines.append(f'take_picture, C2, +, {offset_str}, {camera_name}, {shutter}, {ap}, {iso}, "Corona {layer_desc} #{corona_shot_count}{settings_note}"')
                                    
                                    # Move to next available time slot (after current shot completes)
                                    current_time = shot_end_time
                                else:
                                    # Skip past the conflicting window
                                    if conflict_end is not None and conflict_end < totality_duration - end_buffer:
                                        current_time = conflict_end
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
                        
                        # Generate bracket at MAX (5 exposures)
                        base_exposure = parse_shutter_speed(corona_middle_shutter)
                        bracket_exposures = get_exposure_bracket(base_exposure, stops=2, step=1.0)
                        
                        offset_seconds = 0.0
                        for i, exp in enumerate(bracket_exposures):
                            rounded_exp = round_to_camera_shutter_speed(exp)
                            shutter = format_shutter_speed(rounded_exp)
                            ev_offset = i - 2
                            
                            sign = '+' if offset_seconds >= 0 else '-'
                            abs_offset = abs(offset_seconds)
                            offset_str = f"{int(abs_offset // 3600)}:{int((abs_offset % 3600) // 60):02d}:{int(abs_offset % 60):02d}.0"
                            
                            lines.append(f'take_picture, MAX, {sign}, {offset_str}, {camera_name}, {shutter}, {aperture}, {preferred_iso}, "Corona maximum ({ev_offset:+d} EV)"')
                            
                            offset_seconds += rounded_exp + 2.0
                        
                        lines.append("")
                        
                except Exception as e:
                    # Fallback if timing calculation fails
                    lines.append("# Totality - Solar Corona (error in timing)")
                    lines.append(f"# Warning: {str(e)}")
                    corona_middle_shutter = get_shutter('corona_middle', '1/15')
                    
                    # Generate bracket at MAX (5 exposures)
                    base_exposure = parse_shutter_speed(corona_middle_shutter)
                    bracket_exposures = get_exposure_bracket(base_exposure, stops=2, step=1.0)
                    
                    offset_seconds = 0.0
                    for i, exp in enumerate(bracket_exposures):
                        rounded_exp = round_to_camera_shutter_speed(exp)
                        shutter = format_shutter_speed(rounded_exp)
                        ev_offset = i - 2
                        
                        sign = '+' if offset_seconds >= 0 else '-'
                        abs_offset = abs(offset_seconds)
                        offset_str = f"{int(abs_offset // 3600)}:{int((abs_offset % 3600) // 60):02d}:{int(abs_offset % 60):02d}.0"
                        
                        lines.append(f'take_picture, MAX, {sign}, {offset_str}, {camera_name}, {shutter}, {aperture}, {preferred_iso}, "Corona maximum ({ev_offset:+d} EV)"')
                        
                        offset_seconds += rounded_exp + 2.0
                    
                    lines.append("")
            
            # Chromosphere
            if wizard.field('chromosphere'):
                lines.append("# Chromosphere")
                chromo_shutter = get_shutter('chromosphere_c3', '1/250')
                lines.append(f'take_picture, C3, -, 0:00:02.0, {camera_name}, {chromo_shutter}, {aperture}, {preferred_iso}, "Chromosphere pre-C3"')
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
                hdr_start_speed_s = parse_shutter_speed(hdr_start_speed)
                ramp_down = sum(hdr_start_speed_s * (2 ** k) for k in range(hdr_stops + 1))
                ramp_up = sum(hdr_start_speed_s * (2 ** k) for k in range(hdr_stops - 1, -1, -1))
                n_shots = 2 * hdr_stops + 1
                hdr_duration = ramp_down + ramp_up + n_shots * 1.5 + 2.0
                offset_s = math.ceil(hdr_duration / 2)
                offset_str = f"0:{int(offset_s // 60):02d}:{int(offset_s % 60):02d}.0"
                lines.append("# HDR burst at maximum eclipse")
                lines.append(f"# Fires {n_shots} shots ({hdr_stops} stops down and back from {hdr_start_speed})")
                lines.append(f"# Estimated duration: {hdr_duration:.1f}s, starting at MAX-{offset_s}s")
                lines.append(f'take_hdr, MAX, -, {offset_str}, {camera_name}, {hdr_start_speed}, {aperture}, {hdr_iso}, {hdr_stops}, "HDR at maximum eclipse"')
                lines.append("")

            # C3 - Diamond ring and Baily's beads
            if wizard.field('diamond') or wizard.field('bailys'):
                lines.append("# Diamond ring and Baily's beads (C3)")
                diamond_c3_shutter = get_shutter('diamond_ring_c3', '1/250')
                beads_c3_shutter = get_shutter('bailys_beads_c3', '1/500')
                
                # Determine burst parameter based on camera brand:
                # Sony and Nikon use number of frames; Canon uses duration in seconds.
                is_nikon_or_sony = 'nikon' in camera_name.lower() or 'sony' in camera_name.lower()
                diamond_burst_param = 30 if is_nikon_or_sony else 2  # Nikon/Sony: 30 pictures, Canon: 2 seconds
                beads_burst_param = 30 if is_nikon_or_sony else 2
                
                # Start diamond ring 1s earlier, beads burst 1s later to avoid overlap (each burst ~2s + 3s gap)
                lines.append(f'take_burst, C3, +, 0:00:01.0, {camera_name}, {diamond_c3_shutter}, {aperture}, {preferred_iso}, {diamond_burst_param}, "C3 diamond ring"')
                lines.append(f'take_burst, C3, +, 0:00:08.0, {camera_name}, {beads_c3_shutter}, {aperture}, {preferred_iso}, {beads_burst_param}, "Post-C3 beads"')
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
                    c4_sun_alt = calculate_sun_altitude_at_time(
                        c4_time, eclipse_time, longitude, latitude, altitude
                    )
                    
                    # Only add C4 shots if sun is above horizon
                    if c4_sun_alt >= 0:
                        lines.append("# Fourth contact (C4) - with solar filter")
                        c4_shutter = get_shutter('partial_c4', '1/800')
                        lines.append(f'take_picture, C4, -, 0:00:02.0, {camera_name}, {c4_shutter}, {aperture}, {preferred_iso}, "Fourth contact (C4-2s)"')
                        lines.append(f'take_picture, C4, +, 0:00:00.0, {camera_name}, {c4_shutter}, {aperture}, {preferred_iso}, "Fourth contact (C4)"')
                        lines.append(f'take_picture, C4, +, 0:00:02.0, {camera_name}, {c4_shutter}, {aperture}, {preferred_iso}, "Fourth contact (C4+2s)"')
                        lines.append("")
                    else:
                        lines.append(f"# Fourth contact (C4) skipped - sun below horizon (altitude: {c4_sun_alt:.1f}°)")
                        lines.append("")
            except Exception as e:
                # If we can't calculate, skip the shots
                lines.append(f"# Fourth contact (C4) skipped - could not calculate sun position")
                lines.append("")
        
        lines.append("# End of script")
        
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
    app = QApplication(sys.argv)
    app.setApplicationName("Solar Eclipse Workbench Configuration Wizard")
    apply_system_color_scheme(app)

    wizard = SEWConfigWizard()
    wizard.show()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
