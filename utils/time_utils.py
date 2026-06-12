from datetime import datetime, timedelta
import zoneinfo
from typing import List, Tuple

def generate_date_options(days: int = 14, timezone_str: str = "UTC") -> List[Tuple[str, str]]:
    """Returns a list of tuples (Label, ISO Value) for the next X days in the target timezone."""
    options = []
    tz = zoneinfo.ZoneInfo(timezone_str)
    now = datetime.now(tz)
    for i in range(days):
        dt = now + timedelta(days=i)
        label = dt.strftime("%a, %b %d")
        if i == 0:
            label += " (Today)"
        elif i == 1:
            label += " (Tomorrow)"
        val = dt.strftime("%Y-%m-%d")
        options.append((label, val))
    return options

def generate_hour_options() -> List[Tuple[str, str]]:
    """Returns 24 hour labels and values."""
    options = []
    for h in range(24):
        period = "AM" if h < 12 else "PM"
        display_hour = h if h != 0 else 12
        if display_hour > 12:
            display_hour -= 12
        label = f"{display_hour} {period}"
        val = str(h)
        options.append((label, val))
    return options

def generate_minute_options() -> List[Tuple[str, str]]:
    """Returns minute labels and values in 5-minute intervals."""
    options = []
    for m in range(0, 60, 5):
        label = f":{m:02d}"
        val = str(m)
        options.append((label, val))
    return options

def parse_schedule_time(date_str: str, hour_str: str, min_str: str, timezone_str: str) -> datetime:
    """Parses selections into a UTC datetime object."""
    date_part = datetime.strptime(date_str, "%Y-%m-%d")
    
    if ":" in hour_str:
        h_part, m_part = hour_str.split(":", 1)
        hour = int(h_part)
        minute = int(m_part)
        if min_str.upper() in {"AM", "PM"}:
            if min_str.upper() == "PM" and hour < 12:
                hour += 12
            elif min_str.upper() == "AM" and hour == 12:
                hour = 0
    else:
        hour = int(hour_str)
        minute = int(min_str)
        
    dt_naive = datetime(date_part.year, date_part.month, date_part.day, hour, minute)
    tz = zoneinfo.ZoneInfo(timezone_str)
    dt_aware = dt_naive.replace(tzinfo=tz)
    dt_utc = dt_aware.astimezone(zoneinfo.ZoneInfo("UTC"))
    return dt_utc
