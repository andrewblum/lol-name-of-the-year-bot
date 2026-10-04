from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from namebot.periods import month_key, previous_month_key
from namebot.riot import format_rank, opgg_url

PT = ZoneInfo('America/Los_Angeles')


def test_month_key_uses_local_time():
    # 8pm Oct 31 Pacific is already Nov 1 in UTC; it should still count for October.
    assert month_key(datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), PT) == '2026-10'
    assert previous_month_key('2027-01') == '2026-12'


def test_format_rank():
    assert format_rank([]) == 'Unranked'
    assert format_rank([{'queueType': 'RANKED_FLEX_SR', 'tier': 'GOLD', 'rank': 'II', 'leaguePoints': 40}]) \
        == 'Gold II · 40 LP (Flex)'
    assert format_rank([
        {'queueType': 'RANKED_FLEX_SR', 'tier': 'GOLD', 'rank': 'II', 'leaguePoints': 40},
        {'queueType': 'RANKED_SOLO_5x5', 'tier': 'MASTER', 'rank': 'I', 'leaguePoints': 120},
    ]) == 'Master · 120 LP'


def test_opgg_url():
    assert opgg_url('xX Big Gank Xx', 'NA1') == 'https://op.gg/lol/summoners/na/xX%20Big%20Gank%20Xx-NA1'


def test_compact_number():
    from namebot.cards import compact_number

    assert [compact_number(n) for n in (None, 950, 181_371, 1_234_567)] == ['?', '950', '181k', '1.2M']


def test_lookup_includes_main_champ():
    import asyncio

    from namebot.riot import RiotClient

    responses = {
        'accounts/by-riot-id': {'puuid': 'p1', 'gameName': 'Teemothy', 'tagLine': 'Teeto'},
        'summoners/by-puuid': {'summonerLevel': 312, 'profileIconId': 7},
        'entries/by-puuid': [],
        'champion-masteries': [{'championId': 17, 'championLevel': 42, 'championPoints': 1_500_000}],
    }

    async def fake_get(url):
        return next(v for k, v in responses.items() if k in url)

    async def fake_champ(champion_id):
        return {17: 'Teemo'}[champion_id]

    client = RiotClient('key', session=None)
    client._get = fake_get
    client.champion_name = fake_champ
    profile = asyncio.run(client.lookup('teemothy', 'teeto'))
    assert (profile.main_champ, profile.mastery_level, profile.mastery_points) == ('Teemo', 42, 1_500_000)
    assert profile.game_name == 'Teemothy' and profile.level == 312
