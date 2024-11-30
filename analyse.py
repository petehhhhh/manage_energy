from .const import BATTERY_DISCHARGE_RATE, MAX_BATTERY_LEVEL


import datetime
from homeassistant.core import HomeAssistant, StateMachine  # type: ignore
from homeassistant.components.recorder import get_instance  # type: ignore
from homeassistant.components.recorder.history import state_changes_during_period  # type: ignore
from homeassistant.helpers.event import async_track_time_interval, async_call_later  # type: ignore
from .forecasts import Forecasts, Actuals, is_demand_window


class Analysis:
    """ "Analysis of passed forecasts and actuals."""

    def __init__(self, forecasts: Forecasts, actuals: Actuals, hub) -> None:
        """Initiatise Analysis."""
        self.forecasts = forecasts
        self.actuals = actuals
        self.hub = hub

        self.discharge_blocks_available = 0
        self.max_values = None
        self.start_high_prices = None
        self.insufficient_margin = None
        self.end_high_prices = None
        self.insufficient_margin = None
        self.battery_at_peak = None
        self.available_max_values = None
        self.peak_start_str = ""
        self.peak_start_time = None
        self._minimum_margin = hub.minimum_margin

        # scaled minimum margin to avoid eg charging at $15 when it is forecast to be $15.50... High risk of disappointment...
        if actuals.feedin > 0.5:
            self.scaled_min_margin = self._minimum_margin / 0.20 * actuals.feedin
        else:
            self.scaled_min_margin = self._minimum_margin

    def analyze_price_peaks(self):
        """Analyse forecast and actual data for peak prices for deciding whethre to discharge/charge."""
        TTL_FORECAST_BLOCKS = 24
        forecasts = self.forecasts
        actuals = self.actuals
        next12hours = forecasts.amber_feed_in[0:TTL_FORECAST_BLOCKS]

        self.discharge_blocks_available = (
            int(round(actuals.battery_max_usable_energy / BATTERY_DISCHARGE_RATE, 0))
            * 2
        )

        # work out when in next 12 hours we can best use available blocks of discharge
        self.max_values = sorted(next12hours, reverse=True)[
            : (self.discharge_blocks_available)
        ]

        # get rid of max values that are less than the minimum margin
        self.max_values = [
            x for x in self.max_values if x > (min(next12hours) + self._minimum_margin)
        ]

        # find  when high prices start
        self.start_high_prices = None
        for index, value in enumerate(next12hours):
            if value in self.max_values:
                self.start_high_prices = index
                break

            # now find the first entry that has the minimum margin to export to grid. Trim the max values to ensure there is sufficient margin
            self.insufficient_margin = True
            self.end_high_prices = None
            last_end_high_prices = None
            for index1, value1 in enumerate(self.max_values):
                self.end_high_prices = None
                for index, value in enumerate(next12hours):
                    # if this entry is after the start of high prices and it is less than this value less required margin...
                    if (index > self.start_high_prices) and (
                        (value + self.minimum_margin) <= value1
                    ):
                        self.end_high_prices = index
                        self.insufficient_margin = False
                        break

                if index1 == 0 and self.end_high_prices is None:
                    # the max value in the array has too little margin
                    break
                elif self.end_high_prices is None:  # noqa: RET508
                    # the last value in the max series doesn't have enough margin. Probably shouldnt happen as check above...
                    self.max_values = self.max_values[:(index1)]
                    self.end_high_prices = last_end_high_prices
                    self.insufficient_margin = False
                    break

                last_end_high_prices = self.end_high_prices  # noqa: F841

            # if we didn't find one then check that the current price is the tail of the peak
            self.available_max_values = None
            if self.end_high_prices is None:
                if actuals.feedin >= (next12hours[0] + self._minimum_margin):
                    self.insufficient_margin = False
                else:
                    self.insufficient_margin = True
            else:
                # failsafe as can get abberations in data - don't discharge if current price isn't greater than the minimum margin over next 5 hours
                if actuals.feedin < (min(next12hours) + self._minimum_margin):
                    self.insufficient_margin = True
                # to give us how many blocks of high prices we have
                blocks_till_price_drops = self.end_high_prices - self.start_high_prices

                # recalculate actual half hour blocks of discharge available less enough battery to cover consumption
                self.available_max_values = self.max_values
                energy_to_discharge = float(
                    actuals.available_battery_energy
                    - sum(forecasts.consumption[0 : blocks_till_price_drops - 1])
                )
                self.discharge_blocks_available = int(
                    round(energy_to_discharge / BATTERY_DISCHARGE_RATE * 2 + 0.5, 0)
                )
                if self.discharge_blocks_available < 1:
                    self.discharge_blocks_available = 0
                if self.discharge_blocks_available < len(self.max_values):
                    self.available_max_values = self.max_values[
                        : self.discharge_blocks_available
                    ]
                # if i have less available max values then make sure current actuals included in available valuess.
                if len(
                    self.available_max_values
                ) < self.discharge_blocks_available and actuals.feedin >= (
                    min(next12hours) + self.minimum_margin
                ):
                    self.available_max_values.append(actuals.feedin)

            # estimate how much solar power we will have at time of peak power

            if self.start_high_prices != None:
                self.battery_at_peak = forecasts.battery_energy[self.start_high_prices]
                self.peak_start_time = forecasts.start_time[self.start_high_prices]
                self.peak_start_time = forecasts.format_date(self.peak_start_time)
                self.peak_start_str = self.peak_start_time.strftime("%I:%M%p")
