"""Storage interface for Cricsheet records.

The same iterator from `cricsheet.iter_matches` feeds two impls:
  - `SqliteStore` for Phase 1 (local prototype)
  - `ParquetStore` for Phase 2 (S3 + Athena)

Call sites should depend on `Store`, not on either impl directly.
"""

from __future__ import annotations

from typing import Protocol

from cricdata.schema.models import Delivery, Match


class Store(Protocol):
    def write(self, match: Match, deliveries: list[Delivery]) -> None: ...
    def close(self) -> None: ...
