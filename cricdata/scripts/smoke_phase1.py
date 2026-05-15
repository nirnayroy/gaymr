"""Phase 1 smoke: download IPL 2024 Cricsheet ZIP and load into SQLite.

Exits non-zero on failure so this doubles as a regression check.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cricdata.ingest.cricsheet import fetch_zip
from cricdata.scripts.load_sqlite import load

URL = "https://cricsheet.org/downloads/ipl_json.zip"
CACHE = Path(__file__).resolve().parents[1] / ".cache"
ZIP_PATH = CACHE / "ipl_json.zip"
DB_PATH = CACHE / "phase1.sqlite"


def main() -> int:
    print(f"fetching {URL}")
    fetch_zip(URL, ZIP_PATH)
    print(f"loading into {DB_PATH}")
    if DB_PATH.exists():
        DB_PATH.unlink()
    n_matches, n_deliveries = load(ZIP_PATH, DB_PATH)
    print(f"loaded {n_matches} matches, {n_deliveries} deliveries")
    if n_matches < 5 or n_deliveries == 0:
        print("FAIL: expected >=5 matches and >0 deliveries", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
