""" Solar Eclipse Workbench GUI, implemented according to the MVC pattern:

    - Model: SolarEclipseModel
    - View: SolarEclipseView
    - Controller: SolarEclipseController
"""
import datetime
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer, QRect
from PyQt6.QtGui import QIcon, QAction, QPainter
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, QGridLayout, \
    QGroupBox, QComboBox, QPushButton

from solareclipseworkbench import camera
from solareclipseworkbench.observer import Observer, Observable

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

        self.eclipse_date: datetime.datetime = None

        self.local_time: datetime.datetime = None
        self.utc_time: datetime.datetime = None

        self.longitude: float = None
        self.latitude: float = None
        self.altitude: float = None

        self.reference_moments: dict = None

        self.camera_overview: dict = None

    def set_position(self, longitude: float, latitude: float, altitude: float):

        self.longitude = longitude
        self.latitude = latitude
        self.altitude = altitude

    def set_reference_moments(self, reference_moments: dict):

        self.reference_moments = reference_moments

    def set_camera_overview(self):

        camera_overview = camera.get_camera_overview()


class SolarEclipseView(QMainWindow, Observable):

    def __init__(self):

        super().__init__()
        # self.setWindowIcon(QIcon(str(ICON_PATH / "logo-small.png")))

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

        self.init_ui()

    def init_ui(self):

        app_frame = QFrame()
        app_frame.setObjectName("AppFrame")

        self.add_toolbar()

        vbox_left = QVBoxLayout()

        eclipse_date_group_box = QGroupBox()
        eclipse_date_grid_layout = QGridLayout()
        eclipse_date_grid_layout.addWidget(self.eclipse_date_label, 0, 0)
        eclipse_date_grid_layout.addWidget(self.eclipse_date, 0, 1)

        eclipse_date_group_box.setLayout(eclipse_date_grid_layout)
        vbox_left.addWidget(eclipse_date_group_box)

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

        # place_time_layout.addLayout(date_layout)
        # place_time_layout.addLayout(time_layout)

        # self.place_time_frame.setLayout(place_time_layout)
        # self.place_time_frame.setLayout(grid)
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

        reference_moments_group_box = QGroupBox()
        reference_moments_grid_layout = QGridLayout()
        reference_moments_grid_layout.addWidget(QLabel("Time (local)"), 0, 1)
        reference_moments_grid_layout.addWidget(QLabel("Time (UTC)"), 0, 2)
        reference_moments_grid_layout.addWidget(QLabel("Countdown"), 0, 3)
        reference_moments_grid_layout.addWidget(QLabel("First contact (C1)"), 1, 0)
        reference_moments_grid_layout.addWidget(QLabel("Second contact (C2)"), 2, 0)
        reference_moments_grid_layout.addWidget(QLabel("Maximum eclipse"), 3, 0)
        reference_moments_grid_layout.addWidget(QLabel("Third contact (C3)"), 4, 0)
        reference_moments_grid_layout.addWidget(QLabel("Fourth contact (C4)"), 5, 0)
        reference_moments_grid_layout.addWidget(QLabel("Sunrise"), 6, 0)
        reference_moments_grid_layout.addWidget(QLabel("Sunset"), 7, 0)
        reference_moments_group_box.setLayout(reference_moments_grid_layout)

        hbox = QHBoxLayout()
        hbox.addLayout(vbox_left)
        hbox.addWidget(reference_moments_group_box)

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
        sender = self.sender()
        self.notify_observers(sender)

    def update_time(self, current_time_local: datetime.datetime, current_time_utc: datetime.datetime):

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


class SolarEclipseController(Observer):

    def __init__(self, model: SolarEclipseModel, view: SolarEclipseView):

        self.model = model

        self.view = view
        self.view.add_observer(self)

        # self.date_format = "%d/%m/%Y"
        # self.time_format = "%d/%m/%Y"

        self.time_display_timer = QTimer()
        self.time_display_timer.timeout.connect(self.update_time)
        self.time_display_timer.setInterval(1000)
        self.time_display_timer.start()

    def update_time(self):

        current_time_local = datetime.datetime.now()
        current_time_utc = current_time_local.astimezone(tz=datetime.timezone.utc)

        self.model.local_time = current_time_local
        self.model.utc_time = current_time_utc

        self.view.update_time(current_time_local, current_time_utc)

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
            self.model.eclipse_date = datetime.datetime.strptime(eclipse_date, DATE_FORMATS[self.view.date_format])

            self.view.eclipse_date.setText(changed_object.eclipse_combobox.currentText())
            return

        elif isinstance(changed_object, ReferenceMomentsPopup):
            return

        elif isinstance(changed_object, SettingsPopup):
            date_format = changed_object.date_combobox.currentText()
            self.view.date_format = date_format
            if self.model.eclipse_date:
                self.view.eclipse_date.setText(self.model.eclipse_date.strftime(DATE_FORMATS[date_format]))

            time_format = changed_object.time_combobox.currentText()
            self.view.time_format = time_format

            return

        text = changed_object.text()

        if text == "Location":
            self.location_popup = LocationPopup(self)
            # self.location_popup.setGeometry(QRect(100, 100, 400, 200))
            self.location_popup.show()

        elif text == "Date":
            self.eclipse_popup = EclipsePopup(self)
            # eclipse_popup.setGeometry(QRect(100, 100, 400, 200))
            self.eclipse_popup.show()

        elif text == "Reference moments":
            # TODO
            print("Reference moments")
            self.reference_moments_popup = ReferenceMomentsPopup(self)
            self.reference_moments_popup.show()

        elif text == "Camera(s)":
            # TODO
            print("Camera(s)")

        elif text == "Settings":
            self.settings_popup = SettingsPopup(self)
            self.settings_popup.show()


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

