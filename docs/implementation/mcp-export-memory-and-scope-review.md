# Export admission and remaining artifact scopes

Source review and local hardening checkpoint, 2026-09-30. This is not production
capacity qualification. The reported production backend usage of 2.17 / 2.5 GiB
comes from the coordinating agent's observation; this review did not access the
VPS or measure its memory.

## Implemented follow-up

All four existing MCP export service families now acquire a shared nonwaiting
kernel lease in `core/mcp_export_admission.py` before inspect/prepare source
reads and across generation/storage. The lease is independent of the existing
native-image lease. Reentry is limited to the same process and asyncio task;
inherited child-task context cannot authorize simultaneous work. Existing
per-family limits remain secondary guards. A worker crash releases kernel
ownership; lock files are never unlinked to reset admission.

Passport Excel now enforces a 16 MiB canonical snapshot, 256 resolved catalog
fields, 320 actual columns, a conservative 250,000-cell envelope checked before
workbook allocation, a 32 MiB output buffer and a 120-second render deadline.
The cell envelope reserves up to two separator rows per source row. Optional
canonical helper arguments preserve website defaults. Canonical hashing streams
the same sorted JSON bytes without recursively copying dataclasses or joining
the whole JSON string. A bounded output failure closes the ZIP and deletes only
that writer's own temporary worksheet XML.

Repeated cancellation drains the existing render/storage helper before closing
its temporary file or releasing admission. A completed conditional private PUT
can still become an orphan after transaction rollback; transfer-copy TTL cleanup
remains necessary. No business history or accessible artifact is retained on
failed/canceled generation. A busy prepare rolls back its tentative operation;
the same original retry key remains usable. Inspect, prepare and resume expose
audited, static `export_busy` results without raw lock paths or exceptions.

Local qualification: 177 tests passed and one POSIX fork test skipped across
kernel admission, capacity, all four export families, canonical website XLSX and
history regressions; 12 PostgreSQL export races passed; the official SDK through
the connector proxy to a real loopback HTTP server passed busy inspect/prepare/
resume, audit, unchanged retry intent, and verified delivery checks. The native
tests exercise real Windows processes and crash release, child-task exclusion,
deadline drain and repeated storage cancellation. The local Docker Linux engine
was unavailable.

The coordinating agent separately ran the exact frozen kernel sources on Linux
at 2026-09-29 18:59:30 UTC. Its receipt is
`outputs/mcp-linux-export-gate-2026-09-29T185930.471475_0000.json`. Four checks passed:
same-task reentry with child-task denial, cross-process nonwaiting contention,
fork children not retaining the parent's descriptor, and owned-helper SIGKILL
releasing the lease. Source SHA-256 values are
`bcf9f6dbbf345fe99dfe1062c01635c53ec59ac613e8851fae426d52c2c21a61`
for the export gate and
`5076186356e98000b6e93737e68287c9072db064dd0847fd8c27a8bd5ebcbe06`
for the reused native-image kernel helpers. The isolated host harness used Python
3.12.3, a 96 MiB address-space limit per process, and observed 23,552 KiB parent /
17,136 KiB helper RSS. Production backend Python 3.11 Linux CI remains necessary.
This was a kernel-primitive proof, not an application/container load test. The
coordinator retained its new empty lock directory and performed no deletions or
application/container/data access.

**Remaining memory gate:** source ORM rows and some helper results are loaded
before the 16 MiB canonical snapshot check. A single request with unusually large
retained JSON/text can allocate more than that limit before safe rejection. The
shared slot prevents the former family-level aggregate admission, but it does not
prove the reported 338 MiB production headroom is sufficient. A complete DB-side
size/projection preflight must cover group and joined source fields, not only
passport JSON. Actual mixed-load/cgroup/RSS qualification remains mandatory;
website export overlap is also outside this new MCP-only gate.

## Original admission findings

The deployment uses four backend workers. Each completed MCP export family has
its own process-local generation limiter:

