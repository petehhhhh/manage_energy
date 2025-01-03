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
from homeassistant.helpers.storage import Store
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .forecasts import Forecasts, is_demand_window
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
    ) -> None:
        self._hass = hass
        self._state = ""

        self._listeners = []
        self._running = False

        self._host = host
        self._name = host
        self._poll_frequency = int(poll_frequency)
        self.minimum_margin = float(minimum_margin) / 100
        self.cheap_price = 0.04
        self.manufacturer = "Pete"
        self._locked = False
        self._curtailment = False
        self._auto = True
        self.tesla = TeslaCharging(self)

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
        self.forecasts = Forecasts(self)

    @property
    def cheap_price(self) -> str:
        """Current state of Manage Energy."""
        return self._cheap_price

    @cheap_price.setter
    def cheap_price(self, value: float):
        """property to set the cheap price in cents we should charge from Grid"""
        self._cheap_price = value

    async def load_cheap_price(self):
        """Load state from storage"""
        data = await self._storage.async_load()
        if data is not None:
            self._state = data
        else:
            self._state = {}  # Default state if no data exists

    def add_listener(self, callback):
        """Add a listener that will be notified when the state changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        """Notify all listeners about the current state."""
        for callback in self._listeners:
            callback(self)

    def clear_status(self):
        self._state = ""
        self._notify_listeners()

    def update_status(self, msg):
        """Write a status msg to status field and log it."""
        msg = msg.strip()

        if self._state == "":
            self._state = msg
        else:
            self._state = self._state + ". " + msg

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
        self._notify_listeners()

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
        self._curtailment = True
        self._notify_listeners()

    async def maximise_self(self):
        _LOGGER.info("Maximising self consumption")
        await self.set_mode(PowerSelectOptions.MAXIMISE)

    async def uncurtail_solar(self):
        _LOGGER.info("Uncurtailing Solar")
        self._curtailment = False
        self._notify_listeners()

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

    async def refresh_on_state_change(self, *args):
        """Method called when entity states change"""
        await self.handle_manage_energy()

    async def handle_manage_energy(self):
        """Maing method in Manage_Energy."""
        try:
            if self._running:
                return
            self._running = True
            self.clear_status()
            self.update_status("Runnning manage energy...")

            await self.forecasts.build()

            self.clear_status()

            self.tesla_charging = await self.tesla.tesla_charging(self.forecasts)
            # Now we can now make a decision if we start to feed in...

            if self._auto:
                self.forecasts.actuals.rule.run()
                if (
                    #   not self.tesla_charging
                    self.forecasts.actuals.battery_pct >= CURTAIL_BATTERY_LEVEL
                    and self.forecasts.actuals.feedin < 0
                ):
                    await self.curtail_solar()
                    self.update_status("Curtailing solar")
                else:
                    await self.uncurtail_solar()
            else:
                self.update_status("Auto disabled")

        except Exception as e:
            error_details = traceback.format_exc()
            self.update_status("Error: " + str(e))
            _LOGGER.error("Error: " + str(e) + "\n" + error_details)
            self.set_mode(PowerSelectOptions.MAXIMISE)

        finally:
            # if failing, make sure set to Maximise Energy

            self._running = False
