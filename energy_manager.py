from .const import (
    BATTERY_DISCHARGE_RATE,
    CURTAIL_BATTERY_LEVEL,
    DOMAIN,
    PowerSelectOptions,
    MAX_BATTERY_LEVEL,
    TeslaModeSelectOptions,
)

import logging
import datetime
import traceback
from pytz import timezone
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .forecasts import Forecasts, Actuals, is_demand_window
from .tesla import TeslaCharging

_LOGGER = logging.getLogger(__name__)


class manage_energy:
    manufacturer = "Pete"

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        poll_frequency: int,
        minimum_margin: int,
        cheap_price: int,
    ) -> None:
        self._hass = hass
        self._state = ""

        self._listeners = []
        self._running = False

        self._host = host
        self._name = host
        self._poll_frequency = int(poll_frequency)
        self.minimum_margin = float(minimum_margin) / 100
        self._cheap_price = cheap_price / 100
        self.manufacturer = "Pete"
        self._locked = False
        self._curtailment = False
        self._auto = True
        self._tesla_amps = 0

        self._mode = PowerSelectOptions.MAXIMISE
        self._tesla_mode = TeslaModeSelectOptions.AUTO
        self._id = host.lower()
        _LOGGER.info(
            "Setting up polling for every " + str(self._poll_frequency) + " seconds"
        )
        _LOGGER.info(
            "Minimum margin set to " + str(int(self.minimum_margin)) + " cents"
        )
        self._unsub_refresh = async_track_time_interval(
            self._hass,
            self.refresh_interval,
            datetime.timedelta(seconds=self._poll_frequency),
        )
        self.actuals = Actuals(self)
        self.forecasts = Forecasts(self)

    def set_cheap_price(self, value):
        self._cheap_price = value / 100

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
    def hass(self):
        """Hass object."""
        return self._hass

    @property
    def curtailment(self) -> bool:
        """Curtail solar."""
        return self._curtailment

    @property
    def state(self) -> str:
        """Current state of Manage Energy."""
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
            self._hass,
            self.refresh_interval,
            datetime.timedelta(seconds=self._poll_frequency),
        )

    async def stop_poll(self):
        if self._unsub_refresh is not None:
            self._unsub_refresh()

    async def set_solar_curtailment(self, state):
        self._curtailment = state
        await self.refresh()

    async def get_solar_curtailment(self):
        return self._curtailment

    def get_auto(self):
        return self._auto

    async def set_auto(self, state):
        self._auto = state
        await self.refresh()

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
        old_mode = self._mode
        self._mode = mode
        if old_mode != mode:
            self._notify_listeners()
            await self.refresh()

    def get_mode(self) -> str:
        return self._mode

    async def discharge_battery(self):
        _LOGGER.info("Discharging battery")
        await self.set_mode(PowerSelectOptions.DISCHARGE)

    async def preserve_battery(self):
        _LOGGER.info("Preserving battery - top up from Solar if available")
        await self.set_mode(PowerSelectOptions.OFF)

    async def charge_battery(self):
        _LOGGER.info("Charging battery")
        await self.set_mode(PowerSelectOptions.CHARGE)

    async def curtail_solar(self):
        _LOGGER.info("Curtailing solar")

    async def maximise_self(self):
        _LOGGER.info("Maximising self consumption")
        await self.set_mode(PowerSelectOptions.MAXIMISE)

    async def uncurtail_solar(self):
        _LOGGER.info("Uncurtailing Solar")

    async def auto_mode(self) -> bool:
        if self._auto:
            return True
        elif self._mode == PowerSelectOptions.DISCHARGE:
            await self.discharge_battery()
            await self.update_status("Override: Discharging Battery")
        elif self._mode == PowerSelectOptions.CHARGE:
            await self.charge_battery()
            await self.update_status("Override: Charging Battery")
        elif self._mode == PowerSelectOptions.MAXIMISE:
            await self.maximise_self()
            await self.update_status("Override: Maximising Self")
        elif self._mode == PowerSelectOptions.OFF:
            await self.battery_off()
            await self.update_status("Override: Solar only - Battery Off")

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

    def should_i_charge_as_not_enough_solar(self) -> bool:
        """Works out whether now is a good time to charge battery if going to be importing in the next forecast window."""
        actuals = self.actuals
        FORECAST_WINDOW = 24
        # half an hour blocks it will take to charge...
        blocks_to_charge = (
            int(
                round(
                    (1 - (actuals.battery_pct_level / 100))
                    * actuals.battery_max_usable_energy
                    / BATTERY_DISCHARGE_RATE,
                    0,
                )
            )
            * 2
        )
        # If my battery level is not going to hit 100... or i am going to be importing power before it does
        # and power cheap now. Top up..
        battery_charged = next(
            (
                i
                for i, num in enumerate(self.forecasts.battery_energy)
                if num >= self.actuals.battery_max_energy
            ),
            None,
        )
        firstgridimport = next(
            (i for i, num in enumerate(self.forecasts.export) if num < 0), None
        )

        # if battery will be charged before we next import power, don't charge
        if firstgridimport is None or (
            (battery_charged is not None and firstgridimport > battery_charged)
            or actuals.battery_pct_level >= MAX_BATTERY_LEVEL
            or is_demand_window(datetime.datetime.now())
        ):
            return False

        if battery_charged is None or firstgridimport < battery_charged:
            first_no_grid_export = None
            for i, num in enumerate(self.forecasts.export):
                if num >= 0 and i > firstgridimport:
                    first_no_grid_export = i
                    break

        # else check for the blocks up to when it will be charged or for the entire window.

        if battery_charged is None or first_no_grid_export is None:
            blocks_to_check = FORECAST_WINDOW
        else:
            blocks_to_check = first_no_grid_export

        # find when next higher price is coming...
        first_higher_price = None
        for i, num in enumerate(self.forecasts.amber_scaled_price):
            if num * 0.9 > actuals.scaled_price:
                first_higher_price = i
                break
        # if i have a higher price upcoming that i will need to import for, check whether this is a good time...
        if (
            first_higher_price is not None
            and first_higher_price < blocks_to_check
            and first_higher_price < first_no_grid_export
        ):
            blocks_to_check = first_higher_price

        blocks_to_charge = min(blocks_to_check + 1, blocks_to_charge)

        if blocks_to_check == 0:
            if actuals.scaled_price < 0.9 * self.forecasts.amber_scaled_price[0]:
                return True
        else:
            if actuals.scaled_price <= max(
                sorted(self.forecasts.amber_scaled_price[0 : blocks_to_check - 1])[
                    : blocks_to_charge - 1
                ]
            ):
                return True

        # also check whether prices will be higher when we don't have enough power

        return False

    async def handle_manage_energy(self):
        try:
            if self._running:
                return
            self._running = True
            await self.clear_status()
            await self.update_status("Runnning manage energy...")

            self.actuals.refresh()
            actuals = self.actuals

            forecasts = self.forecasts
            await forecasts.build()
            TTL_FORECAST_BLOCKS = 24
            next12hours = forecasts.amber_feed_in[0:TTL_FORECAST_BLOCKS]

            discharge_blocks_available = (
                int(
                    round(actuals.battery_max_usable_energy / BATTERY_DISCHARGE_RATE, 0)
                )
                * 2
            )

            # work out when in next 12 hours we can best use available blocks of discharge
            max_values = sorted(next12hours, reverse=True)[
                :(discharge_blocks_available)
            ]

            # get rid of max values that are less than the minimum margin
            max_values = [
                x for x in max_values if x > (min(next12hours) + self.minimum_margin)
            ]

            # find  when high prices start
            start_high_prices = None
            for index, value in enumerate(next12hours):
                if value in max_values:
                    start_high_prices = index
                    break

            # now find the first entry that has the minimum margin to export to grid. Trim the max values to ensure there is sufficient margin
            insufficient_margin = True
            end_high_prices = None
            for index1, value1 in enumerate(max_values):
                end_high_prices = None
                for index, value in enumerate(next12hours):
                    # if this entry is after the start of high prices and it is less than this value less required margin...
                    if (index > start_high_prices) and (
                        (value + self.minimum_margin) <= value1
                    ):
                        end_high_prices = index
                        insufficient_margin = False
                        break

                if index1 == 0 and end_high_prices is None:
                    # the max value in the array has too little margin
                    break
                elif end_high_prices is None:  # noqa: RET508
                    # the last value in the max series doesn't have enough margin. Probably shouldnt happen as check above...
                    max_values = max_values[:(index1)]
                    end_high_prices = last_end_high_prices
                    insufficient_margin = False
                    break

                last_end_high_prices = end_high_prices

            # if we didn't find one then check that the current price is the tail of the peak
            available_max_values = None
            if end_high_prices is None:
                if actuals.feedin >= (next12hours[0] + self.minimum_margin):
                    insufficient_margin = False
                else:
                    insufficient_margin = True
            else:
                # failsafe as can get abberations in data - don't discharge if current price isn't greater than the minimum margin over next 5 hours
                if actuals.feedin < (min(next12hours) + self.minimum_margin):
                    insufficient_margin = True
                # to give us how many blocks of high prices we have
                blocks_till_price_drops = end_high_prices - start_high_prices

                # recalculate actual half hour blocks of discharge available less enough battery to cover consumption
                available_max_values = max_values
                energy_to_discharge = float(
                    actuals.available_battery_energy
                    - sum(forecasts.consumption[0 : blocks_till_price_drops - 1])
                )
                discharge_blocks_available = int(
                    round(energy_to_discharge / BATTERY_DISCHARGE_RATE * 2 + 0.5, 0)
                )
                if discharge_blocks_available < 1:
                    discharge_blocks_available = 0
                if discharge_blocks_available < len(max_values):
                    available_max_values = max_values[:(discharge_blocks_available)]
                # if i have less available max values then make sure current actuals included in available valuess.
                if len(
                    available_max_values
                ) < discharge_blocks_available and actuals.feedin >= (
                    min(next12hours) + self.minimum_margin
                ):
                    available_max_values.append(actuals.feedin)

            # estimate how much solar power we will have at time of peak power

            start_str = ""
            if start_high_prices != None:
                battery_at_peak = forecasts.battery_energy[start_high_prices]
                start_time = forecasts.start_time[start_high_prices]
                start_time = forecasts.format_date(start_time)
                start_str = start_time.strftime("%I:%M%p")
            await self.clear_status()

            tesla = TeslaCharging(self)

            tesla_charging = await tesla.tesla_charging(forecasts)
            # Now we can now make a decision if we start to feed in...

            # scaled minimum margin to avoid eg charging at $15 when it is forecast to be $15.50... High risk of disappointment...
            if actuals.feedin > 0.5:
                scaled_min_margin = self.minimum_margin / 0.20 * actuals.feedin
            else:
                scaled_min_margin = self.minimum_margin

            if self._auto:
                # if i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities...
                if (actuals.available_battery_energy > actuals.battery_min_energy) and (
                    (
                        # if it is currently 90% of the maximum forecsated and there is acceptable margin then take it !
                        actuals.feedin
                        >= (0.9 * float(max(next12hours[0:10]) + scaled_min_margin))
                    )
                    or (
                        # otherwise if it is moire than the max values (that already are calced with minimum margin)
                        available_max_values != None
                        and len(available_max_values) > 0
                        and actuals.feedin >= 0.9 * min(available_max_values)
                    )
                ):
                    await self.update_status("Discharging into Price Spike")
                    await self.discharge_battery()

                elif self.should_i_charge_as_not_enough_solar():
                    await self.charge_battery()
                    await self.update_status(
                        "Charging battery as cheaper time to charge."
                    )

                elif (
                    len(max_values) > 0
                    and actuals.scaled_price + scaled_min_margin < (max_values[0] * 0.9)
                    and battery_at_peak < actuals.battery_max_energy
                    and actuals.battery_pct_level < MAX_BATTERY_LEVEL
                ):
                    await self.update_status(
                        "Making sure battery charged for upcoming price spike at "
                        + start_str
                    )
                    await self.charge_battery()

                elif tesla_charging:
                    await self.preserve_battery()
                    await self.update_status("Charging from Solar while charging Tesla")

                else:
                    if not insufficient_margin:
                        await self.update_status(
                            "Maximising current usage. Next peak at " + start_str
                        )
                    else:
                        await self.update_status("Maximising current usage.")
                    await self.maximise_self()

            if (
                not tesla_charging
                and actuals.battery_pct_level >= CURTAIL_BATTERY_LEVEL
                and actuals.feedin < 0
            ):
                await self.curtail_solar()
                await self.update_status("Curtailing solar")
            else:
                await self.uncurtail_solar()

        except Exception as e:
            error_details = traceback.format_exc()
            await self.update_status("Error: " + str(e))
            raise RuntimeError("Error in handle_manage_energy: " + str(e))
        finally:
            self._running = False
