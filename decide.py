from .const import BATTERY_DISCHARGE_RATE, MAX_BATTERY_LEVEL, PowerSelectOptions


import datetime
import logging
import traceback
from .const import MAX_BATTERY_LEVEL, BATTERY_CHARGE_RATE
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .utils import is_demand_window, safe_max

_LOGGER = logging.getLogger(__name__)


def largest_entry(block, no_of_entry) -> float:
    """Returns the max value from block across the three lowest elements in an array"""
    if len(block) == 0:
        return None
    if len(block) == 1 or no_of_entry <= 1:
        return block[0]
    return max(sorted(block)[0:no_of_entry])


class Decide:
    def __init__(self, f):
        self.forecast = f
        self.rules = []
        self.rule_no = None
        self.rule = None
        self.Decide_Battery_Action()

    def Decide_Battery_Action(self):
        """Run rules to decide what action to take with battery."""
        f = self.forecast
        # lambda functions allow to load into an array of rules. Rules are defined in decide.py

        self.rules = [
            lambda: ChargeInNegativePrices(
                f, 0, PowerSelectOptions.CHARGE, "Charging. Negative Prices."
            ),
            lambda: ShouldIDischarge(
                f, 1, PowerSelectOptions.DISCHARGE, "Discharging into Price Spike"
            ),
            lambda: Should_i_charge_as_not_enough_solar(
                f, 2, PowerSelectOptions.CHARGE, "Charging as cheaper now"
            ),
            lambda: ShouldIChargeforPriceSpike(
                f,
                3,
                PowerSelectOptions.CHARGE,
                "Charging for price spike at " + f.analysis.peak_start_str,
            ),
            # lambda: PreserveWhileTeslaCharging(
            #    f, PowerSelectOptions.OFF, "Preserving charge"
            # ),
            lambda: MaximiseUsage(
                f, 4, PowerSelectOptions.MAXIMISE, "Maximising usage"
            ),
            lambda: MaximiseUsage(f, 4, PowerSelectOptions.CHARGE, "Maximising usage"),
        ]
        # and will run one by one, stopping when the first is successful. The last maximise usage should always be successful.
        for i, rule in enumerate(self.rules):
            try:
                r = rule()
                if r.eval():
                    self.action = r.action
                    self.rule_no = i
                    self.rule = r
                    break

            except Exception as e:
                # Extract the traceback
                tb = traceback.extract_tb(e.__traceback__)

                # Get the last entry in the traceback (where the exception occurred)
                if tb:
                    last_trace = tb[-1]
                    function_name = last_trace.name
                    line_number = last_trace.lineno
                else:
                    function_name = "Unknown"
                    line_number = "Unknown"

                # Build the error message
                error_message = f"Rule failed: {function_name} at line {line_number}. Error: {str(e)}"

                # Log the error
                _LOGGER.error(error_message)

        return self.rule


class baseRule:
    "Decide on action and execute."

    def __init__(self, forecast, id, cmd: PowerSelectOptions, msg: str) -> None:
        """Pass analysis include actuals and forecasts on which to decide."""
        self.a = forecast.analysis
        self.hub = forecast.hub
        self.forecast = forecast
        self.actuals = forecast.actuals
        self._cmd = cmd
        self._msg = msg
        self.id = id

    def run(self):
        self.hub.set_mode(self._cmd)
        self.hub.update_status(self._msg)

    @property
    def action(self) -> PowerSelectOptions:
        """Execute an action and write a status msg."""
        return self._cmd

    def run(self):
        self.hub.set_mode(self._cmd)
        self.hub.update_status(self._msg)

    def eval(self):
        """Default just return True if just want to run actions regardless."""
        return True


class ChargeInNegativePrices(baseRule):
    """If negative prices, then charge the battery. Even if full will stop discharging...."""

    def eval(self):
        """Evaluate rule."""

        if self.actuals.price < 0 and not is_demand_window(self.actuals.time):
            return True

        return False


class Should_i_charge_as_not_enough_solar(baseRule):
    """Works out whether now is a good time to charge battery if going to be importing in the next forecast window."""

    def eval(self):
        """Eval rule for this one."""
        actuals = self.actuals
        FORECAST_WINDOW = len(self.forecast.battery_energy) - 1

        # If my battery level is not going to hit 100... or i am going to be importing power before it does
        # and power cheap now. Top up..
        battery_charged = next(
            (
                i
                for i, num in enumerate(self.forecast.battery_energy)
                if num >= self.actuals.battery_max_energy
            ),
            None,
        )
        firstgridimport = next(
            (
                i
                for i, num in enumerate(self.forecast.grid[0:FORECAST_WINDOW])
                if num > 0
                and i < len(self.forecast.action)
                and self.forecast.action[i] != PowerSelectOptions.CHARGE
            ),
            None,
        )

        # if battery will be charged before we next import power, don't charge

        if firstgridimport is None or (
            (battery_charged is not None and firstgridimport > battery_charged)
            or actuals.battery_pct >= MAX_BATTERY_LEVEL
            or is_demand_window(datetime.datetime.now())
        ):
            return False

        if battery_charged is None or firstgridimport < battery_charged:
            first_no_grid_export = None
            for i, num in enumerate(self.forecast.grid):
                if num >= 0 and i > firstgridimport:
                    first_no_grid_export = i
                    break

        # else check for the blocks up to when it will be charged or for the entire window.

        if battery_charged is None or first_no_grid_export is None:
            blocks_to_check = FORECAST_WINDOW
        else:
            blocks_to_check = first_no_grid_export

        blocks = self.forecast.amber_scaled_price[0 : blocks_to_check - 1]

        if len(blocks) < 1:
            return False

        val = largest_entry(blocks, 3)

        # check whether a better time to charge. Should really work out how many blocks we need mim but on future iterations, should then eliminate export and never hit here. We will see...
        if val is not None and self.actuals.scaled_price <= val:
            return True

        return False


class ShouldIDischarge(baseRule):
    """If i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities."""

    def eval(self):
        if self.a.point_battery_empty is None:
            battery_window = len(self.a.next12hours) - 1
        else:
            battery_window = min(
                self.a.point_battery_empty, len(self.a.next12hours) - 1
            )
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
                and self.a.has_sufficient_margin(
                    self.actuals.feedin, min(self.a.next12hours[:battery_window])
                )
            )
        ):
            return True

        return False


class ShouldIChargeforPriceSpike(baseRule):
    """If i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities."""

    def eval(self):
        """Evaluate rule."""

        if (
            self.a.start_high_prices is not None
            and len(self.a.max_values) > 0
            and self.actuals.scaled_price + self.a.scaled_min_margin
            < (self.a.max_values[0] * 0.9)
            and self.a.battery_at_peak < self.actuals.battery_max_energy
            and (
                self.actuals.scaled_price
                # ...and this is the best possible time to charge...
                <= largest_entry(
                    self.forecast.amber_scaled_price[0 : self.a.start_high_prices],
                    self.a.charge_blocks_required_for_peak,
                )
                or self.a.charge_blocks_required_for_peak > self.a.start_high_prices
            )
            # If battery never hits peak before start of high prices...
            and safe_max(self.forecast.battery_pct[0 : self.a.start_high_prices])
            < MAX_BATTERY_LEVEL
        ):
            return True

        return False


class PreserveWhileTeslaCharging(baseRule):
    """Whilst Tesla charging, stop battery from discharging."""

    def eval(self):
        """Evaluate rule."""

        if self.hub.tesla_charging:
            return True
        return False


class MaximiseUsage(baseRule):
    """Just use default base class to execute actions."""
