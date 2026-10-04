"""Month/year bucketing in the league's local timezone."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def month_key(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime('%Y-%m')


def previous_month_key(key: str) -> str:
    year, month = map(int, key.split('-'))
    return f'{year - 1}-12' if month == 1 else f'{year}-{month - 1:02d}'


def month_label(key: str) -> str:
    return datetime.strptime(key, '%Y-%m').strftime('%B %Y')
