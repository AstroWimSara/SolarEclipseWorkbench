import locale
import logging
import time

import gphoto2
import gphoto2 as gp
from datetime import datetime

from gphoto2 import Camera


class CameraError(Exception):
    pass


class CameraSettings:

    def __init__(self, camera_name: str, shutter_speed: str, aperture: str, iso: int):
        """ Initialise new camera settings.

        Args:
            - camera_name: Name of the camera
            - shutter_speed: Exposure time [s], e.g. "1/2000".
            - aperture: Aperture (f-number), e.g. 5.6.
            - iso: ISO-value.
        """
        self.camera_name = camera_name
        self.shutter_speed = shutter_speed
        self.aperture = aperture
        self.iso = iso


def take_picture(camera: Camera, camera_settings: CameraSettings) -> None:
    """ Take a picture with the selected camera 
    
    Args: 
        - camera_name: Camera object
        - camera_settings: Settings of the camera (exposure, f, iso)
    """

    context, config = __adapt_camera_settings(camera, camera_settings)

    # Take picture
    camera.capture(gp.GP_CAPTURE_IMAGE, context)


def __adapt_camera_settings(camera, camera_settings):
    context = gp.gp_context_new()
    config = gp.check_result(gp.gp_camera_get_config(camera, context))
    # Set ISO
    if "Nikon" in camera_settings.camera_name:
        gp.gp_widget_set_value(gp.check_result(gp.gp_widget_get_child_by_name(config, 'autoiso')), str("Off"))
        # set config
        gp.gp_camera_set_config(camera, config, context)

    gp.gp_widget_set_value(gp.check_result(gp.gp_widget_get_child_by_name(config, 'iso')), str(camera_settings.iso))
    # set config
    gp.gp_camera_set_config(camera, config, context)
    time.sleep(0.1)

    # Set aperture
    try:
        if "Canon" in camera_settings.camera_name:
            gp.gp_widget_set_value(gp.check_result(gp.gp_widget_get_child_by_name(config, 'aperture')),
                                   str(camera_settings.aperture))
        elif "Nikon" in camera_settings.camera_name:
            gp.gp_widget_set_value(gp.check_result(gp.gp_widget_get_child_by_name(config, 'f-number')),
                                   str(camera_settings.aperture))
        # set config
        gp.gp_camera_set_config(camera, config, context)
        time.sleep(0.1)
    except gphoto2.GPhoto2Error:
        pass

    # Set shutter speed
    gp.gp_widget_set_value(gp.check_result(gp.gp_widget_get_child_by_name(config, 'shutterspeed')),
                           str(camera_settings.shutter_speed))
    # set config
    gp.gp_camera_set_config(camera, config, context)
    time.sleep(0.1)

    return context, config


def take_burst(camera: Camera, camera_settings: CameraSettings, duration: float) -> None:
    """ Take a burst with the selected camera.  For Canon, the duration is the duration in seconds, for Nikon, the
        duration is the number of pictures to take.

    Args:
        - camera_name: Camera object
        - camera_settings: Settings of the camera (exposure, f, iso)
        - duration: Duration of the burst in seconds (Canon) or number of pictures (Nikon)
    """
    context, config = __adapt_camera_settings(camera, camera_settings)

    # Take picture
    if "Canon" in camera_settings.camera_name:
        # Push the button
        remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        gp.gp_widget_set_value(remote_release, "Press Full")
        # set config
        gp.gp_camera_set_config(camera, config, context)
        time.sleep(duration)

        # Release the button
        remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        gp.gp_widget_set_value(remote_release, "Release Full")
        # set config
        gp.gp_camera_set_config(camera, config, context)
    elif "Nikon" in camera_settings.camera_name:
        # Push the button
        capture_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturemode'))
        gp.gp_widget_set_value(capture_mode, "Burst")
        # set config
        gp.gp_camera_set_config(camera, config, context)

        burst_number = gp.check_result(gp.gp_widget_get_child_by_name(config, 'burstnumber'))
        gp.gp_widget_set_value(burst_number, round(duration))
        # set config
        gp.gp_camera_set_config(camera, config, context)

        camera.capture(gp.GP_CAPTURE_IMAGE, context)


