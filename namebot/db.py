"""SQLite store. Discord is the voting UI; this is the record of names, votes, and brackets."""

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS names (
    id INTEGER PRIMARY KEY,
    puuid TEXT UNIQUE,                  -- NULL when submitted while Riot was unavailable
    game_name TEXT NOT NULL,
    tag_line TEXT NOT NULL,
    riot_id_lower TEXT NOT NULL,        -- 'foo#na1', for dedupe of unverified names
    submitted_by INTEGER NOT NULL,
    submitted_at TEXT NOT NULL,         -- UTC ISO
    month TEXT NOT NULL,                -- 'YYYY-MM' in the league timezone
    card_channel_id INTEGER,
    card_message_id INTEGER UNIQUE,
    level INTEGER,
    icon_id INTEGER,
    rank TEXT,
    removed INTEGER NOT NULL DEFAULT 0,
    main_champ TEXT,
    mastery_level INTEGER,
    mastery_points INTEGER
);
CREATE INDEX IF NOT EXISTS names_month ON names(month);
CREATE INDEX IF NOT EXISTS names_riot_id ON names(riot_id_lower);

CREATE TABLE IF NOT EXISTS votes (
    name_id INTEGER NOT NULL REFERENCES names(id),
    user_id INTEGER NOT NULL,
    PRIMARY KEY (name_id, user_id)
);

