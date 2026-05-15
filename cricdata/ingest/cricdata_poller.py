"""CricketData.org live poller with a fail-closed quota guard.

The free tier allows 100 hits/day. We fail closed at 95 to leave a 5-hit
buffer for clock skew and retries. **Do not lower this threshold.**

Phase 1 backs the quota table with SQLite; Phase 3 swaps the backend for
DynamoDB without changing the call sites.
"""

from __future__ import annotations

import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

DAILY_LIMIT = 100
FAIL_CLOSED_THRESHOLD = 95  # do not change without re-reading the handover doc


class QuotaExceeded(RuntimeError):
    pass


class QuotaStore(Protocol):
    def get(self, day: str) -> int: ...
    def increment(self, day: str) -> int: ...


class SqliteQuotaStore:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS api_quota (date TEXT PRIMARY KEY, hits INTEGER NOT NULL)"
        )
        self.conn.commit()

    def get(self, day: str) -> int:
        cur = self.conn.execute("SELECT hits FROM api_quota WHERE date = ?", (day,))
        row = cur.fetchone()
        return row[0] if row else 0

    def increment(self, day: str) -> int:
        self.conn.execute(
            "INSERT INTO api_quota(date, hits) VALUES (?, 1) "
            "ON CONFLICT(date) DO UPDATE SET hits = hits + 1",
            (day,),
        )
        self.conn.commit()
        return self.get(day)


class Poller:
    def __init__(self, api_key: str, store: QuotaStore, base_url: str = "https://api.cricapi.com/v1"):
        self.api_key = api_key
        self.store = store
        self.base_url = base_url.rstrip("/")

    def _today_utc(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def call(self, endpoint: str, params: dict | None = None) -> dict:
        day = self._today_utc()
        if self.store.get(day) >= FAIL_CLOSED_THRESHOLD:
            raise QuotaExceeded(
                f"refusing API call: {self.store.get(day)} hits today (threshold {FAIL_CLOSED_THRESHOLD}/{DAILY_LIMIT})"
            )
        q = dict(params or {})
        q["apikey"] = self.api_key
        url = f"{self.base_url}/{endpoint.lstrip('/')}?{urllib.parse.urlencode(q)}"
        self.store.increment(day)
        with urllib.request.urlopen(url) as resp:
            import json
            return json.load(resp)