def take_bracket(camera: Camera, camera_settings: CameraSettings, steps: str) -> None:
    """ Take a bracketing of images with the selected camera.

    Args:
        - camera_name: Camera object
        - camera_settings: Settings of the camera (exposure, f, iso)
        - steps: Steps for each bracketing step (e.g. +/- 1 2/3)
    """
    context, config = __adapt_camera_settings(camera, camera_settings)

    if "Canon" in camera_settings.camera_name:
        # Set aeb
        aeb = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aeb'))
        gp.gp_widget_set_value(aeb, steps)
        # set config
        gp.gp_camera_set_config(camera, config, context)

        camera.capture(gp.GP_CAPTURE_IMAGE, context)
        camera.capture(gp.GP_CAPTURE_IMAGE, context)
        camera.capture(gp.GP_CAPTURE_IMAGE, context)
        camera.capture(gp.GP_CAPTURE_IMAGE, context)
        camera.capture(gp.GP_CAPTURE_IMAGE, context)

        # Set aeb
        aeb = gp.check_result(gp.gp_widget_get_child_by_name(config, 'aeb'))
        gp.gp_widget_set_value(aeb, "off")
        # set config
        gp.gp_camera_set_config(camera, config, context)


def mirror_lock(camera: Camera, camera_settings: CameraSettings) -> None:
    """ Lock the mirror

    Args:
        - camera_name: Camera object
    """
    context = gp.gp_context_new()
    config = gp.check_result(gp.gp_camera_get_config(camera, context))

    if "Canon" in camera_settings.camera_name:
        lock = gp.check_result(gp.gp_widget_get_child_by_name(config, 'mirrorlock'))
        gp.gp_widget_set_value(lock, "1")
        # set config
        gp.gp_camera_set_config(camera, config, context)

        context, config = __adapt_camera_settings(camera, camera_settings)

        # # Push the button
        # remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        # gp.gp_widget_set_value(remote_release, "Press 2")
        # # set config
        # gp.gp_camera_set_config(camera, config, context)

        # Release the button
        # remote_release = gp.check_result(gp.gp_widget_get_child_by_name(config, 'eosremoterelease'))
        # gp.gp_widget_set_value(remote_release, "Release Full")
        # # set config
        # gp.gp_camera_set_config(camera, config, context)

        # Set mirror lock back to off
        lock = gp.check_result(gp.gp_widget_get_child_by_name(config, 'mirrorlock'))
        gp.gp_widget_set_value(lock, "0")
        # set config
        gp.gp_camera_set_config(camera, config, context)


