# gaymr — System Design

Last updated: 2026-05-06.

This document is the canonical source of truth for the gaymr platform's architecture. It is **prescriptive**, not descriptive — it describes how the system *should* be built, and PRs that diverge from it should either update this document first or come with an ADR explaining why.

For phase-by-phase build plans, see the implementation roadmap in the project plan file. For specific decisions, see `docs/adr/`.

---

## 1. What we are building

A cloud gaming platform that streams games from rented NVIDIA GPU nodes to browsers. Users:

1. Sign in (Clerk).
2. Optionally connect their own AWS account (BYOC) via a CloudFormation one-click role.
3. Click "Play" on a game; the platform provisions a GPU node, starts the game, returns a stream URL.
4. The browser receives the stream over WebRTC, decodes via WebCodecs, renders via WebGL, and sends keyboard/mouse/gamepad input back over a data channel.
5. Billing meters GPU-seconds consumed.

Target: 1080p60 H.264 with sub-80 ms round-trip latency. <100 concurrent sessions in year one.

## 2. Hard constraints

- **Latency budget.** Total p95 round-trip <80 ms. This forces:
  - GPU node region close to user (Mumbai for Bengaluru users).
  - Hardware encoding (NVENC, `preset=p1`, no B-frames, GOP=60).
  - WebCodecs decode (no WASM decoders).
  - 60Hz input polling on the browser.
- **Cost control.** Idle GPU instances are the #1 way to lose money. Every session has a watchdog with a hard TTL.
- **Idempotency.** Provisioning, billing, and teardown must all be safe to retry.
- **Trust.** BYOC means we operate inside the user's AWS account. We use external-id-scoped `sts:AssumeRole`, never store long-lived user credentials.

## 3. Architecture (logical view)

### 3.1 Browser client

A Vite-built React app served as static assets from CloudFront. No SSR. WebRTC, WebCodecs, WebGL are all native browser APIs — no WASM components.

| Concern | Module | Notes |
|---|---|---|
| Transport | `web/src/webrtc/` | `RTCPeerConnection`, ICE handling, data channel for input. |
| Decode | `web/src/decoder/` | `VideoDecoder` configured for H.264. AV1 path gated by capability detection. |
| Render | `web/src/renderer/` | WebGL canvas. YUV420 → RGB fragment shader; 3 planar textures (`Y`, `U`, `V`). |
| Input | `web/src/input/` | Pointer Lock + keyboard listeners + Gamepad polling at 60Hz inside `requestAnimationFrame`. |
| API client | `web/src/api/` | Generated from `api/openapi.yaml`; never hand-written. |

### 3.2 Control plane

Four Go services on AWS ECS Fargate. All share one Postgres + one Redis. All emit traces + logs via OpenTelemetry.

| Service | Role | Scale model |
|---|---|---|
| `gaymr-api` | Public REST API. Clerk JWT auth. Behind ALB. Creates sessions, returns signed signaling tokens, exposes billing/credit dashboards. | Horizontal, stateless. |
| `gaymr-orchestrator` | Worker. Consumes asynq jobs to provision and tear down GPU nodes. Runs the watchdog sweeper. Holds the session state machine. | Horizontal, stateless. Multiple replicas race-safe via Postgres row locks. |
| `gaymr-signaling` | WebSocket server. Relays SDP + ICE between browser and node-agent. Sticky-by-session via consistent hash. | Horizontal, sticky. |
| `gaymr-billing-worker` | Consumes `session.ended` events, posts Stripe Usage Records with idempotency keys. | Horizontal, stateless. |

Shared internal packages (no cross-imports between domains except via interfaces):

- `internal/providers/` — GPU provider interface + impls.
- `internal/sessions/` — state machine.
- `internal/signaling/` — SDP/ICE helpers.
- `internal/billing/` — Stripe client.
- `internal/store/` — sqlc-generated DB queries.
- `internal/obs/` — OTel boilerplate.
- `internal/auth/` — Clerk middleware.
- `internal/config/` — typed config loading.

### 3.3 Data plane (GPU node, per session)

Each session gets a fresh EC2 instance (g4dn.xlarge default). On boot, SSM Run Command executes a hardened version of `infra/sunshine-node/provision.sh` (later `infra/gpu-node/provision.sh`). The node runs:

- `gaymr-node-agent` — Go binary. Holds a WebSocket back to the orchestrator. Reports heartbeat, lifecycle events, structured logs. Owns the local game process.
- The game process under `Xvfb` / a real Xorg session driving the GPU.
- A Pion-based WebRTC server (Phase 2) that publishes the encoded H.264 video track + accepts the input data channel.

Phase 1 substitutes Sunshine + moonlight-web for the node-agent + Pion stack — purely as a verification stand-in.

### 3.4 GPU provider abstraction

```go
type Provider interface {
    Provision(ctx context.Context, req SessionRequest) (*Node, error)
    Terminate(ctx context.Context, nodeID string) error
    GetStatus(ctx context.Context, nodeID string) (*NodeStatus, error)
    EstimatedCostPerSecond(sku string) (decimal.Decimal, error)
}
```

Implementations live in `internal/providers/{aws_managed,aws_byoc,vastai,runpod}.go`. Tests use a `fake.go` impl. New providers added by writing one file + a registration entry.

`aws_byoc.go` is the only impl that calls `sts:AssumeRole`. All other impls use long-lived credentials from Secrets Manager.

### 3.5 Data model (Postgres)

```sql
users               -- mirrors Clerk subjects
sessions            -- one row per provisioned/active/terminated session
nodes               -- one row per provisioned GPU instance (1:1 with sessions for now)
gpu_skus            -- pricing table per provider+instance type
billing_events      -- ledger of session.started / session.ended / session.error
gpu_provider_credentials  -- KMS-encrypted, per-user provider keys
byoc_aws_credentials      -- role ARN + hashed external_id, per user
```

