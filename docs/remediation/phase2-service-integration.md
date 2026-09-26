# Current real-service qualification — 2026-09-27

All **163 unique service-integration cases** now have passing local evidence, with **zero remaining failed, errored or skipped cases**. This is explicitly split-run evidence: the complete lane passed **162/163 in 474.23 seconds**; the corrected saved-notification family then passed **10/10 in 41.72 seconds**, including the one previously failing case and nine repeated controls. It is not a claim that one complete 163-case run was green. The final post-push CI lane must execute every case and rejects any skip.

The machine-readable receipt is [service-integration-phase2-evidence.json](service-integration-phase2-evidence.json). The earlier phase-one 132-case split-run receipt remains unchanged for history.

## Environment and retained data

The run used the isolated `passdetection-service-contract-qualification` Docker project, Linux Python 3.11.16, PostgreSQL 16, dedicated Redis and realtime Redis, the pinned maintained SeaweedFS provider, a separately pinned RustFS Object Lock service, and a real Celery prefork worker. A new test-only image derives from the qualified `c2688994…` runtime and adds the hash-locked development dependencies. The existing custom OpenCV distribution satisfied the lock and was not replaced. Source and tests were mounted read-only, with bytecode and pytest caches inside the container's `/tmp`.

Only `passdetection_ci_services` was upgraded from `0107` to `0111_roster_revision`; migration topology and Alembic schema-drift checks passed. The separate FCM database remained isolated. PostgreSQL and application-storage container IDs and volume IDs match their pre-run identities; no retained database or volume was removed. The independent capacity-test project was not restarted or changed by this lane.

A fresh `passdetection_ci_phase2_service_roles` database at `0111` passed **18 role, row-preservation and DSN assertions** using distinct new runtime and migration identities. These include denied runtime DDL/audit mutation/role assumption, successful ordinary CRUD, idempotent provisioning and credentials containing reserved characters and Unicode. Earlier qualification databases and identities were retained.

## Corrections found by the complete lane

The first refreshed run collected 161 cases: 52 passed, 107 errored during the same fixture setup, and two failed for an absent test-only Redis setting. The new ORM search indexes need PostgreSQL's `pg_trgm` operator class, but the UUID-only fixture search path could not see the public extension. The test-only shared setup now requires an explicitly synthetic database and a fresh empty UUID schema, exposes public only during table creation, uses `checkfirst=False` so public application tables cannot substitute for fixture tables, and restores the original search path even after a DDL error. Two actual PostgreSQL negative tests prove rejection of public/nonempty schemas and rollback of partial tables with path restoration. All business assertions remain enabled.

The reporter's explicit Redis opt-in is now supplied locally and in CI. The non-root test runtime uses a writable `/tmp` pytest cache instead of the image's root-owned `/app` directory. These were verification setup defects, not application vulnerabilities.

The complete second run executed all 163 cases without skips. Its one failure was a stale exception catch after application/HTTP separation: the saved-notification test directly invokes a presentation route that correctly returns HTTP 410 for a deleted draft without a send. The fixture caught only the application exception class. A separate HTTP exception catch now preserves the exact 410 response/message, actual PostgreSQL lock wait, zero-batch count and retained tombstone assertions. The entire ten-case family passes after that narrow correction. No production behavior changed to make this test pass.

## Evidence boundaries

The receipt records source hashes and the limited overlap: two CSRF/OpenAPI descriptions were clarified during the complete run. Reversing the exact description additions and one formatting wrap reproduces the original file hashes. One unrelated, uncollected query-audit unit test was Ruff-formatted by its owner and belongs to the separate core lane. The saved-notification test change occurred after the complete run; reversing its added import/catch reproduces the prior source after newline normalization.

Raw failure and final logs/JUnit files remain under the ignored `outputs/service-integration-qualification/` directory. The receipt identifies each file and every service-test family. No native application source, production service or customer data was changed. External notification providers are synthetic fakes; this evidence does not prove live provider delivery, production throughput, off-host recovery or a human alert receipt.
