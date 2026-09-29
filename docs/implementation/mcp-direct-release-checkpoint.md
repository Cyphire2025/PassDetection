# Direct VPS release checkpoint

The user authorized pushing the stable checkpoint to main and deploying on the
existing VPS before hosted CI, then continuing the accepted eight-phase plan.
This is a separate operator path; the signed hosted-CI updater is unchanged.
Every existing container, image, source file, business file, and database row is
retained. New builders, candidate containers, source archives, receipts and
backups are retained too. No cleanup, prune, forced stop, or automatic downgrade
is part of this path. The temporary SSH key keeps its original expiry.

The initial runtime enables MCP with only `mcp:read` and `mcp:export`, and exposes
only the `passport_excel` export family. Source admission allows at most 100
retained rows per source family and 1 MiB of cumulative database-measured text
values before full ORM reads. These are input limits, not a measured heap or
combined production-load capacity claim. The database control starts disabled;
an authenticated active superadmin must explicitly enable and authorize the
connection through the Administration flow.

`scripts/mcp_direct_release.py` implements explicit prepare, build, stage,
activate, verify, and guarded source-schema recovery phases. Builds derive from
the exact existing backend/frontend image IDs and the existing pinned Node image
ID. They use finite memory/CPU/PID limits, retain hash-pinned dependency additions
in a separate import directory, and verify the backend OpenAPI contract. The
builder budget includes all running host containers and a 2 GiB host reserve.
Workers drain during builds and their original IDs resume afterward.

Activation uses a new set of stopped application containers with unique network
aliases and retained original runtime security/resource settings. It drains
ingress, scheduler and workers, verifies the writer fence, takes and validates a
fresh PostgreSQL custom archive, then applies the exact nine migrations from
`0113_document_follow_up` through `0122_mcp_gc_push` using the existing migration
owner. The archive is decoded and hashed; it is not claimed as a production
restore rehearsal. Target-schema recovery is forward repair only.

Local evidence at this source checkpoint:

- Broad backend run: 5,729 passed, 11 failed, 3 skipped, 275 deselected; all eleven
  failures were subsequently fixed and their affected tests passed. A second
  whole-backend run is not claimed.
- Frontend: 1,093 Vitest tests and 714 contract tests passed, with TypeScript and
  module budgets passing.
- Final passport export/source admission/envelope/architecture check: 24 passed;
  actual PostgreSQL export concurrency checks: 3 passed; scoped mypy/Ruff and 87
  backend module budgets passed.
- Connector: 95 tests passed. Rebuilt local version 0.2.0 wheel SHA-256:
  `9ddb16aa489e6cfd3e403f0778955c76f6c8bb050f81e3724368efec06518214`.
- Database helper: 9 focused tests plus a real PostgreSQL backup/decode/hash,
  five-second lock failure/transaction rollback, successful retry, retained row,
  disabled control and target retry proof passed.

These are pre-deployment results. Production build, migration, public readiness,
browser authorization, real Codex use and verified live export are recorded only
after each actually succeeds. This checkpoint does not complete the full plan.
