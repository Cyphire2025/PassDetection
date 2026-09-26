# Global Connects Dashboard - Passport OCR Platform

Passport processing platform for travel agencies. Production readiness depends on
the tested release and deployed controls; see the [current release procedure](docs/PRODUCTION_RELEASE_READINESS.md)
and [recovery evidence requirements](docs/PRODUCTION_RESILIENCE_AND_DR.md).


Engineering assurance is bounded by the [evidence and claim register](docs/ENGINEERING_CLAIMS.md). Start with the [contributor reading order and test map](docs/CONTRIBUTOR_GUIDE.md). Production activation requires the [signed qualified image inventory](docs/IMMUTABLE_RELEASES.md); local builds alone do not establish enterprise readiness.

## Architecture

Layered architecture organized around domain entities, application workflows,
infrastructure adapters and presentation. Some application modules still import
infrastructure or presentation code; strict dependency inversion is a work in progress.

```text
backend/
  app/
    core/           # Config, logging, security - cross-cutting concerns
    domain/         # Entities, exceptions, repository interfaces (zero deps)
    application/    # Use cases, DTOs, application interfaces
    infrastructure/ # DB, S3, OCR adapters, repository implementations
    presentation/   # FastAPI routes, schemas, middleware

frontend/
  app/              # Next.js App Router (route groups, pages, layouts)
  components/       # Reusable UI: ui/ layout/ shared/
  features/         # Feature modules: auth/ dashboard/ passports/ upload/
  hooks/            # Global custom hooks
  stores/           # Zustand state stores
  types/            # TypeScript type definitions
  constants/        # Routes, query keys, labels
  lib/              # API client, utilities
  providers/        # React context providers
```

## Tech Stack

| Layer       | Technology                                    |
|-------------|-----------------------------------------------|
| Frontend    | Next.js 16, TypeScript, Tailwind CSS          |
| State       | TanStack Query, Zustand, React Hook Form + Zod |
| Backend     | Python 3.11, FastAPI, Pydantic, SQLAlchemy    |
| Database    | PostgreSQL 16                                 |
| Cache/Queue | Redis 7                                       |
| Storage     | S3-compatible (MinIO for local dev)           |
| OCR         | PaddleOCR, EasyOCR, Tesseract (pluggable)     |
| Proxy       | Nginx                                         |
| Container   | Docker + Docker Compose                       |
| CI/CD       | GitHub Actions                                |

## Quick Start

### Prerequisites

- Docker Desktop
- Node.js 24+
- Python 3.11 (the supported backend line is `>=3.11,<3.12`)

### 1. Copy environment file

```bash
cp .env.example .env
# Edit .env and fill in all required values
```

### 2. Start full stack

```bash
docker compose up --build
```

Services:

- Frontend: https://localhost
- Backend API: https://localhost/api/v1
- API Docs: https://localhost/docs
- MinIO Console: http://localhost:9001

### 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 4. Seed the first super admin

Set the required email and password in your shell, then pass them into the backend container:

```bash
export ADMIN_EMAIL="owner@example.com"
read -r -s -p "Admin password: " ADMIN_PASSWORD
printf '\n'
export ADMIN_FULL_NAME="Platform Owner"

docker compose exec \
  -e ADMIN_EMAIL="$ADMIN_EMAIL" \
  -e ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  -e ADMIN_FULL_NAME="$ADMIN_FULL_NAME" \
  backend python scripts/seed_admin.py
```

`ADMIN_EMAIL` and `ADMIN_PASSWORD` are required; replace the email/name examples and choose a
unique password when prompted because the script has no default credentials. Email syntax and the
shared password policy (at least 10 characters, including uppercase, lowercase, and a number) are
validated before application settings or the database are loaded. `ADMIN_FULL_NAME` is optional
and defaults to `Super Admin`. Re-running the command with the same normalized email is safe: the
existing account is left unchanged.

### 5. Docker hot-reload mode

Use this when you want both backend and frontend to live-reload inside Docker.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Services in hot-reload mode:

- Frontend dev server: http://localhost:3000
- Backend API: http://localhost:8000
- Nginx reverse proxy: https://localhost

### 6. Local development without Docker

Backend (bootstrap from the repository root; existing target directories and unsupported interpreters are refused):

