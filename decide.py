from .const import BATTERY_DISCHARGE_RATE, MAX_BATTERY_LEVEL, PowerSelectOptions


import datetime
import logging
from .const import MAX_BATTERY_LEVEL
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .forecasts import Forecasts, Actuals, is_demand_window
from .analyse import Analysis

_LOGGER = logging.getLogger(__name__)


class baseDecide:
    "Decide on action and execute."

    def __init__(self, a: Analysis) -> None:
        """Pass analysis include actuals and forecasts on which to decide."""
        self.a = a
        self.hub = a.hub
        self.forecasts = a.forecasts
        self.actuals = a.actuals

    def run(self, action, msg) -> bool:
        """Run the rule and then the action if successful. return the result."""
        result = self.eval_rule()
        if result:
            self.action(action, msg)
        return result

    def action(self, action: PowerSelectOptions, msg: str) -> None:
        """Execute an action and write a status msg."""

        _LOGGER.info(msg)
        self.hub.set_mode(action)
        self.hub.update_status(msg)

    def eval_rule(self):
        """Default just return True if just want to run actions regardless"""
        return True


class Should_i_charge_as_not_enough_solar(baseDecide):
    """Works out whether now is a good time to charge battery if going to be importing in the next forecast window."""

    def eval_rule(self):
        """Eval rule for this one."""
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

        if blocks_to_charge == 0:
            return False

        if blocks_to_check == 0:
            if actuals.scaled_price < 0.9 * self.forecasts.amber_scaled_price[0]:
                return True
        else:
            blocks = self.forecasts.amber_scaled_price[0 : blocks_to_check - 1]
            if len(blocks) == 0:
                return False

            if len(blocks) == 1:
                val = blocks[0]
            else:
                blocks = sorted(blocks)[: blocks_to_charge - 1]
                if len(blocks) == 1:
                    val = blocks[0]
                else:
                    val = max(blocks)

            if actuals.scaled_price <= val:
                return True

        # also check whether prices will be higher when we don't have enough power

        return False


class ShouldIDischarge(baseDecide):
    """If i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities."""

    def eval_rule(self):
        if (
            self.actuals.available_battery_energy > self.actuals.battery_min_energy
        ) and (
            (
                # if it is currently 90% of the maximum forecsated and there is acceptable margin then take it !
                self.actuals.feedin
                >= (
                    0.9
                    * float(max(self.a.next12hours[0:10]) + self.a.scaled_min_margin)
                )
            )
            or (
                # otherwise if it is moire than the max values (that already are calced with minimum margin)
                self.a.available_max_values is not None
                and len(self.a.available_max_values) > 0
                and self.actuals.feedin >= 0.9 * min(self.a.available_max_values)
            )
        ):
            return True

        return False


class ShouldIChargeforPriceSpike(baseDecide):
    """If i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities."""

    def eval_rule(self):
        """ "Evaluate rule."""

        if (
            len(self.a.max_values) > 0
            and self.actuals.scaled_price + self.a.scaled_min_margin
            < (self.a.max_values[0] * 0.9)
            and self.a.battery_at_peak < self.actuals.battery_max_energy
            and self.actuals.battery_pct_level < MAX_BATTERY_LEVEL
        ):
            return True
        return False


class PreserveWhileTeslaCharging(baseDecide):
    """Whilst Tesla charging, stop battery from discharging."""

    def eval_rule(self):
        """Evaluate rule."""

        if self.hub.tesla_charging:
            return True
        return False


class MaximiseUsage(baseDecide):
    """Just use default base class to execute actions."""
