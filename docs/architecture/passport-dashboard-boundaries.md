# Passport dashboard API boundaries

The public API is composed in `backend/app/presentation/api/v1/routes/passports.py`.
The facade retains the established route order, endpoint names and legacy helper
imports. Workflows live in ordinary Python modules in `passport_routes/`; runtime
source rewriting, module proxies and global dependency forwarding are not used.
Tests patch the module that owns a dependency.

| Boundary | Responsibility |
|---|---|
| `public_upload`, `public_security` | Public upload, credential verification and lifecycle checks |
| `queries`, `response_support` | Office list/view queries and response rendering |
| `submission_review`, `bulk_actions` | Review, approval, deletion and bulk operations |
| `document_import`, `excel_import` | Staff imports and durable processing intent |
| `images`, `image_support` | Authorized image access, crops and library operations |
| `excel_exports`, `selected_exports`, `image_exports` | Export workflow orchestration |
| `export_context`, `export_history` | Scoped export inputs and immutable download history |
| `visa_ai_jobs`, `visa_ai_edits`, `visa_ai_library`, `visa_ai_support` | Visa job lifecycle, edits, inputs and shared policy |
| `processing_support`, `dependencies`, `constants` | Shared processing boundaries, dependency providers and compatibility imports |

Each new route module has a reviewed size/complexity ratchet in
`backend/backend_quality_budgets.json`. The largest is below 650 lines; this is a
maintainability guard, not a substitute for testing business behavior.

## Authorization and roster consistency

`public_upload_capability.require_active_public_upload` rejects missing, closed,
archived and deleted groups before accessing retained submissions or private
objects. Public upload checks the capability before image validation/decoding.
The same lifecycle policy applies to retry, reconcile and discard. There is no
implicit grace period after a group closes.

`operational_roster_member()` expresses the active replacement/rejection policy
as a tenant-and-group-scoped SQL predicate. Live exports, document delivery,
attendance, rooming and QR issuance/validation apply it before limiting or
counting passengers. Office review/history can still show excluded submissions.
Restoring a resolution makes that passenger operational again without rewriting
historical attendance, export or delivery records.

## Durable processing and uncertain commits

Staff document imports stage OCR job rows in the same transaction as their
image references. Broker publication happens after commit. The API application
runs bounded periodic extraction recovery: it leases stale queued or expired
running jobs using `FOR UPDATE SKIP LOCKED`, commits the lease, then dispatches
outside the request thread. Queued rows remain recoverable even if a previous
broker task identifier was recorded. Exhausted jobs enter the existing dead
letter state. Each API process supervises at most two local recovery tasks;
this limit is per process, not a cluster-wide concurrency promise.

When an import transaction fails after storage uploads, a fresh database session
checks canonical submission/image-library references before staging encrypted,
durable cleanup jobs. An ambiguous commit cannot trigger immediate deletion of
the objects it may have saved. If that fresh check is unavailable, uncertain
objects are retained and an operational event is logged. The API returns an
explicit uncertain-result response so the operator can refresh before retrying.

## Export and page cost

Workbook generation runs outside the async request thread. Explicit append-row
counters avoid repeatedly scanning the worksheet cell collection. Existing
styling, formulas-as-text protection, dates, zone separators and pending-row
highlighting remain covered by workbook regressions. Combined group exports
reject more than 1,500 active-plus-pending rows before workbook generation.

The submission view loads a narrow authorized identity projection, computes the
existing duplicate/search/order rules outside the request thread, then hydrates
full records and image crops for the requested page. The second query repeats
tenant, staff/coordinator, lifecycle and office-status restrictions. A missing
row or changed extraction revision/update timestamp returns a recoverable 409
instead of mixing old identity metadata with a newly changed record.

Identity computation and selection ordering still inspect the authorized group.
The API preserves whole duplicate clusters across page boundaries; one unusually
large cluster can therefore exceed the requested page size. It is inaccurate to
describe this as constant-cost pagination or a strict 50-row hydration ceiling.
Raw OCR, storage keys and staff/document metadata are not loaded for ordinary
off-page rows. There is no cache shared across users or visibility revisions.

## Local evidence and operational limits

`backend/scripts/benchmark_passport_dashboard.py` compares the checked-out code
with a local Git revision using invented rows and an in-memory SQLite database.
It checks workbook values/styles/table extents and submission ordering as well
as timing and Python allocations. The 5 September 2026 run compared commit
`4a90d422a85a92d0a8a7ae9d672ea46de9f688c7` with this source on Python 3.13.12:

| Synthetic passengers | XLSX baseline / current median | View baseline / current peak Python allocation |
|---:|---:|---:|
| 800 | 0.462 / 0.218 seconds | 12.15 / 1.97 MiB |
| 1,500 | 1.015 / 0.321 seconds | 22.50 / 2.63 MiB |
| 3,000 | 3.347 / 0.592 seconds | 44.88 / 4.49 MiB |

XLSX timing uses three runs and ten additional pending rows; 3,000 rows directly
stress the exporter and exceed the API's combined export limit. The view fixture
contains 8 KiB of invented off-page OCR/metadata per row and unique identities,
with a requested page of 50; actual savings depend on record size and clusters.
SQLite timing and Python allocation tracking do not establish production
PostgreSQL, network, multi-worker, provider or recovery throughput. The local
JSON evidence is `outputs/passport-performance-comparison.json`.

The isolated OpenAPI comparison reports 46 paths, 50 operations, equal schema
definitions and unchanged route order. Source tests cover public lifecycle
denials, lost commit acknowledgement, recovery leasing, operational membership,
distinct per-passenger QR payloads, page hydration races and worker-thread
export execution. Live provider calls and production data were not used.
