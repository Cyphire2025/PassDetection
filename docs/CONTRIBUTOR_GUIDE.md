# Contributor reading order and verification map

Owner: repository maintainer (Nipun / Cyphire2025). Reviewed 2026-09-27; next review 2026-12-25.

1. Read the root README for local setup and product scope.
2. Read `docs/architecture/` for component boundaries, then open the actual entry points: `backend/app/main.py`, `backend/app/core/config/settings.py`, `backend/app/presentation/api/v1/routes/`, and `frontend/app/`. Architecture documents describe intent; CI boundary budgets and source remain authoritative where historical plans differ.
3. Use `docs/remediation/status.md` and `docs/remediation/phase-two-plan.md` to distinguish resolved defects, partial controls and deferred operations. Historical audit reports describe the audited revision and are not evidence of current behavior.
4. Before changing deployments, read `docs/IMMUTABLE_RELEASES.md`, `docs/DATABASE_CONNECTION_CAPACITY.md`, and `docs/PRODUCTION_RELEASE_READINESS.md`. Preserve existing database/storage volumes and use the gated current release helper.
5. Check `docs/ENGINEERING_CLAIMS.md` before repeating any security, capacity, availability or compliance claim externally.

| Lane | Entry point | Dependencies and side effects |
| --- | --- | --- |
| Backend quick checks | `python -m ruff check --no-fix app tests`; targeted `python -m pytest --no-cov path/to/test.py` in `backend` | Selected unit tests use SQLite with foreign keys enabled. Read fixture requirements; do not point tests at production. |
| Operator safety contracts | `python -m unittest discover -s scripts -p 'test_*.py'` from repository root | Mostly pure logic and simulated Docker; they do not prove a deployment, restore, registry signature or provider behavior. |
| Backend measured regression | CI `backend-test` | CPython 3.11, hash locks, PostgreSQL fixture, branch coverage and ratchets. Service-only tests are verified in their separate lane. |
| Real service contracts | CI `backend-service-integration` | Dedicated PostgreSQL/Redis/private S3, Celery and stub external provider. Requires explicit synthetic database/endpoint guards; fails if any test skips. |
| Frontend quick checks | `npm run lint`, `npm run type-check`, `npm run test:unit:coverage` in `frontend` | Node and npm from `tooling/toolchain.json`; `npm ci` respects package-lock. Coverage target scope is explicit in config. |
| Browser contracts | CI `frontend-browser` | Playwright Chromium/Firefox/WebKit, fixture APIs; this is distinct from production-image proof. |
| Joined production-image qualification | `scripts/qa/run_qualification_stack.py` and `frontend/playwright.real-stack.config.ts` | Docker, local TLS, synthetic database, object store, antivirus, Redis and workers. Uses fixed disposable QA service names/ports. Never reuse production credentials. |
| Database migration and storage copy | CI rehearsal/qualified storage jobs | Builds and restores synthetic copies; retains bounded receipts. Does not alter the VPS or certify its backups. |
| Signed release promotion | CI `publish-qualified-artifacts` | Requires GitHub attestation eligibility, protected main/release environment, package/release permissions and retained registry storage. Publishes artifacts only; does not deploy. |

Current documentation is the root README, this guide, `IMMUTABLE_RELEASES.md`, capacity guide/table, operational runbooks linked by `docs/remediation/README.md`, and the evidence matrix. Audit snapshots, dated design notes, completed phase proposals and old release helpers are historical unless a current guide explicitly links them as an active contract. Preserve history; do not treat a checked-off implementation plan as a current assurance claim.

The dashboard visa/flight workspace and its scoped MCP access are documented in [TRAVEL_TRACKER.md](TRAVEL_TRACKER.md) and [the MCP architecture contract](architecture/travel-tracker-mcp.md). These guides define canonical client-group membership, safe matching, API bounds, migration order, and the distinction between local SQLite checks and real PostgreSQL concurrency evidence.

The repository maintainer owns documentation review and release decisions. A change to authentication belongs with the security boundary and its tests; a schema change belongs with the migration owner and populated upgrade rehearsal; a new worker/replica belongs with capacity, shutdown/drain, queue and readiness contracts. Reviewers must update the relevant guide and evidence claim in the same change. No native-app changes are implied by this dashboard/backend guide; existing native documentation and release workflows remain separate.
