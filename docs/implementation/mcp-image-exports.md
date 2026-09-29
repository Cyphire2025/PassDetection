# MCP passport image ZIP exports — local qualification

This family packages the application's current effective passport images for one explicit agency/group. Group exports support all/incremental modes; selected exports support up to 500 exact passport IDs within that group. The shared preparation service now feeds both the existing web routes and MCP. It preserves collision-safe filenames, the full-group naming namespace, staff/agent codes, zones, saved crop derivatives and canonical fallback rendering from saved crop metadata.

## Durable request and delivery

`inspect_image_export` returns the current payload count, source-size/output bounds, history behavior and a revision covering the current naming namespace, selected IDs, source keys, saved crops, zone resolution and baseline/history inputs. It performs database preparation only.

`prepare_image_export` takes the same explicit selection, inspected revision and a stable idempotency key. The operation callback commits an immutable queued request before any image storage client or ZIP renderer is created. Generation runs separately, under current MCP authority and source locks. The same operation UUID becomes the group export-history request UUID. Repeating the key replays the original receipt; completion separately records the existing artifact UUID.

`resume_image_export` revalidates current authority and group scope before finishing a queued request or recovering the same unexpired archive. A new authorized connection for the same actor gets a protected access locator to the same artifact. Missing or expired successful results are never silently regenerated.

Artifacts use the existing `passport_images` purpose and `application/zip` media type. Group export histories retain `image_count`, `uncompressed_bytes` and `archive_bytes`. They remain `prepared` until a complete authenticated stream and the connector's verified local save/checksum acknowledgement invoke the shared export completion service. Selected-image exports have no incremental checkpoint, matching the existing website. No new schema or dependency was required.

## Source, resource and cancellation boundaries

The adapter accepts no server path, object key or URL from MCP arguments. Only keys from the prepared database records are passed to a read-only storage adapter. Each read checks storage size, enforces the current bound, streams 64 KiB chunks, verifies actual size and any available stored SHA-256, and invokes canonical native image inspection. Legacy objects without checksum metadata still require an exact bounded stream and pixel validation. Original images, saved crop metadata, cached derivatives and user source files are never modified.

Current runtime limits are:

- One image generation per backend process; two source fetches per canonical exporter batch.
- Source bytes: the smaller of 32 MiB and the configured upload-file limit (10 MiB by default). The inspection response reports the effective limit.
- Native decode: existing configured upload pixel limit (24 million pixels by default), with the shared native-image admission mechanism. Saved-crop fallback uses the same bounded canonical renderer.
- Cumulative source-read reservations: 256 MiB, including fallback reads; uncompressed rendered ZIP payload: 256 MiB. The downstream protected-artifact limit remains 512 MiB, including ZIP framing.
- Canonical ZIP spooling: 8 MiB memory before disk. At most 5,000 passengers in the full naming namespace and 5,000 linked matching-source rows; selected payloads are capped at 500 IDs. Missing selected IDs fail instead of being filtered out.
- Per source read: 120 seconds; ZIP render: 300 seconds. Cleanup may take additional time to drain native work safely.

Lock order is current control/grant/identity, operation, client group, linked matching sources, passports and crop records. Parent locks prevent new child sources during generation. `NOWAIT` and a local PostgreSQL 250ms lock timeout return a retryable busy response around legacy crop/passport-first writers. The complete revision is checked before rendering, after rendering and after private artifact storage, before committing history/artifact/operation state.

Cancellation drains the render and native inspection/crop threads before releasing generation capacity or closing their spool. The shared canonical ZIP exporter now closes its spool on cancellation as well as ordinary failure and drains fallback crop rendering before returning. SQL rollback retains the previously committed queued receipt. Temporary transfer objects after an ambiguous storage/commit failure are private copies subject to the deployment expiry policy; originals are not cleanup targets.

## Evidence and remaining gates

- `backend/tests/integration/test_mcp_image_exports.py`: 8 tests passed with actual PNGs, native inspection/crop rendering, ZIP reopening and database history. Covers byte-for-byte website parity for saved crops/zones, acknowledgement-only history completion, all/incremental/selected behavior, immutable retries/new-grant recovery/expiry, revision changes and corrupt reads, DB-only preparation, missing cached-crop fallback, cancellation/spool closure/capacity recovery, exact selected IDs and required source pages.
- `backend/tests/unit/infrastructure/test_mcp_image_export_storage.py`: 4 tests passed for key authority, per-source and cumulative size reservations, checksums, pixel limits before decode, and cancellation drainage of native inspection.
- `backend/tests/service_integration/test_mcp_image_exports_postgresql.py`: 3 tests passed against the disposable loopback PostgreSQL database. Independent worker service bodies serialize to one archive/history across connections; a crop-first writer returns busy without deadlock then invalidates the old revision; a revoked grant prevents source reads.
- `mcp-connector/tests/test_image_exports_tcp.py`: 1 test passed through the official SDK client, local connector proxy and real loopback HTTP backend. It inspects/generates/retries, saves a verified ZIP locally, reopens the image bytes, acknowledges delivery and recovers the completed artifact while preserving original objects. The test registers the exact production tool composition when not already installed by the backend fixture.
- Existing selected-image and route-decomposition tests passed after the shared preparation extraction. Scoped Ruff and mypy passed for the new production modules.

The object store and credential vault in these tests are fixture adapters. Real S3 read integrity, production lifecycle/cleanup configuration, ClamAV where uploads require it, browser/MFA/vault behavior, real Codex explicit file handoff and measured memory/load capacity remain separate gates. This does not qualify tracking, rooming or menu exports or the full Phase 4 release.
