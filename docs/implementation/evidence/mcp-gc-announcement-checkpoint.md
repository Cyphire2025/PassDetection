# MCP GC announcement draft checkpoint

Qualification date: 2026-09-30 (Asia/Calcutta). All data and provider activity below are synthetic local fixtures. No production migration, publication or notification was performed.

## Implemented boundary

`get_gc_announcement_change_context` returns the explicit agency/group's current access revision and optionally one exact retained announcement version. Source title/body are labelled untrusted business data. The read audit contains fixed identifiers/counts, not announcement content.

`create_gc_announcement_draft` and `create_gc_announcement_revision` require current super-admin/grant authority, an active explicit agency, a retained publishable group, and the exact current access revision. They use the canonical typed content/window validation and a shared flush-only creation helper. `publish` must be false; additional fields are rejected. The revision operation appends a new version within the selected logical history; it does not call the existing website edit path that replaces earlier draft rows. Every prior draft and published source row remains unchanged. No notifications are queued.

The durable operation layer binds user/operation/key to the canonical payload, replays one immutable initial result across current authorized connections, conflicts on changed arguments, and commits the source, revision and fixed business audit together. Replay and observation recheck current agency/group/access and retained created source before exposing links. Existing published versions remain eligible sources for a new retained draft, but draft creation never republishes them.

The shared content context now takes explicit group UPDATE then access UPDATE locks, with fresh ORM values, preserving its original tenant and removed-access filters. The unlocked read branch is unchanged. This is the same order used by native push source fencing. The audit also checked GC configure, My Photos, emergency revoke and setup removal ordering. The passenger-identity refresh route now acquires its group before access too: otherwise a later identity/journal foreign-key check could request group KEY SHARE after holding access, cycling with a group-first content edit. This is not a claim that every application lock graph has been proven safe.

## Executed checks

- 21/21 announcement integration and existing website atomic/replacement publication tests passed (8.14 seconds). Fourteen new tests cover cross-connection replay, changed payload conflict, exact source/revision and schema rejection, all-prior-version preservation, rollback/retry, live agency/group/access/capability/role loss, and actual SDK descriptor/create/revision calls. Seven existing website publication tests preserve the extracted helper's web behavior.
- 5/5 real PostgreSQL tests passed (12.58 seconds). Concurrent duplicate keys append once across two grants; competing keys with one expected revision have one winner; repeated revision requests retain earlier drafts and allocate one version. Website content edits and native push handoffs serialize in both winner orders and complete with exactly one synthetic provider call.
- An additional focused PostgreSQL passenger-reconciliation test passed (1/1, 2.68 seconds): while another transaction holds group UPDATE, refresh waits before owning access; that group owner can take access NOWAIT and commit, after which refresh completes. All six PostgreSQL cases are retained in the same test module; the sixth was added and executed after the five-case checkpoint.
- Mypy passed for the three new production modules. Focused Ruff passed. Existing backend quality ratchets passed for all 87 budgeted modules.

Commands (from `backend`, using the worktree's `.venv311`):

```text
python -m pytest tests/integration/test_mcp_announcements.py tests/unit/presentation/test_gc_app_announcement_atomic_publish.py tests/unit/presentation/test_gc_app_replacement_publish.py -q --no-cov
python -m pytest tests/service_integration/test_mcp_announcements_postgresql.py -q --no-cov
python -m mypy app/application/use_cases/gc_app/create_announcement.py app/application/mcp/announcement_changes.py app/presentation/mcp/announcement_tools.py
python scripts/verify_backend_quality_budgets.py
```

The PostgreSQL lane uses the guarded loopback CI database and independent retained UUID schemas. It does not drop schemas or modify business data. SQLite tests do not qualify PostgreSQL locking; the separate PostgreSQL lane supplies that evidence.

## Publication effect review

The existing canonical `publish_announcement` keeps previous source rows and content, marks earlier published versions retired, publishes the selected draft, increments access/manifest/announcement revisions, appends a sync upsert and creates in-app feed rows for currently authorized principals. The native dispatcher explicitly excludes `group_announcement`; publication must not be reported as confirmed native push delivery.

Retaining source rows is not the full user-visible effect. Website list/page endpoints omit retired versions. Mobile endpoints select only published versions. Mobile `replaceAnnouncementsInTransaction` replaces the account/trip's local projection with that current set, including removal of old announcement/read-state entries. Therefore replacement publication is not yet qualified under the requested preservation boundary. This is a specific retained-history/cache gap, not a blanket exclusion of all publication.

A separately reviewed first-publication adapter can avoid retirement by requiring that the logical history has never had a published version and that the exact selected draft/access/content and a bounded in-app audience still match a saved preview. It must use current and original authority, preserve immutable results, and keep all source/feed/history rows. Replacement publication remains pending a design that preserves accessible history and mobile cache/read-state semantics.

## Release regression checkpoint

The release-priority follow-up held publication implementation. The six assigned WhatsApp failures were resolved in tests without weakening runtime authorization: HTTP fixtures now provide the required stable key and a persisted active credential state; tenant reassignment updates the stored actor as well as the fresh request snapshot. The archive worker test isolates archive checking after the independently tested MCP origin gate. Route facade assertions now explicitly verify the durable HTTP wrapper and the preserved legacy direct helper/shared queue seam. All 29 WhatsApp schema dictionaries were compared against the pre-extraction HEAD definitions under the pinned Pydantic 2.12.5 and matched exactly; its rendering hash was added without changing older runtime hashes.

The five affected WhatsApp unit modules plus `test_whatsapp_send_intents.py` passed 36/36 (12.28 seconds). Focused Ruff, diff whitespace and all 87 backend module quality budgets passed. These are local release checks, not deployment or production-provider evidence.