| Family | Slots per process | Source / data limits | Rendering / output limits |
| --- | ---: | --- | --- |
| Passport Excel | 2 | 1,500 source passports and bounded recipients; 100 selected groups; explicitly supplied supplemental fields limited to 256 | No generation deadline or dedicated snapshot / workbook byte limit; transfer rejects over 512 MiB only after rendering |
| Passport image ZIP | 1 | Selected IDs limited to 500; group namespace bounded; two source fetches per render; each source at most min(32 MiB, configured upload maximum); 256 MiB cumulative source-read budget | 300-second generation deadline; 8 MiB spool then disk; 256 MiB rendered archive payload budget |
| Group tracking Excel | 1 | 1,500 source rows; 100 linked broadcasts; 256 catalog fields; 16 MiB canonical snapshot | 120-second render deadline; 32 MiB XLSX limit checked after render |
| Hotel rooming / check-in Excel | 1 | 1,500 rows per source family; 100 linked broadcasts; six priority fields; 16 MiB canonical snapshot | 120-second render deadline; 32 MiB XLSX limit checked after render |

Therefore, family limiters alone permit up to 20 concurrent generation bodies
across four workers. Database locks and other limits can reduce actual
concurrency, but they are not an aggregate memory admission contract. Inspect
and DB-only prepare calls can materialize their source snapshots outside these
generation limits. Website exports can also overlap MCP work.

`artifacts.py` has two transfer slots per process, 64 KiB chunks and disk-backed
temporary files. Its 512 MiB export limit does not mean a transfer retains that
much RAM. It also does not bound an earlier in-memory workbook. Likewise, the
ZIP's 256 MiB source budget is cumulative workload, not 256 MiB retained at once.
Two compressed image source buffers can overlap during one ZIP generation.

The existing `native_image_admission.py` already protects native image memory
across workers in one container: one execution lock, four admitted calls, bounded
waiting, kernel-owned locks, cancellation-safe ownership by the native worker,
and qualified Linux heap reclamation before releasing its slot. Independent
containers have independent memory limits and lock namespaces. A second image
decoder gate is unnecessary.

`run_bounded_storage_operations` bounds and drains a single invocation. Its local
semaphore is not a process-wide or container-wide export limit. Keeping that
drain behavior is essential: a canceled async request must not release admission
while its native workbook or image worker still owns memory.

Passport Excel preparation currently recursively canonicalizes dataclasses using
`asdict`, builds the canonical object graph, then calls `json.dumps(...).encode()`
before hashing. It can retain several representations of the same source. Its
default field catalog is also not covered by the request's optional 256-field
limit. Tracking and rooming have byte checks, but these are not a complete heap
budget: Python objects, workbook cells/styles, compression buffers and reread
snapshots can coexist. A compressed XLSX size is especially not a RAM estimate.

## Capacity qualification plan

1. Add shared, container-wide nonwaiting admission for MCP export preparation and
   generation before loading bulk source data. Initially admit one such body per
   container, pending representative mixed-workload measurements. Do not queue
   prepared snapshots in memory while waiting for a rendering slot.
2. Keep admission through cancellation-drained native work and storage. Handle
   nested preparation inside a generation without taking a second slot. Keep
   this gate independent of native image admission and always acquire export
   admission first, before image work.
3. Apply explicit snapshot, resolved field-count, cell/workbook and generation
   deadline limits to passport Excel, preserving website defaults through
   optional bounded preparation parameters. Reject excess source data; do not
   silently truncate a workbook. Reduce repeated snapshot copies where possible.
4. Qualify memory at the actual four-worker container limit using mixed families,
   worst supported cell widths, concurrent inspect/prepare, cancellation and
   website overlap. Capture cgroup peak usage, worker RSS, gate saturation, native
   worker drain and exact workbook contents. Do not infer safety from sequential
   row-count tests alone.

The admission and passport-workbook changes in the first three items are now
implemented locally as described above. The full pre-materialization byte bound
and measured production memory/load gate remain open. No production configuration
or VPS files were changed by this work.

## Next family with the existing group scope