CREATE TABLE IF NOT EXISTS monthly_winners (
    month TEXT PRIMARY KEY,
    name_id INTEGER REFERENCES names(id),
    votes INTEGER NOT NULL,
    decided_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brackets (
    year INTEGER PRIMARY KEY,
    status TEXT NOT NULL,               -- 'active' | 'done'
    current_round INTEGER NOT NULL,
    total_rounds INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    winner_name_id INTEGER REFERENCES names(id)
);

CREATE TABLE IF NOT EXISTS bracket_seeds (
    year INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    name_id INTEGER NOT NULL REFERENCES names(id),
    PRIMARY KEY (year, seed)
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    round INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    a_id INTEGER REFERENCES names(id),
    b_id INTEGER REFERENCES names(id),  -- NULL = bye
    poll_channel_id INTEGER,
    poll_message_id INTEGER,
    ends_at TEXT,
    a_votes INTEGER,
    b_votes INTEGER,
    winner_id INTEGER REFERENCES names(id),
    UNIQUE (year, round, slot)
);
"""

# Columns added after the first deploy; CREATE TABLE IF NOT EXISTS won't add them to an existing DB.
MIGRATIONS = {
    'main_champ': 'ALTER TABLE names ADD COLUMN main_champ TEXT',
    'mastery_level': 'ALTER TABLE names ADD COLUMN mastery_level INTEGER',
    'mastery_points': 'ALTER TABLE names ADD COLUMN mastery_points INTEGER',
}

VOTE_COUNT = '(SELECT COUNT(*) FROM votes v WHERE v.name_id = n.id)'


class Database:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.conn.execute('PRAGMA journal_mode = WAL')
        self.conn.executescript(SCHEMA)
        columns = {r['name'] for r in self.conn.execute('PRAGMA table_info(names)')}
        with self.conn:
            for column, ddl in MIGRATIONS.items():
                if column not in columns:
                    self.conn.execute(ddl)

    # -- names -----------------------------------------------------------------

    def find_duplicate(self, puuid: str | None, game_name: str, tag_line: str) -> sqlite3.Row | None:
        return self.conn.execute(
            'SELECT * FROM names WHERE removed = 0 AND ((? IS NOT NULL AND puuid = ?) OR riot_id_lower = ?)',
            (puuid, puuid, f'{game_name}#{tag_line}'.lower()),
        ).fetchone()

    def add_name(self, *, puuid: str | None, game_name: str, tag_line: str, submitted_by: int,
                 submitted_at: datetime, month: str, level: int | None, icon_id: int | None,
                 rank: str | None, main_champ: str | None = None, mastery_level: int | None = None,
                 mastery_points: int | None = None) -> int:
        with self.conn:
            # A previously removed entry for the same account must not block resubmission.
            if puuid:
                self.conn.execute('UPDATE names SET puuid = NULL WHERE puuid = ? AND removed = 1', (puuid,))
            cur = self.conn.execute(
                'INSERT INTO names (puuid, game_name, tag_line, riot_id_lower, submitted_by, submitted_at,'
                ' month, level, icon_id, rank, main_champ, mastery_level, mastery_points)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (puuid, game_name, tag_line, f'{game_name}#{tag_line}'.lower(), submitted_by,
                 submitted_at.isoformat(), month, level, icon_id, rank, main_champ, mastery_level,
                 mastery_points),
            )
        return cur.lastrowid

    def set_card(self, name_id: int, channel_id: int, message_id: int):
        with self.conn:
            self.conn.execute(
                'UPDATE names SET card_channel_id = ?, card_message_id = ? WHERE id = ?',
                (channel_id, message_id, name_id),
            )

    def delete_name(self, name_id: int):
        """Hard delete — only for a submission whose card never got posted."""
        with self.conn:
            self.conn.execute('DELETE FROM names WHERE id = ?', (name_id,))

    def remove_name(self, name_id: int):
        with self.conn:
            self.conn.execute('UPDATE names SET removed = 1 WHERE id = ?', (name_id,))

    def get_name(self, name_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            f'SELECT n.*, {VOTE_COUNT} AS votes FROM names n WHERE n.id = ?', (name_id,)
        ).fetchone()

    def name_by_card(self, message_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            'SELECT * FROM names WHERE card_message_id = ? AND removed = 0', (message_id,)
        ).fetchone()

    def name_by_riot_id(self, riot_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            'SELECT * FROM names WHERE riot_id_lower = ? AND removed = 0', (riot_id.strip().lower(),)
        ).fetchone()

    def top_names(self, *, month: str | None = None, year: int | None = None,
                  limit: int = 10) -> list[sqlite3.Row]:
        where, params = ['n.removed = 0'], []
        if month:
            where.append('n.month = ?')
            params.append(month)
        if year:
            where.append('n.month LIKE ?')
            params.append(f'{year}-%')
        return self.conn.execute(
            f'SELECT n.*, {VOTE_COUNT} AS votes FROM names n WHERE {" AND ".join(where)}'
            ' ORDER BY votes DESC, n.submitted_at ASC LIMIT ?',
            (*params, limit),
        ).fetchall()

    def random_name(self) -> sqlite3.Row | None:
        return self.conn.execute(
            f'SELECT n.*, {VOTE_COUNT} AS votes FROM names n WHERE n.removed = 0 ORDER BY RANDOM() LIMIT 1'
        ).fetchone()

    # -- votes -----------------------------------------------------------------

    def add_vote(self, name_id: int, user_id: int):
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO votes (name_id, user_id) VALUES (?, ?)', (name_id, user_id))

    def remove_vote(self, name_id: int, user_id: int):
        with self.conn:
            self.conn.execute('DELETE FROM votes WHERE name_id = ? AND user_id = ?', (name_id, user_id))

    def replace_votes(self, name_id: int, user_ids: list[int]):
        """Reconcile with the reactions actually on the card (catches votes made while offline)."""
        with self.conn:
            self.conn.execute('DELETE FROM votes WHERE name_id = ?', (name_id,))
            self.conn.executemany(
                'INSERT OR IGNORE INTO votes (name_id, user_id) VALUES (?, ?)', [(name_id, u) for u in user_ids]
            )

    # -- monthly winners ---------------------------------------------------------

    def undecided_months(self, before_month: str) -> list[str]:
        rows = self.conn.execute(
            'SELECT DISTINCT month FROM names WHERE month < ?'
            ' AND month NOT IN (SELECT month FROM monthly_winners) ORDER BY month',
            (before_month,),
        ).fetchall()
        return [r['month'] for r in rows]

    def names_in_month(self, month: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            'SELECT * FROM names WHERE month = ? AND removed = 0', (month,)
        ).fetchall()

    def record_monthly_winner(self, month: str, name_id: int | None, votes: int, decided_at: datetime):
        with self.conn:
            self.conn.execute(
                'INSERT OR REPLACE INTO monthly_winners (month, name_id, votes, decided_at) VALUES (?, ?, ?, ?)',
                (month, name_id, votes, decided_at.isoformat()),
            )

    def monthly_winners(self, year: int | None = None) -> list[sqlite3.Row]:
        return self.conn.execute(
            'SELECT mw.month, mw.votes, n.* FROM monthly_winners mw JOIN names n ON n.id = mw.name_id'
            ' WHERE mw.month LIKE ? ORDER BY mw.month',
            (f'{year}-%' if year else '%',),
        ).fetchall()

    # -- brackets ----------------------------------------------------------------

    def bracket_entrants(self, year: int, size: int) -> list[sqlite3.Row]:
        """Every monthly winner gets in; remaining spots go to the year's top vote-getters.
        Returned in seed order (most votes first)."""
        winners = self.conn.execute(
            f'SELECT n.*, {VOTE_COUNT} AS votes FROM monthly_winners mw JOIN names n ON n.id = mw.name_id'
            ' WHERE mw.month LIKE ? AND n.removed = 0',
            (f'{year}-%',),
        ).fetchall()
        winner_ids = {r['id'] for r in winners}
        wildcards = [r for r in self.top_names(year=year, limit=size + len(winner_ids))
                     if r['id'] not in winner_ids]
        by_votes = lambda r: (-r['votes'], r['submitted_at'])  # noqa: E731
        entrants = (sorted(winners, key=by_votes) + wildcards)[:size]
        return sorted(entrants, key=by_votes)

    def get_bracket(self, year: int) -> sqlite3.Row | None:
        return self.conn.execute('SELECT * FROM brackets WHERE year = ?', (year,)).fetchone()

    def active_bracket(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM brackets WHERE status = 'active' ORDER BY year LIMIT 1"
        ).fetchone()

    def latest_bracket(self) -> sqlite3.Row | None:
        return self.conn.execute('SELECT * FROM brackets ORDER BY year DESC LIMIT 1').fetchone()

    def create_bracket(self, year: int, seeded_ids: list[int], total_rounds: int, created_at: datetime,
                       first_round: list[tuple[int, int | None]]):
        """Bracket, seeds, and round-1 matches in one transaction. Byes are decided immediately."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO brackets (year, status, current_round, total_rounds, created_at)"
                " VALUES (?, 'active', 1, ?, ?)",
                (year, total_rounds, created_at.isoformat()),
            )
            self.conn.executemany(
                'INSERT INTO bracket_seeds (year, seed, name_id) VALUES (?, ?, ?)',
                [(year, seed, name_id) for seed, name_id in enumerate(seeded_ids, start=1)],
            )
            self.conn.executemany(
                'INSERT INTO matches (year, round, slot, a_id, b_id, winner_id) VALUES (?, 1, ?, ?, ?, ?)',
                [(year, slot, a, b, a if b is None else None) for slot, (a, b) in enumerate(first_round)],
            )

    def open_round(self, year: int, round_: int, pairs: list[tuple[int, int]]):
        """Advance the bracket and create the round's matches atomically, so a crash can't strand it."""
        with self.conn:
            self.conn.execute('UPDATE brackets SET current_round = ? WHERE year = ?', (round_, year))
            self.conn.executemany(
                'INSERT INTO matches (year, round, slot, a_id, b_id) VALUES (?, ?, ?, ?, ?)',
                [(year, round_, slot, a, b) for slot, (a, b) in enumerate(pairs)],
            )

    def seeds(self, year: int) -> dict[int, int]:
        """name_id -> seed"""
        rows = self.conn.execute('SELECT seed, name_id FROM bracket_seeds WHERE year = ?', (year,)).fetchall()
        return {r['name_id']: r['seed'] for r in rows}

    def set_match_poll(self, match_id: int, channel_id: int, message_id: int, ends_at: datetime):
        with self.conn:
            self.conn.execute(
                'UPDATE matches SET poll_channel_id = ?, poll_message_id = ?, ends_at = ? WHERE id = ?',
                (channel_id, message_id, ends_at.isoformat(), match_id),
            )

    def decide_match(self, match_id: int, winner_id: int, a_votes: int, b_votes: int):
        with self.conn:
            self.conn.execute(
                'UPDATE matches SET winner_id = ?, a_votes = ?, b_votes = ? WHERE id = ?',
                (winner_id, a_votes, b_votes, match_id),
            )

    def matches(self, year: int, round_: int | None = None) -> list[sqlite3.Row]:
        if round_ is None:
            return self.conn.execute(
                'SELECT * FROM matches WHERE year = ? ORDER BY round, slot', (year,)
            ).fetchall()
        return self.conn.execute(
            'SELECT * FROM matches WHERE year = ? AND round = ? ORDER BY slot', (year, round_)
        ).fetchall()

    def finish_bracket(self, year: int, winner_id: int):
        with self.conn:
            self.conn.execute(
                "UPDATE brackets SET status = 'done', winner_name_id = ? WHERE year = ?", (winner_id, year)
            )

    def year_winners(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT b.year, n.* FROM brackets b JOIN names n ON n.id = b.winner_name_id"
            " WHERE b.status = 'done' ORDER BY b.year"
        ).fetchall()
