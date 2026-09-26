# Roster computation and scaling qualification — 2026-09-27

The PERF-04 candidate replaces repeated complete-group SQL projection and duplicate clustering with a shared computed index bound to a transactional database revision. Existing full-group duplicate semantics, filter/sort ordering, cluster boundaries, selection revisions and page response fields remain. SCALE-03 receives measured component evidence here; the complete mixed workload and declared operating limits are qualified separately.

Migration `0111_roster_revision` adds a revision to each group. PostgreSQL statement triggers invalidate every affected group after passport or staff/coordinator assignment inserts, updates and deletes, including both ends of a group move. A bulk statement increments each affected group once. Group metadata and lifecycle updates also increment the revision without a recursive SQL update. Rollback rolls the revision back with the business mutation. No retained business row is rewritten or deleted by this migration.

The cache key binds actor, tenant, role, group, revision, date, travel date, inclusion policy, filtering, sorting and page size. Every request checks live visibility before consulting the cache; page details still use the existing live passport policy. A final revision/visibility check after hydration returns conflict if data changed during the read. Coordinators retain the established passenger-assignment access even when there is no separate group assignment. Closed groups remain usable, while archived/retained restrictions follow the existing authorization policy.

The Redis payload is authenticated and encrypted JSON, with bounded decompression and no pickled/ORM objects. Cache keys contain an HMAC rather than search text or identity fields. Entries expire after 60 seconds. Each application-secret namespace is bounded to 64 entries and 32 MiB of encrypted payload, with 4 MiB per stored entry and 8 MiB of uncompressed JSON. Atomic eviction enforces count and byte limits across workers. A bounded shared computation claim reduces duplicate work; unavailable, missing, invalid or oversized cache data falls back to authoritative computation. SQLite bypasses this cache because it does not run the PostgreSQL invalidation triggers.

## Evidence

- Final focused roster and checkpoint suite: **51 passed in 15.79s**, including **9 actual PostgreSQL/Redis roster cases** (`outputs/phase2-roster-audit-final.txt`). It covers cross-session warm reuse, eight concurrent sessions sharing one cold projection, bulk mutation, rollback, all three assignment tables, passenger move/delete, group lifecycle/travel metadata, coordinator passenger-only access and immediate revocation, Redis bounds, encryption/corruption and page hydration conflicts.
- Eight concurrent uploads, 20 synthetic passengers each: **0.504 seconds**, exactly eight revision increments, 280 final fixture rows, no deadlock and no lost increment under a five-second lock timeout.
- Independent populated migration rehearsal: all business-table hashes remained unchanged across the retained 100,001-passport dataset; `0111` upgrade and strict Alembic metadata comparison passed. See `populated-search-roster-migration.json`.
- Whole-app mypy passed at the 712-file checkpoint. Final aggregate/static gates are maintained by the coordinating workstream.

The actual backend runtime image, real PostgreSQL schema at `0111` and Redis were used for authenticated API requests including response serialization. Four staff ran concurrently in one ASGI process. There were 80 warm samples per case. Every warm request avoided the full-group projection: **zero projections across 320 requests**, versus one per cold request. SQL count changed from 11 to 10 statements per request, including authentication, live authorization, page hydration and auditing.

| Group | Cold four-request maximum | Warm p50 | Warm p95 | Warm p99 | Peak Python allocation cold / warm | Largest response |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 250 ordinary passengers | 491 ms | 140 ms | 187 ms | 1,008 ms | 1.44 / 1.20 MB | 138,019 bytes |
| 1,000 ordinary passengers | 397 ms | 199 ms | 850 ms | 1,027 ms | 2.85 / 1.77 MB | 228,022 bytes |
| 5,000 ordinary passengers | 2,241 ms | 431 ms | 1,318 ms | 1,370 ms | 11.01 / 5.94 MB | 288,023 bytes |
| 5,000 in one duplicate cluster | 1,380 ms | 1,275 ms | 1,545 ms | 1,608 ms | 14.42 / 9.69 MB | 291,876 bytes |

Exact measurements, image identity and limitations are retained in `roster-performance-evidence.json`; the reproducible runner is `backend/scripts/qualify_roster_cache.py`. Allocation samples ran separately from latency measurements. Cold samples are too few to establish a stable tail distribution. The container image precedes a subsequent coordinator-only permission compatibility correction; that correction passed the real PostgreSQL tests and does not change the measured staff branch.

These are local component measurements, not a production VPS SLO. Warm decoding and ordered-selection preparation still scale with group size; the change removes repeated projection and clustering rather than making every operation constant-time. Oversized indexes deliberately use the original authoritative computation. Cache eviction and frequent concurrent edits also cause recomputation. The standalone ASGI harness did not start application lifespan services and printed Redis connection-destructor warnings after completed measurements; it exited successfully. Complete proxy/network, four-worker, mixed-upload/scanner/queue capacity belongs to the separate workload qualification.

Only synthetic local records and isolated services were used. The migration preserves retained data. No native application, VPS service, external provider account or production record was changed by this workstream.

The subsequent [final mixed-workload qualification](phase2-workload-capacity.md) passed every strengthened SCALE-04 gate on the final four-worker runtime image with a 2,560 MiB API cap and the intended three-plus-three connection pools. The large-tenant expected-load roster p95/p99 were 377.731/448.223 ms, with 437.383 ms recovery p99. Cold requests, both tenant cohorts, real public uploads/scans, overload and queue recovery were retained. This is a separate local operating-envelope result; the component limitations above and the absence of a production/whole-host/long-soak claim remain.
