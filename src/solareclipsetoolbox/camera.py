import locale
import logging
import time
import gphoto2 as gp
from datetime import datetime

class CameraError(Exception):
    pass

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

def get_address(camera_name: str) -> str:
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
    addr = get_address(camera_name)
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
    Returns: Free space on the card of the camera
    """
    camera = get_camera(camera_name)
    return str(round(camera.get_storageinfo()[0].freekbytes / 1024 / 1024, 1)) + " gb"

def get_battery_level(camera_name: str) -> float:
    """ Return the battery level of the selected camera 
    
    Args: 
        - camera_name: Name of the camera
    Returns: Current battery level of the camera
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
        OK, datetime_config = gp.gp_widget_get_child_by_name(config, name)
        if OK >= gp.GP_OK:
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

    if set_datetime(config):
        # apply the changed config
        camera.set_config(config)
    else:
        logging.error('Could not set date & time')

    # clean up
    camera.exit()

def set_datetime(config) -> bool:
    """ Private method to set the date and time of the camera. """
    OK, date_config = gp.gp_widget_get_child_by_name(config, 'datetimeutc')
    if OK >= gp.GP_OK:
        widget_type = date_config.get_type()
        if widget_type == gp.GP_WIDGET_DATE:
            now = int(time.time())
            date_config.set_value(now)
        else:
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            date_config.set_value(now)
        return True
    return False
