import locale
import logging
import time
import gphoto2 as gp
from datetime import datetime


class CameraError(Exception):
    pass


class CameraSettings:

    def __init__(self, shutter_speed: str, aperture: float, iso: int):
        """ Initialise new camera settings.

        Args:
            - shutter_speed: Exposure time [s], e.g. "1/2000".
            - aperture: Aperture (f-number), e.g. 5.6.
            - iso: ISO-value.
        """

        self.shutter_speed = shutter_speed
        self.aperture = aperture
        self.iso = iso


def take_picture(camera_name: str, camera_settings: CameraSettings, description: str):
    """ Take a picture with the selected camera 
    
    Args: 
        - camera_name: Name of the camera
        - camera_settings: Settings of the camera (exposure, f, iso)
        - description: Description of the picture
    """

    camera = get_camera(camera_name)
    context = gp.gp_context_new()
    config = gp.check_result(gp.gp_camera_get_config(camera, context))

    iso = gp.check_result(
        gp.gp_widget_get_child_by_name(config, 'iso'))
    gp.check_result(gp.gp_widget_set_value(iso, str(camera_settings.iso)))
    # set config
    gp.check_result(gp.gp_camera_set_config(camera, config))

    # Set aperture
    aperture = gp.check_result(
        gp.gp_widget_get_child_by_name(config, 'aperture'))
    gp.check_result(gp.gp_widget_set_value(aperture, str(camera_settings.aperture)))
    # set config
    gp.check_result(gp.gp_camera_set_config(camera, config))

    # Set shutter speed
    shutter_speed = gp.check_result(
        gp.gp_widget_get_child_by_name(config, 'shutterspeed'))
    gp.check_result(gp.gp_widget_set_value(shutter_speed, str(camera_settings.shutter_speed)))
    # set config
    gp.check_result(gp.gp_camera_set_config(camera, config))

    # find the capture target config item (to save to the memory card)
    capture_target = gp.check_result(
        gp.gp_widget_get_child_by_name(config, 'capturetarget'))
    # set value
    value = gp.check_result(gp.gp_widget_get_choice(capture_target, 1))
    gp.check_result(gp.gp_widget_set_value(capture_target, value))
    # set config
    gp.check_result(gp.gp_camera_set_config(camera, config))

    # Take picture
    camera.capture(gp.GP_CAPTURE_IMAGE)

    camera.exit() 


def get_cameras() -> list:
    """ Returns a list with the cameras.

    Returns: List with all the attached cameras.
    """

    locale.setlocale(locale.LC_ALL, '')

    gp.check_result(gp.use_python_logging())
    # make a list of all available cameras
    return list(gp.Camera.autodetect())


def __get_address(camera_name: str) -> str:
    """ Gets the address of the camera if the name is given 
    
    Args:
        - camera_name: Name of the camera
    
    Returns: Address of the camera
    """

    camera_tuple = [camera[1] for camera in get_cameras() if camera[0] == camera_name]
    try:
        return camera_tuple[0]
    except IndexError:
        raise CameraError(f"Camera {camera_name} not found")


def get_camera(camera_name: str):
    """ Returns the initialized camera object of the selected camera

    Args: 
        - camera_name: Name of the camera
    
    Returns: Initialized camera object of the selected camera.
    """

    addr = __get_address(camera_name)
    if addr == '':
        return ''

    # get port info
    port_info_list = gp.PortInfoList()
    port_info_list.load()
    abilities_list = gp.CameraAbilitiesList()
    abilities_list.load()

    camera = gp.Camera()
    idx = port_info_list.lookup_path(addr)
    camera.set_port_info(port_info_list[idx])
    idx = abilities_list.lookup_model(camera_name)
    camera.set_abilities(abilities_list[idx])

    # Initialize the camera
    camera.init()
    return camera


def get_free_space(camera_name: str) -> str:
    """ Return the free space on the card of the selected camera 
    
    Args: 
        - camera_name: Name of the camera

    Returns: Free space on the card of the camera [GB]
    """

    camera = get_camera(camera_name)
    return round(camera.get_storageinfo()[0].freekbytes / 1024 / 1024, 1)


def get_space(camera_name: str) -> str:
    """ Return the size of the memory card of the selected camera 
    
    Args: 
        - camera_name: Name of the camera

    Returns: Size of memory card of the camera [GB]
    """

    camera = get_camera(camera_name)
    return round(camera.get_storageinfo()[0].capacitykbytes / 1024 / 1024, 1)


def get_shooting_mode(camera_name: str) -> str:
    """ Return the shooting mode of the selected camera. Should be "Manual".
    
    Args: 
        - camera_name: Name of the camera

    Returns: Shooting mode of the camera
    """

    camera = get_camera(camera_name)
    return camera.get_config().get_child_by_name('autoexposuremodedial').get_value()


