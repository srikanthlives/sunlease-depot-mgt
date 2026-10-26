"""All schedule timestamps are derived from (operating date, day offset,
local time, timezone). Durations are ALWAYS computed from full timestamps."""
import datetime as dt
from zoneinfo import ZoneInfo


def to_datetime(operating_date: dt.date, day_offset: int, local_time: dt.time, tz: str) -> dt.datetime:
    d = operating_date + dt.timedelta(days=day_offset)
    return dt.datetime.combine(d, local_time).replace(tzinfo=ZoneInfo(tz))


def rel_minutes(day_offset: int, local_time: dt.time) -> int:
    """Minutes since the operating date's local midnight (wall-clock, tz-free).
    Used for overlap/conflict maths where only relative ordering matters."""
    return day_offset * 1440 + local_time.hour * 60 + local_time.minute


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"