Row-level locking on `sessions.status` transitions; no advisory locks. Migrations via `golang-migrate`; rollbacks must be tested before merge.

### 3.6 Redis usage

- **Job queue** for asynq (provision, terminate, sweep).
- **Session TTLs** — heartbeat refreshes a key with TTL=60s; absence triggers the watchdog.
- **Signaling routing** — `signaling:session:<id> → pod_id` for sticky reconnects.
- **Rate limits** — token bucket per user for session creation.

Redis is a cache. Postgres is the source of truth. If Redis dies, sessions still tear down via the orchestrator's reconciliation loop.

## 4. Cross-cutting concerns

### 4.1 Observability

OTel from day 1. One trace covers: HTTP request → orchestrator job → AWS API calls → SSM Run Command → node-agent boot → first frame. Sampling: 100% in dev, 5% in prod, 100% on errors. Backend: Honeycomb (free tier covers MVP).

Structured logs (JSON, `slog`). Every log line carries `trace_id`, `session_id` (when in scope), `user_id` (when in scope).

Metrics published to OTel: session lifecycle counters, p50/p95/p99 latencies for each state transition, provider error rates, watchdog sweeps, Stripe billing posts.

### 4.2 Security

- All secrets in AWS Secrets Manager. Loaded into ECS tasks via task IAM role; never committed.
- TLS everywhere. ALB terminates; mTLS between control plane and node-agent (Phase 2+).
- Clerk JWTs verified per request; no session tokens stored server-side.
- BYOC: external IDs are per-user UUIDs, stored hashed (SHA-256 + salt). Never logged in cleartext.
- WebRTC DTLS-SRTP for video; DTLS-SCTP for the data channel. No fallback to insecure transports.
- DependencyTrack scan in CI; Snyk for high-severity CVEs gates merge.

### 4.3 Configuration

Typed config via `internal/config/`. Sources, in precedence order: env vars > Secrets Manager > defaults. A startup validation step prints the resolved config (with secrets redacted) and exits non-zero on missing required values.

### 4.4 Testing strategy

- **Unit tests** on pure logic: state machine transitions, billing math, SDP parsing, provider request shaping. Fast (<5s for the suite).
- **Integration tests** with `testcontainers-go`: real Postgres + Redis. Cover store/, sessions/, billing/.
- **Provider tests** use a `fake` impl by default; one nightly job runs against real provider sandboxes (where they exist).
- **End-to-end smoke** per phase: a single happy-path script that exercises browser → API → orchestrator → node → stream. Run on every deploy.
- No flaky tests merged. Quarantine and fix or delete.

### 4.5 Deployment

- Trunk-based development. PRs target `main`.
- Merge to `main` → image built, pushed to ECR, deployed to `dev` automatically.
- Tag `vX.Y.Z` → deployed to `prod` via Terraform (`-var image_tag=vX.Y.Z`).
- ECS deployment circuit breaker on; failed health checks roll back.
- Rollback procedure: `terraform apply -var image_tag=<prev>`. Verified quarterly.

### 4.6 Incident response

- On-call rotation tracked in `docs/runbook.md` (written Phase 9).
- Severity-based response times: SEV1 (down) <15 min, SEV2 (degraded) <1 hr.
- Post-incident review for every SEV1/2 → ADR if a structural change is needed.

## 5. Failure modes and how we handle them

| Failure | Detection | Handling |
|---|---|---|
| GPU node fails to boot | Provision job times out (5 min) | Mark session `failed`, refund credits, terminate instance, alert. |
| Node-agent loses connection mid-session | Heartbeat TTL expires | Watchdog terminates instance, marks session `terminated`, partial-bills up to last heartbeat. |
| Provider API down | Circuit breaker opens | New sessions for that provider rejected with retryable error; existing sessions continue. |
| Stripe webhook lost | Reconciliation job (hourly) | Compares Stripe usage to local ledger; emits missing usage records. |
| RDS failover | App reconnects via pgx | In-flight queries fail; retried by job queue. WebSocket connections drop and reconnect. |
| Redis loss | Detected on next op | Queue jobs persist via Postgres outbox (Phase 9); session TTLs reseed from Postgres. |
| TURN saturation | Bytes/sec metric alert | Twilio fallback config kicks in; long-term mitigation is per-region TURN. |
| Bad deploy | Health checks fail | ECS rolls back automatically. Alert fires. |

## 6. What is *not* in this design (intentional)

- A custom Moonlight-protocol bridge. We're going straight to native WebRTC (Phase 2).
- Multi-region active-active. Single primary region (`us-east-1` control plane, GPU nodes wherever), failover is manual.
- Multi-tenant isolation beyond row-level scoping. We are not enterprise/B2B at MVP.
- A queue abstraction. asynq works; if we outgrow it, we go to Temporal — direct migration, no abstraction layer in the meantime.
- A microservices framework. The four binaries share a module; they're "services" only because they have different lifecycles.

## 7. Glossary

- **BYOC** — Bring Your Own Cloud. The user's AWS account hosts the GPU; we orchestrate via cross-account role.
- **NVENC** — NVIDIA's hardware H.264/H.265 encoder.
- **NVFBC** — NVIDIA Frame Buffer Capture; zero-copy framebuffer access on Linux.
- **DLAMI** — AWS Deep Learning AMI; ships with NVIDIA drivers preinstalled.
- **STUN/TURN** — NAT traversal helpers used by WebRTC.
- **SFU** — Selective Forwarding Unit; a WebRTC topology we may use later. Not MVP.
- **Moonlight protocol** — NVIDIA GameStream-compatible streaming protocol (custom, not WebRTC). Used by Sunshine in Phase 1 only.
