from .const import BATTERY_DISCHARGE_RATE, MAX_BATTERY_LEVEL, PowerSelectOptions


import datetime
import logging
import traceback
from .const import MAX_BATTERY_LEVEL, BATTERY_CHARGE_RATE
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .utils import is_demand_window, safe_max, safe_min

_LOGGER = logging.getLogger(__name__)


def largest_entry(block, no_of_entry) -> float:
    """Returns the max value from block across the three lowest elements in an array"""

    block = sorted(block)
    if len(block) == 0:
        return None
    if len(block) == 1 or no_of_entry <= 1:
        return block[0]
    return max(block[0:no_of_entry])


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
            lambda: ShouldIDischarge_No_Regrets(
                f, 1, PowerSelectOptions.DISCHARGE, "Discharging as No Regrets"
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
            lambda: ShouldIDischarge_in_Spike(
                f, 4, PowerSelectOptions.DISCHARGE, "Discharging into Price Spike"
            ),
            lambda: MaximiseUsage(
                f, 5, PowerSelectOptions.MAXIMISE, "Maximising usage"
            ),
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

        forecast_window = len(self.forecast.battery_energy) - 1

        # If my battery level is not going to hit 100... or i am going to be importing power before it does
        # and power cheap now. Top up..
        battery_full = next(
            (
                i
                for i, num in enumerate(self.forecast.battery_energy)
                if num >= self.actuals.battery_max_energy
            ),
            None,
        )

        battery_empty = next(
            (
                i
                for i, num in enumerate(self.forecast.battery_energy)
                if num <= self.actuals.battery_min_energy
            ),
            None,
        )
        firstgridimport = next(
            (
                i
                for i, num in enumerate(self.forecast.grid[0:forecast_window])
                if num > 0
            ),
            None,
        )

        first_net_positive = next(
            (
                i
                for i, num in enumerate(self.forecast.net[0:forecast_window])
                if num >= 0 and (battery_empty is None or i > battery_empty)
            ),
            None,
        )
        forecast_window = first_net_positive
        if forecast_window is None:
            forecast_window = len(self.forecast.battery_energy)

        min_battery = safe_min(self.forecast.battery_energy[0:first_net_positive])
        if (
            battery_empty is None
            or min_battery is None
            or min_battery > self.actuals.battery_min_energy * 1.2
        ):
            # if battery is not going to be empty (with a safety margin) in the next forecast window, then don't charge
            return False

        # if battery will be charged before we next import power, don't charge

        if firstgridimport is None or (
            (battery_full is not None and firstgridimport > battery_full)
            or actuals.battery_pct >= MAX_BATTERY_LEVEL
            or is_demand_window(actuals.time)
        ):
            return False

        blocks = self.forecast.amber_scaled_price[0:forecast_window]

        if len(blocks) < 1:
            return False

        blocks_to_charge = int(
            round(
                (
                    self.actuals.battery_max_energy
                    - safe_max(self.forecast.battery_energy[:forecast_window])
                )
                / BATTERY_CHARGE_RATE
                * 2
                + 0.5,
                0,
            )
        )
        if blocks_to_charge == 0:
            return False

        blocks_to_check = blocks[: max(firstgridimport, 24)]
        val = largest_entry(blocks_to_check, blocks_to_charge)

        # this is one of the cheapest times and has at least ~10% saving on max
        if (
            val is not None
            and self.actuals.scaled_price <= val
            and self.actuals.scaled_price < 0.9 * max(blocks_to_check)
        ):
            return True

        return False


class ShouldIDischarge_No_Regrets(baseRule):
    """If i have available energy and actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities."""

    def eval(self):
        if self.a.is_battery_empty():
            return False

        if self.a.has_sufficient_margin(
            self.actuals.feedin,
            0.9
            * float(
                max(self.forecast.amber_price[0 : self.a.battery_window])
                + self.a.scaled_min_margin
            ),
        ):
            return True

        return False


class ShouldIDischarge_in_Spike(baseRule):
    """If i have available energy and the actual is as good as it gets in the next five hours (with margin) or there is a price spike in the next 5 hours and this is one of the best opportunities."""

    def eval(self):
        if self.a.is_battery_empty():
            return False

        min_value = safe_min(self.a.available_max_values)
        if (
            # This is the time with one of the best prices and has sufficient marging
            self.a.available_max_values is not None
            and len(self.a.available_max_values) > 0
            and min_value is not None
            and self.actuals.feedin >= 0.9 * min_value
            and self.a.has_sufficient_margin(
                self.actuals.feedin,
                safe_min(self.forecast.amber_price[0 : self.a.battery_window]),
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
            and self.a.start_high_prices > 0
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
