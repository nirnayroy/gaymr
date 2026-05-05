# ADR 0002 — Control plane on AWS ECS Fargate

- Status: Accepted
- Date: 2026-05-06

## Context

The control plane (API, orchestrator, signaling, billing-worker, coturn) needs a hosting target. Options: Fly.io, AWS ECS Fargate, AWS EKS (Kubernetes), Heroku, Render. The data plane (GPU nodes) is firmly AWS EC2.

Constraints:

- We provision EC2 instances in user-owned AWS accounts (BYOC). Operating the control plane in AWS makes the IAM story coherent: one cloud, one trust model, AssumeRole works without VPN.
- MVP scale (<100 concurrent sessions) doesn't need k8s. EKS would burn weeks we don't have.
- We need to ship something working in 6–8 weeks, then iterate.

## Decision

Run all control-plane services on ECS Fargate in `us-east-1`. One cluster, one service per binary, ALB in front of `api` and `signaling`. RDS Postgres, ElastiCache Redis, Secrets Manager, ECR — all AWS native.

GPU nodes still launch on EC2 in whichever region is closest to the user (`ap-south-1` for our first user).

## Consequences

**Positive**

- IAM roles for tasks: each service gets least-privilege creds without storing keys.
- Native VPC peering / private endpoints between control plane (`us-east-1`) and GPU nodes.
- AWS BYOC users keep everything inside AWS-trust boundaries; no inter-cloud egress charges except for browser traffic (which goes direct over WebRTC anyway).
- No node management — Fargate handles it.
- Terraform-native; the entire control plane is reproducible from code.

**Negative**

- Fargate is more expensive per-CPU than EC2-backed ECS (~20–30% premium). At MVP scale the absolute cost is small (<$200/month).
- ECS deploys are slower than `fly deploy` (3–5 min vs 30s).
- Region choice (`us-east-1`) means signaling RTT to Bengaluru users is ~250 ms — but signaling is pre-stream control traffic, not the game stream itself. Stream latency is unaffected because video flows browser ↔ GPU node directly.

**Forecloses**

- Cross-cloud control plane (we'd need a major refactor to leave AWS).
- Edge-deployed signaling (would need Lambda@Edge or a CDN-worker layer added later).

## Alternatives considered

- **Fly.io.** Faster to deploy, simpler ops. Rejected because BYOC's STS AssumeRole flow benefits from being inside AWS, and control plane → GPU node API calls are tighter in-cloud. The "ship faster" benefit is real but only saves us ~1 week up front; we'd then pay it back on integration friction over months.
- **AWS EKS (Kubernetes).** Right answer at scale; wrong answer for MVP. Operator burden is large, debugging is harder, and we don't need any k8s primitive yet (no autoscaling complexity, no service mesh need).
- **Render / Heroku.** Underpowered for a workload that holds long-lived WebSockets and runs jobs against AWS APIs.

## References

- ADR 0004 — modular monolith deployment unit (sibling decision).
- AWS ECS deployment circuit breaker docs.
