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


class manage_energy ():
    manufacturer = "Pete"

    def __init__(self, hass: HomeAssistant, host: str, poll_frequency: int, minimum_margin: int, cheap_price: int) -> None:
        self._hass = hass
        self._state = ""
        self._listeners = []
        self.clear_state()

        self._host = host
        self._name = host
        self._poll_frequency = int(poll_frequency)
        self._minimum_margin = float(minimum_margin)/100
        self._cheap_price = cheap_price/100
        self._price = 0
        self.manufacturer = "Pete"
        self._locked = False
        self._curtailment = False

        self._mode = PowerSelectOptions.AUTO
        self._tesla_mode = TeslaModeSelectOptions.AUTO
        self._id = host.lower()
        self._recorder = get_instance(hass)
        _LOGGER.info("Setting up polling for every " +
                     str(self._poll_frequency) + " seconds")
        _LOGGER.info("Minimum margin set to " +
                     str(int(self._minimum_margin*100)) + " cents")
        self._unsub_refresh = async_track_time_interval(
            self._hass, self.refresh_interval, datetime.timedelta(seconds=self._poll_frequency))
        # self._recorder = get_instance(hass)

    def add_listener(self, callback):
        """Add a listener that will be notified when the state changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        """Notify all listeners about the current state."""
        for callback in self._listeners:
            callback(self.state)

    def clear_state(self):
        self._state = ""
        self._notify_listeners()

    async def update_state(self, msg):

        msg = msg.strip()
        if msg[-1] != ".":  # add a full stop if not there
            msg = msg + "."

        if self._state == "":
            self._state = msg
        else:
            self._state = self._state + " " + msg

        _LOGGER.info(msg)
        self._notify_listeners()

    @property
    def state(self) -> str:
        return self._state

    @property
    def hub_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    async def stop_poll(self):
        if self._unsub_refresh is not None:
            self._unsub_refresh()

    async def set_solar_curtailment(self, state):
        self._curtailment = state
        await self.refresh()

    async def get_solar_curtailment(self):
        return self._curtailment

    async def async_will_remove_from_hass(self):
        if self._unsub_refresh is not None:
            self._unsub_refresh()

    async def refresh(self):

        if not self._locked:
            self._locked = True
            try:
                await self.handle_manage_energy()
            finally:
                self._locked = False

    async def refresh_proxy(self, now):
        await self.refresh()

    async def refresh_interval(self, now):
        #    async_call_later(self._hass, 2, self.refresh_proxy)
        await self.refresh()

    async def set_mode(self, mode):
        self._mode = mode
        await self.refresh()

    async def set_tesla_mode(self, mode):
        self._tesla_mode = mode
        await self.refresh()

    async def tesla_charging(self, available_power):
        _LOGGER.info("Checking whether to charge Tesla")
        # Turn Tesla charging on if the plugged in and at home.
        tesla_plugged_in = (self._hass.states.get(
            "binary_sensor.pete_s_tesla_charger").state == 'on')
        tesla_home = (self._hass.states.get(
            "device_tracker.tesla").state == 'home')
        charge_limit = int(self._hass.states.get(
            "number.pete_s_tesla_charge_limit").state)
        current_charge = int(self._hass.states.get(
            "sensor.pete_s_tesla_battery").state)
        # check  pete_s_tesla_charger_door is closed
        tesla_door = self._hass.states.get(
            "cover.pete_s_tesla_charger_door").state
        tesla_charger_door_closed = (self._hass.states.get(
            "cover.pete_s_tesla_charger_door").state == 'closed')

        if self._tesla_mode == TeslaModeSelectOptions.FAST_GRID or (self._price <= self._cheap_price and self._tesla_mode == TeslaModeSelectOptions.CHEAP_GRID):
            charge_amps = 16
        else:
            charge_amps = round(available_power*1000 / 240 / 3, 0)

        if tesla_plugged_in and not tesla_charger_door_closed and tesla_home and charge_limit > current_charge and charge_amps > 0:
            self._hass.services.call('number', 'set_value', {
                'entity_id': ' number.pete_s_tesla_charging_amps', 'value': charge_amps}, True)
            self._hass.services.call('switch', 'turn_on', {
                'entity_id': 'switch.pete_s_tesla_charger'}, True)
            self.update_state("Charging Tesla at " +
                              str(charge_amps) + " amps")
            return True
        else:
            if tesla_home and tesla_plugged_in and tesla_charger_door_closed:
                if charge_amps <= 0:
                    self.update_state(
                        "Tesla home and plugged in but no available power. Turning off charging")
                else:
                    if tesla_home and not tesla_charger_door_closed and tesla_plugged_in and charge_limit > current_charge:
                        self.update_state(
                            "Tesla home and plugged in but charge limit reached. Turning off charging")
                    else:
                        _LOGGER.info(
                            "Tesla not plugged in. Turning off charging")

                await self._hass.services.async_call('switch', 'turn_off', {
                    'entity_id': 'switch.pete_s_tesla_charger'}, True)
                await self._hass.services.async_call('number', 'set_value', {
                    'entity_id': ' number.pete_s_tesla_charging_amps', 'value': 16}, True)
            return False

    async def discharge_battery(self):

        _LOGGER.info("Discharging battery")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_control_mode',
            'option': 'Remote Control'}, True)
        await asyncio.sleep(5)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_default_mode',
            'option': 'Discharge to Maximize Export'}, True)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_command_mode',
            'option': 'Discharge to Maximize Export'}, True)

    async def preserve_battery(self):

        _LOGGER.info("Preserving battery - top up from Solar if available")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_control_mode',
            'option': 'Remote Control'}, True)
        await asyncio.sleep(5)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_default_mode',
            'option': 'Charge from Solar Power'}, True)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_command_mode',
            'option': 'Charge from Solar Power'}, True)

    async def charge_battery(self):

        _LOGGER.info("Charging battery")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_control_mode',
            'option': 'Remote Control'}, True)
        await asyncio.sleep(5)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_default_mode',
            'option': 'Charge from Solar Power and Grid'}, True)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_command_mode',
            'option': 'Charge from Solar Power and Grid'}, True)

    async def charge_from_solar(self):

        _LOGGER.info("Charging battery")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_control_mode',
            'option': 'Remote Control'}, True)
        await asyncio.sleep(5)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_default_mode',
            'option': 'Charge from Solar Power'}, True)
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_command_mode',
            'option': 'Charge from Solar Power'}, True)

    async def curtail_solar(self):
        _LOGGER.info("Curtailing solar")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_limit_control_mode',
            'option': 'Export Control (Export/Import Meter)'}, True)
        time.asyncio.sleep(5)
        await self._hass.services.async_call('number', 'set_value', {
            'entity_id': 'number.solaredge_i1_site_limit', 'value': '0'}, True)

    async def maximise_self(self):

        _LOGGER.info("Maximising self consumption")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_storage_control_mode',
            'option': 'Maximize Self Consumption'}, True)

    async def uncurtail_solar(self):

        _LOGGER.info("Uncurtailing Solar")
        await self._hass.services.async_call('select', 'select_option', {
            'entity_id': 'select.solaredge_i1_limit_control_mode',
            'option': 'Disabled'}, True)

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
        recorder = get_instance(self._hass)
        changes = await recorder.async_add_executor_job(
            state_changes_during_period, self._hass, start_time, end_time, entity_id)
        vals = []
        for f in changes['sensor.power_consumption']:
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

    async def auto_mode(self) -> bool:

        if self._mode == PowerSelectOptions.AUTO:
            return True
        elif self._mode == PowerSelectOptions.DISCHARGE:
            await self.discharge_battery()
        elif self._mode == PowerSelectOptions.CHARGE:
            await self.charge_battery()
        elif self._mode == PowerSelectOptions.MAXIMISE:
            await self.maximise_self()

        return False

    async def tesla_mode(self) -> bool:

        if self._mode == TeslaModeSelectOptions.AUTO:
            return True
        elif self._mode == TeslaModeSelectOptions.CHEAP_GRID:
            await self.discharge_battery()
        elif self._mode == TeslaModeSelectOptions.FAST_GRID:
            await self.charge_battery()
        elif self._mode == PowerSelectOptions.MAXIMISE:
            await self.maximise_self()

        return False

    async def handle_manage_energy(self):
        try:
            self.clear_state()
            time_of_day = datetime.datetime.now()  # Adjust the time as needed
            avg = await self.get_sensor_state_changes_for_fixed_period(
                'sensor.power_consumption', time_of_day)

            _LOGGER.info("Average for prior day is " + str(avg))
            forecast_data = self._hass.states.get(
                "sensor.amber_feed_in_forecast")
        #   forecasts = forecast.attributes["forecasts"][0]['per_kwh']
            forecast = [f['per_kwh']
                        for f in forecast_data.attributes["forecasts"]]
            next5hours = forecast[0:10]
            sfd = self._hass.states.get(
                "sensor.solcast_pv_forecast_forecast_today")
            sf_data = sfd.attributes["detailedForecast"]

        # line up solar_forecast start time with that of the amber forecast...
            solar_forecast = []
            for index, value in enumerate(sf_data):
                if self.compare_datetimes(value["period_start"], forecast_data.attributes["forecasts"][0]["start_time"]):
                    solar_forecast = [sf['pv_estimate']
                                      for sf in sf_data[index:]]
                    tomorrow_rows = len(forecast) - len(solar_forecast)
                    if tomorrow_rows > 0:
                        solar_forecast = solar_forecast + [sf['pv_estimate'] for sf in self._hass.states.get(
                            "sensor.solcast_pv_forecast_forecast_tomorrow").attributes["detailedForecast"][0: tomorrow_rows]]

            # create a new list with the consumption from yesterday matching the start time of forecast_data
    #      consumption_forecast = []
    #       for value in (forecast_data.attributes["forecasts"]):
    #           if value["start_time"] != None:
    #                consumption_forecast.append(
    #                    self.get_sensor_state_changes_for_fixed_period('sensor.power_consumption', self.format_date(value["start_time"])))
    #        _LOGGER.info("Consumption forecast is " + str(consumption_forecast))
            self._price = float(self._hass.states.get(
                "sensor.amber_general_price").attributes["per_kwh"])
            feedin = float(self._hass.states.get(
                "sensor.amber_feed_in_price").attributes["per_kwh"])
            battery_level_state = self._hass.states.get(
                "sensor.solaredge_b1_state_of_energy")
            if battery_level_state is None or battery_level_state.state == "unavailable":
                raise RuntimeError("Solaredge unavailable")
            battery_level = float(battery_level_state.state)
            usable = float(self._hass.states.get(
                "sensor.solaredge_b1_available_energy").state)
            max_energy = float(self._hass.states.get(
                "sensor.solaredge_b1_maximum_energy").state)
            solar_generation = float(self._hass.states.get(
                "sensor.power_solar_generation").state)
            battery_charge_rate = float(self._hass.states.get(
                "sensor.solaredge_b1_dc_power").state)

    # energy in battery is the level of the battery less the unusable energy circa 10%
            available_energy = (max_energy * battery_level /
                                100) - (max_energy - usable)
            consumption = float(self._hass.states.get(
                "sensor.power_consumption").state)

    # Assume we have 2 hours worth of discharge at 5 KW
            discharge_blocks_available = 4

    # work out when in next 5 hours we can best use available blocks of discharge
            max_values = sorted(next5hours, reverse=True)[
                :(discharge_blocks_available)]

    # find  when high prices start
            for index, value in enumerate(next5hours):
                if value in max_values:
                    start_high_prices = index
                    break

            # now find the first entry that is 0.2 less than this - this is the minimum margin to export to grid. Trim the max values to ensure there is sufficient margin
            insufficient_margin = True
            end_high_prices = None
            for index1, value1 in enumerate(max_values):
                end_high_prices = None
                for index, value in enumerate(next5hours):
                    # if this entry is after the start of high prices and it is less than this value less required margin...
                    if (index > start_high_prices) and (value <= (value1 - self._minimum_margin)):
                        end_high_prices = index
                        insufficient_margin = False
                        break

                if index1 == 0 and end_high_prices == None:
                    # the max value in the array has too little margin
                    break
                elif end_high_prices == None:
                    # the last value in the max series doesn't have enough margin. Probably shouldnt happen as check above...
                    max_values = max_values[:(index1)]
                    end_high_prices = last_end_high_prices
                    insufficient_margin = False
                    break
                last_end_high_prices = end_high_prices

            # if we didn't find one then check that the current price is the tail of the peak
            available_max_values = None
            if end_high_prices == None:
                if feedin >= (next5hours[0] + self._minimum_margin):
                    insufficient_margin = False
                else:
                    insufficient_margin = True
            else:
                # to give us how many blocks of high prices we have
                blocks_till_price_drops = end_high_prices - start_high_prices

                # recalculate actual half hour blocks of discharge available at 5kw rated energy less enough battery to cover consumption
                available_max_values = max_values
                discharge_blocks_available = int(round(
                    (available_energy - (blocks_till_price_drops * (consumption/2))) / ((BATTERY_DISCHARGE_RATE - consumption)/2), 0))
            # and then trim the max values block to just enough to ensure we preserve enough energy for peak period consumption
                if discharge_blocks_available < 1:
                    discharge_blocks_available = 0
                if discharge_blocks_available < len(max_values):
                    available_max_values = max_values[:(
                        discharge_blocks_available)]

    # estimate how much solar power we will have at time of peak power
            battery_at_peak = available_energy + \
                sum(solar_forecast[0:start_high_prices]) - \
                (consumption * start_high_prices)
            start_str = ""
            if start_high_prices != None:
                start_time = forecast_data.attributes['forecasts'][start_high_prices]['start_time']
                start_time = self.format_date(start_time)
                start_str = start_time.strftime('%I:%M%p')
            available_power = solar_generation - consumption - battery_charge_rate
            tesla_charging = await self.tesla_charging(available_power)
    # Now we can now make a decision if we start to feed in...
            if await self.auto_mode():
                if discharge_blocks_available > 0 and available_max_values != None and (feedin >= min(available_max_values) and not insufficient_margin):
                    await self.update_state("Discharging battery into Price Spike")
                    await self.discharge_battery()

                elif feedin * 1.2 < max(next5hours[0:5]) and feedin <= min(next5hours[0:5]) and consumption * 4 > (available_energy + sum(solar_forecast[0:3])) and battery_level < 100:
                    await self.charge_battery()
                    await self.update_state(
                        "Charging battery as not enough solar & battery and prices rising at" + start_str)

                elif self._price < (max_values[0] - self._minimum_margin) and battery_at_peak < max_energy and battery_level < 100:
                    await self.update_state("Making sure battery charged for upcoming price spike at " +
                                            start_str + " as insufficent solar to charge to peak")
                    await self.charge_battery()

                else:
                    if tesla_charging:
                        await self.charge_from_solar()
                        await self.update_state(
                            "Charging from Solar while charging Tesla")
                    else:
                        if not insufficient_margin:
                            await self.update_state(
                                "Maximising current usage. Next peak at " + start_str)
                        else:
                            await self.update_state(
                                "Maximising current usage. No useful peak in next 5 hours")
                        await self.maximise_self()

            if (not tesla_charging and battery_level >= CURTAIL_BATTERY_LEVEL and feedin < 0) or self._curtailment:
                await self.curtail_solar()
                await self.update_state("Curtailing solar")
            else:
                await self.uncurtail_solar()

        except Exception as e:
            error_details = traceback.format_exc()
            await self.update_state("Error: " + str(e))
            raise RuntimeError("Error in handle_manage_energy: " + str(e))
