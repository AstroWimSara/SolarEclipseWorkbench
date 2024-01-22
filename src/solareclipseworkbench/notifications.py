import os
from enum import Enum


class Notifications(str, Enum):
    """ Enumeration of notifications that will be used for the voice prompt."""

    MINUTES_10 = "10 minutes until totality!"
    MINUTES_5 = "5 minutes until totality!"
    MINUTES_2 = "2 minutes until totality!"
    MINUTES_1 = "1 minute until totality!"
    SECONDS_30 = "30 seconds until totality!"
    SECONDS_10 = "10 seconds until totality!"
    MAX_ECLIPSE = "Maximum eclipse!"
    FILTERS_OFF = "Filters OFF!  Filters OFF!"
    FILTERS_ON = "Filters ON!  Filters ON!"
    # CHECK_FOCUS = "Check focus!"


def voice_prompt(notification: str) -> int:
    """ Voice prompt of the given notification.

    In the current implementation, the default voice from your system settings will be used.

    Args:
        - notification: Notification

    Returns: On Unix, the return value is the exit status of the process and on Windows, the return value is the value
             returned by the system shell after running command.
    """

    os.system(f"say {Notifications[notification.lstrip()].value}")
