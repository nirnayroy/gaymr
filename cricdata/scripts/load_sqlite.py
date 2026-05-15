"""Phase 1 entry point: load a Cricsheet ZIP into a local SQLite DB.

Usage:
    python -m cricdata.scripts.load_sqlite <zip_path> <sqlite_path>
"""

from __future__ import annotations

import sys
from pathlib import Path

from cricdata.ingest.cricsheet import iter_matches
from cricdata.ingest.sqlite_store import SqliteStore


def load(zip_path: Path, db_path: Path) -> tuple[int, int]:
    store = SqliteStore(db_path)
    n_matches = n_deliveries = 0
    try:
        for match, deliveries in iter_matches(zip_path):
            store.write(match, deliveries)
            n_matches += 1
            n_deliveries += len(deliveries)
    finally:
        store.close()
    return n_matches, n_deliveries


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    m, d = load(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"loaded {m} matches, {d} deliveries")
