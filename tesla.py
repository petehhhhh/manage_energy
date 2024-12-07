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

_LOGGER = logging.getLogger(__name__)


class TeslaCharging:
    """Tesla Charging class to work out how to charge."""

    def __init__(self, hub):
        self._hass = hub.hass
        self._hub = hub
        self.actuals = hub.forecasts.actuals

    async def set_tesla_mode(self, mode):
        self._tesla_mode = mode
        await self._hass.services.async_call(
            "button", "press", {"entity_id": "button.pete_s_tesla_force_data_update"}
        )

        await self.refresh()

    async def tesla_charging(self, forecasts):  # noqa: D102
        _LOGGER.info("Checking whether to charge Tesla")
        # Turn Tesla charging on if the plugged in and at home.
        try:
            tesla_home = (
                self._hass.states.get("binary_sensor.pete_s_tesla_presence").state
                == "on"
            )
            cheap_price = (
                float(self._hass.states.get("input_number.cheap_grid_price").state)
                / 100
            )

            tesla_charger_door_closed = (
                self._hass.states.get("cover.pete_s_tesla_via_fleet_charger_door").state
                != "open"
            )

            if tesla_charger_door_closed or not tesla_home:
                return False

            tesla_charging = (
                self._hass.states.get(
                    "binary_sensor.pete_s_tesla_via_fleet_charging"
                ).state
                == "on"
            )
            charge_limit = int(
                self._hass.states.get(
                    "number.pete_s_tesla_via_fleet_charge_limit"
                ).state
            )
            current_amps = int(
                self._hass.states.get(
                    "number.pete_s_tesla_via_fleet_charging_amps"
                ).state
            )

            current_charge = int(
                self._hass.states.get("sensor.pete_s_tesla_via_fleet_battery").state
            )

            isDemandWindow = await self._hub.is_demand_window()

            if (
                self._tesla_mode == TeslaModeSelectOptions.FAST_GRID
                or (
                    (
                        self.actuals.price <= cheap_price
                        and self._tesla_mode == TeslaModeSelectOptions.CHEAP_GRID
                    )
                    or self.actuals.price <= 0
                )
                and not isDemandWindow
            ):
                charge_amps = 16
            else:
                if self.actuals.feedin <= cheap_price:
                    charge_amps = round(self.actuals.excess_energy * 1000 / 240 / 3, 0)
                    if tesla_charging:
                        charge_amps += self._tesla_amps
                    if charge_amps < 0:
                        charge_amps = 0
                elif self.actuals.feedin > cheap_price:
                    charge_amps = 0

            if charge_limit > current_charge and charge_amps > 0:
                await self._hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": " number.pete_s_tesla_charging_amps",
                        "value": charge_amps,
                    },
                    True,
                )
                self._tesla_amps = charge_amps

                await self._hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.pete_s_tesla_charger"},
                    True,
                )
                self._hub.update_status(
                    "Charging Tesla at " + str(charge_amps) + " amps"
                )
                return True
            else:
                if charge_limit <= current_charge:
                    self._hub.update_status("Tesla: charge limit reached.")
                elif (
                    self.actuals.price > self._cheap_price
                    and self._tesla_mode == TeslaModeSelectOptions.CHEAP_GRID
                ):
                    self._hub.update_status(
                        "Tesla: Grid price over maximum of "
                        + str(self._cheap_price)
                        + " cents."
                    )
                else:
                    if (
                        isDemandWindow
                        and self._tesla_mode == TeslaModeSelectOptions.CHEAP_GRID
                        and self.actuals.price <= cheap_price
                    ):
                        self._hub.update_status("Tesla: In demand window.")
                    elif self.actuals.feedin <= cheap_price:
                        self._hub.update_status("Tesla: No excess solar.")
                    else:
                        self._hub.update_status("Tesla: Feed in over cheap price.")

                await self._hass.services.async_call(
                    "switch",
                    "turn_off",
                    {"entity_id": "switch.pete_s_tesla_charger"},
                    True,
                )
                if current_amps != 16:
                    await self._hass.services.async_call(
                        "number",
                        "set_value",
                        {
                            "entity_id": " number.pete_s_tesla_charging_amps",
                            "value": 16,
                        },
                        True,
                    )

            return False

        except Exception as e:
            msg = str(e)
            self._hub.update_status("Error in Tesla_Charging. Error : " + msg)
            error_message = traceback.format_exc()
            # Log the error with the traceback
            _LOGGER.error(
                f"Error in Tesla_Charging: {error_message}\n"  # noqa: G004
            )
            return False
