# Working on PassDetection

This repository contains the Python API and workers in `backend/`, the Next.js
dashboard in `frontend/`, the Expo application in `mobile/`, and the desktop MCP
connector in `mcp-connector/`. Read narrower `AGENTS.md` files before editing.

## Reproducible development

- Use the reviewed versions in `tooling/toolchain.json`: CPython 3.11, Node.js
  24.21.0, npm 11.20.0 and the pinned Python development tools.
- Install Python packages from `backend/requirements-dev.lock` with hash checks.
  `scripts/bootstrap_backend.py` creates a new environment without replacing an
  existing developer environment. Do not regenerate dependency locks for an
  unrelated task.
- Use `npm ci` in `frontend/` and `mobile/`; dependencies and caches are local
  to the checkout and are not part of the source repository.
- For an OpenAI-hosted Linux development environment, run
  `bash scripts/setup_codex_cloud.sh`. Select the supported runtimes first.

## Verification

Run checks appropriate to the affected applications and preserve useful results.
Start with one test worker when available memory is limited.

Backend, from `backend/` with its virtual environment activated:

```sh
python -m ruff check --no-fix app tests
python -m mypy app
python scripts/verify_migration_topology.py
python scripts/verify_backend_quality_budgets.py
python scripts/verify_architecture_boundaries.py
python -m pytest -q -o addopts='' tests/unit tests/integration
```

Web, from `frontend/`:

```sh
npm run lint
npm run type-check
node node_modules/vitest/vitest.mjs run --maxWorkers=1 --pool=threads
npm run maintainability:check
npm run build
```

Mobile, from `mobile/`:

```sh
npm run typecheck
npm run lint
npm test -- --runInBand
npm run maintainability:check
```

The main CI workflow also checks the connector, real PostgreSQL/Redis/private
object-storage integrations, API contracts, populated migrations, browser flows,
and release artifacts. A passing SQLite suite does not establish that those
service-dependent checks passed. Browser fixtures use isolated loopback services;
follow `frontend/playwright.config.ts` and `frontend/config/e2e-isolation.ts`.

## Preserve running releases and user data

- Use synthetic test accounts, documents, and service credentials. Do not copy
  production `.env` files, passenger exports, tokens, or VPS credentials into a
  cloud environment to make tests pass. Real provider sends are not test fixtures.
- Preserve published migrations and the current release's validation and
  authorization checks while reconciling an older working copy.
- Worktree files, cloud task files, and GitHub branches are separate working
  copies. Commit and push work that must be continued in a different cloud task;
  an unrelated new task does not inherit another task's uncommitted files.
- `main` has a CI/CD workflow that can deploy to the VPS after qualification.
  Follow the user's requested branch and release scope. Run meaningful checks
  before an authorized push and report any checks that could not run.