class VLine(QFrame):
    """Presents a simple Vertical Bar that can be used in e.g. the status bar."""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.VLine | QFrame.Sunken)


class HLine(QFrame):
    """Presents a simple Horizontal Bar that can be used to separate widgets."""

    def __init__(self):
        super().__init__()
        self.setLineWidth(0)
        self.setMidLineWidth(1)
        self.setFrameShape(QFrame.HLine | QFrame.Sunken)


class LocationPopup(QWidget, Observable):
    def __init__(self, observer: SolarEclipseController):
        QWidget.__init__(self)
        self.setWindowTitle("Location")
        self.setGeometry(QRect(100, 100, 1000, 800))
        self.add_observer(observer)

        layout = QVBoxLayout()

        grid_layout = QGridLayout()
        grid_layout.addWidget(QLabel("Longitude [°]"), 0, 0)
        self.longitude = QLineEdit()
        longitude_validator = QDoubleValidator()
        longitude_validator.setRange(-180, 180, 5)
        self.longitude.setValidator(longitude_validator)
        self.longitude.setToolTip("Positive values: East of Greenwich meridian; "
                                  "Negative values: West of Greenwich meridian")
        grid_layout.addWidget(self.longitude, 0, 1)

        grid_layout.addWidget(QLabel("Latitude [°]"), 1, 0)
        self.latitude = QLineEdit()
        latitude_validator = QDoubleValidator()
        latitude_validator.setRange(-90, 90, 5)
        self.latitude.setValidator(latitude_validator)
        self.latitude.setToolTip("Positive values: Northern hemisphere; Negative values: Southern hemisphere")
        grid_layout.addWidget(self.latitude, 1, 1)

        grid_layout.addWidget(QLabel("Altitude [m]"), 2, 0)
        self.altitude = QLineEdit()
        altitude_validator = QDoubleValidator()
        self.altitude.setValidator(altitude_validator)
        grid_layout.addWidget(self.altitude, 2, 1)
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
        print("Plotting location...")
        self.location_plot.plot_location(longitude=float(self.longitude.text()), latitude=float(self.latitude.text()))

    def accept_location(self):
        self.notify_observers(self)
        self.close()


class EclipsePopup(QWidget, Observable):

    def __init__(self, observer: SolarEclipseController):
        QWidget.__init__(self)
        self.setWindowTitle("Eclipse date")
        self.setGeometry(QRect(100, 100, 400, 200))
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

        self.notify_observers(self)
        self.close()


class ReferenceMomentsPopup(QWidget, Observable):

    def __init__(self, observer: SolarEclipseController):
        QWidget.__init__(self)
        self.setWindowTitle("Reference Moments")
        self.setGeometry(QRect(100, 100, 400, 200))
        self.add_observer(observer)

    def paintEvent(self, e):
        dc = QPainter(self)
        dc.drawLine(0, 0, 100, 100)
        dc.drawLine(100, 0, 0, 100)


class SettingsPopup(QWidget, Observable):

    def __init__(self, observer: SolarEclipseController):
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
        self.notify_observers(self)
        self.close()

    def cancel_settings(self):
        self.close()


class LocationPlot(FigureCanvas):
    """ Display the world with the selected location overplotted in red."""

    def __init__(self, parent=None, dpi=100):
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
        world.clip([-180, -90, 180, 90]).plot(color="white", edgecolor="black", ax=self.ax)     # TODO
        self.draw()

    def plot_location(self, longitude: float, latitude: float):

        if self.location_is_drawn:
            self.gdf.plot(ax=self.ax, color="white")    # TODO
        #     self.location.
        #     self.location.remove()
        #     print("Remove previous location")
        #     self.ax.lines[-1].remove()

        df = pd.DataFrame(
            {
                "Latitude": [latitude],
                "Longitude": [longitude],
            }
        )
        self.gdf = geopandas.GeoDataFrame(df, geometry=geopandas.points_from_xy(df.Longitude, df.Latitude), crs="EPSG:4326")
        self.gdf.plot(ax=self.ax, color="red")

        self.draw()
        self.location_is_drawn = True


if __name__ == "__main__":

    sys.exit(main())