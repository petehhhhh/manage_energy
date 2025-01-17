from .const import (
    BATTERY_DISCHARGE_RATE,
    BATTERY_CHARGE_RATE,
    PowerSelectOptions,
    TeslaModeSelectOptions,
    DEMAND_SCALE_UP,
)
import time
import logging
import traceback
import copy

from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, StateMachine
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.helpers.event import async_track_time_interval, async_call_later
from datetime import datetime, timedelta
from .analyse import Analysis
from .decide import Decide
from .utils import is_demand_window, scale_price_for_demand_window

_LOGGER = logging.getLogger(__name__)


class Actuals:
    def __init__(self, hub) -> None:
        self.hub = hub

    def refresh(self):
        """Refresh actuals from meters."""
        self.price = self.get_entity_state("sensor.amber_general_price")
        self.scaled_price = scale_price_for_demand_window(datetime.now(), self.price)
        self.feedin = self.get_entity_state("sensor.amber_feed_in_price")
        self.battery_pct = self.get_entity_state("sensor.home_charge")
        self.battery_max_energy = self.get_entity_state(
            "sensor.battery1_battery_capacity"
        ) + self.get_entity_state("sensor.battery2_battery_capacity")
        self.battery_reserve = self.get_entity_state("sensor.home_backup_reserve")
        # assume 3% reserve on battery.
        self.battery_max_usable_energy = self.battery_max_energy * (
            1 - self.battery_reserve / 100
        )

        self.solar = self.get_entity_state("sensor.home_solar_power")
        self.battery_charge_rate = (
            self.get_entity_state("sensor.home_battery_power") * -1
        )
        self.consumption = self.get_entity_state("sensor.home_load_power")
        self.curtailed = self.hub.curtailment
        self.net_energy = self.solar - self.consumption
        if self.curtailed:
            self.net_energy += self.solar
        self.grid = self.get_entity_state("sensor.home_site_power")

        self.battery_min_energy = (
            round((self.battery_max_energy - self.battery_max_usable_energy), 1) + 0.1
        )
        self.available_battery_energy = self.battery_max_energy * self.battery_pct / 100

        self.time = datetime.now()

    def get_entity_state(self, entity_id, attribute=None):
        # get the current value of an entity or its attribute

        val = self.hub.hass.states.get(entity_id)
        val = val.state
        if val is None or val == "unavailable":
            raise RuntimeError("Entity Unavailable:" + entity_id)
        if attribute is not None:
            val = val.attributes[attribute]

        return float(val)


