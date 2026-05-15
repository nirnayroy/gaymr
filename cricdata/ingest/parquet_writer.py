"""Parquet impl of the Store protocol — Phase 2 backend.

Writes partitioned Parquet at:
    s3://<bucket>/<prefix>/matches/year=YYYY/format=FMT/part-<uuid>.parquet
    s3://<bucket>/<prefix>/deliveries/year=YYYY/format=FMT/part-<uuid>.parquet

Partitioning by (year, format) prunes the typical analytical query
(season + format) without exploding into a per-match small-file problem.
Files are buffered per partition and flushed on close, so a single
Cricsheet ZIP load produces O(#partitions) files, not O(#matches).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from io import BytesIO
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from cricdata.schema.models import Delivery, Match


class ParquetStore:
    def __init__(self, s3_client: Any, bucket: str, prefix: str = "curated"):
        self.s3 = s3_client
        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        self._matches: dict[tuple[int, str], list[dict]] = defaultdict(list)
        self._deliveries: dict[tuple[int, str], list[dict]] = defaultdict(list)

    def write(self, match: Match, deliveries: list[Delivery]) -> None:
        key = (match.date.year, match.format)
        self._matches[key].append({
            "match_id": match.match_id,
            "date": match.date.isoformat(),
            "venue": match.venue,
            "team_home": match.team_home,
            "team_away": match.team_away,
            "winner": match.winner,
        })
        for d in deliveries:
            self._deliveries[key].append({
                "match_id": d.match_id,
                "innings": d.innings,
                "over": d.over,
                "ball": d.ball,
                "batter": d.batter,
                "bowler": d.bowler,
                "non_striker": d.non_striker,
                "runs_batter": d.runs_batter,
                "runs_extras": d.runs_extras,
                "runs_total": d.runs_total,
                "wicket_kind": d.wicket_kind,
                "player_out": d.player_out,
            })

    def close(self) -> None:
        for (year, fmt), rows in self._matches.items():
            self._flush("matches", year, fmt, rows)
        for (year, fmt), rows in self._deliveries.items():
            self._flush("deliveries", year, fmt, rows)
        self._matches.clear()
        self._deliveries.clear()

    def _flush(self, table: str, year: int, fmt: str, rows: list[dict]) -> None:
        if not rows:
            return
        table_arrow = pa.Table.from_pylist(rows)
        buf = BytesIO()
        pq.write_table(table_arrow, buf, compression="snappy")
        key = f"{self.prefix}/{table}/year={year}/format={fmt}/part-{uuid.uuid4()}.parquet"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=buf.getvalue())
