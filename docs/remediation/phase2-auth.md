# Phase 2 authentication qualification — 2026-09-27

This is local candidate evidence, not a deployed VPS claim. Native application directories were not changed.

| Finding | Candidate behavior |
| --- | --- |
| SEC-02 | Dashboard JWTs carry a durable session ID checked by HTTP and realtime authorization. Logout through access or refresh credentials revokes that family, including a concurrent refresh successor. Copied cookies/bearers fail; unrelated sessions survive. Logout-all retains account-generation fencing and revokes every family. |
| SEC-03 | Known consumed refresh-token reuse revokes successor refresh credentials and all access JWTs from that sign-in, records a chained audit event and creates an internal security notification for agency users. Unknown random credentials cannot revoke another family. Genuine concurrent transactions that observed the unconsumed row before the winning commit receive `409 REFRESH_IN_PROGRESS`; a later replay receives 401 and revokes the family. This uses database visibility, not client timestamps or a post-commit grace period. |
| SEC-05 | Redis atomically reserves account, IP and global budgets before bcrypt: respectively 20, 120 and 1200 attempts per 60-second window. The failed account+IP lockout remains. Changing IPs and successful authentication do not clear the account budget. Denials do not extend the window; counters lacking a TTL gain a bounded expiry. Unknown, inactive and unassigned mobile identities incur one verifier operation and the same credential error. |
| PERF-01 | All asynchronous password hash/verify callers use bounded off-thread work: four admitted jobs per event loop and no unbounded expensive-work queue. Overload returns dependency-unavailable. Request cancellation retains the slot until the underlying worker finishes. |
| API-03 | Password creation/change/reset enforce at most 72 UTF-8 bytes before bcrypt. Exact-boundary ASCII and multibyte controls work. New overflow is rejected, never truncated. Verification preserves older bcrypt's first-72-byte equivalence so previously valid long credentials remain usable after the bcrypt 5 upgrade. |

Migration `0109_dashboard_sessions` deliberately invalidates pre-migration **dashboard** refresh credentials while retaining their rows under revoked cutover families. JWTs without a session claim are rejected. Dashboard users sign in once after this update. Passwords, MFA configuration, account generation and native mobile session rows/generation are unchanged by the migration.

The web client retries only `REFRESH_IN_PROGRESS` once after one second within existing same-tab/cross-tab coordination. A 401 follows the normal sign-in redirect without recursion. Rotation preserves the original deadline and MFA assurance. A lost refresh response followed by later reuse of its old credential requires signing in again; this is deliberately not an unlimited replay grace period.

Budgets expire rather than permanently disabling an account. An attacker can still consume a victim's short admission window; existing authenticated sessions are unaffected. The security notice is internal to the application, not an external operational alert.

Legacy bcrypt hashes do not encode whether an original password exceeded 72 bytes. Login verification therefore preserves the first-72-byte behavior for retained hashes, including multibyte input; differing suffix bytes beyond that boundary cannot be distinguished. No password/account row is rewritten and no password reset is forced. All newly chosen passwords are byte-bounded before hashing.

## Evidence

- Focused HTTP, repository, MFA, refresh, logout, password, mobile backend compatibility, menu and traveller suite: **155 passed in 137.58s** (`outputs/phase2-auth-final.txt`).
- Follow-up retained-password compatibility and bounded worker tests: **15 passed in 1.08s** (`outputs/phase2-auth-legacy-compatibility.txt`). Real bcrypt fixtures verify original long ASCII/multibyte credentials through the login use case, reject an incorrect first-72-byte prefix, and keep new-password overflow rejected.
- Actual isolated PostgreSQL and Redis: **7 passed in 36.26s** (`outputs/phase2-auth-services-final.txt`). Includes refresh/refresh and refresh/logout concurrency, forty Redis clients changing IPs, IP/global budgets, expiry/no-TTL repair, and real 0109 cutover preservation.
- Six concurrency/budget cases repeated with the restricted runtime database identity: **6 passed in 33.31s** (`outputs/phase2-auth-restricted-services-final.txt`).
- Fresh `passdetection_ci_auth` database migration and role qualification: **18 PostgreSQL privilege, DSN and row-preservation assertions passed**, including idempotent provisioning (`outputs/phase2-auth-roles.txt`). Role provisioning discovers and grants the new session table.
- Actual 0109 operations in a rolled-back schema preserve legacy refresh IDs/deadlines, password/MFA, account generation and mobile state while revoking only dashboard credentials.
- Scoped Ruff: **passed** (`outputs/phase2-auth-ruff.txt`). Whole-app mypy at this checkpoint: **684 files, no issues** (`outputs/phase2-auth-mypy-final.txt`). Broader integrated checks remain with the coordinating workstream.

Implementation: `backend/app/infrastructure/database/dashboard_session_models.py`, `backend/alembic/versions/0109_dashboard_sessions.py`, session/refresh repositories, auth use cases and boundaries, `backend/app/infrastructure/security/login_attempt_limiter.py`, `backend/app/core/security/password.py`, and the shared password-schema callers. Regression tests: `test_dashboard_session_families.py`, `test_auth_concurrency.py`, `test_dashboard_session_cutover.py`, `test_password_work_budget.py`, `test_mobile_login_password_work.py`, plus updated existing auth and workflow fixtures.

Only disposable local PostgreSQL/Redis qualification services were used. No production database, live credential, provider account or native application was modified. Raw diagnostics remain ignored in `outputs/`; this report retains compact outcomes.
