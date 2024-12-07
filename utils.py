from datetime import datetime, time
from .const import (
    DEMAND_SCALE_UP,
)


def is_demand_window(t: datetime):
    """Is the passed datetime wihtin the demand window."""
    # Define peak period months: June to August and November to March
    peak_months = list(range(6, 9)) + [11, 12, 1, 2, 3]

    start_time = time(15, 0, 0)
    end_time = time(21, 0, 0)

    if t.month in peak_months and (start_time <= t.time() <= end_time):
        return True

    return False


def scale_price_for_demand_window(vtime, val) -> bool:
    if is_demand_window(vtime):
        return val + DEMAND_SCALE_UP

    return val
