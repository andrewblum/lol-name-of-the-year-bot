"""Minimal async Riot API client: Riot ID -> account, level, icon, rank, main champ (NA only)."""

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

REGIONAL_HOST = 'https://americas.api.riotgames.com'
PLATFORM_HOST = 'https://na1.api.riotgames.com'
DDRAGON = 'https://ddragon.leagueoflegends.com'

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
    main_champ: str | None = None
    mastery_level: int | None = None
    mastery_points: int | None = None


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
        self._champion_names: dict[int, str] = {}

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
        summoner, entries, top_mastery = await asyncio.gather(
            self._get(f'{PLATFORM_HOST}/lol/summoner/v4/summoners/by-puuid/{puuid}'),
            self._get(f'{PLATFORM_HOST}/lol/league/v4/entries/by-puuid/{puuid}'),
            self._top_mastery(puuid),
        )
        # An account with no NA summoner plays on another shard.
        if not summoner:
            return None
        profile = Profile(
            puuid=puuid,
            game_name=account.get('gameName') or game_name,
            tag_line=account.get('tagLine') or tag_line,
            level=summoner.get('summonerLevel'),
            icon_id=summoner.get('profileIconId'),
            rank=format_rank(entries or []),
        )
        if top_mastery:
            profile.main_champ = await self.champion_name(top_mastery['championId'])
            profile.mastery_level = top_mastery.get('championLevel')
            profile.mastery_points = top_mastery.get('championPoints')
        return profile

    async def _top_mastery(self, puuid: str) -> dict | None:
        """Most-played champion by mastery points. Nice-to-have, so failures just mean no main champ."""
        try:
            top = await self._get(
                f'{PLATFORM_HOST}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count=1'
            )
        except RiotUnavailable as exc:
            log.warning('Mastery lookup failed: %s', exc)
            return None
        return top[0] if top else None

    async def _ddragon_json(self, path: str):
        async with self.session.get(f'{DDRAGON}{path}', timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return await resp.json()

    async def _version(self) -> str | None:
        if not self._ddragon_version:
            try:
                self._ddragon_version = (await self._ddragon_json('/api/versions.json'))[0]
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return None
        return self._ddragon_version

    async def champion_name(self, champion_id: int) -> str:
        if champion_id not in self._champion_names:
            version = await self._version()
            try:
                data = await self._ddragon_json(f'/cdn/{version}/data/en_US/champion.json')
                self._champion_names = {int(c['key']): c['name'] for c in data['data'].values()}
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                log.warning('Could not load champion names from Data Dragon')
        return self._champion_names.get(champion_id, f'Champion #{champion_id}')

    async def icon_url(self, icon_id: int | None) -> str | None:
        version = await self._version() if icon_id is not None else None
        if not version:
            return None
        return f'{DDRAGON}/cdn/{version}/img/profileicon/{icon_id}.png'
