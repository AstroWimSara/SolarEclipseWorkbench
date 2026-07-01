"""
Shared location UI components for Solar Eclipse Workbench.

Provides:
    - ConfigManager: saves/loads camera and location configurations (JSON).
    - GeocodingWorker: background thread that geocodes an address via Nominatim
      and fetches elevation from Open-Elevation.
    - LocationWidget: a self-contained QWidget with a saved-locations drop-down,
      an optional address-search bar and coordinate fields.  Used by both
      gui.py (LocationPopup) and wizard.py (EclipseConfigPage).
"""
import json
import time
import requests
from datetime import timedelta
from pathlib import Path
from typing import Optional, Dict, List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QMessageBox,
    QDialog, QDialogButtonBox,
)
from solareclipseworkbench.qt_utils import dark_lineedit_style, apply_dark_to_lineedit

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Manages saving and loading of camera and location configurations."""

    def __init__(self):
        self.config_file = Path.home() / ".sew_wizard_config.json"
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load configuration from file, or create a default one."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return self._default_config()
        return self._default_config()

    def _default_config(self) -> Dict:
        """Return the default (empty) configuration structure."""
        return {
            "cameras": [],
            "locations": [],
            "last_used": {
                "camera": None,
                "location": None,
            },
            # Maps camera serial numbers to user-defined alias names.
            # A single serial can have *multiple* aliases so that the same physical
            # camera body can be saved under different configuration names
            # (e.g. "Canon EOS 80D (telescope)" and "Canon EOS 80D (lens)").
            # Format: {"<serial_number>": ["alias1", "alias2", ...], ...}
            "camera_aliases": {},
        }

    def save_config(self):
        """Persist the in-memory configuration to disk."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save configuration: {e}")

    # ------------------------------------------------------------------
    # Camera helpers
    # ------------------------------------------------------------------

    def add_camera(self, name: str, focal_length: int, aperture_min: float,
                   aperture_max: float, filter_nd: str, preferred_iso: int = 400,
                   iso_min: int = 100, iso_max: int = 1600) -> None:
        """Add or update a camera configuration."""
        for camera in self.config["cameras"]:
            if camera["name"] == name:
                camera.update({
                    "focal_length": focal_length,
                    "aperture_min": aperture_min,
                    "aperture_max": aperture_max,
                    "filter_nd": filter_nd,
                    "preferred_iso": preferred_iso,
                    "iso_min": iso_min,
                    "iso_max": iso_max,
                })
                self.save_config()
                return
        self.config["cameras"].append({
            "name": name,
            "focal_length": focal_length,
            "aperture_min": aperture_min,
            "aperture_max": aperture_max,
            "filter_nd": filter_nd,
            "preferred_iso": preferred_iso,
            "iso_min": iso_min,
            "iso_max": iso_max,
        })
        self.save_config()

    def get_cameras(self) -> List[Dict]:
        """Return all saved camera configurations."""
        return self.config["cameras"]

    def get_camera(self, name: str) -> Optional[Dict]:
        """Return a camera configuration by name, or None."""
        for camera in self.config["cameras"]:
            if camera["name"] == name:
                return camera
        return None

    def set_last_used_camera(self, name: str) -> None:
        """Record the most-recently used camera name."""
        self.config["last_used"]["camera"] = name
        self.save_config()

    def get_last_used_camera(self) -> Optional[str]:
        """Return the most-recently used camera name, or None."""
        return self.config["last_used"].get("camera")

    # ------------------------------------------------------------------
    # Location helpers
    # ------------------------------------------------------------------

    def add_location(self, name: str, latitude: float, longitude: float,
                     altitude: float) -> None:
        """Add or update a named location."""
        for location in self.config["locations"]:
            if location["name"] == name:
                location.update({
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude": altitude,
                })
                self.save_config()
                return
        self.config["locations"].append({
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
        })
        self.save_config()

    def get_locations(self) -> List[Dict]:
        """Return all saved locations."""
        return self.config["locations"]

    def get_location(self, name: str) -> Optional[Dict]:
        """Return a saved location by name, or None."""
        for location in self.config["locations"]:
            if location["name"] == name:
                return location
        return None

    def set_last_used_location(self, name: str) -> None:
        """Record the most-recently used location name."""
        self.config["last_used"]["location"] = name
        self.save_config()

    def get_last_used_location(self) -> Optional[str]:
        """Return the most-recently used location name, or None."""
        return self.config["last_used"].get("location")

    def delete_location(self, name: str) -> bool:
        """Remove a saved location by name. Returns True if it was found and deleted."""
        original_len = len(self.config["locations"])
        self.config["locations"] = [
            loc for loc in self.config["locations"] if loc["name"] != name
        ]
        if len(self.config["locations"]) < original_len:
            # Clear last_used if we just deleted it
            if self.config["last_used"].get("location") == name:
                self.config["last_used"]["location"] = None
            self.save_config()
            return True
        return False

    def delete_camera(self, name: str) -> bool:
        """Remove a saved camera by name. Returns True if it was found and deleted."""
        original_len = len(self.config["cameras"])
        self.config["cameras"] = [
            cam for cam in self.config["cameras"] if cam["name"] != name
        ]
        if len(self.config["cameras"]) < original_len:
            # Clear last_used if we just deleted it
            if self.config["last_used"].get("camera") == name:
                self.config["last_used"]["camera"] = None
            self.save_config()
            return True
        return False

    # ------------------------------------------------------------------
    # Camera alias helpers  (serial number → script alias mapping)
    # ------------------------------------------------------------------

    def get_camera_aliases(self) -> Dict[str, List[str]]:
        """Return the full serial-number → aliases mapping dict.

        Each serial maps to a **list** of alias names.  A single physical camera
        body can have multiple aliases — e.g. the same body used with a telescope
        ("Canon EOS 80D (telescope)") and with a lens
        ("Canon EOS 80D (lens)").

        Old config files that stored a plain string value per serial are migrated
        to a one-element list on first read so that callers always see lists.
        """
        raw = self.config.setdefault("camera_aliases", {})
        # Migrate old string → list format transparently
        for serial, val in list(raw.items()):
            if isinstance(val, str):
                raw[serial] = [val]
        return raw

    def set_camera_alias(self, serial: str, alias: str) -> None:
        """Link *alias* to *serial*.

        A physical camera (identified by *serial*) can have **multiple** aliases.
        For example, the same camera body used with a telescope and with a lens
        can be saved as two named configurations and the script picks the right
        one by name.  ``set_camera_alias`` therefore *adds* *alias* to the list
        for *serial* rather than replacing it.

        The reverse direction remains 1-to-1: if *alias* was previously mapped to
        a **different** serial, that old mapping is removed first so that the same
        alias name never points to two different physical camera bodies.
        """
        raw = self.config.setdefault("camera_aliases", {})
        # Migrate any legacy string values
        for s, v in list(raw.items()):
            if isinstance(v, str):
                raw[s] = [v]
        # Remove alias from any other serial that currently owns it
        for s, aliases_list in list(raw.items()):
            if s != serial and alias in aliases_list:
                aliases_list.remove(alias)
                if not aliases_list:
                    del raw[s]
        # Add alias to this serial's list
        serial_aliases = raw.setdefault(serial, [])
        if alias not in serial_aliases:
            serial_aliases.append(alias)
        self.save_config()

    def delete_camera_alias(self, serial: str, alias: Optional[str] = None) -> bool:
        """Remove an alias mapping for *serial*.

        If *alias* is given, only that specific alias is removed from *serial*'s
        list.  If *alias* is ``None``, **all** aliases for *serial* are removed.
        Returns ``True`` if anything was changed.
        """
        raw = self.config.get("camera_aliases", {})
        if serial not in raw:
            return False
        if alias is None:
            del raw[serial]
        else:
            val = raw[serial]
            if isinstance(val, str):
                val = [val]
            if alias not in val:
                return False
            val.remove(alias)
            if val:
                raw[serial] = val
            else:
                del raw[serial]
        self.save_config()
        return True

    def get_serial_for_alias(self, alias: str) -> Optional[str]:
        """Return the serial number that is mapped to *alias*, or None."""
        for serial, val in self.config.get("camera_aliases", {}).items():
            aliases_list = [val] if isinstance(val, str) else val
            if alias in aliases_list:
                return serial
        return None