```powershell
py -3.11 scripts/bootstrap_backend.py
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

```bash
python3.11 scripts/bootstrap_backend.py
cd backend
.venv/bin/python -m uvicorn app.main:app --reload
```

Bootstrap installs `backend/requirements-dev.lock` with hashes, including runtime and exact test/lint/type/audit tools. It never replaces an existing virtual environment; use `--directory` for a fresh path. `python scripts/bootstrap_backend.py --check` verifies the active interpreter/tool versions. Supported Python is CPython 3.11. `.python-version`, `.node-version` and `tooling/toolchain.json` record the reviewed developer setup; production container pins are separately recorded in the Dockerfiles.

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

## Development Phases

| Phase | Feature                        | Status   |
|-------|--------------------------------|----------|
| 1     | Project setup & infrastructure | Complete |
| 2     | Authentication                 | Complete |
| 3     | Agency dashboard               | Complete |
| 4     | Secure upload links            | Complete |
| 5     | Smart camera interface         | Complete |
| 6     | Real-time passport detection   | Complete |
| 7     | Blur detection                 | Complete |
| 8     | Lighting detection             | Complete |
| 9     | Glare detection                | Complete |
| 10    | Perspective correction         | Complete |
| 11    | Auto capture                   | Complete |
| 12    | OCR + MRZ extraction pipeline  | Complete |
| 13    | Field review and confirmation  | Complete |
| 14-16 | Confidence scoring polish      | Complete |
| 17-19 | Client review & submission     | Complete |
| 20    | Excel export                   | Complete |
| 21-27 | Admin, search, audit, analytics, notifications, API docs, deployment guidance | Complete |

## Code Quality

```bash
# Backend lint
cd backend && ruff check . && ruff format --check .

# Backend type check
cd backend && mypy app/

# Backend tests
cd backend && pytest

# Frontend lint
cd frontend && npm run lint
```

## Security

- Runtime secrets are configured outside source defaults; deployment scope and remaining obligations are in the claim register
- JWT authentication with refresh token rotation
- Rate limiting at Nginx + application level
- S3 presigned URLs for secure image access
- Non-root Docker user in production images
- SQLAlchemy parameterization is used in database access; ORM use alone does not prove absence of every injection path
- Request schemas use Pydantic and frontend forms use Zod where configured; entry-point coverage is established by scoped tests and review

## Operational Capabilities

- Client review and editable extracted fields before final submission.
- Submission workflow with duplicate email/phone prevention per group.
- Excel export for each passport group from the group detail screen.
- Passport search by client name, email, phone, surname, or passport number.
- Admin overview for super admins and agency admins.
- Audit logs for export, re-extraction, confirmation, and client submission events.
- Analytics summary for status distribution, confidence quality, and daily volume.
- Agency notifications for client-submitted passport reviews.
- OpenAPI JSON at `/openapi.json`; interactive `/docs` and `/redoc` remain development-only.

## Production Deployment Notes

Use the [current release and storage procedure](docs/CURRENT_RELEASE_AND_STORAGE.md)
for the existing single-VPS installation, with the
[production readiness gates](docs/PRODUCTION_RELEASE_READINESS.md). The current
[manifest](backend/app/core/config/release_manifest.json) requires database
`0107_passport_ecr_checks`, **eight workers** and the separate `email-beat`
scheduler. An older database needs a separately reviewed upgrade; historical
release helpers are not the current deployment procedure.

`scripts/release_current.py` prepares and activates the exact pushed revision
using `docker-compose.yml`, `docker-compose.prod.yml` and
`docker-compose.storage-production.yml`, with the `maintenance` profile and
optional APNs overlay when configured. It retains old application images,
verifies a fresh database archive, provisions separate database identities and
copies legacy object versions to a **different named volume** before switching
the stable `minio:9000` endpoint to the maintained provider. Plain Compose `up`
is not a substitute: the two-file legacy path can select the old provider, and
the three-file path alone does not perform the verified copy.

Plan a maintenance window. Pause new uploads and message sends before activation;
the helper then fences the backend, all eight workers and beat during storage
copy and verification. Expected downtime grows with retained object history.
The old storage volume remains intact, but it is no longer authoritative after
new writes reach the replacement. Never use `down -v`, delete volumes, or switch
back to that stale source as rollback. Interrupted writer fencing has a protected
checkpoint and recovery checks when the same release command is rerun.

Keep `.env`, release evidence and identity files private. Use independent strong
secrets, trusted Nginx TLS certificates and explicit production CORS origins.
The production override removes development bind mounts/hot reload, fails
closed for the public-upload limiter, and passes only listed `NEXT_PUBLIC_*`
values to the frontend. Keep interactive API documentation development-only.

The maintained-provider adapter, version-preserving copy, restricted identities,
real HTTPS journeys and recovery paths have local synthetic qualification.
**This repository work has not deployed or migrated the Hostinger KVM 4 VPS.**
Weekly off-server Hostinger backups are confirmed by the owner's account records.
Their restore consistency, PITR, deletion protection, representative capacity,
external alert receipts and production RPO/RTO remain operator evidence gates; see the
[remediation evidence index](docs/remediation/README.md).
