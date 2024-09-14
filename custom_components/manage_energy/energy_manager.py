from .const import BATTERY_DISCHARGE_RATE, CURTAIL_BATTERY_LEVEL, DOMAIN, PowerSelectOptions, TeslaModeSelectOptions
import time
import logging
import datetime
import asyncio
import traceback
from pytz import timezone
from homeassistant.core import HomeAssistant, StateMachine
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.helpers.event import async_track_time_interval, async_call_later
from .forecasts import Forecasts, Actuals

_LOGGER = logging.getLogger(__name__)


class manage_energy ():
    manufacturer = "Pete"

    def __init__(self, hass: HomeAssistant, host: str, poll_frequency: int, minimum_margin: int, cheap_price: int) -> None:
        self._hass = hass
        self._state = ""

        self._listeners = []

        self._host = host
        self._name = host
        self._poll_frequency = int(poll_frequency)
        self._minimum_margin = float(minimum_margin)/100
        self._cheap_price = cheap_price/100
        self.manufacturer = "Pete"
        self._locked = False
        self._curtailment = False

        self._mode = PowerSelectOptions.AUTO
        self._tesla_mode = TeslaModeSelectOptions.AUTO
        self._id = host.lower()
        _LOGGER.info("Setting up polling for every " +
                     str(self._poll_frequency) + " seconds")
        _LOGGER.info("Minimum margin set to " +
                     str(int(self._minimum_margin*100)) + " cents")
        self._unsub_refresh = async_track_time_interval(
            self._hass, self.refresh_interval, datetime.timedelta(seconds=self._poll_frequency))
        self.actuals = Actuals(hass)
        self.forecasts = Forecasts(hass, self.actuals)


    def set_cheap_price(self, value):
        self._cheap_price = value/100

    def add_listener(self, callback):
        """Add a listener that will be notified when the state changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        """Notify all listeners about the current state."""
        for callback in self._listeners:
            callback(self)

    async def clear_status(self):
        self._state = ""
        self._notify_listeners()

    async def update_status(self, msg):

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

    async def update_poll_frequency(self, frequency):

        if self._unsub_refresh is not None:
            self._unsub_refresh()

        self._poll_frequency = frequency
        self._unsub_refresh = async_track_time_interval(
            self._hass, self.refresh_interval, datetime.timedelta(seconds=self._poll_frequency))

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
        await self._hass.services.async_call('button', 'press', {'entity_id': 'button.pete_s_tesla_force_data_update'})

        await self.refresh()

    async def tesla_charging(self, forecasts):
        _LOGGER.info("Checking whether to charge Tesla")
        # Turn Tesla charging on if the plugged in and at home.
        try: 
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

            isDemandWindow = await self.is_demand_window()
    
            if self._tesla_mode == TeslaModeSelectOptions.FAST_GRID or (self.actuals.price <= self._cheap_price and self._tesla_mode == TeslaModeSelectOptions.CHEAP_GRID and not isDemandWindow) :
                charge_amps = 16
            else:
                if self.actuals.feedin <= self._cheap_price:
                    charge_amps = round(
                        self.actuals.excess_energy * 1000 / 240 / 3, 0)
                else:
                    charge_amps = 0
    
            if tesla_plugged_in and not tesla_charger_door_closed and tesla_home:
    
                if charge_limit > current_charge and charge_amps > 0:
                    await self._hass.services.async_call('number', 'set_value', {
                        'entity_id': ' number.pete_s_tesla_charging_amps', 'value': charge_amps}, True)
                    await self._hass.services.async_call('switch', 'turn_on', {
                        'entity_id': 'switch.pete_s_tesla_charger'}, True)
                    await self.update_status("Charging Tesla at " +
                                             str(charge_amps) + " amps")
                    return True
                else:
    
                    if charge_limit <= current_charge:
                        await self.update_status(
                            "Tesla home and plugged in but charge limit reached.")
                    elif (self.actuals.price > self._cheap_price and self._tesla_mode == TeslaModeSelectOptions.CHEAP_GRID):
                        await self.update_status(
                            "Tesla home and plugged in but grid price over maximum price of " + str(self._cheap_price) + " cents.")
                    else:
                        await self.update_status(
                            "Tesla home and plugged in but Auto mode and no excess power available.")
                    await self.update_status(
                        "Turning off charging.")
                    await self._hass.services.async_call('switch', 'turn_off', {
                        'entity_id': 'switch.pete_s_tesla_charger'}, True)
                    await self._hass.services.async_call('number', 'set_value', {
                        'entity_id': ' number.pete_s_tesla_charging_amps', 'value': 16}, True)
        
            return False
        
        except Exception as e:
            await self.update_status("Error in Tesla_Charging. Error : " + str(e))
            error_message = traceback.format_exc()
    # Log the error with the traceback
            _LOGGER.error(f"Error in Tesla_Charging: {str(e)}. Traceback: {error_message}")
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

        _LOGGER.info("Charging battery from Solar")
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
        await asyncio.sleep(5)
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

    async def is_demand_window(self) -> bool:
        current_time = datetime.datetime.now().time()
        start_time = datetime.time(15, 0, 0)
        end_time = datetime.time(21, 0, 0)
        return start_time <= current_time <= end_time
    
    async def handle_manage_energy(self):
        try:
            await self.clear_status()
            await self.update_status("Runnning manage energy...")
            
            self.actuals.refresh()
            actuals = self.actuals

            forecasts = self.forecasts
            await forecasts.build()

            next5hours = forecasts.amber[0:10]
        # Assume we have 2 hours worth of discharge at 5 KW
            discharge_blocks_available = 4

        # work out when in next 5 hours we can best use available blocks of discharge
            max_values = sorted(next5hours, reverse=True)[
                :(discharge_blocks_available)]

            # get rid of max values that are less than the minimum margin
            max_values = [x for x in max_values if x > (
                min(next5hours) + self._minimum_margin)]

        # find  when high prices start
            start_high_prices = None
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
                if actuals.feedin >= (next5hours[0] + self._minimum_margin):
                    insufficient_margin = False
                else:
                    insufficient_margin = True
            else:
                # failsafe as can get abberations in data - don't discharge if current price isn't greater than the minimum margin over next 5 hours
                if actuals.feedin < (min(next5hours) + self._minimum_margin):
                    insufficient_margin = True
                # to give us how many blocks of high prices we have
                blocks_till_price_drops = end_high_prices - start_high_prices

                # recalculate actual half hour blocks of discharge available at 5kw rated energy less enough battery to cover consumption
                available_max_values = max_values
                energy_to_discharge = float(
                    actuals.available_battery_energy - sum(forecasts.consumption[0:blocks_till_price_drops - 1]))
                discharge_blocks_available = int(
                    round(energy_to_discharge/BATTERY_DISCHARGE_RATE * 2 + 0.5, 0))
                if discharge_blocks_available < 1:
                    discharge_blocks_available = 0
                if discharge_blocks_available < len(max_values):
                    available_max_values = max_values[:(
                        discharge_blocks_available)]
                # if i have less available max values then make sure current actuals included in available valuess.
                if len(available_max_values) < discharge_blocks_available and actuals.feedin >= (min(next5hours) + self._minimum_margin):
                    available_max_values.append(actuals.feedin)

        # estimate how much solar power we will have at time of peak power

            start_str = ""
            if start_high_prices != None:
                battery_at_peak = forecasts.battery_energy[start_high_prices]
                start_time = forecasts.start_time[start_high_prices]
                start_time = forecasts.format_date(start_time)
                start_str = start_time.strftime('%I:%M%p')
            await self.clear_status()
            tesla_charging = await self.tesla_charging(forecasts)
        # Now we can now make a decision if we start to feed in...

         
            isDemandWindow = await self.is_demand_window()
            
            if await self.auto_mode():
                # if i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities...
                if (actuals.available_battery_energy > actuals.battery_min_energy) and ((actuals.feedin >= (0.9 * max(next5hours[0:5]) + self._minimum_margin)) or (available_max_values != None and len(available_max_values) > 0 and actuals.feedin >= 0.9 * min(available_max_values))):
                    await self.update_status("Discharging into Price Spike")
                    await self.discharge_battery()
            # charge battery if prices rising in the next 2 hours and we will be importing energy at the end of the max period
                elif  actuals.feedin * 1.3 < max(next5hours[0:6]) and actuals.feedin <= min(next5hours[0:5]) and start_high_prices != None and end_high_prices != None and forecasts.export[end_high_prices] < 0 and actuals.battery_pct_level < 100:
                    await self.charge_battery()
                    await self.update_status(
                        "Charging battery as not enough solar & battery and prices rising at " + start_str)

                elif len(max_values) > 0 and actuals.price < ((max_values[0] *.9 )- self._minimum_margin) and battery_at_peak < actuals.battery_max_energy and actuals.battery_pct_level < 100:
                    await self.update_status("Making sure battery charged for upcoming price spike at " +
                                             start_str + " as insufficent solar to charge to peak")
                    await self.charge_battery()

                else:
                    if tesla_charging:
                        await self.charge_from_solar()
                        await self.update_status(
                            "Charging from Solar while charging Tesla")
                    else:
                        if not insufficient_margin:
                            await self.update_status(
                                "Maximising current usage. Next peak at " + start_str)
                        else:
                            await self.update_status(
                                "Maximising current usage.")
                        await self.maximise_self()

            if (not tesla_charging and actuals.battery_pct_level >= CURTAIL_BATTERY_LEVEL and actuals.feedin < 0) or self._curtailment:
                await self.curtail_solar()
                await self.update_status("Curtailing solar")
            else:
                await self.uncurtail_solar()

        except Exception as e:
            error_details = traceback.format_exc()
            await self.update_status("Error: " + str(e))
            raise RuntimeError("Error in handle_manage_energy: " + str(e))
