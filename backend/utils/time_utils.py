"""
Time utilities for Indian stock market trading.
Handles market hours, IST timezone, and trading day calculations.
"""

from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

# Indian Standard Time
IST = ZoneInfo("Asia/Kolkata")

# Market hours
MARKET_OPEN = time(9, 15)   # 9:15 AM IST
MARKET_CLOSE = time(15, 30)  # 3:30 PM IST
PRE_MARKET_OPEN = time(9, 0)  # 9:00 AM IST

# No new entries after this time (need buffer to exit positions)
LAST_ENTRY_TIME = time(15, 15)  # 3:15 PM IST

# Holidays (2024-2025) - Update annually
# Format: (month, day)
NSE_HOLIDAYS_2024 = [
    (1, 26),   # Republic Day
    (3, 8),    # Mahashivratri
    (3, 25),   # Holi
    (3, 29),   # Good Friday
    (4, 11),   # Eid
    (4, 14),   # Dr. Ambedkar Jayanti
    (4, 17),   # Ram Navami
    (4, 21),   # Mahavir Jayanti
    (5, 1),    # Maharashtra Day
    (5, 23),   # Buddha Purnima
    (6, 17),   # Eid Ul Adha
    (7, 17),   # Muharram
    (8, 15),   # Independence Day
    (10, 2),   # Gandhi Jayanti
    (10, 12),  # Dussehra
    (10, 31),  # Diwali Laxmi Pujan
    (11, 1),   # Diwali Balipratipada
    (11, 15),  # Guru Nanak Jayanti
    (12, 25),  # Christmas
]


def now_ist() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    """Convert datetime to IST."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def is_market_open() -> bool:
    """
    Check if the market is currently open.

    Returns:
        True if market is open, False otherwise.
    """
    current = now_ist()

    # Check if it's a weekend
    if current.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False

    # Check if it's a holiday
    if is_holiday(current.date()):
        return False

    # Check if within market hours
    current_time = current.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_pre_market() -> bool:
    """Check if in pre-market session."""
    current = now_ist()

    if current.weekday() >= 5 or is_holiday(current.date()):
        return False

    current_time = current.time()
    return PRE_MARKET_OPEN <= current_time < MARKET_OPEN


def can_place_new_entry() -> bool:
    """
    Check if we can place new entry orders.
    Returns False near market close to allow time for exits.
    """
    if not is_market_open():
        return False

    current_time = now_ist().time()
    return current_time <= LAST_ENTRY_TIME


def is_holiday(check_date: Optional[date] = None) -> bool:
    """Check if a date is a market holiday."""
    if check_date is None:
        check_date = now_ist().date()

    month_day = (check_date.month, check_date.day)
    return month_day in NSE_HOLIDAYS_2024


def get_market_hours() -> Tuple[datetime, datetime]:
    """
    Get today's market open and close times.

    Returns:
        Tuple of (open_time, close_time) in IST.
    """
    today = now_ist().date()
    return (
        datetime.combine(today, MARKET_OPEN, tzinfo=IST),
        datetime.combine(today, MARKET_CLOSE, tzinfo=IST),
    )


def time_to_market_open() -> timedelta:
    """
    Get time remaining until market opens.

    Returns:
        Timedelta until market opens. Negative if market is already open.
    """
    current = now_ist()
    today_open = datetime.combine(current.date(), MARKET_OPEN, tzinfo=IST)

    if current.time() >= MARKET_OPEN:
        # Market already opened today, calculate for tomorrow
        tomorrow = current.date() + timedelta(days=1)
        # Skip weekends
        while tomorrow.weekday() >= 5 or is_holiday(tomorrow):
            tomorrow += timedelta(days=1)
        next_open = datetime.combine(tomorrow, MARKET_OPEN, tzinfo=IST)
        return next_open - current

    return today_open - current


def time_to_market_close() -> timedelta:
    """
    Get time remaining until market closes.

    Returns:
        Timedelta until market closes. Zero if market is closed.
    """
    if not is_market_open():
        return timedelta(0)

    current = now_ist()
    today_close = datetime.combine(current.date(), MARKET_CLOSE, tzinfo=IST)
    return today_close - current


def get_previous_trading_day(from_date: Optional[date] = None) -> date:
    """Get the previous trading day."""
    if from_date is None:
        from_date = now_ist().date()

    prev_day = from_date - timedelta(days=1)

    while prev_day.weekday() >= 5 or is_holiday(prev_day):
        prev_day -= timedelta(days=1)

    return prev_day


def get_next_trading_day(from_date: Optional[date] = None) -> date:
    """Get the next trading day."""
    if from_date is None:
        from_date = now_ist().date()

    next_day = from_date + timedelta(days=1)

    while next_day.weekday() >= 5 or is_holiday(next_day):
        next_day += timedelta(days=1)

    return next_day


def get_trading_days_in_range(
    start_date: datetime.date,
    end_date: datetime.date
) -> list[datetime.date]:
    """Get all trading days in a date range."""
    trading_days = []
    current = start_date

    while current <= end_date:
        if current.weekday() < 5 and not is_holiday(current):
            trading_days.append(current)
        current += timedelta(days=1)

    return trading_days


def format_ist_time(dt: Optional[datetime] = None) -> str:
    """Format datetime in IST for display."""
    if dt is None:
        dt = now_ist()
    else:
        dt = to_ist(dt)

    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


def parse_datetime(date_str: str) -> datetime:
    """
    Parse datetime string in various formats.

    Supports:
    - YYYY-MM-DD HH:MM:SS
    - YYYY-MM-DD
    - Epoch timestamp (milliseconds)
    """
    # Try epoch milliseconds
    try:
        ts = int(date_str)
        return datetime.fromtimestamp(ts / 1000, tz=IST)
    except ValueError:
        pass

    # Try standard formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=IST)
        except ValueError:
            continue

    raise ValueError(f"Unable to parse datetime: {date_str}")
