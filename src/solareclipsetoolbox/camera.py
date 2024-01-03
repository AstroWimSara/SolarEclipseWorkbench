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
