# Phase 2 — Lift to AWS (Branch B: Athena + S3 Parquet)

**Status:** planned, not started. Decision recorded in [ADR 0005](../docs/adr/0005-cricdata-store.md).

## Why Branch B
Slice-and-dice analytics are in scope. Athena-over-Parquet is the general substrate; DynamoDB can be added later for hot lookups if needed. The reverse retrofit is not possible without re-ingesting.

## Pre-flight gates (do not skip)
1. Phase 1 loads 5 Cricsheet matches into SQLite; Kohli totals spot-checked vs ESPNCricinfo.
2. AWS Budgets alert set at **$1/month** on account `471824291894` before any `cdk deploy`.
3. Region pinned to `ap-south-1`.

## Stack (single CDK app, `cricdata/infra/app.py`)

### Storage
- `s3://gaymr-cricdata-raw-<account>` — Cricsheet ZIPs + CricketData JSON, versioned, lifecycle IA@30d / Glacier@180d
- `s3://gaymr-cricdata-curated-<account>` — partitioned Parquet, no lifecycle (query target)
- `s3://gaymr-cricdata-athena-<account>` — Athena query results, 30d expiry

### Compute
- Lambda `cricsheet_etl` (Python 3.12, 1024MB, 5min timeout) — S3 PUT trigger on `raw/cricsheet/*.zip`; writes partitioned Parquet via `pyarrow`
- Lambda `cricdata_poller` (Python 3.12, 256MB) — EventBridge schedule, **initially disabled**; writes raw JSON to S3 and increments quota
- Both Lambdas packaged with the existing `cricdata/` code via a shared Lambda layer

### Catalog + query
- Glue Database `cricdata`
- Glue tables (declared in CDK, no crawler):
  - `deliveries` — partitions `year`, `format`
  - `matches` — partitions `year`, `format`
- Athena workgroup `cricdata` with **1 GB scan limit per query**

### Quota guard (stays strongly consistent)
- DynamoDB table `api_quota` (PK `date`, TTL 30d, PAY_PER_REQUEST)
- New `cricdata/ingest/dynamo_quota.py` implements the existing `QuotaStore` protocol in [cricdata_poller.py](ingest/cricdata_poller.py) — poller code unchanged

## Code changes
- `cricdata/ingest/parquet_writer.py` — Phase-1 dataclasses → `pyarrow` tables → partitioned write
- `cricdata/ingest/dynamo_quota.py` — quota store backed by DynamoDB
- `cricdata/ingest/store.py` — extract the SQLite write loop from `scripts/load_sqlite.py`; SQLite + Parquet become two impls of one interface
- `cricdata/infra/app.py` + `cricdata/infra/stacks/cricdata_stack.py` — CDK
- `cricdata/infra/README.md` — deploy/destroy runbook

## Partition layout
```
curated/deliveries/year=2024/format=T20/part-<uuid>.parquet
curated/matches/year=2024/format=T20/part-<uuid>.parquet
```
Rationale: year+format are the cheapest pruning keys for the typical question. Keeps file count bounded.

## Verification
1. `cdk deploy` → stack `CREATE_COMPLETE` in ap-south-1
2. Upload one Cricsheet match ZIP to `raw/` → Parquet file lands in `curated/`
3. Athena query: `SELECT COUNT(*) FROM cricdata.deliveries` returns expected delivery count
4. **Quota fail-closed test:** manually set `api_quota[today].hits = 95`, invoke the poller, expect `QuotaExceeded` and **zero** outbound HTTP in CloudWatch
5. `aws budgets describe-budgets` confirms the $1 alert
6. EventBridge schedule remains **disabled** (turning it on is Phase 3)

## Cost expectation
- Backfill of ~10k Cricsheet matches: one-time Lambda + S3 PUT, expect under $0.20
- Steady state: <$0.50/month at personal scale (Athena scans dominated by the 1GB cap)

## Out of scope
- Enabling the live polling schedule (Phase 3)
- User-facing surface (Phase 4, still blocked on Q1, Q2, Q4, Q5)
- Full Cricsheet backfill — Phase 2 only proves the pipeline with a 5-match smoke
