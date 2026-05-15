# cricdata

Cricket data pipeline — lives inside the gaymr repo but is independent of the cloud-gaming work.

See the approved handover at `~/.claude/plans/handover-doc-ready-a-humming-torvalds.md` for full context.

## Phase 1 (current): local SQLite prototype

No AWS spend. Goal: parse Cricsheet JSON into SQLite and spot-check totals.

```
cricdata/
  ingest/          Cricsheet downloader + parser, CricketData poller
  schema/          Shared dataclasses / pydantic models
  scripts/         Phase-1 entry points (load_sqlite.py)
  infra/           CDK app — Phase 2+
  tests/
```

## Non-negotiables

- Preserve the **95-hit/day fail-closed quota guard** on the CricketData poller.
- No AWS provisioning until Phase 1 works end-to-end against SQLite.
- All timestamps UTC; quota table keyed on UTC date.
- Cricsheet data is CC-BY-4.0 — attribution required if surfaced publicly.

## Open questions (must resolve before Phase 4)

1. What does the app *do* for the end user?
2. Surface: web / mobile / CLI?
3. Slice-and-dice analytics in scope? If yes, DynamoDB is wrong — use Athena+Parquet or Postgres.
4. Single-user or multi-user with auth?
5. Acceptable to live within the 100-hits/day free tier?
