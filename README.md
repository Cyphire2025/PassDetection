# PassDetection - Enterprise Passport OCR Platform

Enterprise-grade passport processing platform for travel agencies.

## Architecture

Clean Architecture (Hexagonal) with strict layer boundaries:

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
- Python 3.11+

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

```bash
docker compose exec backend python scripts/seed_admin.py
```

Default credentials created by the script:

- Email: `admin@passdetection.com`
- Password: `Admin@1234!`

Override them with `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `ADMIN_FULL_NAME` when needed.

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

Backend:

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
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

- All secrets via environment variables - never hardcoded
- JWT authentication with refresh token rotation
- Rate limiting at Nginx + application level
- S3 presigned URLs for secure image access
- Non-root Docker user in production images
- SQL injection prevention via SQLAlchemy ORM
- Input validation on every request with Pydantic and Zod

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

1. Set strong values for every secret in `.env`; never reuse local defaults.
2. Always apply `docker-compose.prod.yml` after the development base file. It
   removes backend source bind mounts and restores the built runtime image's
   Gunicorn command. It also forces `APP_ENV=production` and
   `APP_DEBUG=false` for backend workers, forces durable Celery dispatch, and
   keeps the shared Redis public-upload limiter fail-closed; the frontend
   receives only the explicitly listed `NEXT_PUBLIC_*` values, never the
   server `.env`.
   Production also clears the development URL at both build time and runtime:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
   python scripts/verify_compose_runtime.py
   docker compose -f docker-compose.yml -f docker-compose.prod.yml build
   ```

3. Run migrations before serving traffic:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
   ```

   Do not deploy with `docker-compose.yml` alone; that file intentionally
   retains the local backend bind mount and Uvicorn hot reload.
4. Provision a trusted certificate and private key at the configured Nginx
   certificate paths before startup. Port 80 serves only `/nginx-health` and
   redirects every application request to HTTPS; if TLS terminates at an
   upstream load balancer, connect it to Nginx over TLS as well.
5. Point object storage to durable S3-compatible storage and verify bucket lifecycle policies.
6. Configure `SENTRY_DSN`, production CORS origins, and database backup/restore procedures.
7. Keep `/openapi.json` available for generated clients and CI contract checks; expose `/docs` only in non-production environments.