def get_focus_mode(camera_name: str) -> str:
    """ Return the focus mode of the selected camera. Should be "Manual"
    
    Args: 
        - camera_name: Name of the camera

    Returns: Focus mode of the camera
    """

    camera = get_camera(camera_name)
    return camera.get_config().get_child_by_name('focusmode').get_value()


def get_battery_level(camera_name: str) -> str:
    """ Return the battery level of the selected camera 
    
    Args: 
        - camera_name: Name of the camera

    Returns: Current battery level of the camera [%]
    """

    camera = get_camera(camera_name)
    return camera.get_config().get_child_by_name('batterylevel').get_value()


def get_time(camera_name: str) -> str:
    """ Returns the current time of the selected camera

    Args: 
        - camera_name: Name of the camera

    Returns: Current time of the camera
    """

    camera = get_camera(camera_name)
    # get configuration tree
    config = camera.get_config()
    # find the date/time setting config item and get it
    # name varies with camera driver
    #   Canon EOS - 'datetime'
    #   PTP - 'd034'
    for name, fmt in (('datetime', '%Y-%m-%d %H:%M:%S'),
                      ('d034',     None)):
        now = datetime.now()
        ok, datetime_config = gp.gp_widget_get_child_by_name(config, name)
        if ok >= gp.GP_OK:
            widget_type = datetime_config.get_type()
            raw_value = datetime_config.get_value()
            if widget_type == gp.GP_WIDGET_DATE:
                camera_time = datetime.fromtimestamp(raw_value)
            else:
                if fmt:
                    camera_time = datetime.strptime(raw_value, fmt)
                else:
                    camera_time = datetime.utcfromtimestamp(float(raw_value))
            logging.info('Camera clock:  ', camera_time.isoformat(' '))
            logging.info('Computer clock:', now.isoformat(' '))
            err = now - camera_time
            if err.days < 0:
                err = -err
                lead_lag = 'ahead'
                logging.info('Camera clock is ahead by',)
            else:
                lead_lag = 'behind'
            logging.warning('Camera clock is %s by %d days and %d seconds' % (
                lead_lag, err.days, err.seconds))
            break
    else:
        logging.warning('Unknown date/time config item')
    # clean up
    camera.exit()
    return camera_time.isoformat(' ')


def set_time(camera_name: str) -> None:
    """ Set the computer time on the selected camera """

    camera = get_camera(camera_name)
    # get configuration tree
    config = camera.get_config()

    if __set_datetime(config):
        # apply the changed config
        camera.set_config(config)
    else:
        logging.error('Could not set date & time')

    # clean up
    camera.exit()


def __set_datetime(config) -> bool:
    """ Private method to set the date and time of the camera. """

    ok, date_config = gp.gp_widget_get_child_by_name(config, 'datetimeutc')
    if ok >= gp.GP_OK:
        widget_type = date_config.get_type()
        if widget_type == gp.GP_WIDGET_DATE:
            now = int(time.time())
            date_config.set_value(now)
        else:
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            date_config.set_value(now)
        return True
    return False


def get_camera_overview():
    """ Returns a dictionary with information of the connected cameras.

    The keys in the dictionary are the camera names and the values (the camera information) contains information about
    the battery level and space on the memory card of the camera.

    Returns: Dictionary with information of the connected cameras.
    """

    camera_overview = {}

    camera_names = get_cameras()

    for camera_name in camera_names:

        battery_level = get_battery_level(camera_name)
        free_space = get_free_space(camera_name)
        total_space = get_space(camera_name)

        camera_overview[camera_name] = CameraInfo(camera_name, battery_level, free_space)

    return camera_overview


class CameraInfo():

    def __init__(self, camera_name: str, battery_level: float, free_space: float, total_space: float) -> None:
        """ Create a new CameraInfo object.

        Args:
            - camera_name: Name of the camera
            - battery_level: Battery level [%]
            - free_space: Free space on the camera memory card [GB]
            - total_space: Total space on the camera memory card [GB]
        """

        self.camera_name = camera_name
        self.battery_level = battery_level
        self.free_space = free_space
        self.total_space = total_space

    def get_camera_name(self) -> str:
        """ Returns the name of the camera.

        Returns: Name of the camera.
        """
        return self.camera_name

    def get_battery_level(self) -> float:
        """ Returns the battery level of the camera.

        Returns: Battery level of the camera [%].
        """
        return self.battery_level

    def get_absolute_free_space(self) -> float:
        """ Returns the absolute free space on the memory card of the camera.

        Returns: Free space on the memory card of the camera [GB].
        """

        return self.free_space

    def get_relative_free_space(self) -> float:
        """ Returns the relative free space on the memory card of the camera.

        Returns: Free space on the memory card of the camera [%].
        """

        return self.get_absolute_free_space() / self.get_total_space() * 100

    def get_total_space(self) -> float:
        """ Returns the total space on the memory card of the camera.

        Returns: Total space on the memory card of the camera [GB].
        """
        return self.total_space
