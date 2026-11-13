"""Map of the eclipse path with the observer's position (issues #68 and #81).

``EclipsePathWidget`` shows the land masses, the path of totality or annularity (shaded, with its northern and
southern limits and the centre line) and the observer as a red dot.  Below the map a line of text says how far the
observer is from the centre line and how long totality (or annularity) lasts there.

The computations live in ``eclipse_path``; this module only draws.
"""

import datetime
import logging
import math
from typing import List, Optional, Tuple

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from solareclipseworkbench import eclipse_path as ep
from solareclipseworkbench.solar_eclipse import get_local_circumstances

LOGGER = logging.getLogger(__name__)

PATH_COLOUR = "#1f4e9c"
CENTRE_COLOUR = "#0b2557"
OBSERVER_COLOUR = "red"

_LAND = None


def format_eclipse_choice(eclipse: dict, date_format: str) -> str:
    """Label for an eclipse in a drop-down: '<date> - <type> - <duration or magnitude>'.

    Args:
        - eclipse: An entry of ``solar_eclipse.get_solar_eclipses`` (date as DD/MM/YYYY).
        - date_format: strftime format for the date.
    """
    label = datetime.datetime.strptime(eclipse['date'], "%d/%m/%Y").strftime(date_format) + " - " + eclipse['type']
    if eclipse['type'] in ("T", "A", "H"):
        minutes, seconds = divmod(eclipse["duration"], 60)
        return label + f" - {int(minutes)}m {int(seconds):02}s"
    return label + " - " + str(int(eclipse["magnitude"] * 100)) + "%"


def eclipse_choices(count: int, date_format: str, include: Optional[str] = None) -> List[Tuple[str, str]]:
    """The next ``count`` eclipses as (label, 'YYYY-MM-DD') pairs.

    Args:
        - count: Number of upcoming eclipses.
        - date_format: strftime format for the date in the labels.
        - include: 'YYYY-MM-DD' of an eclipse to list as well when it is not among the upcoming ones (e.g. a past
          eclipse loaded from the settings); it is put first.
    """
    from solareclipseworkbench.solar_eclipse import get_solar_eclipses
    from solareclipseworkbench.utils import calculate_next_solar_eclipses

    def iso(eclipse):
        return datetime.datetime.strptime(eclipse['date'], "%d/%m/%Y").strftime("%Y-%m-%d")

    choices = [(format_eclipse_choice(e, date_format), iso(e)) for e in calculate_next_solar_eclipses(count)]
    if include and include not in [c[1] for c in choices]:
        match = [e for e in get_solar_eclipses(start_date=include) if iso(e) == include]
        if match:
            choices.insert(0, (format_eclipse_choice(match[0], date_format), include))
    return choices


def _land():
    """The Natural Earth land polygons, read once per process."""
    global _LAND
    if _LAND is None:
        import geopandas
        from geodatasets import get_path

        _LAND = geopandas.read_file(get_path("naturalearth.land"))
    return _LAND


class EclipsePathMap(FigureCanvas):
    """World map with the eclipse path and the observer drawn on it."""

    def __init__(self, parent=None, dpi=100):
        self.figure = Figure(dpi=dpi)
        self.ax = self.figure.add_subplot(111)
        FigureCanvas.__init__(self, self.figure)
        self.setParent(parent)
        FigureCanvas.updateGeometry(self)

        try:
            _land().clip([-180, -90, 180, 90]).plot(color="white", edgecolor="black", linewidth=0.5, ax=self.ax)
        except Exception:
            # The land polygons are downloaded the first time (geodatasets): offline at the site that fails.
            # The path and the observer are still drawn, against the grid of longitude and latitude.
            LOGGER.warning("Could not draw the land masses on the eclipse path map", exc_info=True)
        self.ax.set_xlabel("Longitude [°]")
        self.mpl_connect("resize_event", lambda _event: self.figure.tight_layout())
        self.ax.set_ylabel("Latitude [°]")

        self.path: Optional[ep.EclipsePath] = None
        self._path_artists = []
        self._observer_artist = None
        self.observer: Optional[tuple] = None  # (lat, lon)

        self.figure.tight_layout()
        self._update_view()

    def set_path(self, path: Optional[ep.EclipsePath]):
        """Draw ``path`` (None or empty: remove the path)."""
        for artist in self._path_artists:
            artist.remove()
        self._path_artists = []
        self.path = path

        if path is not None and not path.is_empty:
            band = PolyCollection(ep.path_polygons(path), facecolors=PATH_COLOUR, edgecolors="none", alpha=0.3,
                                  zorder=2)
            self.ax.add_collection(band)
            self._path_artists.append(band)

            label = "Limits"
            for limit in (path.north, path.south):
                for run in ep.split_at_dateline(limit):
                    (line,) = self.ax.plot([p[1] for p in run], [p[0] for p in run], color=PATH_COLOUR,
                                           linewidth=1.2, zorder=3, label=label)
                    self._path_artists.append(line)
                    label = None

            label = "Centre line"
            for run in ep.split_at_dateline([(p.lat, p.lon) for p in path.central]):
                (line,) = self.ax.plot([p[1] for p in run], [p[0] for p in run], color=CENTRE_COLOUR,
                                       linewidth=1, linestyle="--", zorder=3, label=label)
                self._path_artists.append(line)
                label = None

        self._update_legend()
        self._update_view()
        self.draw_idle()

    def set_observer(self, latitude: float, longitude: float):
        """Mark the observer with a red dot."""
        if self._observer_artist is not None:
            self._observer_artist.remove()
        self.observer = (latitude, longitude)
        (self._observer_artist,) = self.ax.plot([longitude], [latitude], marker="o", markersize=6,
                                                color=OBSERVER_COLOUR, markeredgecolor="black", linestyle="none",
                                                zorder=5, label="Observer")
        self._update_legend()
        self._update_view()
        self.draw_idle()

    def _update_legend(self):
        legend = self.ax.get_legend()
        if legend is not None:
            legend.remove()
        if self._path_artists:
            self.ax.legend(loc="best", fontsize="small", framealpha=0.8)

    def _update_view(self):
        """Zoom to the path and the observer, or show the whole world when there is no path."""
        bounds = ep.path_bounds(self.path) if self.path is not None else None
        if bounds is None:
            self.ax.set_xlim(-180, 180)
            self.ax.set_ylim(-90, 90)
            self.ax.set_aspect("equal")
            return

        min_lon, min_lat, max_lon, max_lat = bounds
        if self.observer is not None:
            lat, lon = self.observer
            min_lon, max_lon = max(-180.0, min(min_lon, lon - 3)), min(180.0, max(max_lon, lon + 3))
            min_lat, max_lat = max(-90.0, min(min_lat, lat - 3)), min(90.0, max(max_lat, lat + 3))
        self.ax.set_xlim(min_lon, max_lon)
        self.ax.set_ylim(min_lat, max_lat)
        # Keep a degree of longitude and of latitude the same length on the ground at the centre of the view.
        mid_lat = (min_lat + max_lat) / 2
        self.ax.set_aspect(1 / max(0.2, math.cos(math.radians(mid_lat))), adjustable="box")


