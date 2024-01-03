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