class Forecasts:
    def __init__(self, hub) -> None:
        self.hub = hub
        self.actuals = Actuals(hub)
        self._listeners = []
        self.history = []
        self.amber_feed_in = []
        self.amber_scaled_price = []
        self.amber_price = []
        self.start_time = []
        self.solar = []
        self.consumption = []
        self.net = []
        self.battery_energy = []
        self.battery_charge_rate = []
        self.net = []
        self.forecast_data = None
        self.recorder = get_instance(self.hub.hass)
        self.forecast = []
        self.analysis = None
        self.action = []
        self.rule = []

    def add_listener(self, callback):
        """Add a listener that will be notified when the state changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        """Notify all listeners about the current state."""
        for callback in self._listeners:
            callback(self.history)

    def forecast_and_scale_amber_prices(self):
        self.forecast_data = self.hub.hass.states.get("sensor.amber_general_forecast")
        forecast = [f["per_kwh"] for f in self.forecast_data.attributes["forecasts"]]
        # Iterate over self.times and adjust the forecast
        scale_forecast = forecast.copy()
        for i, tme in enumerate(self.start_time):
            scale_forecast[i] = scale_price_for_demand_window(tme, forecast[i])

        return forecast, scale_forecast

    def forecast_amber_feed_in_and_times(self):
        # Retrieve forecast data from the sensor
        self.forecast_data = self.hub.hass.states.get("sensor.amber_feed_in_forecast")

        # Extract forecast prices
        forecast = [f["per_kwh"] for f in self.forecast_data.attributes["forecasts"]]

        # Extract times and convert to datetime objects
        times = [
            self.format_date(f["start_time"])
            for f in self.forecast_data.attributes["forecasts"]
        ]

        return forecast, times

    def forecast_solar(self):
        # line up solar_forecast start time with that of the amber forecast...
        solar_forecast = []
        sfd = self.hub.hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        if (
            sfd is not None
            and sfd.attributes is not None
            and "detailedForecast" in sfd.attributes
        ):
            sf_data = sfd.attributes["detailedForecast"]
            for index, value in enumerate(sf_data):
                if self.compare_datetimes(value["period_start"], self.start_time[0]):
                    solar_forecast = [sf["pv_estimate"] for sf in sf_data[index:]]
            tomorrow_rows = len(self.amber_feed_in) - len(solar_forecast)
            if tomorrow_rows > 0:
                solar_forecast = solar_forecast + [
                    sf["pv_estimate"]
                    for sf in self.hub.hass.states.get(
                        "sensor.solcast_pv_forecast_forecast_tomorrow"
                    ).attributes["detailedForecast"][0:tomorrow_rows]
                ]
        return solar_forecast

    async def get_yesterday_consumption(self):
        """Forecast consumption based on yesterday by querying stats database. create a new list with the consumption from yesterday matching the start time of forecast_data."""
        consumption = []
        solar = []
        for value in self.forecast_data.attributes["forecasts"]:
            if value["start_time"] != None:
                consumption_yesterday = (
                    await self.get_sensor_state_changes_for_fixed_period(
                        "sensor.home_load_power",
                        self.format_date(value["start_time"]),
                    )
                )
                # subtract tesla or overstates consumption
                tesla_yesterday = (
                    16
                    * 3
                    / 1000
                    * await self.get_sensor_state_changes_for_fixed_period(
                        "number.pete_s_tesla_charging_amps",
                        self.format_date(value["start_time"]),
                    )
                )
                solar_yesterday = await self.get_sensor_state_changes_for_fixed_period(
                    "sensor.home_solar_power",
                    self.format_date(value["start_time"]),
                )
                net_consumption = consumption_yesterday - tesla_yesterday
                # consumption can be negative if we pick up a spike in tesla so limit to being 0.5 KW - roughly minimum house consumption
                net_consumption = max(net_consumption, 0.5)
                consumption.append(net_consumption)
                solar.append(solar_yesterday)

        return consumption, solar

    def calc_battery_percent(self, battery_energy_level: float) -> int:
        return int(battery_energy_level / self.actuals.battery_max_energy * 100)

    def forecast_battery_and_grid(self, f):
        # current energy in battery is the level of the battery less the unusable energy circa 10%

        battery_energy_level = f.actuals.available_battery_energy
        battery_forecast = []
        pct_forecast = []
        battery_charge_rate_forecast = []
        grid_forecast = []
        for i, forecast_net_energy in enumerate(f.net):
            # assume battery is charged at 5kw and discharged at 5kw and calc based on net energy upto 5kw for a half hour period ie KWH = KW/2
            battery_charge_rate, grid = self.calc_battery_and_grid(
                battery_energy_level, forecast_net_energy
            )

            battery_forecast.append(battery_energy_level)

            battery_charge_rate_forecast.append(battery_charge_rate)
            grid_forecast.append(grid)
            if i == len(f.net) - 1:
                end_time = f.start_time[i] + timedelta(minutes=30)
            else:
                end_time = f.start_time[i + 1]
            battery_energy_level = self.calc_battery_energy(
                battery_energy_level, battery_charge_rate, f.start_time[i], end_time
            )
            battery_pct = self.calc_battery_percent(battery_energy_level)
            pct_forecast.append(battery_pct)

        return (
            battery_forecast,
            pct_forecast,
            battery_charge_rate_forecast,
            grid_forecast,
        )

    def calc_battery_and_grid(
        self,
        battery_energy_level: float,
        net_energy: float,
        action=PowerSelectOptions.MAXIMISE,
    ):
        # assume battery is charged at 5kw and discharged at 5kw and calc based on net energy upto 5kw for a half hour period ie KWH = KW/2

        battery_charge_rate = self.calc_battery_charge_rate(
            net_energy, battery_energy_level, action
        )

        battery_energy_level = battery_energy_level + battery_charge_rate / 2

        grid = battery_charge_rate - net_energy

        # make sure battery never exeeds max or min
        if battery_energy_level > self.actuals.battery_max_energy:
            battery_energy_level = self.actuals.battery_max_energy
        elif battery_energy_level < self.actuals.battery_min_energy:
            battery_energy_level = self.actuals.battery_min_energy

        return (battery_charge_rate, grid)

    def store_forecast(self):
        """Store the forecast for use in a sensor."""

        #  history = self.hub.hass.states.get(
        #     "sensor.manage_energy_history")
        self.forecast = []

        for i, _ in enumerate(self.start_time):
            if i < len(self.action):
                action = self.action[i].value
                rule = self.rule[i].id
            else:
                action = ""

            self.forecast.append(
                {
                    "start_time": self.start_time[i],
                    "feed_in": self.amber_feed_in[i],
                    "price": self.amber_price[i],
                    "solar": round(self.solar[i], 1),
                    "consumption": round(self.consumption[i], 1),
                    "net": round(self.net[i], 1),
                    "battery": self.battery_pct[i],
                    "grid": round(self.grid[i], 1),
                    "action": action,
                    "rule": rule,
                    "battery_charge_rate": self.battery_charge_rate[i],
                }
            )

    async def store_history(self):
        # store the forecast history and the actuals in a sensor

        #  history = self.hub.hass.states.get(
        #     "sensor.manage_energy_history")
        history = self.history

        # only want one half hour block record keep on popping old record till we move to next half hour block...
        if len(history) > 0:
            if self.compare_datetimes(self.start_time[6], history[-1]["start_time"]):
                # remove the last record and replace with the new one
                history.pop()

        history.append(
            {
                "start_time": self.start_time[6],
                "amber": self.amber_feed_in[6],
                "solar": self.solar[6],
                "consumption": self.consumption[6],
                "net": self.net[6],
                "battery": int(
                    self.battery_energy[6] / self.actuals.battery_max_energy * 100
                ),
                "export": self.net[6],
            }
        )
        # search for start_time in history and store actuals for that time - effectively stores the actuals versus forecast generated 3 hours ago
        for index, value in enumerate(history):
            if self.compare_datetimes(value["start_time"], self.start_time[0]):
                history[index].update(
                    {
                        "actual_consumption": self.actuals.consumption,
                        "actual_solar": self.actuals.solar,
                        "actual_battery": self.actuals.battery_pct,
                        "actual_export": self.actuals.feedin,
                        "actual_net": self.actuals.consumption - self.actuals.solar,
                    }
                )
                break

        self.history = history[-24:]

    #  self.hub.hass.states.async_set(
    #     "sensor.manage_energy_history", len(history), {"history": history})

    async def build(self):
        """ "Build the foreacst."""

        self.actuals.refresh()
        actuals = self.actuals

        self.amber_feed_in, self.start_time = self.forecast_amber_feed_in_and_times()
        self.amber_price, self.amber_scaled_price = (
            self.forecast_and_scale_amber_prices()
        )
        self.consumption, yesterday_solar = await self.get_yesterday_consumption()
        solar_forecast = self.forecast_solar()
        if len(solar_forecast) < len(self.amber_feed_in):
            self.solar = yesterday_solar
        else:
            self.solar = solar_forecast
        self.net = [s - c for s, c in zip(self.solar, self.consumption)]
        (
            self.battery_energy,
            self.battery_pct,
            self.battery_charge_rate,
            self.grid,
        ) = self.forecast_battery_and_grid(self)
        self.analysis = Analysis(self, actuals, self.hub)
        self.analysis.analyze_price_peaks()
        self.actuals.rule = Decide(self).Decide_Battery_Action()
        self.actuals.action = self.actuals.rule.action
        await self.store_history()

        self.build_charge_forecast()
        self.store_forecast()

        self._notify_listeners()

    def build_charge_forecast(self):
        """ "Cycle through forecasts to work through charging rules for the next x hours."""

        ff = Forecasts(self.hub)
        ff.actuals = self.actuals
        a = ff.actuals
        backup_actuals = copy.copy(self.actuals)

        # initialise actions in forecast as they don't yet exist
        self.action = [None] * len(self.amber_feed_in)
        self.rule = [None] * len(self.amber_feed_in)

        for i in range(len(self.amber_feed_in)):
            self.build_fwd_actuals(ff, i)
            ff = self.build_fwd_forecast(ff, i)
            ff.analysis = Analysis(ff, ff.actuals, self.hub)
            ff.analysis.analyze_price_peaks()
            decision = Decide(ff)
            a.rule = decision.rule
            a.action = decision.rule.action
            a.battery_charge_rate, a.grid = self.calc_battery_and_grid(
                a.available_battery_energy, a.net_energy, a.action
            )

            self.update_forecast(ff, i)

        self.actuals = copy.copy(backup_actuals)

    def calc_battery_energy(
        self, current_energy, charge_rate, start: datetime, finish: datetime
    ):
        start = start.replace(tzinfo=None)
        finish = finish.replace(tzinfo=None)

        portion_of_hour = (finish - start).total_seconds() / 3600
        energy = current_energy + charge_rate * portion_of_hour
        if energy > self.actuals.battery_max_energy:
            energy = self.actuals.battery_max_energy
        elif energy < self.actuals.battery_min_energy:
            energy = self.actuals.battery_min_energy

        return energy

    def update_forecast(self, ff, i):
        """ "Capture the actual action and values in original forecast."""
        a: Actuals
        a = self.actuals

        self.battery_charge_rate[i] = a.battery_charge_rate
        self.action[i] = a.action
        self.rule[i] = a.rule
        self.net[i] = a.net_energy
        self.grid[i] = a.grid
        self.battery_energy[i] = a.available_battery_energy
        self.battery_pct[i] = a.battery_pct

    def build_fwd_actuals(self, ff, i):
        """Build actuals for next forecast in spot 0. Assumes actuals contains last actuals."""
        a: Actuals
        a = self.actuals
        if i == 0:
            start_time = datetime.now()
        else:
            start_time = self.start_time[i - 1]

        a.available_battery_energy = self.calc_battery_energy(
            a.available_battery_energy,
            a.battery_charge_rate,
            start_time,
            self.start_time[i],
        )
        a.battery_pct = self.calc_battery_percent(a.available_battery_energy)

        a.scaled_price = self.amber_scaled_price[i]
        a.price = self.amber_price[i]
        a.feedin = self.amber_feed_in[i]
        a.time = self.start_time[i]
        a.solar = self.solar[i]
        a.consumption = self.consumption[i]
        a.net_energy = a.solar - a.consumption

        (a.battery_charge_rate, a.grid) = self.calc_battery_and_grid(
            a.available_battery_energy, a.net_energy
        )

        # self.curtailed = self.hub.curtailment

        # if self.curtailed:
        #    self.excess_energy += self.solar

    def calc_battery_charge_rate(self, net_power, available_battery_energy, action):
        """Calculates the battery charge rate based on action and accounting for battery max and min"""

        match action.value:
            case PowerSelectOptions.CHARGE:
                rate = BATTERY_CHARGE_RATE
            case PowerSelectOptions.DISCHARGE:
                rate = BATTERY_DISCHARGE_RATE * -1
            case PowerSelectOptions.MAXIMISE:
                rate = net_power
            case PowerSelectOptions.OFF:
                rate = max(0, net_power)

        if rate > 0:
            rate = min(rate, BATTERY_CHARGE_RATE)
        else:
            rate = max(rate, BATTERY_DISCHARGE_RATE * -1)

        if available_battery_energy > self.actuals.battery_max_energy:
            rate = min(0, rate)

        if available_battery_energy <= self.actuals.battery_min_energy:
            rate = max(0, rate)

        return rate

    def build_fwd_forecast(self, ff, i):
        """Shift forecasts one space to the left to enable eval of rules on next block."""

        ff.amber_feed_in = self.amber_feed_in[i:]
        ff.amber_scaled_price = self.amber_scaled_price[i:]
        ff.amber_price = self.amber_price[i:]
        ff.start_time = self.start_time[i:]
        ff.solar = self.solar[i:]
        ff.net = self.net[i:]
        ff.consumption = ff.consumption[i:]
        (
            ff.battery_energy,
            ff.battery_pct,
            ff.battery_charge_rate,
            ff.grid,
        ) = self.forecast_battery_and_grid(ff)
        return ff

    def format_date(self, std1):
        """Converts a date string or datetime to the specified time zone using zoneinfo."""
        # Use ZoneInfo for the Australia/Sydney timezone
        tz = ZoneInfo("Australia/Sydney")

        # Format string for parsing the input
        format_string = "%Y-%m-%dT%H:%M:%S%z"

        # Parse std1 if it's not already a datetime object
        if not isinstance(std1, datetime):
            std1 = datetime.strptime(std1, format_string)

        # Convert to the specified timezone
        std1 = std1.astimezone(tz)

        # Remove seconds for consistency
        std1 = std1.replace(second=0)

        return std1

    def compare_datetimes(self, std1, std2):
        # returns true if two string format date times are the same.
        d1 = self.format_date(std1)
        d2 = self.format_date(std2)

        return d1 == d2

    def get_entity_state(self, entity_id, attribute=None):
        # get the current value of an entity or its attribute

        val = self.hub.hass.states.get(entity_id).state

        if val is None or val == "unavailable":
            raise RuntimeError("Solaredge unavailable")
        if attribute is not None:
            val = val.attributes[attribute]

        return float(val)

    async def get_sensor_state_changes_for_fixed_period(self, entity_id, start_time):
        # Returns average sensor value for the 30 minute block yesterday from start_time
        duration_minutes = 30  # Adjust the duration as needed

        # Calculate the previous day
        previous_day = start_time - timedelta(days=1)

        # Calculate the corresponding end time
        end_time = previous_day + timedelta(minutes=duration_minutes)

        # Convert times to UTC using zoneinfo
        start_time = previous_day.astimezone(ZoneInfo("UTC"))
        end_time = end_time.astimezone(ZoneInfo("UTC"))

        # Retrieve state changes for the sensor during the specified time period

        changes = await self.recorder.async_add_executor_job(
            state_changes_during_period, self.hub.hass, start_time, end_time, entity_id
        )
        vals = []
        avg = 0
        if entity_id in changes:
            for f in changes[entity_id]:
                # if f.state is a valid float value add it to the list of values
                try:
                    vals.append(float(f.state))
                except:
                    continue
            if len(vals) != 0:
                avg = sum(vals) / len(vals)

        return round(avg, 2)
