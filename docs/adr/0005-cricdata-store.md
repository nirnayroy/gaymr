# ADR 0005 — cricdata primary store: Athena over S3 Parquet

- Status: Accepted
- Date: 2026-05-15
- Deciders: nroy

## Context

cricdata Phase 2 needs a primary store on AWS. The shape of queries the project intends to answer includes ad-hoc analytical slices (e.g. "Kohli vs left-arm spin in death overs"). The handover doc flagged this as the decision that gates Phase 2 — DynamoDB cannot serve those queries without re-ingesting into something else. Scale is personal (Cricsheet ~10k matches, ~2M deliveries; CricketData free tier 100 hits/day), so cost-per-query matters more than throughput.

## Decision

Use **Athena over partitioned Parquet in S3** as the primary store for matches and deliveries. Keep DynamoDB only for the strongly-consistent `api_quota` table that backs the fail-closed poller guard.

## Consequences

- Positive: ad-hoc SQL works out of the box; no servers; pay-per-query; trivial to dump to a notebook; future ML/feature work can read Parquet directly.
- Positive: existing `QuotaStore` protocol means the poller swaps SQLite → DynamoDB with one new file and no call-site changes.
- Negative: no sub-100ms point lookups. If a user-facing surface (Phase 4) needs them, layer DynamoDB or a cache on top — that is an additive change, not a rewrite.
- Negative: small-file problem if partitions are too granular; mitigated by year+format partitioning, no per-match partition.
- Forecloses: DynamoDB-as-primary. Reverting would require re-ingesting everything.

## Alternatives considered

- **DynamoDB as primary (Branch A in PHASE2 plan)** — rejected because slice-and-dice analytics are in scope; DynamoDB cannot answer them and the retrofit cost is total re-ingest.
- **RDS Postgres** — rejected for Phase 2: idle compute cost breaks the "stays in free tier" target from the handover; revisit only if Phase 4 needs heavy joins.
- **Glue crawler instead of declared tables** — rejected; partitions are deterministic, crawler adds cost and a moving part for no gain.

## References

- [cricdata/PHASE2.md](../../cricdata/PHASE2.md)
- Handover doc: `~/.claude/plans/handover-doc-ready-a-humming-torvalds.md`
- [cricdata/ingest/cricdata_poller.py](../../cricdata/ingest/cricdata_poller.py) — `QuotaStore` protocol the DynamoDB impl will satisfy