# ---------------------------------------------------------------------------
# GeocodingWorker
# ---------------------------------------------------------------------------

class GeocodingWorker(QThread):
    """Background thread that geocodes an address and fetches its elevation.

    Signals:
        finished(dict): emitted on success with keys latitude, longitude,
            altitude, display_name.
        error(str): emitted on failure with a human-readable message.
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, address: str):
        super().__init__()
        self.address = address

    def run(self):
        """Perform geocoding in a background thread."""
        try:
            if not GEOPY_AVAILABLE:
                self.error.emit(
                    "Geopy library not installed. Install with: pip install geopy"
                )
                return

            geolocator = Nominatim(user_agent="SolarEclipseWorkbench/1.3.0")

            # Nominatim usage policy: max 1 request per second.
            time.sleep(1)

            location = geolocator.geocode(self.address, timeout=10)
            if not location:
                self.error.emit(f"Address not found: {self.address}")
                return

            latitude = location.latitude
            longitude = location.longitude
            display_name = location.address

            # Try to fetch elevation from Open-Elevation.
            altitude = 0.0
            try:
                response = requests.get(
                    f"https://api.open-elevation.com/api/v1/lookup"
                    f"?locations={latitude},{longitude}",
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results"):
                        altitude = float(data["results"][0]["elevation"])
            except Exception as exc:
                print(f"Elevation lookup failed: {exc}")

            self.finished.emit({
                "latitude": latitude,
                "longitude": longitude,
                "altitude": altitude,
                "display_name": display_name,
            })

        except GeocoderTimedOut:
            self.error.emit("Geocoding service timed out. Please try again.")
        except GeocoderServiceError as exc:
            self.error.emit(f"Geocoding service error: {exc}")
        except Exception as exc:
            self.error.emit(f"Error: {exc}")


# ---------------------------------------------------------------------------
# ElevationWorker
# ---------------------------------------------------------------------------

class ElevationWorker(QThread):
    """Background thread that fetches elevation from Open-Elevation.

    Used as a fallback when the phone/browser does not report altitude.

    Signals:
        finished(float): emitted on success with the elevation in metres.
        error(str): emitted on failure with a human-readable message.
    """

    finished = pyqtSignal(float)
    error = pyqtSignal(str)

    def __init__(self, latitude: float, longitude: float):
        super().__init__()
        self.latitude = latitude
        self.longitude = longitude

    def run(self):
        try:
            response = requests.get(
                "https://api.open-elevation.com/api/v1/lookup",
                params={"locations": f"{self.latitude},{self.longitude}"},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    self.finished.emit(float(data["results"][0]["elevation"]))
                    return
            self.error.emit(f"Open-Elevation returned status {response.status_code}")
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# LocationWidget
# ---------------------------------------------------------------------------

class LocationWidget(QWidget):
    """Self-contained widget for choosing an observation location.

    Features
    --------
    * Drop-down of saved locations (populated from *config_manager*).
    * Optional address-search bar (requires the *geopy* package).
    * Editable coordinate fields (longitude, latitude, altitude).
    * "Save Location" button that persists the entered coordinates.
    * "Get GPS from Phone" button (phone browser via local HTTPS server).
    * "Get GPS from USB Device" button (reads NMEA directly from a USB GPS
      receiver such as the VK-162 G-Mouse, no gpsd required).

    The widget exposes the individual ``QLineEdit`` widgets as public
    attributes so that callers (wizard field-registration, plot callbacks,
    etc.) can access their text directly:

        ``longitude_edit``, ``latitude_edit``, ``altitude_edit``,
        ``location_name_edit``, ``location_combo``

    After a USB GPS fix the measured GPS-time offset is available as:

        ``gps_time_offset``  (``timedelta``, GPS UTC − computer UTC)

    and the ``gps_time_offset_changed`` signal is emitted.

    Usage
    -----
    ::

        mgr = ConfigManager()
        w = LocationWidget(mgr)
        # pre-fill from an existing model:
        w.set_coordinates(lon, lat, alt)
        # retrieve validated coordinates:
        lon, lat, alt = w.get_coordinates()   # raises ValueError if invalid
    """

    # Emitted when a USB GPS fix provides a GPS–computer time offset.
    # Carries the timedelta (GPS UTC − computer UTC); zero if no GPS fix yet.
    gps_time_offset_changed = pyqtSignal(object)

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self._config_manager = config_manager
        self._geocoding_worker: Optional[GeocodingWorker] = None
        self._gps_worker = None
        self._gps_dialog: Optional[QDialog] = None
        self._gps_status_label: Optional[QLabel] = None
        self._gps_url_label: Optional[QLabel] = None
        self._usb_gps_worker = None
        self._usb_gps_dialog: Optional[QDialog] = None
        self._usb_gps_status_label: Optional[QLabel] = None
        self._elevation_worker: Optional[ElevationWorker] = None
        # GPS–computer time offset measured by the USB GPS worker.
        # Zero (timedelta(0)) until a USB GPS fix is acquired.
        self.gps_time_offset: timedelta = timedelta(0)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Widget lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Ensure all background threads are stopped when the widget closes."""
        self._cleanup_usb_gps_worker()
        for attr in ('_geocoding_worker', '_elevation_worker'):
            worker = getattr(self, attr, None)
            if worker is not None:
                setattr(self, attr, None)
                worker.wait(2000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_coordinates(self, longitude: Optional[float],
                        latitude: Optional[float],
                        altitude: Optional[float]) -> None:
        """Pre-fill coordinate fields with existing values (may be None)."""
        if longitude is not None:
            self.longitude_edit.setText(str(longitude))
        if latitude is not None:
            self.latitude_edit.setText(str(latitude))
        if altitude is not None:
            self.altitude_edit.setText(str(altitude))

    def get_coordinates(self):
        """Return ``(longitude, latitude, altitude)`` as floats.

        Raises ``ValueError`` if any field contains a non-numeric value or
        is empty.
        """
        longitude = float(self.longitude_edit.text())
        latitude = float(self.latitude_edit.text())
        altitude = float(self.altitude_edit.text())
        return longitude, latitude, altitude

    def reload_saved_locations(self) -> None:
        """Repopulate the drop-down with the current saved locations."""
        # Remove all "(Saved)" items, then re-add from config.
        for i in range(self.location_combo.count() - 1, -1, -1):
            if self.location_combo.itemText(i).endswith(" (Saved)"):
                self.location_combo.removeItem(i)
        for saved in self._config_manager.get_locations():
            self.location_combo.addItem(f"{saved['name']} (Saved)")

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Saved-locations drop-down ---
        saved_row = QHBoxLayout()
        saved_row.addWidget(QLabel("Saved Location:"))
        self.location_combo = QComboBox()
        self.location_combo.addItem("Custom")
        for saved in self._config_manager.get_locations():
            self.location_combo.addItem(f"{saved['name']} (Saved)")
        saved_row.addWidget(self.location_combo, 1)
        layout.addLayout(saved_row)

        # --- Address search (only when geopy is available) ---
        if GEOPY_AVAILABLE:
            search_row = QHBoxLayout()
            search_row.addWidget(QLabel("Search Address:"))
            self.address_search_edit = QLineEdit()
            self.address_search_edit.setPlaceholderText(
                "Enter city, street, or landmark"
            )
            apply_dark_to_lineedit(self.address_search_edit)
            self.address_search_edit.returnPressed.connect(self._search_address)
            search_row.addWidget(self.address_search_edit, 1)

            self.search_btn = QPushButton("Search")
            self.search_btn.clicked.connect(self._search_address)
            self.search_btn.setToolTip(
                "Search for the address and auto-fill coordinates & elevation"
            )
            search_row.addWidget(self.search_btn)
            layout.addLayout(search_row)

            self.search_status_label = QLabel("")
            self.search_status_label.setStyleSheet(
                "QLabel { color: #555; font-style: italic; }"
            )
            self.search_status_label.setWordWrap(True)
            layout.addWidget(self.search_status_label)
        else:
            self.address_search_edit = None
            self.search_btn = None
            self.search_status_label = None

        # --- Coordinate fields ---
        coord_grid = QGridLayout()

        coord_grid.addWidget(QLabel("Location Name:"), 0, 0)
        self.location_name_edit = QLineEdit()
        self.location_name_edit.setPlaceholderText("Name this location to save it")
        apply_dark_to_lineedit(self.location_name_edit)
        coord_grid.addWidget(self.location_name_edit, 0, 1)

        coord_grid.addWidget(QLabel("Longitude [°]:"), 1, 0)
        self.longitude_edit = QLineEdit()
        self.longitude_edit.setPlaceholderText("-180 to 180 (E: +, W: −)")
        self.longitude_edit.setValidator(QDoubleValidator(-180.0, 180.0, 5))
        apply_dark_to_lineedit(self.longitude_edit)
        self.longitude_edit.setToolTip(
            "Positive values: East of Greenwich meridian; "
            "Negative values: West of Greenwich meridian"
        )
        coord_grid.addWidget(self.longitude_edit, 1, 1)

        coord_grid.addWidget(QLabel("Latitude [°]:"), 2, 0)
        self.latitude_edit = QLineEdit()
        self.latitude_edit.setPlaceholderText("-90 to 90 (N: +, S: −)")
        self.latitude_edit.setValidator(QDoubleValidator(-90.0, 90.0, 5))
        apply_dark_to_lineedit(self.latitude_edit)
        self.latitude_edit.setToolTip(
            "Positive values: Northern hemisphere; Negative values: Southern hemisphere"
        )
        coord_grid.addWidget(self.latitude_edit, 2, 1)

        coord_grid.addWidget(QLabel("Altitude [m]:"), 3, 0)
        self.altitude_edit = QLineEdit()
        self.altitude_edit.setPlaceholderText("Altitude above sea level")
        self.altitude_edit.setValidator(QDoubleValidator(-500.0, 9000.0, 1))
        apply_dark_to_lineedit(self.altitude_edit)
        coord_grid.addWidget(self.altitude_edit, 3, 1)

        self.save_location_btn = QPushButton("Save Location")
        self.save_location_btn.clicked.connect(self._save_location)
        self.save_location_btn.setToolTip("Save this location for future use")
        coord_grid.addWidget(self.save_location_btn, 4, 1)

        self.delete_location_btn = QPushButton("Delete Location")
        self.delete_location_btn.clicked.connect(self._delete_location)
        self.delete_location_btn.setToolTip("Delete the currently selected saved location")
        self.delete_location_btn.setEnabled(False)
        coord_grid.addWidget(self.delete_location_btn, 5, 1)

        layout.addLayout(coord_grid)

        # --- GPS from phone button ---
        self.gps_btn = QPushButton("\U0001f4f1  Get GPS from Phone")
        self.gps_btn.setToolTip(
            "Start a local HTTPS server and open the URL on your phone's browser "
            "to capture your GPS coordinates automatically.\n"
            "Works over WiFi or phone hotspot (no internet required)."
        )
        self.gps_btn.clicked.connect(self._start_gps_capture)
        layout.addWidget(self.gps_btn)

        # --- USB GPS button ---
        self.usb_gps_btn = QPushButton("\U0001F6F0  Get GPS from USB Device")
        self.usb_gps_btn.setToolTip(
            "Read coordinates and precise UTC time from a connected USB GPS\n"
            "receiver (e.g. VK-162 G-Mouse). No gpsd required.\n"
            "Linux/WSL: user must be in the 'dialout' group."
        )
        self.usb_gps_btn.clicked.connect(self._start_usb_gps_capture)
        layout.addWidget(self.usb_gps_btn)

        # Connect combo *after* creating all sub-widgets.
        self.location_combo.currentTextChanged.connect(self._on_location_changed)

        # Restore last-used location (fires _on_location_changed if found).
        last = self._config_manager.get_last_used_location()
        if last:
            idx = self.location_combo.findText(f"{last} (Saved)")
            if idx >= 0:
                self.location_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_fields_editable(self, editable: bool) -> None:
        """Enable or disable the manual-entry coordinate fields."""
        self.location_name_edit.setEnabled(editable)
        self.longitude_edit.setEnabled(editable)
        self.latitude_edit.setEnabled(editable)
        self.altitude_edit.setEnabled(editable)
        self.save_location_btn.setEnabled(editable)
        self.delete_location_btn.setEnabled(not editable)

    # ------------------------------------------------------------------
    # Phone GPS capture
    # ------------------------------------------------------------------

    def _start_gps_capture(self) -> None:
        """Start the phone GPS web server and show a dialog with the URL."""
        try:
            from solareclipseworkbench.phone_gps import get_phone_gps_worker_class
            PhoneGpsWorker = get_phone_gps_worker_class()
        except Exception as exc:
            QMessageBox.critical(self, "GPS Error",
                                 f"Could not load GPS server module:\n{exc}")
            return

        # Build the URL dialog
        self._gps_dialog = QDialog(self)
        self._gps_dialog.setWindowTitle("Get GPS from Phone")
        self._gps_dialog.setMinimumWidth(520)
        self._gps_dialog.setMinimumHeight(300)
        dlg_layout = QVBoxLayout(self._gps_dialog)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.setSpacing(10)

        self._gps_status_label = QLabel("\u23f3 Starting server\u2026")
        self._gps_status_label.setWordWrap(True)
        dlg_layout.addWidget(self._gps_status_label)

        self._gps_url_label = QLabel("")
        self._gps_url_label.setWordWrap(True)
        self._gps_url_label.setTextInteractionFlags(
            self._gps_url_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._gps_url_label.setMinimumHeight(80)
        dlg_layout.addWidget(self._gps_url_label)

        note = QLabel(
            "<small><i>"
            "No WiFi at your eclipse site? Enable your phone\u2019s hotspot,<br>"
            "connect this laptop to it, then open the URL on the phone\u2019s<br>"
            "own browser. See <b>docs/GPS_PHONE.md</b> for details."
            "</i></small>"
        )
        note.setWordWrap(True)
        dlg_layout.addWidget(note)

        dlg_layout.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btn_box.rejected.connect(self._cancel_gps_capture)
        dlg_layout.addWidget(btn_box)

        # Start the worker
        self._gps_worker = PhoneGpsWorker(port=8765, parent=self)
        self._gps_worker.server_started.connect(self._on_gps_server_started)
        self._gps_worker.location_received.connect(self._on_gps_location_received)
        self._gps_worker.error.connect(self._on_gps_error)
        self._gps_worker.start()

        self.gps_btn.setEnabled(False)
        self._gps_dialog.exec()

    def _on_gps_server_started(self, lan_url: str, local_url: str) -> None:
        """Update the dialog once the server is ready."""
        if self._gps_status_label:
            self._gps_status_label.setText(
                "\u2197\ufe0e Open this URL on your phone\u2019s browser "
                "(same WiFi or phone hotspot):"
            )
        if self._gps_url_label:
            self._gps_url_label.setText(
                f"<p style='font-size:14pt; font-weight:bold; margin:4px 0'>{lan_url}</p>"
                f"<p style='color:gray; margin:2px 0'><small>Or from this laptop: {local_url}</small></p>"
                "<p style='color:gray; margin:2px 0'><small>"
                "Certificate warning: tap \u2018Advanced\u2019 \u2192 \u2018Proceed\u2019 (Chrome) "
                "/ \u2018Visit this website\u2019 (Safari)"
                "</small></p>"
            )

    def _on_gps_location_received(self, data: dict) -> None:
        """Fill coordinate fields with the received GPS fix and close the dialog."""
        # Switch combo to Custom so fields become editable
        self.location_combo.setCurrentText("Custom")
        self._set_fields_editable(True)

        lat = data.get("lat")
        lon = data.get("lon")
        alt = data.get("alt")

        if lat is not None:
            self.latitude_edit.setText(f"{lat:.6f}")
        if lon is not None:
            self.longitude_edit.setText(f"{lon:.6f}")
        if alt is not None:
            self.altitude_edit.setText(f"{alt:.1f}")
        elif lat is not None and lon is not None:
            # Browser did not supply altitude — fetch it from Open-Elevation
            self.altitude_edit.setPlaceholderText("Fetching elevation…")
            self._elevation_worker = ElevationWorker(lat, lon)
            self._elevation_worker.finished.connect(self._on_elevation_received)
            self._elevation_worker.error.connect(self._on_elevation_error)
            self._elevation_worker.start()

        if self._gps_dialog:
            self._gps_dialog.accept()
            self._gps_dialog = None
        self.gps_btn.setEnabled(True)
        if self._gps_worker:
            self._gps_worker.stop_server()
            self._gps_worker = None

    def _on_elevation_received(self, elevation: float) -> None:
        """Fill the altitude field after a successful Open-Elevation lookup."""
        self.altitude_edit.setText(f"{elevation:.1f}")
        self.altitude_edit.setPlaceholderText("Altitude above sea level")
        worker = self._elevation_worker
        self._elevation_worker = None
        if worker is not None:
            worker.wait(1000)

    def _on_elevation_error(self, message: str) -> None:
        """Clear the placeholder text when the elevation lookup fails."""
        self.altitude_edit.setPlaceholderText("Altitude above sea level")
        self.altitude_edit.setText("0.0")
        print(f"Elevation lookup failed: {message}")
        worker = self._elevation_worker
        self._elevation_worker = None
        if worker is not None:
            worker.wait(1000)

    def _on_gps_error(self, message: str) -> None:
        """Show an error and close the GPS dialog."""
        if self._gps_dialog:
            self._gps_dialog.reject()
            self._gps_dialog = None
        self.gps_btn.setEnabled(True)
        QMessageBox.critical(self, "GPS Error", f"GPS server error:\n{message}")

    def _cancel_gps_capture(self) -> None:
        """Called when the user cancels the GPS dialog."""
        if self._gps_worker:
            self._gps_worker.stop_server()
            self._gps_worker.quit()
            self._gps_worker = None
        if self._gps_dialog:
            self._gps_dialog.reject()
            self._gps_dialog = None
        self.gps_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # USB GPS capture
    # ------------------------------------------------------------------

    def _start_usb_gps_capture(self) -> None:
        """Start reading from a USB GPS receiver and show a progress dialog."""
        if self._usb_gps_worker:
            QMessageBox.warning(self, "USB GPS Already Running",
                                "A USB GPS capture is already in progress. Please wait or cancel it first.")
            return

        try:
            from solareclipseworkbench.usb_gps import get_usb_gps_worker_class
            UsbGpsWorker = get_usb_gps_worker_class()
        except Exception as exc:
            QMessageBox.critical(self, "USB GPS Error",
                                 f"Could not load USB GPS module:\n{exc}")
            return

        self._usb_gps_dialog = QDialog(self)
        self._usb_gps_dialog.setWindowTitle("Get GPS from USB Device")
        self._usb_gps_dialog.setMinimumWidth(480)
        dlg_layout = QVBoxLayout(self._usb_gps_dialog)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.setSpacing(10)

        self._usb_gps_status_label = QLabel(
            "\u23f3 Scanning for USB GPS device\u2026"
        )
        self._usb_gps_status_label.setWordWrap(True)
        dlg_layout.addWidget(self._usb_gps_status_label)

        note = QLabel(
            "<small><i>"
            "Plug in the GPS receiver and wait for a satellite fix.<br>"
            "This may take 1\u20133\u00a0minutes in open sky (cold start).<br>"
            "Linux/WSL: user must be in the <b>dialout</b> group \u2014 see README."
            "</i></small>"
        )
        note.setWordWrap(True)
        dlg_layout.addWidget(note)

        dlg_layout.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btn_box.rejected.connect(self._cancel_usb_gps_capture)
        dlg_layout.addWidget(btn_box)

        self._usb_gps_worker = UsbGpsWorker(fix_timeout=120.0, parent=None)
        self._usb_gps_worker.status.connect(self._on_usb_gps_status)
        self._usb_gps_worker.location_received.connect(
            self._on_usb_gps_location_received
        )
        self._usb_gps_worker.error.connect(self._on_usb_gps_error)
        self._usb_gps_worker.start()

        self.usb_gps_btn.setEnabled(False)
        self._usb_gps_dialog.exec()
        
        # Ensure cleanup if dialog was closed by window manager instead of via signals
        self._cleanup_usb_gps_worker()

    def _on_usb_gps_status(self, message: str) -> None:
        """Update the dialog status label with a progress message."""
        if self._usb_gps_status_label:
            self._usb_gps_status_label.setText(message)

    def _cleanup_usb_gps_worker(self) -> None:
        """Safely stop, disconnect, and clean up the USB GPS worker thread."""
        # Move to local variable and clear the instance attribute first so that
        # any re-entrant call (e.g. from a stale queued signal) is a no-op.
        worker = self._usb_gps_worker
        if worker is None:
            return
        self._usb_gps_worker = None

        # Disconnect all signals to prevent stale callbacks.
        for sig in (worker.status, worker.location_received, worker.error):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass

        # Ask the thread to stop its loop, then wait for the OS thread to exit.
        # wait() uses pthread_join internally and guarantees that
        # QThreadPrivate::finish() has set d->running = False before returning,
        # so it is safe to let the Python wrapper be garbage-collected afterwards.
        worker.stop()
        worker.quit()
        if not worker.wait(5000):
            worker.terminate()
            worker.wait(2000)
        # 'worker' local variable goes out of scope → Python refcount → 0 → safe GC.

    def _on_usb_gps_location_received(self, data: dict) -> None:
        """Fill coordinate fields with fix data and store the GPS time offset."""
        self.location_combo.setCurrentText("Custom")
        self._set_fields_editable(True)

        lat = data.get("lat")
        lon = data.get("lon")
        alt = data.get("alt")
        gps_time = data.get("gps_time")
        time_offset: timedelta = data.get("time_offset", timedelta(0))

        if lat is not None:
            self.latitude_edit.setText(f"{lat:.6f}")
        if lon is not None:
            self.longitude_edit.setText(f"{lon:.6f}")
        if alt is not None and alt != 0.0:
            self.altitude_edit.setText(f"{alt:.1f}")
        elif lat is not None and lon is not None:
            self.altitude_edit.setPlaceholderText("Fetching elevation\u2026")
            self._elevation_worker = ElevationWorker(lat, lon)
            self._elevation_worker.finished.connect(self._on_elevation_received)
            self._elevation_worker.error.connect(self._on_elevation_error)
            self._elevation_worker.start()

        # Store the measured GPS\u2013computer time offset
        self.gps_time_offset = time_offset
        self.gps_time_offset_changed.emit(time_offset)

        if self._usb_gps_dialog:
            self._usb_gps_dialog.accept()
            self._usb_gps_dialog = None
        self.usb_gps_btn.setEnabled(True)

        self._cleanup_usb_gps_worker()

        # Show the user what was measured
        offset_secs = time_offset.total_seconds()
        if abs(offset_secs) < 0.5:
            offset_msg = "GPS time matches computer clock (offset < 0.5\u00a0s)."
        else:
            direction = "ahead of" if offset_secs > 0 else "behind"
            offset_msg = (
                f"GPS time is {abs(offset_secs):.1f}\u00a0s {direction} the computer clock.\n"
                "Scheduled actions will be corrected automatically."
            )
        if gps_time:
            offset_msg += f"\nGPS UTC: {gps_time.strftime('%H:%M:%S')}"

        QMessageBox.information(self, "USB GPS Fix Received", offset_msg)

    def _on_usb_gps_error(self, message: str) -> None:
        """Show an error and close the USB GPS dialog."""
        if self._usb_gps_dialog:
            self._usb_gps_dialog.reject()
            self._usb_gps_dialog = None
        self.usb_gps_btn.setEnabled(True)
        self._cleanup_usb_gps_worker()
        QMessageBox.critical(self, "USB GPS Error", message)

    def _cancel_usb_gps_capture(self) -> None:
        """Called when the user cancels the USB GPS dialog."""
        if self._usb_gps_dialog:
            self._usb_gps_dialog.reject()
            self._usb_gps_dialog = None
        self.usb_gps_btn.setEnabled(True)
        self._cleanup_usb_gps_worker()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_location_changed(self, location_name: str) -> None:
        """Populate or clear coordinate fields when the combo changes."""
        if location_name.endswith(" (Saved)"):
            actual_name = location_name[: -len(" (Saved)")]
            saved = self._config_manager.get_location(actual_name)
            if saved:
                self._set_fields_editable(False)
                self.location_name_edit.setText(saved["name"])
                self.longitude_edit.setText(str(saved["longitude"]))
                self.latitude_edit.setText(str(saved["latitude"]))
                self.altitude_edit.setText(str(saved["altitude"]))
                self._config_manager.set_last_used_location(actual_name)
        else:
            # "Custom" – let the user type freely.
            self._set_fields_editable(True)
            self.location_name_edit.clear()
            self.longitude_edit.clear()
            self.latitude_edit.clear()
            self.altitude_edit.clear()

    def _delete_location(self) -> None:
        """Delete the currently selected saved location after confirmation."""
        location_name = self.location_name_edit.text().strip()
        if not location_name:
            return

        reply = QMessageBox.question(
            self, "Delete Location",
            f"Are you sure you want to delete the saved location '{location_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._config_manager.delete_location(location_name)

        combo_text = f"{location_name} (Saved)"
        idx = self.location_combo.findText(combo_text)
        if idx >= 0:
            self.location_combo.blockSignals(True)
            self.location_combo.removeItem(idx)
            self.location_combo.blockSignals(False)

        # Switch back to Custom and clear fields
        self.location_combo.setCurrentText("Custom")

    def _save_location(self) -> None:
        """Validate fields and persist the current location."""
        location_name = self.location_name_edit.text().strip()
        if not location_name:
            QMessageBox.warning(
                self, "Invalid Location Name",
                "Please enter a name for this location."
            )
            return

        try:
            longitude = float(self.longitude_edit.text())
            latitude = float(self.latitude_edit.text())
            altitude = float(self.altitude_edit.text())
        except ValueError:
            QMessageBox.warning(
                self, "Invalid Coordinates",
                "Please enter valid numeric coordinates."
            )
            return

        self._config_manager.add_location(
            name=location_name,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
        )
        self._config_manager.set_last_used_location(location_name)

        combo_text = f"{location_name} (Saved)"
        if self.location_combo.findText(combo_text) < 0:
            self.location_combo.addItem(combo_text)

        # Switch the combo to the new entry without re-triggering the
        # handler (which would clear the fields).
        self.location_combo.blockSignals(True)
        self.location_combo.setCurrentText(combo_text)
        self.location_combo.blockSignals(False)

        self._set_fields_editable(False)
        QMessageBox.information(
            self, "Location Saved",
            f"Location '{location_name}' has been saved."
        )

    def _search_address(self) -> None:
        """Kick off a background geocoding request."""
        if not GEOPY_AVAILABLE:
            QMessageBox.warning(
                self, "Geocoding Not Available",
                "Geocoding requires the 'geopy' library.\n"
                "Install it with:  pip install geopy",
            )
            return

        address = self.address_search_edit.text().strip()
        if not address:
            QMessageBox.warning(
                self, "Empty Address",
                "Please enter an address to search."
            )
            return

        self.search_btn.setEnabled(False)
        self.search_status_label.setText(
            "Searching… (this may take a few seconds)"
        )
        self.search_status_label.setStyleSheet(
            "QLabel { color: #555; font-style: italic; }"
        )

        self._geocoding_worker = GeocodingWorker(address)
        self._geocoding_worker.finished.connect(self._on_geocoding_finished)
        self._geocoding_worker.error.connect(self._on_geocoding_error)
        self._geocoding_worker.start()

    def _on_geocoding_finished(self, result: dict) -> None:
        """Apply a successful geocoding result to the coordinate fields."""
        self.search_btn.setEnabled(True)
        worker = self._geocoding_worker
        self._geocoding_worker = None
        if worker is not None:
            worker.wait(1000)

        # Switch the combo to "Custom" – this enables the fields via
        # _on_location_changed.
        self.location_combo.setCurrentText("Custom")
        self._set_fields_editable(True)

        self.longitude_edit.setText(f"{result['longitude']:.5f}")
        self.latitude_edit.setText(f"{result['latitude']:.5f}")
        self.altitude_edit.setText(f"{result['altitude']:.1f}")

        # Suggest a name derived from the first part of the full address.
        parts = result["display_name"].split(",")
        if len(parts) >= 2:
            suggested = (
                parts[0].strip()
                if len(parts[0]) < 50
                else parts[1].strip()
            )
        else:
            suggested = parts[0].strip()

        if not self.location_name_edit.text():
            self.location_name_edit.setText(suggested)

        self.search_status_label.setText(
            f"✓ Found: {result['display_name']}\n"
            f"Coordinates: {result['latitude']:.5f}°, "
            f"{result['longitude']:.5f}° | "
            f"Elevation: {result['altitude']:.0f} m"
        )
        self.search_status_label.setStyleSheet(
            "QLabel { color: #2a7d2a; font-style: italic; }"
        )

    def _on_geocoding_error(self, error_msg: str) -> None:
        """Show an error after a failed geocoding request."""
        self.search_btn.setEnabled(True)
        worker = self._geocoding_worker
        self._geocoding_worker = None
        if worker is not None:
            worker.wait(1000)
        self.search_status_label.setText(f"✗ Error: {error_msg}")
        self.search_status_label.setStyleSheet(
            "QLabel { color: #c40000; font-style: italic; }"
        )
        QMessageBox.warning(self, "Geocoding Error", error_msg)