def get_cameras() -> list:
    """ Returns a list with the cameras.

    Returns: List with all the attached cameras ([name, USB port]).
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

    context = gp.gp_context_new()

    # Initialize the camera
    try:
        camera.init(context)

        # find the capture target config item (to save to the memory card)
        config = gp.check_result(gp.gp_camera_get_config(camera, context))
        capture_target = gp.check_result(gp.gp_widget_get_child_by_name(config, 'capturetarget'))
        # set value
        value = gp.check_result(gp.gp_widget_get_choice(capture_target, 1))
        gp.gp_widget_set_value(capture_target, value)
        # set config
        gp.gp_camera_set_config(camera, config, context)

        # find the drivemode and set to Continuous high speed
        drive_mode = gp.check_result(gp.gp_widget_get_child_by_name(config, 'drivemode'))
        gp.gp_widget_set_value(drive_mode, "Continuous high speed")
        # set config
        gp.gp_camera_set_config(camera, config, context)
    except gphoto2.GPhoto2Error:
        pass

    return camera


def get_free_space(camera: Camera) -> float:
    """ Return the free space on the card of the selected camera 
    
    Args: 
        - camera: Camera object

    Returns: Free space on the card of the camera [GB]
    """
    return round(camera.get_storageinfo()[0].freekbytes / 1024 / 1024, 1)


def get_space(camera: Camera) -> float:
    """ Return the size of the memory card of the selected camera 
    
    Args: 
        - camera: Camera object

    Returns: Size of memory card of the camera [GB]
    """

    return round(camera.get_storageinfo()[0].capacitykbytes / 1024 / 1024, 1)


def get_shooting_mode(camera_name: str, camera: Camera) -> str:
    """ Return the shooting mode of the selected camera. Should be "Manual".
    
    Args: 
        - camera: Camera object

    Returns: Shooting mode of the camera
    """
    if "Canon" in camera_name:
        return camera.get_config().get_child_by_name('autoexposuremodedial').get_value()
    elif "Nikon" in camera_name:
        mode = camera.get_config().get_child_by_name('expprogram').get_value()
        if mode == "M":
            return "Manual"
        else:
            return mode
    else:
        return ""


def get_focus_mode(camera: Camera) -> str:
    """ Return the focus mode of the selected camera. Should be "Manual"
    
    Args: 
        - camera: Camera object

    Returns: Focus mode of the camera
    """

    return camera.get_config().get_child_by_name('focusmode').get_value()


def get_battery_level(camera: Camera) -> str:
    """ Return the battery level of the selected camera 
    
    Args: 
        - camera: Name of the camera

    Returns: Current battery level of the camera [%]
    """

    return camera.get_config().get_child_by_name('batterylevel').get_value()


def get_time(camera: Camera) -> str:
    """ Returns the current time of the selected camera

    Args: 
        - camera: Camera object

    Returns: Current time of the camera
    """

    # get configuration tree
    config = camera.get_config()
    # find the date/time setting config item and get it
    # name varies with camera driver
    #   Canon EOS - 'datetime'
    #   PTP - 'd034'
    for name, fmt in (('datetime', '%Y-%m-%d %H:%M:%S'),
                      ('d034', None)):
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
                logging.info('Camera clock is ahead by', )
            else:
                lead_lag = 'behind'
            logging.warning('Camera clock is %s by %d days and %d seconds' % (
                lead_lag, err.days, err.seconds))
            break
    else:
        logging.warning('Unknown date/time config item')
        return "Unknown date/time config item"

    return camera_time.isoformat(' ')


def set_time(camera: Camera) -> None:
    """ Set the computer time on the selected camera """

    # get configuration tree
    config = camera.get_config()

    if __set_datetime(config):
        # apply the changed config
        camera.set_config(config)
    else:
        logging.error('Could not set date & time')


def __set_datetime(config) -> bool:
    """ Private method to set the date and time of the camera. """

    ok, date_config = gp.gp_widget_get_child_by_name(config, 'datetimeutc')
    if ok == -2:
        ok, date_config = gp.gp_widget_get_child_by_name(config, 'datetime')

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


def get_camera_dict() -> dict:
    """ Get a dictionary of camera names and their GPhoto2 camera object
    Returns: Dictionary of camera names and their GPhoto2 camera object
    """
    camera_names = get_cameras()
    cameras = dict()
    for camera_name in camera_names:
        cameras[camera_name[0]] = get_camera(camera_name[0])
    return cameras


def get_camera_overview() -> dict:
    """ Returns a dictionary with information of the connected cameras.

    The keys in the dictionary are the camera names and the values (the camera information) contains information about
    the battery level and space on the memory card of the camera.

    Returns: Dictionary with information of the connected cameras.
    """

    camera_overview = {}

    camera_names = get_cameras()
    for camera_name in camera_names:
        camera = get_camera(camera_name[0])

        try:
            battery_level = get_battery_level(camera)
            free_space = get_free_space(camera)
            total_space = get_space(camera)

            camera_overview[camera_name[0]] = CameraInfo(camera_name, battery_level, free_space, total_space)
            # camera.exit()
        except gp.GPhoto2Error:
            logging.error("Could not connect to the camera.  Did you start Solar Eclipse Workbench in sudo mode?")

    return camera_overview


class CameraInfo:

    def __init__(self, camera_name: str, battery_level: str, free_space: float, total_space: float) -> None:
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
        return self.camera_name[0]

    def get_battery_level(self) -> str:
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


def main():
    # Get cameras
    cameras = get_cameras()

    # Get all information for the gui
    get_camera_overview()

    # Get battery and free space
    for camera in cameras:
        try:
            camera_object = get_camera(camera[0])

            # Get general info
            print(f"{camera[0]}: {get_battery_level(camera_object)} - {get_free_space(camera_object)} GB "
                  f"of {get_space(camera_object)} GB free.")

            # Check if the lens and the camera are set to manual
            if get_shooting_mode(camera[0], camera_object) != "Manual":
                print("Set the camera in Manual mode!")
                exit()

            if get_focus_mode(camera_object) != "Manual":
                print("Set the lens in Manual mode!")
                exit()

            # Set the correct time
            print(get_time(camera_object))
            set_time(camera_object)

            # Take picture
            camera_settings = CameraSettings(camera[0], "1/1000", "8", 100)

            take_picture(camera_object, camera_settings)

            time.sleep(1)
            camera_settings = CameraSettings(camera[0], "1/200", "6.3", 400)
            # take_bracket(camera_object, camera_settings, "+/- 1 2/3")
            take_picture(camera_object, camera_settings)

            # Mirror lock
            # mirror_lock(camera_object, camera_settings)

            # take_picture(camera_object, camera_settings)

            time.sleep(1)
            camera_settings = CameraSettings(camera[0], "1/4000", "5.6", 200)
            take_burst(camera_object, camera_settings, 1)
            time.sleep(3)
            camera_object.exit()

        except gphoto2.GPhoto2Error:
            print("Could not connect to the camera.  Did you start Solar Eclipse Workbench in sudo mode?")


if __name__ == "__main__":
    main()
