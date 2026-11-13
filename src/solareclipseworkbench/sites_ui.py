"""The "Compare sites" window: a shortlist of candidate sites side by side.

Each row is a place (name, longitude, latitude, altitude, editable in the
table).  "Compare" computes, for the eclipse date set in the main window,
the totality there, the Sun's altitude at maximum eclipse, the time of C2 and
the Baily's beads windows; "Cloud forecast" adds the Open-Meteo cloud cover
at maximum eclipse.  The shortlist is kept in the same file as the saved
locations, so it is still there the night before the eclipse.
"""

import datetime
import itertools
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from solareclipseworkbench import site_comparison
from solareclipseworkbench.location_ui import ConfigManager, parse_number
from solareclipseworkbench.site_comparison import CloudForecast, Site, SiteResult

COLUMNS = ["Site", "Longitude", "Latitude", "Altitude [m]", "Eclipse", "Totality", "C2 (local)",
           "Sun at MAX", "Beads C2", "Beads C3", "Cloud cover at MAX"]
(COL_NAME, COL_LON, COL_LAT, COL_ALT, COL_ECLIPSE, COL_TOTALITY, COL_C2, COL_SUN, COL_BEADS_C2,
 COL_BEADS_C3, COL_CLOUDS) = range(len(COLUMNS))
INPUT_COLUMNS = (COL_NAME, COL_LON, COL_LAT, COL_ALT)
RESULT_COLUMNS = tuple(range(COL_ECLIPSE, len(COLUMNS)))

LOW_SUN_DEGREES = 10.0
CLEAR = QColor(40, 170, 40, 70)
CLOUDY = QColor(220, 60, 40, 70)
WARNING = QColor(240, 150, 0, 80)

_ROW_IDS = itertools.count(1)


class _CompareWorker(QThread):
    """Computes the sites one by one, off the GUI thread (about half a second each)."""
    computed = pyqtSignal(int, object)

    def __init__(self, jobs: List[Tuple[int, Site]], date: str):
        super().__init__()
        self.jobs = jobs
        self.date = date

    def run(self):
        for row_id, site in self.jobs:
            self.computed.emit(row_id, site_comparison.compare_site(site, self.date))


class _ForecastWorker(QThread):
    """Fetches the cloud cover of the computed sites from Open-Meteo."""
    fetched = pyqtSignal(int, object)

    def __init__(self, jobs: List[Tuple[int, SiteResult]]):
        super().__init__()
        self.jobs = jobs

    def run(self):
        for row_id, result in self.jobs:
            self.fetched.emit(row_id, site_comparison.fetch_cloud_cover_for(result))


