from .const import (
    BATTERY_DISCHARGE_RATE,
    CURTAIL_BATTERY_LEVEL,
    DOMAIN,
    PowerSelectOptions,
    TeslaModeSelectOptions,
)
import time
import logging
import traceback
import datetime
import asyncio
from pytz import timezone
from homeassistant.core import HomeAssistant, StateMachine
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.helpers.event import async_track_time_interval, async_call_later

_LOGGER = logging.getLogger(__name__)


class Actuals:
    def __init__(self, hass) -> None:
        self._hass = hass

    def refresh(self):
        self.price = self.get_entity_state("sensor.amber_general_price")
        self.feedin = self.get_entity_state("sensor.amber_feed_in_price")
        self.battery_pct_level = self.get_entity_state(
            "sensor.home_battery"
        )
        self.battery_max_energy = self.get_entity_state(
            "sensor.battery1_battery_capacity") + self.get_entity_state(
            "sensor.battery2_battery_capacity") 
        
        # assume 3% reserve on battery.
        self.battery_max_usable_energy = self.battery_max_energy * 0.97
        
        self.solar = self.get_entity_state("sensor.power_solar_generation")
        self.battery_charge_rate = self.get_entity_state("sensor.home_load_import") * -1
        self.consumption = self.get_entity_state("sensor.power_consumption")
        self.curtailed =  (self._hass.states.get("select.solaredge_i1_limit_control_mode").state != "Disabled")
        self.excess_energy = self.solar - self.consumption - self.battery_charge_rate
        if self.curtailed :
            self.excess_energy += self.solar
       
        self.available_battery_energy = (
            self.battery_max_energy * self.battery_pct_level / 100
        ) - (self.battery_max_energy - self.battery_max_usable_energy)
        self.battery_min_energy = (
            self.battery_max_energy - self.battery_max_usable_energy
        )

    def get_entity_state(self, entity_id, attribute=None):
        # get the current value of an entity or its attribute

        val = self._hass.states.get(entity_id)
        val = val.state
        if val is None or val == "unavailable":
            raise RuntimeError("Solaredge unavailable")
        if attribute is not None:
            val = val.attributes[attribute]

        return float(val)


