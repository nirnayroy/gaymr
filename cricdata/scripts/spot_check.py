"""Spot-check: Kohli's batter runs in IPL 2024 match RCB vs CSK (2024-03-22).

Cross-reference against ESPNCricinfo:
  https://www.espncricinfo.com/series/indian-premier-league-2024-1410320/chennai-super-kings-vs-royal-challengers-bengaluru-1st-match-1422119/full-scorecard
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / ".cache" / "phase1.sqlite"
MATCH_ID = "1422119"
BATTER = "V Kohli"


def main() -> int:
    if not DB_PATH.exists():
        print(f"FAIL: {DB_PATH} missing — run smoke_phase1 first", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB_PATH)

    runs = conn.execute(
        "SELECT COALESCE(SUM(runs_batter), 0) FROM deliveries WHERE match_id=? AND batter=?",
        (MATCH_ID, BATTER),
    ).fetchone()[0]
    balls = conn.execute(
        "SELECT COUNT(*) FROM deliveries WHERE match_id=? AND batter=? AND (wicket_kind IS NULL OR wicket_kind != 'wides')",
        (MATCH_ID, BATTER),
    ).fetchone()[0]

    distinct_batters = conn.execute(
        "SELECT COUNT(DISTINCT batter) FROM deliveries WHERE match_id=?",
        (MATCH_ID,),
    ).fetchone()[0]

    print(f"match {MATCH_ID}: distinct batters = {distinct_batters}")
    print(f"{BATTER}: {runs} runs off {balls} balls (faced)")
    print("compare to: https://www.espncricinfo.com/series/indian-premier-league-2024-1410320/chennai-super-kings-vs-royal-challengers-bengaluru-1st-match-1422119/full-scorecard")

    if distinct_batters == 0:
        print(f"FAIL: match {MATCH_ID} not in DB", file=sys.stderr)
        return 1
    if runs == 0:
        print(f"WARN: 0 runs for '{BATTER}' — check Cricsheet's player-name spelling in this match", file=sys.stderr)
        sample = conn.execute(
            "SELECT DISTINCT batter FROM deliveries WHERE match_id=? ORDER BY batter",
            (MATCH_ID,),
        ).fetchall()
        print("batters in this match:", [r[0] for r in sample])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
