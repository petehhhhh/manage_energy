from .const import BATTERY_DISCHARGE_RATE, CURTAIL_BATTERY_LEVEL, DOMAIN, PowerSelectOptions, TeslaModeSelectOptions
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


class Forecasts():

    def __init__(self, hass) -> None:
        self._hass = hass
        self.available_energy = 0
        self.price = 0
        self.feedin = 0
        self.battery_level = 0
        self.usable_batttery = 0
        self.max_battery_energy = 0
        self.solar_generation = 0
        self.battery_charge_rate = 0
        self.power_consumption = 0

        self.amber = []
        self.start_time = []
        self.solar = []
        self.consumption = []
        self.net = []
        self.battery = []
        self.export = []
        self.forecast_data = self._hass.states.get(
            "sensor.amber_feed_in_forecast")
        self.recorder = get_instance(hass)
        self.get_current_state()

    def get_current_state(self):
        self.price = self.get_entity_state("sensor.amber_general_price")
        self.feedin = self.get_entity_state("sensor.amber_feed_in_price")
        self.battery_level = self.get_entity_state(
            "sensor.solaredge_b1_state_of_energy")
        self.usable_batttery = self.get_entity_state(
            "sensor.solaredge_b1_available_energy")
        self.max_battery_energy = self.get_entity_state(
            "sensor.solaredge_b1_maximum_energy")
        self.solar_generation = self.get_entity_state(
            "sensor.power_solar_generation")
        self.battery_charge_rate = self.get_entity_state(
            "sensor.solaredge_b1_dc_power")
        self.power_consumption = self.get_entity_state(
            "sensor.power_consumption")

    def forecast_amber(self):

        forecast = [f['per_kwh']
                    for f in self.forecast_data.attributes["forecasts"]]
        times = [f['start_time']
                 for f in self.forecast_data.attributes["forecasts"]]
        return forecast, times

    def forecast_solar(self):

        # line up solar_forecast start time with that of the amber forecast...
        solar_forecast = []
        sfd = self._hass.states.get(
            "sensor.solcast_pv_forecast_forecast_today")
        if 'detailedForecast' in sfd.attributes:
            sf_data = sfd.attributes["detailedForecast"]
            for index, value in enumerate(sf_data):
                if self.compare_datetimes(value["period_start"], self.start_time[0]):
                    solar_forecast = [sf['pv_estimate']
                                      for sf in sf_data[index:]]
                    tomorrow_rows = len(self.amber) - len(solar_forecast)
                    if tomorrow_rows > 0:
                        solar_forecast = solar_forecast + [sf['pv_estimate'] for sf in self._hass.states.get(
                            "sensor.solcast_pv_forecast_forecast_tomorrow").attributes["detailedForecast"][0: tomorrow_rows]]
        return solar_forecast

    async def get_yesterday(self):
        # Forecast consumption based on yesterday by querying stats database. create a new list with the consumption from yesterday matching the start time of forecast_data
        consumption = []
        solar = []
        for value in (self.forecast_data.attributes["forecasts"]):
            if value["start_time"] != None:
                consumption_yesterday = await self.get_sensor_state_changes_for_fixed_period(
                    'sensor.power_consumption', self.format_date(value["start_time"]))
                solar_yesterday = await self.get_sensor_state_changes_for_fixed_period(
                    'sensor.power_solar_generation', self.format_date(value["start_time"]))
                consumption.append(consumption_yesterday)
                solar.append(solar_yesterday)
        return consumption, solar

    def forecast_battery_and_exports(self):

        # current energy in battery is the level of the battery less the unusable energy circa 10%
        self.available_energy = (self.max_battery_energy * self.battery_level /
                                 100) - (self.max_battery_energy - self.usable_batttery)
        battery_level = self.available_energy
        battery_forecast = []
        export_forecast = []
        for val in self.net:
            # assume battery is charged at 5kw and discharged at 5kw and calc based on net energy upto 5kw for a half hour period ie KWH = KW/2

            if battery_level >= 100 and val > 0:
                max_rate = 0

            elif battery_level > .9 * self.max_battery_energy and val > 1:
                # if battery is charging and over 90% then assume charging current = 1kw
                max_rate = 1
            elif val > BATTERY_DISCHARGE_RATE:
                max_rate = BATTERY_DISCHARGE_RATE

            elif battery_level <= (self.usable_batttery/self.max_battery_energy) and val < 0:
                max_rate = 0

            elif val < -1 * BATTERY_DISCHARGE_RATE:
                max_rate = -1 * BATTERY_DISCHARGE_RATE

            else:
                max_rate = val

            battery_level = battery_level + max_rate/2
            battery_forecast.append(battery_level)
            export_forecast.append(val - max_rate)

        return battery_forecast, export_forecast

    def store_history(self):
        # store the forecast history and the actuals in a sensor
        history = self._hass.states.get("manage_energy.forecast_history")
        if history is None:
            history = []
        else:
            history = history.attributes["history"]

        # check if have history record for this start time before adding it
        if len(history) > 0:
            if self.compare_datetimes(self.start_time[0], history[-1]["start_time"]):
                # remove the last record and replace with the new one
                history.pop()

        history.append({"start_time": self.start_time[0], "amber": self.amber[0], "solar": self.solar[0],
                       "consumption": self.consumption[0], "net": self.net[0], "battery": self.battery[0], "export": self.export[0]})
        # keep the last 24 hours of history
        history = history[-24:]
        self._hass.states.async_set(
            "manage_energy.forecast_history", len(history), {"history": history})

    async def build(self):

        self.amber, self.start_time = self.forecast_amber()
        self.consumption, yesterday_solar = await self.get_yesterday()
        solar_forecast = self.forecast_solar()
        if len(solar_forecast) < len(self.amber):
            self.solar = yesterday_solar
        else:
            self.solar = solar_forecast
        self.net = [s - c for s, c in zip(self.solar, self.consumption)]
        self.battery, self.export = self.forecast_battery_and_exports()

    def format_date(self, std1):
        format_string = "%Y-%m-%dT%H:%M:%S%z"
        tz = timezone('Australia/Sydney')
        if not isinstance(std1, datetime.datetime):
            std1 = datetime.datetime.strptime(std1, format_string)
        std1 = std1.astimezone(tz)
        std1 = std1.replace(second=0)
        return std1

    def compare_datetimes(self, std1, std2):
        # returns true if two string format date times are the same.
        d1 = self.format_date(std1)
        d2 = self.format_date(std2)

        return (d1 == d2)

    def get_entity_state(self, entity_id, attribute=None):
        # get the current value of an entity or its attribute

        val = (self._hass.states.get(entity_id).state)

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
        end_time = previous_day + \
            datetime.timedelta(minutes=duration_minutes)

        # Convert times to UTC
        start_time = previous_day.astimezone(datetime.timezone.utc)
        end_time = end_time.astimezone(datetime.timezone.utc)

        # Retrieve state changes for the sensor during the specified time period

        changes = await self.recorder.async_add_executor_job(
            state_changes_during_period, self._hass, start_time, end_time, entity_id)
        vals = []
        for f in changes[entity_id]:
            # if f.state is a valid float value add it to the list of values
            try:
                vals.append(float(f.state))
            except:
                continue
        if len(vals) == 0:
            avg = 0
        else:
            avg = sum(vals) / len(vals)

        return round(avg, 2)