class Forecasts:
    def __init__(self, hass, actuals) -> None:
        self._hass = hass
        self._actuals = actuals
        self._listeners = []
        self.history = []
        self.amber = []
        self.start_time = []
        self.solar = []
        self.consumption = []
        self.net = []
        self.battery_energy = []
        self.export = []
        self.forecast_data = None
        self.recorder = get_instance(hass)

    def add_listener(self, callback):
        """Add a listener that will be notified when the state changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        """Notify all listeners about the current state."""
        for callback in self._listeners:
            callback(self.history)

    def forecast_amber(self):
        self.forecast_data = self._hass.states.get("sensor.amber_feed_in_forecast")
        forecast = [f["per_kwh"] for f in self.forecast_data.attributes["forecasts"]]
        times = [
            self.format_date(f["start_time"])
            for f in self.forecast_data.attributes["forecasts"]
        ]
        return forecast, times

    def forecast_solar(self):
        # line up solar_forecast start time with that of the amber forecast...
        solar_forecast = []
        sfd = self._hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        if (
            sfd is not None
            and sfd.attributes is not None
            and "detailedForecast" in sfd.attributes
        ):
            sf_data = sfd.attributes["detailedForecast"]
            for index, value in enumerate(sf_data):
                if self.compare_datetimes(value["period_start"], self.start_time[0]):
                    solar_forecast = [sf["pv_estimate"] for sf in sf_data[index:]]
                    tomorrow_rows = len(self.amber) - len(solar_forecast)
                    if tomorrow_rows > 0:
                        solar_forecast = solar_forecast + [
                            sf["pv_estimate"]
                            for sf in self._hass.states.get(
                                "sensor.solcast_pv_forecast_forecast_tomorrow"
                            ).attributes["detailedForecast"][0:tomorrow_rows]
                        ]
        return solar_forecast

    async def get_yesterday_consumption(self):
        # Forecast consumption based on yesterday by querying stats database. create a new list with the consumption from yesterday matching the start time of forecast_data
        consumption = []
        solar = []
        for value in self.forecast_data.attributes["forecasts"]:
            if value["start_time"] != None:
                consumption_yesterday = (
                    await self.get_sensor_state_changes_for_fixed_period(
                        "sensor.power_consumption",
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
                    "sensor.power_solar_generation",
                    self.format_date(value["start_time"]),
                )
                net_consumption = consumption_yesterday - tesla_yesterday
                # consumption can be negative if we pick up a spike in tesla so limit to being 0.7 KW - roughly minimum house consumption
                if net_consumption < 0.7:
                    net_consumption = 0.7
                consumption.append(net_consumption)
                solar.append(solar_yesterday)

        return consumption, solar

    def forecast_battery_and_exports(self):
        # current energy in battery is the level of the battery less the unusable energy circa 10%

        battery_energy_level = self._actuals.available_battery_energy
        battery_forecast = []
        export_forecast = []
        for forecast_net_energy in self.net:
            # assume battery is charged at 5kw and discharged at 5kw and calc based on net energy upto 5kw for a half hour period ie KWH = KW/2
            battery_pct_level = battery_energy_level / self._actuals.battery_max_energy
            if battery_pct_level >= 1 and forecast_net_energy > 0:
                max_rate = 0

            elif (
                battery_pct_level > 0.9 * self._actuals.battery_max_energy
                and forecast_net_energy > 1
            ):
                # if battery is charging and over 90% then assume charging current = 1kw
                max_rate = 1
            elif forecast_net_energy > BATTERY_DISCHARGE_RATE:
                max_rate = BATTERY_DISCHARGE_RATE

            elif (
                battery_pct_level
                <= (self._actuals.battery_min_energy / self._actuals.battery_max_energy)
                and forecast_net_energy < 0
            ):
                max_rate = 0

            elif forecast_net_energy < -1 * BATTERY_DISCHARGE_RATE:
                max_rate = -1 * BATTERY_DISCHARGE_RATE

            else:
                max_rate = forecast_net_energy

            battery_energy_level = battery_energy_level + max_rate / 2

            # make sure battery never exeeds max or min
            if battery_energy_level > self._actuals.battery_max_energy:
                battery_energy_level = self._actuals.battery_max_energy
            elif battery_energy_level < self._actuals.battery_min_energy:
                battery_energy_level = self._actuals.battery_min_energy

            battery_forecast.append(battery_energy_level)
            export_forecast.append(forecast_net_energy - max_rate)

        return battery_forecast, export_forecast

    async def store_history(self):
        # store the forecast history and the actuals in a sensor

        #  history = self._hass.states.get(
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
                "amber": self.amber[6],
                "solar": self.solar[6],
                "consumption": self.consumption[6],
                "net": self.net[6],
                "battery": int(
                    self.battery_energy[6] / self._actuals.battery_max_energy * 100
                ),
                "export": self.export[6],
            }
        )
        # search for start_time in history and store actuals for that time - effectively stores the actuals versus forecast generated 3 hours ago
        for index, value in enumerate(history):
            if self.compare_datetimes(value["start_time"], self.start_time[0]):
                history[index].update(
                    {
                        "actual_consumption": self._actuals.consumption,
                        "actual_solar": self._actuals.solar,
                        "actual_battery": self._actuals.battery_pct_level,
                        "actual_export": self._actuals.feedin,
                        "actual_net": self._actuals.consumption - self._actuals.solar,
                    }
                )
                break

        self.history = history[-24:]
        self._notify_listeners()

    #  self._hass.states.async_set(
    #     "sensor.manage_energy_history", len(history), {"history": history})

    async def build(self):
        self.amber, self.start_time = self.forecast_amber()
        self.consumption, yesterday_solar = await self.get_yesterday_consumption()
        solar_forecast = self.forecast_solar()
        if len(solar_forecast) < len(self.amber):
            self.solar = yesterday_solar
        else:
            self.solar = solar_forecast
        self.net = [s - c for s, c in zip(self.solar, self.consumption)]
        self.battery_energy, self.export = self.forecast_battery_and_exports()

        await self.store_history()

    def format_date(self, std1):
        format_string = "%Y-%m-%dT%H:%M:%S%z"
        tz = timezone("Australia/Sydney")
        if not isinstance(std1, datetime.datetime):
            std1 = datetime.datetime.strptime(std1, format_string)
        std1 = std1.astimezone(tz)
        std1 = std1.replace(second=0)
        return std1

    def compare_datetimes(self, std1, std2):
        # returns true if two string format date times are the same.
        d1 = self.format_date(std1)
        d2 = self.format_date(std2)

        return d1 == d2

    def get_entity_state(self, entity_id, attribute=None):
        # get the current value of an entity or its attribute

        val = self._hass.states.get(entity_id).state

        if val is None or val == "unavailable":
            raise RuntimeError("Solaredge unavailable")
        if attribute is not None:
            val = val.attributes[attribute]

        return float(val)

    async def get_sensor_state_changes_for_fixed_period(self, entity_id, start_time):
        # Returns average sensor value for the 30 minute block yesterday from start_time
        duration_minutes = 30  # Adjust the duration as needed

        # Calculate the previous day
        previous_day = start_time - datetime.timedelta(days=1)

        # Calculate the corresponding end time
        end_time = previous_day + datetime.timedelta(minutes=duration_minutes)

        # Convert times to UTC
        start_time = previous_day.astimezone(datetime.timezone.utc)
        end_time = end_time.astimezone(datetime.timezone.utc)

        # Retrieve state changes for the sensor during the specified time period

        changes = await self.recorder.async_add_executor_job(
            state_changes_during_period, self._hass, start_time, end_time, entity_id
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
