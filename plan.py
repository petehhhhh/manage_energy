from .const import (
    BATTERY_DISCHARGE_RATE,
    CURTAIL_BATTERY_LEVEL,
    DOMAIN,
    PowerSelectOptions,
    TeslaModeSelectOptions,
    DEMAND_SCALE_UP,
)
import time
import logging
import traceback

from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, StateMachine
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.helpers.event import async_track_time_interval, async_call_later
from datetime import datetime, time, date, timedelta
from .forecasts import Actuals, Forecasts
from .analyse import Analysis

_LOGGER = logging.getLogger(__name__)


class BatteryPlanner:
    """Build a 12 hour forecast of what the battery will do."""

    def __init__(self, hub):
        """Init class."""
        self.hub = hub

    def build_plan(self):
        """Build a plan for the 12 next hours."""
        hub = self.hub
        for i in range(24):
            self.plan.append(self.plan_iteration(i))

    def plan_iteration(self, i):
        """ "Build a plan for the next entry i"""
        a = Plan_Actuals(i, hub)
        f = Plan_Forecast(i, hub, a)

        a = Analysis(f, p, self)
        a.analyze_price_peaks()

    class Plan_Actuals(Actuals):
        def __init(self, i: int, hub) -> None:
            self.price = hub.forecasts.amber_price[i]
            self.scaled_price = hub.forecasts.amber_scaled_price[i]
            self.feedin = hub.forecasts.amber_scaled_price[i]
            self.battery_max_energy = hub.actuals.battery_max_energy
            self.available_battery_energy = hub.forecasts.battery_energy[i]
            self.available_battery_energy = hub.forecasts.battery_energy[i]
            self.battery_pct_level = int(
                hub.forecasts.battery_energy[i] / self.battery_max_energy
            )
            # assume 3% reserve on battery.
            self.battery_max_usable_energy = self.actuals.battery_max_usable_energy
            self.solar = hub.forecasts.solar[i]

            if i == 0:
                prior_energy = hub.actuals.available_battery_energy

            else:
                prior_energy = hub.forecasts.battery_energy[i - 1]

            # done in half hour block so charge rate is amount of energy in kwh x 2
            self.battery_charge_rate = self.available_battery_energy - prior_energy * 2
            self.consumption = hub.forecasts.consumption[i]
            # self.curtailed = self._hub.curtailment
            self.excess_energy = (
                self.solar - self.consumption - self.battery_charge_rate
            )

            self.battery_min_energy = (
                self.battery_max_energy - self.battery_max_usable_energy
            )

    class Plan_Forecast(Forecasts):
        def __init__(self, i: int, hub, plan_actuals) -> None:
            self._hass = hub.hass
            self._actuals = plan_actuals
            self.amber_feed_in = hub.forecasts.amber_feed_in[i + 1 :]
            self.amber_scaled_price = hub.forecasts.amber_scaled_price[i + 1 :]
            self.amber_price = hub.forecasts.amber_price[i + 1 :]
            self.start_time = hub.forecasts.start_time[i + 1 :]
            self.solar = hub.forecasts.solar[i + 1 :]
            self.consumption = hub.forecasts.consumption[i + 1 :]
            self.net = hub.forecasts.net[i + 1 :]
            self.battery_energy = hub.forecasts.battery_energy[i + 1 :]
            self.export = hub.forecasts.self.export[i + 1 :]
