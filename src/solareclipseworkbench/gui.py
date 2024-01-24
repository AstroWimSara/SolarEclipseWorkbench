""" Solar Eclipse Workbench GUI, implemented according to the MVC pattern:

    - Model: SolarEclipseModel
    - View: SolarEclipseView
    - Controller: SolarEclipseController
"""

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QMainWindow, QApplication

from solareclipseworkbench import camera
from solareclipseworkbench.observer import Observer, Observable

ICON_PATH = Path(__file__).parent.resolve() / ".." / ".." / "img"


class SolarEclipseModel:

    def __init__(self):
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

        self.toolbar = None
        self.init_ui()

    def init_ui(self):

        self.add_toolbar()

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

    def on_toolbar_button_click(self):
        sender = self.sender()
        self.notify_observers(sender)


class SolarEclipseController(Observer):

    def __init__(self, model: SolarEclipseModel, view: SolarEclipseView):

        self.model = model

        self.view = view
        self.view.add_observer(self)

    def do(self, actions):
        pass

    def update(self, changed_object):
        text = changed_object.text()

        if text == "Location":
            # TODO
            print("Location")

        elif text == "Date":
            # TODO
            print("Date")

        elif text == "Reference moments":
            # TODO
            print("Reference moments")

        elif text == "Camera(s)":
            # TODO
            print("Camera(s)")


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
