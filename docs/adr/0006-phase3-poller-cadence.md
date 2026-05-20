# ADR 0006 — Phase 3 poller starting cadence: every 4 hours

- Status: Accepted
- Date: 2026-05-15
- Deciders: nroy

## Context

cricdata Phase 3 enables the CricketData.org poller for the first time. The free tier is hard-capped at 100 hits/day and the in-code quota guard fails closed at 95 (5-hit buffer for clock skew, retries, and accidental manual invocations). The PHASE2 plan originally proposed an every-30-min cadence (48 hits/day), which leaves only 47 hits of headroom — fine in theory, brittle in practice because any of the following burns through it quickly: a Lambda retry storm, a manual `aws lambda invoke` during debugging, daylight-saving / clock-skew edge cases around the UTC date rollover, or running the smoke script twice.

The initial enable is a one-way ratchet on observability: until we have 24h of real data with alarms wired, we can't tell whether the cadence is too aggressive without burning the quota.

## Decision

Start the EventBridge schedule at **every 4 hours = 6 hits/day**. Re-evaluate after a clean 24h soak.

## Consequences

- Positive: ~16x headroom under the daily cap. Accommodates a full day of manual debugging without tripping the fail-closed guard.
- Positive: makes the `QuotaExceededFrequent` alarm (>5 quota rejections in 24h) meaningful — at 6 hits/day, that alarm firing genuinely means something is wrong, not just "we're using the budget."
- Negative: 4-hour resolution on "current matches" is too coarse for any live-scoreboard product. That's acceptable because no user-facing surface exists yet (Phase 4 is still blocked on Q1/Q2).
- Forecloses nothing — cadence is a one-line `aws events put-rule --schedule-expression` change.

## Alternatives considered

- **Every 30 min (48/day)** — original PHASE2 default. Rejected for first-enable; revisit after Phase 4 defines a real product need.
- **Hourly (24/day)** — the obvious middle ground. Rejected as the starting point because it costs 4x the daily quota relative to 4h without any current consumer demanding the freshness. Likely the *second* cadence we land on, after the 24h soak.
- **Daily once** — too coarse to be useful even as a smoke; we'd learn nothing about the schedule's failure modes.

## References

- [cricdata/PHASE2.md](../../cricdata/PHASE2.md) — original (now superseded) every-30-min target
- `~/.claude/plans/handover-doc-ready-a-humming-torvalds.md` — Phase 3 plan
- [cricdata/ingest/cricdata_poller.py](../../cricdata/ingest/cricdata_poller.py) — `FAIL_CLOSED_THRESHOLD = 95`
