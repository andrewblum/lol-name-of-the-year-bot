from datetime import datetime, timezone

import pytest

from namebot import bracket
from namebot.db import Database

T0 = datetime(2026, 3, 5, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return Database(':memory:')


def add(db, name, month='2026-03', puuid=None, votes=0, by=1):
    name_id = db.add_name(puuid=puuid, game_name=name, tag_line='NA1', submitted_by=by, submitted_at=T0,
                          month=month, level=30, icon_id=1, rank='Unranked')
    db.set_card(name_id, 555, 1000 + name_id)
    db.replace_votes(name_id, list(range(votes)))
    return name_id


def test_dedupes_by_puuid_and_riot_id(db):
    add(db, 'Teemothy', puuid='p1')
    assert db.find_duplicate('p1', 'Renamed', 'NA1')  # same account, new name
    assert db.find_duplicate(None, 'teemothy', 'na1')  # unverified, same text
    assert db.find_duplicate('p2', 'Other', 'NA1') is None


def test_removed_names_can_be_resubmitted(db):
    name_id = add(db, 'Teemothy', puuid='p1')
    db.remove_name(name_id)
    assert db.find_duplicate('p1', 'Teemothy', 'NA1') is None
    add(db, 'Teemothy', puuid='p1')  # must not violate the puuid UNIQUE constraint


def test_votes_are_one_per_user(db):
    name_id = add(db, 'Teemothy')
    db.add_vote(name_id, 7)
    db.add_vote(name_id, 7)
    db.add_vote(name_id, 8)
    db.remove_vote(name_id, 8)
    assert db.get_name(name_id)['votes'] == 1


def test_top_names_by_period(db):
    a = add(db, 'March1', votes=2)
    b = add(db, 'March2', votes=5)
    add(db, 'April1', month='2026-04', votes=9)
    add(db, 'LastYear', month='2025-12', votes=20)
    assert [r['id'] for r in db.top_names(month='2026-03')] == [b, a]
    assert len(db.top_names(year=2026)) == 3
    assert db.top_names()[0]['game_name'] == 'LastYear'


def test_undecided_months(db):
    add(db, 'A', month='2026-02')
    add(db, 'B', month='2026-03')
    add(db, 'C', month='2026-04')
    db.record_monthly_winner('2026-02', None, 0, T0)
    assert db.undecided_months('2026-04') == ['2026-03']


def test_bracket_entrants_include_every_monthly_winner(db):
    # A monthly winner with few votes still beats a high-vote wildcard for a spot.
    low_winner = add(db, 'QuietMonth', month='2026-01', votes=1)
    db.record_monthly_winner('2026-01', low_winner, 1, T0)
    wildcards = [add(db, f'Loud{i}', month='2026-02', votes=10 + i) for i in range(4)]
    db.record_monthly_winner('2026-02', wildcards[-1], 13, T0)
    entrants = [r['id'] for r in db.bracket_entrants(2026, 4)]
    assert low_winner in entrants
    assert entrants[0] == wildcards[-1]  # seeded by votes
    assert entrants[-1] == low_winner
    assert len(entrants) == 4


def test_bracket_rounds(db):
    ids = [add(db, f'N{i}', votes=10 - i) for i in range(3)]
    size = bracket.bracket_size(3, 16)
    db.create_bracket(2026, ids, bracket.total_rounds(size), T0, bracket.first_round(ids, size))
    r1 = db.matches(2026, 1)
    assert [(m['a_id'], m['b_id'], m['winner_id']) for m in r1] == [(ids[0], None, ids[0]), (ids[1], ids[2], None)]
    db.decide_match(r1[1]['id'], ids[2], 1, 4)
    db.open_round(2026, 2, bracket.next_round([ids[0], ids[2]]))
    assert db.active_bracket()['current_round'] == 2
    final = db.matches(2026, 2)
    assert [(m['a_id'], m['b_id']) for m in final] == [(ids[0], ids[2])]
    db.finish_bracket(2026, ids[2])
    assert db.active_bracket() is None
    assert db.year_winners()[0]['id'] == ids[2]


def test_migrates_db_created_before_mastery_columns(tmp_path):
    import sqlite3

    path = tmp_path / 'old.sqlite3'
    old = sqlite3.connect(path)
    old.execute('CREATE TABLE names (id INTEGER PRIMARY KEY, puuid TEXT UNIQUE, game_name TEXT NOT NULL,'
                ' tag_line TEXT NOT NULL, riot_id_lower TEXT NOT NULL, submitted_by INTEGER NOT NULL,'
                ' submitted_at TEXT NOT NULL, month TEXT NOT NULL, card_channel_id INTEGER,'
                ' card_message_id INTEGER UNIQUE, level INTEGER, icon_id INTEGER, rank TEXT,'
                ' removed INTEGER NOT NULL DEFAULT 0)')
    old.commit()
    old.close()
    db = Database(path)
    name_id = db.add_name(puuid='p', game_name='Teemothy', tag_line='NA1', submitted_by=1, submitted_at=T0,
                          month='2026-03', level=1, icon_id=1, rank='Unranked', main_champ='Teemo',
                          mastery_level=42, mastery_points=99)
    assert db.get_name(name_id)['main_champ'] == 'Teemo'
    Database(path)  # re-opening an already-migrated DB is a no-op


def test_search_names(db):
    add(db, 'Teemothy')
    add(db, 'TeemoMain')
    gone = add(db, 'TeemoGone')
    db.remove_name(gone)
    add(db, 'Other')
    assert {r['game_name'] for r in db.search_names('teemo')} == {'Teemothy', 'TeemoMain'}
    assert len(db.search_names('')) == 3
    assert db.search_names('%') == []  # no LIKE wildcards
