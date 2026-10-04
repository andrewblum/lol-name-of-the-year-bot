"""Minimal async Riot API client: Riot ID -> account, level, icon, rank (NA only)."""

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

REGIONAL_HOST = 'https://americas.api.riotgames.com'
PLATFORM_HOST = 'https://na1.api.riotgames.com'
DDRAGON_VERSIONS = 'https://ddragon.leagueoflegends.com/api/versions.json'

QUEUE_LABELS = {'RANKED_SOLO_5x5': '', 'RANKED_FLEX_SR': ' (Flex)'}
APEX_TIERS = {'MASTER', 'GRANDMASTER', 'CHALLENGER'}


class RiotUnavailable(Exception):
    """Key missing/expired or Riot down — caller should fall back to an unverified submission."""


@dataclass
class Profile:
    puuid: str
    game_name: str  # Riot's canonical capitalization
    tag_line: str
    level: int | None
    icon_id: int | None
    rank: str


def opgg_url(game_name: str, tag_line: str) -> str:
    return f'https://op.gg/lol/summoners/na/{quote(game_name)}-{quote(tag_line)}'


def format_rank(entries: list[dict]) -> str:
    by_queue = {e.get('queueType'): e for e in entries}
    for queue, suffix in QUEUE_LABELS.items():
        entry = by_queue.get(queue)
        if not entry:
            continue
        tier = entry['tier'].title()
        division = '' if entry['tier'] in APEX_TIERS else f' {entry["rank"]}'
        return f'{tier}{division} · {entry["leaguePoints"]} LP{suffix}'
    return 'Unranked'


class RiotClient:
    def __init__(self, api_key: str | None, session: aiohttp.ClientSession):
        self.api_key = api_key
        self.session = session
        self._ddragon_version: str | None = None

    async def _get(self, url: str):
        if not self.api_key:
            raise RiotUnavailable('no RIOT_API_KEY configured')
        for attempt in range(4):
            try:
                async with self.session.get(
                    url, headers={'X-Riot-Token': self.api_key}, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return None
                    if resp.status in (401, 403):
                        raise RiotUnavailable(
                            f'Riot returned {resp.status} — key invalid or expired (dev keys last 24h)'
                        )
                    if resp.status == 429:
                        wait = float(resp.headers.get('Retry-After', 5))
                    elif resp.status >= 500:
                        wait = 2 ** attempt
                    else:
                        raise RiotUnavailable(f'Riot returned {resp.status}: {(await resp.text())[:200]}')
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                wait = 2 ** attempt
                log.warning('Riot request failed (%s), retrying in %ss', exc, wait)
            await asyncio.sleep(wait)
        raise RiotUnavailable(f'Riot API: too many retries for {url}')

    async def lookup(self, game_name: str, tag_line: str) -> Profile | None:
        """None if no such NA account exists. Raises RiotUnavailable if we can't tell."""
        account = await self._get(
            f'{REGIONAL_HOST}/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}'
        )
        if not account:
            return None
        puuid = account['puuid']
        summoner, entries = await asyncio.gather(
            self._get(f'{PLATFORM_HOST}/lol/summoner/v4/summoners/by-puuid/{puuid}'),
            self._get(f'{PLATFORM_HOST}/lol/league/v4/entries/by-puuid/{puuid}'),
        )
        # An account with no NA summoner plays on another shard.
        if not summoner:
            return None
        return Profile(
            puuid=puuid,
            game_name=account.get('gameName') or game_name,
            tag_line=account.get('tagLine') or tag_line,
            level=summoner.get('summonerLevel'),
            icon_id=summoner.get('profileIconId'),
            rank=format_rank(entries or []),
        )

    async def icon_url(self, icon_id: int | None) -> str | None:
        if icon_id is None:
            return None
        if not self._ddragon_version:
            try:
                async with self.session.get(DDRAGON_VERSIONS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    self._ddragon_version = (await resp.json())[0]
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return None
        return f'https://ddragon.leagueoflegends.com/cdn/{self._ddragon_version}/img/profileicon/{icon_id}.png'
