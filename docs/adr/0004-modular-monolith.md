# ADR 0004 — Modular monolith for the control plane

- Status: Accepted
- Date: 2026-05-06

## Context

The control plane has four logical services (API, orchestrator, signaling, billing-worker). They share most of their domain logic: provider adapters, session state, store layer, observability setup. The question is whether they should be:

1. Four independent services with their own repos, builds, deploys.
2. Four binaries built from one Go module with shared `internal/` packages.
3. One process exposing four HTTP/queue endpoints.

Option (1) is microservices. Option (3) is a true monolith. Option (2) is the modular monolith — one codebase, one set of internal types, but distinct deployable artifacts with different lifecycles.

At MVP scale (<100 concurrent sessions, one to two engineers), microservices would cost weeks of plumbing for benefits we won't realize. A single process bundles too many concerns into one fault domain (API restarts shouldn't terminate active sessions). The modular monolith is the right size.

## Decision

One Go module at the repo root. Four binaries under `cmd/{api,orchestrator,signaling,billing-worker}` plus `cmd/node-agent`. Shared logic in `internal/` packages, organized by domain (`providers/`, `sessions/`, `billing/`, `signaling/`, `store/`, `obs/`, `auth/`, `config/`).

**Hard boundary rule:** internal packages must not import each other across domains except via interfaces defined in the importing package. Enforced in CI by [`go-arch-lint`](https://github.com/fe3dback/go-arch-lint) or similar.

Concretely: `sessions/` may define a `BillingEmitter` interface and depend on it. `billing/` may implement it. `sessions/` may *not* import `billing/` directly.

## Consequences

**Positive**

- One `go test ./...` runs everything.
- Refactors that span "services" are one PR, not four.
- Shared types (`SessionRequest`, `Node`, `BillingEvent`) are defined once, used everywhere — no manual proto-style sync.
- We can always extract a service later (move package, define gRPC boundary, deploy separately) if scale demands it. The boundary discipline today makes that extraction surgical, not a rewrite.

**Negative**

- All services share a Go module version; bumping a dep affects everything (usually fine; occasionally annoying).
- A logic bug in shared code can land in all four services on the same deploy. Mitigation: integration tests cover shared paths; canary deploys to dev first.
- Team scaling beyond ~5 engineers may want stricter ownership boundaries; modular monolith handles 10+ comfortably with ownership at the package level.

**Forecloses**

- Polyglot services (we'd have to extract first if a service genuinely needed Rust/Elixir).
- Per-service dependency versioning.

## Alternatives considered

- **Microservices from day 1.** Rejected: high operational tax (separate deploys, network IPC, distributed tracing complexity, schema sync) for benefits we don't need at this scale. Premature.
- **Single process.** Rejected: API and orchestrator have different scaling needs (orchestrator is CPU-light/IO-heavy and bursty; API is steady), and we want independent restart blast radius (an orchestrator deploy shouldn't drop user sessions).
- **gRPC between four separate Go modules.** Rejected: gives us most of the costs of microservices with few of the benefits when the binaries are still co-deployed in one ECS cluster.

## References

- [Modular Monoliths (Shopify)](https://shopify.engineering/shopify-monolith)
- ADR 0001 — monorepo (sibling decision).
- ADR 0002 — ECS Fargate (each binary becomes one ECS service).
