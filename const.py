"""Constants for the Detailed Hello World Push integration."""

# This is the internal name of the integration, it should also match the directory
# name for the integration.
from enum import StrEnum, IntEnum

DOMAIN = "manage_energy"
MIN_MARGIN = 0.2
BATTERY_DISCHARGE_RATE = 8
# Rate battery charges when gets above 95%
REDUCED_CHARGE_RATE = 4
BATTERY_CHARGE_RATE = 7
CURTAIL_BATTERY_LEVEL = 97
MAX_BATTERY_LEVEL = 99
# how much to add to general forecast price for when in demand window.... 30 days at 30 cents for 5 extra kW...
DEMAND_SCALE_UP = 30 * 5 * 0.3 / 8


class EntityIDs(StrEnum):
    """Entity IDs to be used when registring"""

    SOLAR_CURTAILMENT = "switch.solar_curltailment"
    MODE_SELECT = "select.manage_energy_power_mode"
    TESLA_MODE_SELECT = "select.manage_energy_tesla_mode"
    MAX_PRICE = "number.cheap_charge_price"
    AUTO = "switch.manage_energy_auto"


class PowerSelectOptions(StrEnum):
    """Power select options."""

    MAXIMISE = "Maximise Self"
    DISCHARGE = "Discharge"
    CHARGE = "Charge"
    OFF = "Solar only (off)"


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
