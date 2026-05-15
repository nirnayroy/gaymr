"""Phase 1 entry point: load a Cricsheet ZIP into a local SQLite DB.

Usage:
    python -m cricdata.scripts.load_sqlite <zip_path> <sqlite_path>
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from cricdata.ingest.cricsheet import iter_matches

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


def load(zip_path: Path, db_path: Path) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    n_matches = n_deliveries = 0
    for match, deliveries in iter_matches(zip_path):
        conn.execute(
            "INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?)",
            (match.match_id, match.date.isoformat(), match.format, match.venue,
             match.team_home, match.team_away, match.winner),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(d.match_id, d.innings, d.over, d.ball, d.batter, d.bowler,
              d.non_striker, d.runs_batter, d.runs_extras, d.runs_total,
              d.wicket_kind, d.player_out) for d in deliveries],
        )
        n_matches += 1
        n_deliveries += len(deliveries)
    conn.commit()
    conn.close()
    return n_matches, n_deliveries


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    m, d = load(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"loaded {m} matches, {d} deliveries")
