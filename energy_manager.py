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
from .decide import (
    Should_i_charge_as_not_enough_solar,
    ShouldIDischarge,
    ShouldIChargeforPriceSpike,
    PreserveWhileTeslaCharging,
    MaximiseUsage,
)
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .forecasts import Forecasts, Actuals, is_demand_window
from .tesla import TeslaCharging
from .analyse import Analysis

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

    def update_status(self, msg):
        """Write a status msg to status field and log it."""
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

    def set_mode(self, mode):
        old_mode = self._mode
        self._mode = mode
        if old_mode != mode:
            self._notify_listeners()

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
        """Maing method in Manage_Energy."""
        try:
            if self._running:
                return
            self._running = True
            await self.clear_status()
            self.update_status("Runnning manage energy...")

            self.actuals.refresh()
            actuals = self.actuals

            forecasts = self.forecasts
            await forecasts.build()

            a = Analysis(forecasts, actuals, self)
            a.analyze_price_peaks()

            await self.clear_status()
            tesla = TeslaCharging(self)

            self.tesla_charging = await tesla.tesla_charging(forecasts)
            # Now we can now make a decision if we start to feed in...

            # lambda functions allow to load into an array of rules. Rules are defined in decide.py
            if self._auto:
                rules = [
                    lambda: ShouldIDischarge(a).run(
                        PowerSelectOptions.DISCHARGE, "Discharging into Price Spike"
                    ),
                    lambda: Should_i_charge_as_not_enough_solar(a).run(
                        PowerSelectOptions.CHARGE, "Charging as cheaper now."
                    ),
                    lambda: ShouldIChargeforPriceSpike(a).run(
                        PowerSelectOptions.CHARGE,
                        "Charging for price spike at " + a.peak_start_str,
                    ),
                    lambda: PreserveWhileTeslaCharging(a).run(
                        PowerSelectOptions.OFF, "Preserving charge"
                    ),
                    lambda: MaximiseUsage(a).run(
                        PowerSelectOptions.MAXIMISE, "Maximising usage"
                    ),
                ]
                # and will run one by one, stopping when the first is succesful. The last maximise usage is always successful.
                for rule in rules:
                    if rule():
                        break

            if (
                not self.tesla_charging
                and actuals.battery_pct_level >= CURTAIL_BATTERY_LEVEL
                and actuals.feedin < 0
            ):
                await self.curtail_solar()
                self.update_status("Curtailing solar")
            else:
                await self.uncurtail_solar()

        except Exception as e:
            error_details = traceback.format_exc()
            self.update_status("Error: " + str(e))
            raise RuntimeError("Error in handle_manage_energy: " + str(e))
        finally:
            self._running = False
