# ADR 0001 — Monorepo for backend, frontend, and infra

- Status: Accepted
- Date: 2026-05-06

## Context

The platform has four backend services (`api`, `orchestrator`, `signaling`, `billing-worker`) plus a node-agent that ships with each GPU instance, a TypeScript browser client, Terraform for AWS, and OpenAPI as the contract between client and server. We have to choose between one repo or several.

Multi-repo gets attractive at scale (independent CI, blast radius isolation), but at our size (one or two engineers for the next 6 months) it adds friction every time we change a contract. Cross-repo PRs, version skew, generated-client publishing pipelines — all real costs we'd pay daily.

## Decision

One repo (`gaymr/`) holds: all Go code (backend services + node-agent), the React/TS browser client, OpenAPI spec, Terraform, migrations, docs.

Module layout:

- Root `go.mod` covers everything Go.
- `web/package.json` is its own npm workspace (single-package, no nested workspaces yet).
- `infra/terraform/` is independently `terraform init`-able per environment.

CI runs all jobs in parallel; jobs scope themselves via path filters when desired.

## Consequences

**Positive**

- Atomic refactors across services + client + infra.
- One PR review per change, no cross-repo dance.
- Generated TypeScript client lives next to the OpenAPI spec it's generated from; no publish step.
- Easy to onboard: `git clone` + `make dev` boots everything.

**Negative**

- CI gets slightly slower as the repo grows; we'll add path-based filters when it bites.
- Discipline required to enforce `internal/` package boundaries (linter handles this).
- One repo's bad commit can block deploys for everything; mitigated by per-service CI gates.

**Forecloses**

- Independent open-sourcing of components (would require an extraction effort later).
- Per-service IAM permissions on the repo (we treat the whole repo as one trust boundary).

## Alternatives considered

- **One repo per service.** Rejected: cross-service refactors become PR storms; OpenAPI spec ownership becomes ambiguous.
- **Backend monorepo + separate frontend repo.** Rejected: the OpenAPI contract crossing repos is the daily-pain case; not worth it for 6+ months.

## References

- [Monorepos in Practice (Google)](https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/)
- The handoff doc lists components but is silent on repo structure.
