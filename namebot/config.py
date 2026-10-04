"""Configuration from environment / .env."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    discord_token: str
    guild_id: int
    names_channel_id: int
    announce_channel_id: int
    riot_api_key: str | None
    db_path: Path
    tz: ZoneInfo
    vote_emoji: str = '👍'
    bracket_size: int = 16
    round_hours: int = 48
    bracket_start: tuple[int, int] | None = (1, 2)  # (month, day) the prior year's bracket auto-starts


def _required_int(name: str) -> int:
    raw = os.environ.get(name, '').strip()
    if not raw.isdigit():
        raise SystemExit(f'{name} must be set to a Discord ID (see .env.example).')
    return int(raw)


def load_config() -> Config:
    load_dotenv(PROJECT_ROOT / '.env')
    token = os.environ.get('DISCORD_TOKEN', '').strip()
    if not token:
        raise SystemExit('DISCORD_TOKEN is not set (see .env.example).')
    names_channel_id = _required_int('NAMES_CHANNEL_ID')
    announce = os.environ.get('ANNOUNCE_CHANNEL_ID', '').strip()

    start_raw = os.environ.get('BRACKET_START', '01-02').strip()
    bracket_start = None
    if start_raw:
        month, day = start_raw.split('-')
        bracket_start = (int(month), int(day))

    size = int(os.environ.get('BRACKET_SIZE', '16'))
    if size < 2 or size & (size - 1):
        raise SystemExit('BRACKET_SIZE must be a power of 2 (e.g. 8, 16, 32).')

    db_path = Path(os.environ.get('DB_PATH', '').strip() or PROJECT_ROOT / 'data' / 'names.sqlite3')
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        discord_token=token,
        guild_id=_required_int('GUILD_ID'),
        names_channel_id=names_channel_id,
        announce_channel_id=int(announce) if announce.isdigit() else names_channel_id,
        riot_api_key=os.environ.get('RIOT_API_KEY', '').strip() or None,
        db_path=db_path,
        tz=ZoneInfo(os.environ.get('TIMEZONE', 'America/Los_Angeles')),
        vote_emoji=os.environ.get('VOTE_EMOJI', '👍').strip() or '👍',
        bracket_size=size,
        round_hours=int(os.environ.get('ROUND_HOURS', '48')),
        bracket_start=bracket_start,
    )
