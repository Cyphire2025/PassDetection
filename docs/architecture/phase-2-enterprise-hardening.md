# Phase 2 Enterprise Hardening Runbook

This phase moves passport extraction out of the upload request path, adds stricter upload security, exposes operational diagnostics, and keeps the public client link fast by polling for processing status.

## Implemented slices

- Async processing: `passport_processing_jobs`, Celery task `passport.process_submission`, local background fallback, progress/status polling, cancellation request endpoint.
- OCR maturity: modular preprocessing/extraction/voting/confidence pipeline, evidence fusion, image quality scoring, OpenAI vision fallback hook, benchmark runner, short-lived OCR result cache.
- Security: magic-byte and PIL upload validation, filename sanitization, size/pixel caps, backend rate limiting, security headers, refresh-token hashing with backward-compatible raw-token lookup.
- Performance: fast-mode OCR avoids eager loading all heavy engines, per-attempt OCR timeouts, Redis/local OCR cache, DB indexes for status/group/agency views.
- Observability: request timing headers, in-process metrics, OCR timing/confidence metrics, `/api/v1/health/diagnostics`, `/api/v1/health/metrics`.
- Client UX: upload returns quickly with `processing`; the upload page polls `/api/v1/passports/upload/{token}/{submission_id}/status` until review fields are available.

## Demo startup

Use the full stack so the Celery worker processes uploads independently:

```powershell
docker compose up -d --build backend worker frontend nginx
```

The backend service runs `alembic upgrade head` on startup. If you need to apply migrations manually:

```powershell
docker compose exec backend alembic upgrade head
```

For development without the worker, set:

```powershell
$env:PROCESSING_BACKEND="background"
docker compose up -d backend frontend nginx
```

## Verification commands

```powershell
docker compose exec backend python -m compileall -q app tests
docker compose exec backend python -m unittest tests.unit.infrastructure.test_ocr_architecture -v
docker compose exec backend python -m unittest tests.unit.infrastructure.test_upload_validator -v
docker compose exec backend python -m unittest tests.unit.infrastructure.test_benchmark_metrics -v
docker compose exec backend python -m unittest tests.unit.infrastructure.test_refresh_token_hashing -v
npm --prefix frontend run lint
npm --prefix frontend run build
```

## Operational notes

- `PROCESSING_BACKEND=celery` is the Compose default for the backend; queued jobs require the `worker` service.
- `PROCESSING_BACKEND=background` is useful for a single-machine demo because the API response still returns quickly and processing continues after response.
- `OCR_CACHE_TTL_SECONDS=0` disables result caching if a deployment policy forbids short-lived OCR result storage.
- `OCR_FAST_MODE_ENABLED=false` enables the deeper local ensemble at the cost of latency.
