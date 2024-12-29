from .const import (
    BATTERY_DISCHARGE_RATE,
    CURTAIL_BATTERY_LEVEL,
    DOMAIN,
    PowerSelectOptions,
    TeslaModeSelectOptions,
)
import logging
import traceback

from pytz import timezone
from homeassistant.core import HomeAssistant, StateMachine
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.helpers.event import async_track_time_interval, async_call_later
from .utils import is_demand_window


_LOGGER = logging.getLogger(__name__)


class TeslaCharging:
    """Tesla Charging class to work out how to charge."""

    def __init__(self, hub):
        self._hass = hub.hass
        self._hub = hub

        self.amps = 0
        self._tesla_amps = 0
        self._mode = TeslaModeSelectOptions.AUTO

    async def set_mode(self, mode):
        self._mode = mode
        await self._hass.services.async_call(
            "button", "press", {"entity_id": "button.pete_s_tesla_force_data_update"}
        )

        await self._hub.refresh()

    def get_max_price(self):
        return (
            float(self._hass.states.get("input_number.max_tesla_charge_price").state)
            / 100
        )

    async def tesla_charging(self, forecasts):  # noqa: D102
        _LOGGER.info("Checking whether to charge Tesla")
        # Turn Tesla charging on if the plugged in and at home.
        try:
            actuals = self._hub.forecasts.actuals
            hass: HomeAssistant = self._hass
            hub = self._hub

            tesla_home = (
                hass.states.get("binary_sensor.pete_s_tesla_presence").state == "on"
            )
            max_price = hub.cheap_price

            tesla_charger_door_closed = (
                hass.states.get("cover.pete_s_tesla_via_fleet_charger_door").state
                != "open"
            )

            if (tesla_charger_door_closed or not tesla_home) and not hass.config.debug:
                return False

            tesla_charging = (
                hass.states.get("binary_sensor.pete_s_tesla_via_fleet_charging").state
                == "on"
            )
            charge_limit = int(
                hass.states.get("number.pete_s_tesla_via_fleet_charge_limit").state
            )
            self.current_amps = int(
                hass.states.get("number.pete_s_tesla_via_fleet_charging_amps").state
            )

            current_charge = int(
                hass.states.get("sensor.pete_s_tesla_via_fleet_battery").state
            )

            isDemandWindow = is_demand_window()

            if (
                (
                    self._mode == TeslaModeSelectOptions.FAST_GRID
                    or (
                        (
                            actuals.price <= max_price
                            and self._mode == TeslaModeSelectOptions.CHEAP_GRID
                        )
                        or actuals.price <= 0
                    )
                )
                or actuals.price <= 0
            ) and not isDemandWindow:
                self.amps = 16

            else:
                if actuals.feedin <= max_price:
                    if actuals.battery_pct < 100:
                        battery_charge = BATTERY_DISCHARGE_RATE
                    else:
                        battery_charge = 0

                    self.amps = round(
                        (actuals.net_energy - battery_charge) * 1000 / 240 / 3,
                        0,
                    )
                    if tesla_charging:
                        self.amps += self._tesla_amps
                    self.amps = max(self.amps, 0)
                    self.amps = min(self.amps, 16)
                elif actuals.feedin > max_price:
                    self.amps = 0

            if charge_limit > current_charge and self.amps > 0:
                await self.enable_charging()
                return True
            else:
                if charge_limit <= current_charge:
                    hub.update_status("Tesla: charge limit reached.")
                elif (
                    actuals.price > max_price
                    and self._mode == TeslaModeSelectOptions.CHEAP_GRID
                ):
                    hub.update_status(
                        "Tesla: Price over maximum of "
                        + str(int(max_price * 100))
                        + " cents."
                    )
                else:
                    if (
                        isDemandWindow
                        and self._mode == TeslaModeSelectOptions.CHEAP_GRID
                        and actuals.price <= max_price
                    ):
                        hub.update_status("Tesla: In demand window")
                    elif actuals.feedin <= max_price:
                        hub.update_status("Tesla: No excess solar")
                    else:
                        hub.update_status("Tesla: Feed in over cheap price")

                await self.disable_charging()

            return False

        except Exception as e:
            msg = str(e)
            hub.update_status("Error in Tesla_Charging. Error : " + msg)
            error_message = traceback.format_exc()
            # Log the error with the traceback
            _LOGGER.error(
                f"Error in Tesla_Charging: {error_message}\n"  # noqa: G004
            )
            return False

    async def disable_charging(self):
        hass = self._hass
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.pete_s_tesla_charger"},
            True,
        )
        if self.current_amps != 16:
            await hass.services.async_call(
                "number",
                "set_value",
                {
                    "entity_id": " number.pete_s_tesla_charging_amps",
                    "value": 16,
                },
                True,
            )

    async def enable_charging(self):
        hass = self._hass

        await hass.services.async_call(
            "number",
            "set_value",
            {
                "entity_id": " number.pete_s_tesla_charging_amps",
                "value": self.amps,
            },
            True,
        )
        self._tesla_amps = self.amps

        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.pete_s_tesla_charger"},
            True,
        )
        self._hub.update_status("Charging Tesla at " + str(self.amps) + " amps")
