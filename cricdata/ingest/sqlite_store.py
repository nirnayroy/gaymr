"""SQLite impl of the Store protocol — Phase 1 prototype backend."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cricdata.schema.models import Delivery, Match

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
    format     TEXT NOT NULL,
    venue      TEXT,
    team_home  TEXT NOT NULL,
    team_away  TEXT NOT NULL,
    winner     TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_date_format ON matches(date, format);

CREATE TABLE IF NOT EXISTS deliveries (
    match_id     TEXT NOT NULL,
    innings      INTEGER NOT NULL,
    over         INTEGER NOT NULL,
    ball         INTEGER NOT NULL,
    batter       TEXT NOT NULL,
    bowler       TEXT NOT NULL,
    non_striker  TEXT NOT NULL,
    runs_batter  INTEGER NOT NULL,
    runs_extras  INTEGER NOT NULL,
    runs_total   INTEGER NOT NULL,
    wicket_kind  TEXT,
    player_out   TEXT,
    PRIMARY KEY (match_id, innings, over, ball)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_batter ON deliveries(batter);
CREATE INDEX IF NOT EXISTS idx_deliveries_bowler ON deliveries(bowler);
"""


class SqliteStore:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)

    def write(self, match: Match, deliveries: list[Delivery]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?)",
            (match.match_id, match.date.isoformat(), match.format, match.venue,
             match.team_home, match.team_away, match.winner),
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(d.match_id, d.innings, d.over, d.ball, d.batter, d.bowler,
              d.non_striker, d.runs_batter, d.runs_extras, d.runs_total,
              d.wicket_kind, d.player_out) for d in deliveries],
        )

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
