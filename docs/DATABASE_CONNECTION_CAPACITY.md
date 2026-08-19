# PostgreSQL connection-capacity contract

## Enforced default budget

SQLAlchemy pools are process-local, so a pool size must always be multiplied by every Gunicorn worker and Celery prefork child. The previous implicit `20 + 10` pool could request 120 connections from four API workers before any background process was counted.

The checked production defaults are now:

| Consumer | Processes | Pool per process | Maximum claim |
| --- | ---: | ---: | ---: |
| Gunicorn API | 4 | 8 base + 2 overflow | 40 |
| General worker | 2 | 1 + 0 | 2 |
| Email worker | 2 | 1 + 0 | 2 |
| Email-AI worker | 2 | 1 + 0 | 2 |
| Extraction worker | 32 | 1 + 0 | 32 |
| Verification worker | 1 | 1 + 0 | 1 |
| Visa-image worker | 1 | 1 + 0 | 1 |
| Celery Beat | 1 | 1 + 0 | 1 |
| **Total application claim** |  |  | **81** |

`POSTGRES_SERVER_MAX_CONNECTIONS=100` and `POSTGRES_RESERVED_CONNECTIONS=10` leave an application budget of 90. The default claim is 81, leaving nine additional application slots plus the ten-connection operational reserve. The reserve is for migrations, administration, probes, incident recovery, and other consumers not represented by the application process calculation.

Staging and production settings fail validation when either:

- `WEB_CONCURRENCY * (POSTGRES_API_POOL_SIZE + POSTGRES_API_MAX_OVERFLOW)` exceeds `POSTGRES_API_CONNECTION_BUDGET`; or
- that API claim plus every configured Celery/Beat process pool exceeds `POSTGRES_SERVER_MAX_CONNECTIONS - POSTGRES_RESERVED_CONNECTIONS`.

Compose forwards the exact concurrency values to every backend service, selects the `api` pool only for Gunicorn, selects the `worker` pool for every Celery/Beat service, and configures the bundled PostgreSQL server with the same declared ceiling. This prevents a host-shell concurrency override from bypassing application validation. A managed PostgreSQL deployment must set `POSTGRES_SERVER_MAX_CONNECTIONS` to its real limit after subtracting provider-reserved slots; never increase the application value without changing the database server or adding a measured pooler.

## Scaling choices, ranked

1. **Keep direct pools and scale within the enforced budget.** Best for the current single deployment because it is simple, fail-fast, and observable. Recalculate before changing workers or replicas.
2. **Add PgBouncer in transaction mode.** Best when horizontal replica count or burst concurrency would otherwise consume too many server backends. Validate session-state assumptions, prepared-statement behavior, migrations, and failover before rollout. It adds another critical component but decouples client connections from PostgreSQL backends.
3. **Increase PostgreSQL `max_connections`.** Use only after memory, CPU, context-switching, and workload tests show it is safe. This is generally the least efficient standalone answer and does not replace query/index optimization.

## Observability and release gates

The protected metrics snapshot exposes `shared.database_pool` with the selected profile, configured base/overflow/timeout, checked-in, checked-out, and overflow values. Counters record checkouts, check-ins, invalidations, and checkout timeouts. Alert on any checkout timeout, sustained checked-out saturation, or positive overflow under ordinary load. The local registry does not provide a precise queue-wait histogram, so production tracing/APM should measure database-acquisition wait separately before capacity certification.

No throughput or concurrency capacity is proven by this arithmetic. Before increasing workers, replicas, or any 1k/10k release claim, run the authorized staging workload against production-like PostgreSQL and record pool saturation, checkout timeouts/wait, database sessions, lock waits, slow queries, CPU, memory, I/O, replication/failover behavior, and p95/p99 request latency.

## Runtime reproducibility boundary

Backend metadata, Docker, and CI now agree on the only verified interpreter line: CPython 3.11 (`>=3.11,<3.12`). `backend/requirements.txt` remains the reviewed direct-dependency input, while `backend/requirements.lock` is the complete universal Python 3.11 resolution with SHA-256 hashes. CI regenerates that lock with the pinned `uv` version and rejects drift; tests and the production image install it with `--require-hashes`; the dependency audit consumes the lock without re-resolving it.

This closes Python transitive-resolution drift, but it is not a complete software-supply-chain claim. Container base-image digest pinning, signed image provenance, registry retention, and a successful clean Docker rebuild remain release/deployment controls and must be verified in the deployment environment.
