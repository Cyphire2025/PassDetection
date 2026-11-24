# Enterprise real-stack QA lane

This lane exercises the production Next.js bundle through a real FastAPI
process backed by migrated PostgreSQL and Redis. MinIO and a Celery worker are
also required for the complete backend service-contract file. Use only an
isolated disposable QA database and object-storage bucket; the deterministic
browser seed updates the UUID namespace reserved for this test lane.

## Required services

- PostgreSQL with the repository's current Alembic head applied.
- Redis reachable by both FastAPI and Celery.
- Private S3-compatible storage for the complete service-contract suite.
- FastAPI at `REAL_STACK_API_BASE_URL` (default `http://127.0.0.1:58000`).

The seed process and FastAPI must receive the same `APP_SECRET_KEY` and identity
key-ring settings. Otherwise the intentionally encrypted test MFA secrets
cannot be verified. Never point these commands at production or a shared
developer database.

## Backend preparation

From `backend/`, export the isolated PostgreSQL, Redis, S3, and application
settings, then run:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe ..\scripts\qa\seed_enterprise_browser_stack.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 58000
```

The seed prints the fixture identifiers and development-only credentials as
JSON. Raw recovery tokens, access tokens, QR values, and passenger document
data are never emitted.

## Production dashboard and browsers

The API rewrite is embedded in the Next.js routes manifest at build time. From
`frontend/`, bind it before building, install both browser engines, and run the
explicit opt-in configuration:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:58000'
$env:NEXT_PUBLIC_APP_URL='http://127.0.0.1:3200'
npm run build -- --webpack
npx playwright install chromium webkit
$env:RUN_REAL_STACK='1'
$env:REAL_STACK_API_BASE_URL='http://127.0.0.1:58000'
npx playwright test --config=playwright.real-stack.config.ts
```

The Playwright configuration starts `.next/standalone/server.js`, after copying
the generated static and public assets exactly as the production container
does. It refuses to collect tests without `RUN_REAL_STACK=1`, so a missing real
stack cannot be mistaken for a passing mocked lane.

The browser projects use separate seeded manager accounts to avoid TOTP replay
collisions while running Chromium, WebKit, and a mobile Chromium viewport.
Reseed before a repeated run to reset deterministic fixture state.

## Backend service contracts

Start a Celery worker subscribed to `enterprise-ci` with the same isolated
settings, then run from `backend/`:

```powershell
$env:RUN_SERVICE_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/service_integration/test_real_service_contracts.py -q -s
```

The file covers migrated PostgreSQL behavior, Redis atomicity, real
authentication/session persistence, private MinIO cleanup, transaction-first
storage tombstones, append-only audit enforcement, runtime/discard tenant
isolation, multi-device closeout, a 25-coordinator/800-passenger attendance
burst, broker round trips, and idempotent lifecycle task execution.
