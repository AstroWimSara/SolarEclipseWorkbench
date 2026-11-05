"""Registry of non-camera hardware available to scheduled script commands.

Lives in its own module so both the GUI and the scheduler (utils) can import it
without creating an import cycle: utils imports the GUI, so the GUI cannot
import utils at module level.
"""

import logging

# Devices opened by the GUI or the command line, looked up when a job fires.
HARDWARE: dict = {}

# Script commands that act on a piece of hardware rather than a camera, mapped to
# the kind of device they need.  Lives here rather than in utils so that scripts
# can consult it too without importing utils, which would be a cycle.
HARDWARE_COMMANDS = {
    'relay_shoot': 'relay',
    'relay_burst': 'relay',
    'relay_bulb': 'relay',
    'relay_arm': 'relay',
    'relay_release': 'relay',
}

#: The kind under which a camera registers when it keeps a USB session open
#: while the relay fires it.  The relay commands call the hooks of this camera
#: (relay_trigger lists them), so that it can prepare for the relay frames and
#: clear up after them.
TETHERED_CAMERA = 'tethered_camera'


def register_hardware(kind: str, device) -> None:
    """Make a device (e.g. a relay trigger) available to scheduled commands.

    Pass None to unregister, so a disconnected device does not leave scheduled
    commands pointing at a dead handle.
    """
    if device is None:
        HARDWARE.pop(kind, None)
        logging.info("Unregistered %s", kind)
    else:
        HARDWARE[kind] = device
        logging.info("Registered %s: %s", kind, getattr(device, 'describe', lambda: device)())


def get_hardware(kind: str):
    """The registered device of the given kind, or None."""
    return HARDWARE.get(kind)
