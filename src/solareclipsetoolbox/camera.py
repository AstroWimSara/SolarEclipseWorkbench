import locale
import gphoto2 as gp

class CameraSettings:

    def __init__(self, exposure_time: float, f: float, iso: int):
        """ Initialise new camera settings.

        Args:
            - exposure_time: Exposure time [s].
            - f: f-number.
            - iso: ISO-value.
        """

        self.exposure_time = exposure_time
        self.f = f
        self.iso = iso


def take_picture(camera_name: str, camera_settings: CameraSettings, description: str):

    raise NotImplementedError

def get_cameras() -> list:
    """ Returns a list with the cameras.

    Returns: List with all the attached cameras.
    """
    locale.setlocale(locale.LC_ALL, '')

    gp.check_result(gp.use_python_logging())
    # make a list of all available cameras
    return list(gp.Camera.autodetect())