Document-assignment XLSX is the next approved bounded adapter. Its website
surface is `document_distribution_groups_read.export_document_assignments`.
Inputs are an exact agency/group pair, one supported document type, one of
`all`, `assigned`, `missing`, `sent`, `not_sent`, `multiple_pdfs`, and an optional
passenger-name search. The workbook generator and assignment-row filter are
already canonical. Exporting has no assignment, approval, sending or history
completion side effects.

The existing review loader reads the group passports, retained documents and
delivery ledgers. It also creates presigned PDF URLs and loads batch/rejection
metadata that the spreadsheet does not use. Extract the pure document response
calculation, reuse canonical passenger grouping and workbook construction, and
omit URL generation from export preparation. The source revision must cover all
data affecting the output, including document multiplicity/storage identity and
accepted/latest delivery states, phone and timestamps.

Proposed MCP limits are 1,500 passengers, the existing 3,000 document-assignment
scope limit, an explicit delivery-source bound, 16 MiB canonical inputs and
32 MiB workbook output. Exceeding any limit rejects the whole request. Use the
existing durable DB-only receipt, separate generation transaction, current
authority checks, source revision fences, protected artifact and explicit local
delivery acknowledgement. No passport export checkpoint is appropriate for this
read-only review workbook. No schema change is needed.

## Exports that have no legitimate group

Meal-plan XLSX and standalone broadcast-filter XLSX cannot be attached to an
invented group. The following schema proposal requires root review and migration
approval before implementation:

| Artifact owner | Required binding | Additional group associations |
| --- | --- | --- |
| `group` | Non-null agency and group; existing behavior | Exact retained pairs, including the primary group |
| `meal_plan` | Meal-plan FK; agency UUID or explicit platform NULL; no group | Empty |
| `broadcast` | Non-null agency and broadcast FK; no primary group | Exact groups whose records enriched the selected export; may be empty for standalone contacts |

Add `scope_kind`, nullable `meal_plan_id` and `broadcast_id`; make `group_id`
nullable and permit nullable `agency_id` only for an explicitly scoped platform
meal plan. CHECK constraints require exactly the appropriate owner columns.
Non-group scopes support exports only and cannot carry a passport history,
checkpoint or ingestion operation. Code-owned purpose-to-owner mappings reject
unsupported combinations. Use CASCADE owner FKs for temporary metadata, matching
existing manual business-record deletion semantics. Backfill existing rows as
`group`, preserve all handles/access rows, and refuse downgrade while a non-group
artifact remains.

Every metadata, content, acknowledgement and explicit recovery request must
revalidate the current active Super Admin grant and deployment capability, the
exact live owner and its agency, plus every retained group pair. A NULL agency
means the specifically requested platform plan, never every agency. Missing or
mismatched owners return not found; do not filter missing secondary groups and
return a partial file. Ordinary source edits may leave a historical snapshot
downloadable under current exact owner authority; deleting the owner removes its
temporary metadata. Resume never regenerates a missing or expired successful
artifact.

For meal plans, current website authorization compares the plan's agency to the
actor's agency; an unassigned Super Admin sees only platform plans. Preserve that
contextual rule initially unless an explicit policy decision authorizes a wider
MCP agency selection. The revision should include every plan and retained entry
field feeding the canonical matrix and dish-list worksheets. No passport history
or physical event should be created.

For broadcast exports, the existing website can enrich selected recipient,
rejected, replaced, unidentified, and source-traveller rows using linked groups,
overrides and latest delivery attempts. The requested broadcast is the primary
owner. Freeze the exact used group associations and selected row identities;
validate every one before generation and recovery. Read-only export authority
does not imply permission to send a message. Canonical source selection must be
bounded before loading a whole broadcast roster and reject stale/unavailable
requested rows, rather than silently filtering them.

The connector currently requires agency/group UUIDs in artifact metadata. Extend
the wire contract with a versioned discriminated owner scope and validate its
exact shape. Preserve legacy fields for existing group artifacts. Old connectors
should fail closed on unfamiliar non-group artifacts. Local destination and
checksum/size verification contracts remain unchanged.
