# Enforced dependency and transaction contract

Reviewed 27 September 2026. Owner: repository maintainers, with security review for authorization/session boundaries. Next review: 31 December 2026.

This is a modular monolith with domain rules, application DTOs, application transaction services, infrastructure adapters and HTTP presentation. It does not claim strict hexagonal isolation for every application module. Moving active, carefully locked transactions behind trivial interfaces would not by itself improve their safety.

The domain may not import application, database/infrastructure, FastAPI or Starlette. Application code may not import presentation or HTTP frameworks. Shared validated notification, attestation and push-registration inputs now belong to application DTO modules; HTTP schemas re-export them without reversing that dependency. Notification workflows raise framework-independent semantic failures; only the HTTP adapter maps them to status codes, preserving the existing response messages and fields.

The exact infrastructure imports of existing application transaction services are declared in `backend/architecture-dependencies.json`. Entries have a reason, owner and review date. The checker rejects new edges, new unreviewed modules, expired reviews, stale entries and dynamic import bypasses. It checks function-local and type-only imports as well as module-level imports. Removing an import requires removing its allowance. This policy is an explicit design contract, not a claim that every existing dependency has been removed.

| Service family | Why the explicit adapter dependency exists | Transaction ownership |
| --- | --- | --- |
| Authorization and session services | Tenant/lifecycle decisions must compose SQL scopes and read current revocation state | Caller owns the request transaction; destructive workflows acquire ordered parent locks before mutation |
| Notification, device and synchronization services | Durable recipient/delivery/journal records must change atomically with their source state | Workflow caller owns commit; dispatch and receipt helpers document their own claim/commit boundaries |
| Passport extraction workflows | The durable job ledger and passport state must agree through retries and provider failures | Use-case methods own documented stage transitions; provider effects remain outside open long-running transactions |
| Attendance/email projections | Query-specific aggregates and conservative document matching are adapter-dependent services | Read transaction belongs to the caller; no implicit unrelated mutation |

New domain rules and deterministic calculations should remain pure and independently tested. New transaction-service imports require an explicit policy change and review of lock order, tenant scope, retries, and commit ownership. Do not expand the policy simply to make CI green. The existing authorization role/tenant/lifecycle tests and notification success/denial/idempotency tests remain behavior gates.

`python backend/scripts/verify_architecture_boundaries.py` runs without application imports or external services. Unit tests also import and execute selected application DTO/preview rules while actively rejecting FastAPI/Starlette imports. This does not prove the complete runtime graph is acyclic or that dynamic plugins outside these layers are safe.
