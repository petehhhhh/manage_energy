"""Constants for the Detailed Hello World Push integration."""

# This is the internal name of the integration, it should also match the directory
# name for the integration.
from enum import StrEnum, IntEnum
DOMAIN = "energy_manager"
MIN_MARGIN = 0.2
BATTERY_DISCHARGE_RATE = 5


CURTAIL_BATTERY_LEVEL = 90
AUTO = "Auto"
DISCHARGE = "Discharge"
CHARGE = "Charge"
MAXIMISE = "Maximise Self"
SELECT_OPTIONS = [AUTO, DISCHARGE, CHARGE, MAXIMISE]


class ConfName(StrEnum):
    POLLING_FREQUENCY = "polling_frequency"
    MINIMUM_MARGIN = "minimum_margin"


class ConfDefaultInt(IntEnum):
    """Defaults for options that are booleans."""
    POLLING_FREQUENCY = 60
    MINIMUM_MARGIN = 15
