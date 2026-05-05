# ADR 0003 — Use Clerk for authentication

- Status: Accepted
- Date: 2026-05-06

## Context

We need user signup/login, session management, password reset, email verification, and eventually SSO and team accounts. Building these is well-understood but unrewarding work — none of it differentiates a cloud gaming platform. Outsourcing it lets a small team focus on the streaming pipeline, billing, and provider abstraction.

Cost matters: at <100 concurrent / ~1K MAU we're well inside Clerk's free tier; the marginal cost stays small until ~50K MAU.

## Decision

Use Clerk for:

- Signup, signin, OAuth (Google initially).
- Session JWTs, refresh handling.
- Password reset, email verification flows.
- (Future) Org/team management for shared billing accounts.

The browser client uses Clerk's React SDK. The Go backend verifies Clerk JWTs in middleware (`internal/auth/`). A `users` row is lazy-created in our Postgres on first authenticated request, keyed by Clerk's stable `sub` claim. We never store passwords.

## Consequences

**Positive**

- Zero auth code to maintain. No password hashing, no email-sending, no session-rotation bugs.
- MFA, magic links, social login come for free.
- Their hosted UI is acceptable; we override only where brand matters.
- Switching off Clerk later is feasible because we keep our own `users` table (Clerk `sub` ↔ our `user_id`).

**Negative**

- Vendor lock-in for the auth flow. Migrating away requires an email-verification re-run for all users.
- Network dependency on Clerk for every signin. Their uptime is excellent but not ours to control.
- ~$25/mo from ~10K MAU; rises with active users.
- We can't gate features by "is the user's email verified?" without leaning on Clerk's claims.

**Forecloses**

- A fully self-hosted auth story (would require Phase-11+ migration if we ever need it).
- Custom auth flows that need server-side state mid-flow (e.g. multi-step KYC).

## Alternatives considered

- **Supabase Auth.** Cheaper at scale; tighter Postgres integration. Rejected because we don't use Supabase for the database (we have RDS for control over migrations and AWS-native networking), so the integration story is less compelling than Clerk's pure-auth offering.
- **Roll our own.** Adds 1–2 weeks of auth work that nobody will thank us for and that has well-known pitfalls. Rejected on opportunity-cost grounds.
- **AWS Cognito.** Free at our scale, AWS-native. Rejected because the developer experience is famously rough and the UI customization story is poor — we'd burn the savings on frustration.

## References

- [Clerk JWT verification](https://clerk.com/docs/backend-requests/handling/manual-jwt)
- ADR 0004 — keeping a local `users` table to preserve our migration optionality.
