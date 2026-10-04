"""Drives the bot's scheduler logic end to end with Discord faked out."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from namebot import bot as bot_module
from namebot.bot import NameBot
from namebot.config import Config


class FakeChannel:
    id = 999

    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(SimpleNamespace(content=content, **kwargs))
        return SimpleNamespace(id=len(self.sent), poll=None)


@pytest.fixture
def nb(monkeypatch, tmp_path: Path):
    cfg = Config(discord_token='x', guild_id=1, names_channel_id=999, announce_channel_id=999, riot_api_key=None,
                 db_path=tmp_path / 'db.sqlite3', tz=ZoneInfo('America/Los_Angeles'), round_hours=48)
    b = NameBot(cfg)
    b.fake_channel = FakeChannel()
    b.clock = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    b.poll_votes = {}  # poll message id -> (a, b)

    async def channel(_id):
        return b.fake_channel

    async def read_poll(m):
        return (*b.poll_votes.get(m['poll_message_id'], (0, 0)), True)

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(b, 'channel', channel)
    monkeypatch.setattr(b, 'read_poll', read_poll)
    monkeypatch.setattr(b, 'reconcile_votes', noop)
    monkeypatch.setattr(bot_module, 'utcnow', lambda: b.clock)
    b.riot = SimpleNamespace(icon_url=noop)
    return b


def add(b, name, month, votes):
    name_id = b.db.add_name(puuid=None, game_name=name, tag_line='NA1', submitted_by=42,
                            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc), month=month,
                            level=1, icon_id=1, rank='Unranked')
    b.db.set_card(name_id, 999, 5000 + name_id)
    b.db.replace_votes(name_id, list(range(votes)))
    return name_id


def test_month_winner_announced_once(nb):
    add(nb, 'Meh', '2026-10', 1)
    best = add(nb, 'Teemothy', '2026-10', 6)
    add(nb, 'ThisMonth', '2026-11', 50)  # current month: not decided yet
    asyncio.run(nb.decide_months())
    asyncio.run(nb.decide_months())
    assert len(nb.fake_channel.sent) == 1
    assert 'October 2026' in nb.fake_channel.sent[0].embed.title
    assert nb.db.monthly_winners(2026)[0]['id'] == best


def test_full_bracket_runs_to_a_champion(nb):
    ids = [add(nb, f'Name{i}', '2026-05', 10 - i) for i in range(5)]  # 5 entrants -> 8-bracket, 3 byes
    nb.clock = datetime(2027, 1, 3, 12, tzinfo=timezone.utc)

    asyncio.run(nb.maybe_start_bracket())
    b = nb.db.get_bracket(2026)
    assert b['total_rounds'] == 3
    polls = [s for s in nb.fake_channel.sent if getattr(s, 'poll', None)]
    assert len(polls) == 1  # only seed 4 vs seed 5 plays; 1-3 have byes

    # Before the poll ends nothing advances.
    asyncio.run(nb.advance_bracket())
    assert nb.db.get_bracket(2026)['current_round'] == 1

    def play_round(votes_for_b):
        for m in nb.db.matches(2026, nb.db.get_bracket(2026)['current_round']):
            if m['poll_message_id']:
                nb.poll_votes[m['poll_message_id']] = (0, 3) if votes_for_b else (3, 0)
        nb.clock += timedelta(hours=49)
        asyncio.run(nb.advance_bracket())

    play_round(votes_for_b=True)   # seed 5 upsets seed 4
    assert nb.db.get_bracket(2026)['current_round'] == 2
    semis = nb.db.matches(2026, 2)
    assert [(m['a_id'], m['b_id']) for m in semis] == [(ids[0], ids[4]), (ids[1], ids[2])]

    play_round(votes_for_b=True)   # seed 5 and seed 3 advance
    play_round(votes_for_b=False)  # seed 5 wins the final
    final = nb.db.get_bracket(2026)
    assert final['status'] == 'done' and final['winner_name_id'] == ids[4]
    assert '2026 Name of the Year' in nb.fake_channel.sent[-1].content

    # Doesn't restart a finished year.
    asyncio.run(nb.maybe_start_bracket())
    assert nb.db.get_bracket(2026)['status'] == 'done'


def test_bracket_waits_for_december_winner(nb):
    add(nb, 'Dec', '2026-12', 3)
    add(nb, 'Nov', '2026-11', 3)
    nb.clock = datetime(2027, 1, 3, 12, tzinfo=timezone.utc)
    asyncio.run(nb.maybe_start_bracket())
    assert nb.db.get_bracket(2026) is None
    asyncio.run(nb.decide_months())
    asyncio.run(nb.maybe_start_bracket())
    assert nb.db.get_bracket(2026) is not None


def test_slash_commands_register(nb):
    from namebot.commands import register

    register(nb)
    names = {c.name for c in nb.tree.get_commands(guild=nb.guild_obj)}
    assert names == {'top', 'random', 'halloffame', 'bracket', 'bracket-start', 'remove-name'}