class EclipsePathWidget(QWidget):
    """``EclipsePathMap`` with an eclipse selector, a zoom/pan toolbar and a summary of where the observer is."""

    # Emitted with the 'YYYY-MM-DD' date when the user picks another eclipse in the selector.
    eclipse_changed = pyqtSignal(str)

    def __init__(self, parent=None, date_format: str = "%Y-%m-%d", eclipse_count: int = 20):
        super().__init__(parent)
        self.date_format = date_format
        self.eclipse_count = eclipse_count

        self.eclipse_combobox = QComboBox()
        self.eclipse_combobox.setPlaceholderText("Choose an eclipse")
        self.eclipse_combobox.currentIndexChanged.connect(self._eclipse_selected)
        selector = QHBoxLayout()
        selector.addWidget(QLabel("Eclipse:"))
        selector.addWidget(self.eclipse_combobox, stretch=1)

        self.map = EclipsePathMap(self)
        self.toolbar = NavigationToolbar(self.map, self)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(selector)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.map, stretch=1)
        layout.addWidget(self.info)
        self.setLayout(layout)

        self.date: Optional[str] = None
        self.path: Optional[ep.EclipsePath] = None
        self._location: Optional[tuple] = None  # (lat, lon, altitude)

    def _fill_eclipse_combobox(self, selected: Optional[str]):
        """(Re)fill the selector with the upcoming eclipses (plus ``selected``) and select ``selected``."""
        self.eclipse_combobox.blockSignals(True)
        try:
            self.eclipse_combobox.clear()
            try:
                choices = eclipse_choices(self.eclipse_count, self.date_format, include=selected)
            except Exception:
                LOGGER.exception("Could not list the eclipses")
                choices = []
            for label, iso in choices:
                self.eclipse_combobox.addItem(label, iso)
            self.eclipse_combobox.setCurrentIndex(self.eclipse_combobox.findData(selected) if selected else -1)
        finally:
            self.eclipse_combobox.blockSignals(False)

    def _eclipse_selected(self, index: int):
        date = self.eclipse_combobox.itemData(index) if index >= 0 else None
        if date and date != self.date:
            self._show_eclipse(date)
            self.eclipse_changed.emit(date)

    def selected_eclipse_date(self) -> Optional[str]:
        """The eclipse shown on the map, as 'YYYY-MM-DD' (None when none is chosen)."""
        return self.date

    def set_eclipse_date(self, date: Optional[str]):
        """Select the eclipse on ``date`` ('YYYY-MM-DD') and show its path; None shows no path."""
        self._fill_eclipse_combobox(date)
        self._show_eclipse(date)

    def _show_eclipse(self, date: Optional[str]):
        self.date = date
        self.path = None
        if date:
            try:
                self.path = ep.eclipse_path_for_date(date)
            except Exception:
                LOGGER.exception("Could not compute the eclipse path for %s", date)
        self.map.set_path(self.path)
        self._reset_toolbar_home()
        self._update_info()

    def plot_location(self, longitude: float, latitude: float, altitude: float = 0.0):
        """Mark the observer and update the summary below the map."""
        self._location = (latitude, longitude, altitude)
        self.map.set_observer(latitude, longitude)
        self._reset_toolbar_home()
        self._update_info()

    def _reset_toolbar_home(self):
        """Make the toolbar's Home button return to the view chosen by the map, not the one at start-up."""
        self.toolbar.update()

    def _update_info(self):
        if not self.date:
            self.info.setText("Choose an eclipse to show its path of totality on the map.")
            return
        if self.path is None:
            self.info.setText("The eclipse path could not be calculated.")
            return
        if self._location is None:
            self.info.setText("")
            return

        latitude, longitude, altitude = self._location
        try:
            where = ep.locate_observer(self.path, latitude, longitude)
            local_type, local_duration = "Partial", 0.0
            if where is not None:
                circumstances = get_local_circumstances(latitude, longitude, altitude, self.date)
                local_type = circumstances["type"]
                if local_type in ("Total", "Annular"):
                    local_duration = abs(circumstances["ut_third_contact"] - circumstances["ut_second_contact"]) * 3600
            self.info.setText(ep.describe_observer(self.path, where, local_type, local_duration))
        except Exception:
            LOGGER.exception("Could not place the observer in the eclipse path")
            self.info.setText("Could not work out where the observer is relative to the path.")