class SiteComparisonWindow(QWidget):
    """Candidate sites side by side, for the eclipse date set in the main window.

    Args:
        - context: returns ``(date, current_site)``: the eclipse date as YYYY-MM-DD (None when not set) and
          the location of the main window as a Site (None when not set).
        - use_site: called with a Site to make it the location of the main window.
    """

    def __init__(self, context: Callable[[], tuple], use_site: Optional[Callable[[Site], None]] = None,
                 config_manager: Optional[ConfigManager] = None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Compare sites")
        self.resize(1300, 420)
        self._context = context
        self._use_site = use_site
        self.config = config_manager or ConfigManager()
        self.results = {}       # row id -> SiteResult
        self.forecasts = {}     # row id -> CloudForecast
        self.date: Optional[str] = None
        self._worker: Optional[QThread] = None
        self._beads_window = None
        self._busy = False
        self._filling = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        controls = QHBoxLayout()
        self.add_current_button = QPushButton("Add current location")
        self.add_current_button.setToolTip("Add the location set in the main window")
        self.add_current_button.clicked.connect(self.add_current_location)
        controls.addWidget(self.add_current_button)
        self.saved_box = QComboBox()
        self.saved_box.setToolTip("Locations saved in the Location window or the wizard")
        self.saved_box.setMinimumWidth(180)
        controls.addWidget(self.saved_box)
        self.add_saved_button = QPushButton("Add")
        self.add_saved_button.setToolTip("Add the saved location chosen on the left")
        self.add_saved_button.clicked.connect(self.add_saved_location)
        controls.addWidget(self.add_saved_button)
        self.add_empty_button = QPushButton("New row")
        self.add_empty_button.setToolTip("Add an empty row to type in a name and coordinates")
        self.add_empty_button.clicked.connect(lambda: self.add_site(Site("New site", 0.0, 0.0, 0.0), select=True))
        controls.addWidget(self.add_empty_button)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Remove the selected sites from the list")
        self.remove_button.clicked.connect(self.remove_selected)
        controls.addWidget(self.remove_button)
        controls.addSpacing(20)
        self.compare_button = QPushButton("Compare")
        self.compare_button.setToolTip("Compute the eclipse at every site for the date set in the main window")
        self.compare_button.clicked.connect(self.compare)
        controls.addWidget(self.compare_button)
        self.forecast_button = QPushButton("Cloud forecast")
        self.forecast_button.setToolTip("Fetch the cloud cover at maximum eclipse from Open-Meteo (needs a network "
                                        "connection; forecasts reach about 15 days ahead)")
        self.forecast_button.clicked.connect(self.fetch_forecasts)
        controls.addWidget(self.forecast_button)
        self.beads_button = QPushButton("Compare beads")
        self.beads_button.setToolTip("Show the Baily's beads of the sites with totality next to each other "
                                     "(needs the lunar limb profile)")
        self.beads_button.clicked.connect(self.show_beads)
        controls.addWidget(self.beads_button)
        controls.addSpacing(20)
        self.use_button = QPushButton("Use this site")
        self.use_button.setToolTip("Make the selected site the location of the main window")
        self.use_button.clicked.connect(self.use_selected)
        self.use_button.setVisible(use_site is not None)
        controls.addWidget(self.use_button)
        self.text_button = QPushButton("Save as text...")
        self.text_button.setToolTip("Save the comparison as a text file")
        self.text_button.clicked.connect(self.save_text)
        controls.addWidget(self.text_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_CLOUDS, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table, 1)

        self.note = QLabel("Edit a name or coordinate in the table directly.  Hover over a result for details.  "
                           "Cloud cover: Open-Meteo, interpolated to maximum eclipse.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        self.fill_saved_locations()
        for data in self.config.get_candidate_sites():
            try:
                self.add_site(Site.from_dict(data), store=False)
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        if self.table.rowCount() == 0:
            self.add_current_location()
        self.refresh_context()

    # ------------------------------------------------------------------
    # The list of sites
    # ------------------------------------------------------------------

    def fill_saved_locations(self):
        self.saved_box.clear()
        for location in self.config.get_locations():
            self.saved_box.addItem(location["name"])
        has_saved = self.saved_box.count() > 0
        self.saved_box.setEnabled(has_saved)
        self.add_saved_button.setEnabled(has_saved)
        if not has_saved:
            self.saved_box.addItem("(no saved locations)")

    def refresh_context(self):
        """Read the eclipse date of the main window again; results of another date are cleared."""
        date, _ = self._context()
        if date != self.date:
            self.date = date
            for row in range(self.table.rowCount()):
                self._clear_results(row)
        self._update_summary()

    def add_current_location(self):
        _, current = self._context()
        if current is None:
            if self.isVisible():
                QMessageBox.information(self, "Compare sites", "Set a location in the main window first.")
            return
        self.add_site(current, select=True)

    def add_saved_location(self):
        location = self.config.get_location(self.saved_box.currentText())
        if location is None:
            return
        try:
            site = Site(location["name"], parse_number(location["longitude"]), parse_number(location["latitude"]),
                        parse_number(location.get("altitude", 0.0)))
        except (KeyError, TypeError, ValueError):
            QMessageBox.warning(self, "Compare sites",
                                f"The saved location '{location.get('name', '')}' has no valid coordinates.")
            return
        self.add_site(site, select=True)

    def add_site(self, site: Site, store: bool = True, select: bool = False):
        self._filling = True
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(site.name)
        name.setData(Qt.ItemDataRole.UserRole, next(_ROW_IDS))
        self.table.setItem(row, COL_NAME, name)
        for column, value in ((COL_LON, site.longitude), (COL_LAT, site.latitude), (COL_ALT, site.altitude)):
            item = QTableWidgetItem(f"{round(value, 6)}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, column, item)
        for column in RESULT_COLUMNS:
            self.table.setItem(row, column, self._result_item(""))
        self._filling = False
        if select:
            self.table.selectRow(row)
        if store:
            self._store()
        self._update_summary()

    def remove_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            row_id = self._row_id(row)
            self.results.pop(row_id, None)
            self.forecasts.pop(row_id, None)
            self.table.removeRow(row)
        if rows:
            self._store()
            self._highlight_best()
            self._update_summary()

    def sites(self) -> List[Tuple[int, Optional[Site]]]:
        """``(row id, site)`` per row; the site is None when a coordinate does not read as a number."""
        sites = []
        for row in range(self.table.rowCount()):
            sites.append((self._row_id(row), self._site(row)))
        return sites

    def _site(self, row: int) -> Optional[Site]:
        try:
            longitude = parse_number(self.table.item(row, COL_LON).text())
            latitude = parse_number(self.table.item(row, COL_LAT).text())
            altitude = parse_number(self.table.item(row, COL_ALT).text())
        except (AttributeError, ValueError):
            return None
        if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
            return None
        name = self.table.item(row, COL_NAME).text().strip() or f"{latitude:.4f}, {longitude:.4f}"
        return Site(name, longitude, latitude, altitude)

    def _row_id(self, row: int) -> int:
        return self.table.item(row, COL_NAME).data(Qt.ItemDataRole.UserRole)

    def _row_of(self, row_id: int) -> Optional[int]:
        for row in range(self.table.rowCount()):
            if self._row_id(row) == row_id:
                return row
        return None

    def _store(self):
        self.config.set_candidate_sites([site.to_dict() for _, site in self.sites() if site is not None])

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._filling or item.column() not in INPUT_COLUMNS:
            return
        row = item.row()
        valid = self._site(row) is not None
        for column in (COL_LON, COL_LAT, COL_ALT):
            cell = self.table.item(row, column)
            if cell is not None:
                cell.setBackground(QColor(0, 0, 0, 0) if valid else CLOUDY)
                cell.setToolTip("" if valid else "Longitude -180 to 180, latitude -90 to 90, altitude in metres")
        if item.column() != COL_NAME:
            self._clear_results(row)
        self._store()
        self._update_summary()

    def _on_double_click(self, item: QTableWidgetItem):
        if item.column() in RESULT_COLUMNS and self._use_site is not None:
            self.use_selected()

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def compare(self):
        if self._busy:
            return
        self.refresh_context()
        if not self.date:
            QMessageBox.information(self, "Compare sites", "Set the eclipse date in the main window first.")
            return
        jobs = [(row_id, site) for row_id, site in self.sites() if site is not None]
        if not jobs:
            return
        self.results.clear()
        self.forecasts.clear()
        for row in range(self.table.rowCount()):
            self._clear_results(row)
            self.table.item(row, COL_TOTALITY).setText("computing...")
        self._start(_CompareWorker(jobs, self.date), "computed", self._on_computed)

    def fetch_forecasts(self):
        if self._busy:
            return
        if not self.results:
            self.compare()
            if self._busy:
                self._worker.finished.connect(self._fetch_forecasts_after_compare)
            return
        jobs = [(row_id, result) for row_id, result in self.results.items() if self._row_of(row_id) is not None]
        for row_id, _ in jobs:
            self.table.item(self._row_of(row_id), COL_CLOUDS).setText("fetching...")
        self._start(_ForecastWorker(jobs), "fetched", self._on_fetched)

    def _fetch_forecasts_after_compare(self):
        if self.results:
            self.fetch_forecasts()

    def _start(self, worker: QThread, signal: str, slot):
        if self._busy:
            return
        if self._worker is not None:
            self._worker.wait()     # it has emitted finished; let it end before it is released
        self._worker = worker
        self._busy = True
        getattr(worker, signal).connect(slot)
        worker.finished.connect(self._on_worker_finished)
        self._set_busy(True)
        worker.start()

    def _on_worker_finished(self):
        self._busy = False
        self._set_busy(False)
        self._update_summary()

    def _set_busy(self, busy: bool):
        for button in (self.compare_button, self.forecast_button, self.beads_button, self.add_current_button,
                       self.add_saved_button, self.add_empty_button, self.remove_button):
            button.setEnabled(not busy)
        if not busy:
            self.add_saved_button.setEnabled(self.saved_box.isEnabled())
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers if busy
                                   else QAbstractItemView.EditTrigger.AllEditTriggers)

    def _on_computed(self, row_id: int, result: SiteResult):
        row = self._row_of(row_id)
        if row is None:
            return
        self.results[row_id] = result
        self._show_result(row, result)
        self._highlight_best()

    def _on_fetched(self, row_id: int, forecast: CloudForecast):
        row = self._row_of(row_id)
        if row is None:
            return
        self.forecasts[row_id] = forecast
        self._show_forecast(row, forecast)

    def _clear_results(self, row: int):
        row_id = self._row_id(row)
        self.results.pop(row_id, None)
        self.forecasts.pop(row_id, None)
        self._filling = True
        for column in RESULT_COLUMNS:
            self.table.setItem(row, column, self._result_item(""))
        self._filling = False

    @staticmethod
    def _result_item(text: str, tooltip: str = "", background: Optional[QColor] = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if tooltip:
            item.setToolTip(tooltip)
        if background is not None:
            item.setBackground(background)
        return item

    def _show_result(self, row: int, result: SiteResult):
        self._filling = True
        set_item = lambda column, *args: self.table.setItem(row, column, self._result_item(*args))
        if result.error:
            set_item(COL_ECLIPSE, "error", result.error, CLOUDY)
            set_item(COL_TOTALITY, "")
            self._filling = False
            return

        eclipse = result.eclipse_type or "-"
        if result.eclipse_type and result.eclipse_type != "No eclipse":
            eclipse += f" ({result.magnitude:.3f})"
        set_item(COL_ECLIPSE, eclipse, "Eclipse type and magnitude at this site")

        if result.is_total:
            tooltip = [f"C2 {result.c2_utc:%H:%M:%S} UTC"]
            if result.limb_corrected:
                tooltip.append(f"Corrected for the lunar limb; mean limb: "
                               f"{site_comparison.format_duration(result.totality_mean)}")
            else:
                tooltip.append("Mean lunar limb (the limb profile is not installed or switched off)")
            set_item(COL_TOTALITY, site_comparison.describe_totality(result), "\n".join(tooltip))
            set_item(COL_C2, result.c2_local.strftime("%H:%M:%S %Z"),
                     f"{result.c2_utc:%H:%M:%S} UTC")
        else:
            set_item(COL_TOTALITY, "none", "No totality at this site", CLOUDY)
            set_item(COL_C2, "-")

        if result.sun_altitude is not None:
            low = result.sun_altitude < LOW_SUN_DEGREES
            set_item(COL_SUN, site_comparison.describe_sun(result),
                     f"Apparent altitude and azimuth of the Sun at maximum eclipse "
                     f"({result.max_local:%H:%M:%S %Z})"
                     + ("\nLow Sun: check the horizon in that direction for buildings, trees and haze" if low else ""),
                     WARNING if low else None)
        else:
            set_item(COL_SUN, "-")

        for column, contact in ((COL_BEADS_C2, "C2"), (COL_BEADS_C3, "C3")):
            window = result.beads[contact]
            tooltip = {"solved": f"Baily's beads window, from the limb-corrected {contact}",
                       "unresolved": "The Baily's beads window does not close at this site (e.g. near a limit)",
                       }.get(window.status, "Needs totality and the lunar limb profile")
            set_item(column, window.describe(contact), tooltip)
        self._filling = False

    def _show_forecast(self, row: int, forecast: CloudForecast):
        if forecast.error:
            background, tooltip = None, forecast.error
        else:
            background = CLEAR if forecast.total <= 25 else CLOUDY if forecast.total >= 60 else WARNING
            hours = "\n".join(f"{moment:%H:%M} UTC: {'-' if total is None else f'{total:.0f}%'}"
                              for moment, total in forecast.hourly)
            tooltip = f"Open-Meteo {forecast.source}, total cloud cover per hour from C1 to C4:\n{hours}"
        self._filling = True
        self.table.setItem(row, COL_CLOUDS, self._result_item(forecast.describe(), tooltip, background))
        self._filling = False

    def _highlight_best(self):
        best = site_comparison.best_totality(self.results.values())
        for row in range(self.table.rowCount()):
            result = self.results.get(self._row_id(row))
            item = self.table.item(row, COL_TOTALITY)
            if result is None or item is None or not result.is_total:
                continue
            self._filling = True
            item.setText(site_comparison.describe_totality(result, best))
            font = QFont(item.font())
            font.setBold(result.totality == best)
            item.setFont(font)
            self._filling = False

    def _update_summary(self):
        if not self.date:
            self.summary.setText("Set the eclipse date in the main window, then press Compare.")
            return
        count = self.table.rowCount()
        text = f"Eclipse of {self.date}: {count} site{'s' if count != 1 else ''}."
        totals = [r for r in self.results.values() if r.is_total]
        if totals:
            best = max(totals, key=lambda r: r.totality)
            text += f"  Longest totality: {best.site.name} ({site_comparison.format_duration(best.totality)})."
            if not any(r.limb_corrected for r in totals):
                text += "  Totality is for the mean lunar limb (no limb profile)."
        elif not self.results:
            text += "  Press Compare to compute them."
        self.summary.setText(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def use_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if len(rows) != 1 or self._use_site is None:
            QMessageBox.information(self, "Compare sites", "Select one site first.")
            return
        site = self._site(rows[0])
        if site is None:
            return
        self._use_site(site)

    def beads_sites(self) -> list:
        """The sites for the beads comparison: ``(name, longitude, latitude, altitude, caption)``.

        Once compared, sites without totality are left out; the caption gives the bead windows.
        """
        sites = []
        for row_id, site in self.sites():
            if site is None:
                continue
            result = self.results.get(row_id)
            caption = ""
            if result is not None:
                if not result.is_total:
                    continue
                caption = (f"totality {site_comparison.format_duration(result.totality)}   "
                           f"beads {result.beads['C2'].describe('C2')},  {result.beads['C3'].describe('C3')}")
            sites.append((site.name, site.longitude, site.latitude, site.altitude, caption))
        return sites

    def show_beads(self):
        """Open (or bring to front) the Baily's beads of the sites next to each other."""
        from solareclipseworkbench.limb_ui import BeadsComparisonWindow
        self.refresh_context()
        if not self.date:
            QMessageBox.information(self, "Compare sites", "Set the eclipse date in the main window first.")
            return
        sites = self.beads_sites()
        if not sites:
            QMessageBox.information(self, "Compare sites", "None of the sites has totality.")
            return
        if self._beads_window is None:
            self._beads_window = BeadsComparisonWindow()
        self._beads_window.set_sites(self.date, sites)
        self._beads_window.show()
        self._beads_window.activateWindow()
        self._beads_window.raise_()

    def comparison_text(self) -> str:
        ids = [row_id for row_id, _ in self.sites() if row_id in self.results]
        results = [self.results[row_id] for row_id in ids]
        forecasts = [self.forecasts.get(row_id) for row_id in ids] if self.forecasts else None
        return site_comparison.format_comparison(results, self.date or "?", forecasts)

    def save_text(self):
        if not self.results:
            QMessageBox.information(self, "Compare sites", "Press Compare first.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Save the comparison",
                                                  str(Path.home() / f"sites-{self.date}.txt"),
                                                  "Text files (*.txt);;All files (*)")
        if not filename:
            return
        try:
            # UTF-8: the table has degree signs, and site names can be in any script
            Path(filename).write_text(self.comparison_text() + "\n", encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Compare sites", f"Could not write {filename}:\n{e}")

    def closeEvent(self, event):
        if self._beads_window is not None:
            self._beads_window.close()
        if self._worker is not None:
            self._worker.wait(10000)
        super().closeEvent(event)
