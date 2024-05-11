"""Constants for the Detailed Hello World Push integration."""

# This is the internal name of the integration, it should also match the directory
# name for the integration.
from enum import StrEnum, IntEnum
DOMAIN = "manage_energy"
MIN_MARGIN = 0.2
BATTERY_DISCHARGE_RATE = 5


CURTAIL_BATTERY_LEVEL = 90


class PowerSelectOptions(StrEnum):
    """Power select options."""
    AUTO = "Auto"
    DISCHARGE = "Discharge"
    CHARGE = "Charge"
    MAXIMISE = "Maximise Self"


class TeslaModeSelectOptions(StrEnum):
    """Tesla mode select options."""
    AUTO = "Auto"
    CHEAP_GRID = "Charge from Cheap Grid and Solar"
    FAST_GRID = "Fast Charge from Grid"


# POWER_SELECT_OPTIONS = [AUTO, DISCHARGE, CHARGE, MAXIMISE]


class ConfName(StrEnum):
    POLLING_FREQUENCY = "polling_frequency"
    MINIMUM_MARGIN = "minimum_margin"
    CHEAP_PRICE = "cheap_price"
    HOST = "host"


class ConfDefaultInt(IntEnum):
    """Defaults for options that are booleans."""
    POLLING_FREQUENCY = 60
    MINIMUM_MARGIN = 15
    CHEAP_PRICE = 5


HOST_DEFAULT = "Manage Energy"
