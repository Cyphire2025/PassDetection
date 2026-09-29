# MCP coverage, effect boundaries and baseline

The [workflow matrix](mcp-workflow-coverage.json) is a reviewed implementation
ledger. It never grants runtime authority and it does not claim that planned
operations are implemented. Source/API/UI entries can describe the same business
workflow; surface counts must not be advertised as tool counts or completion.

The original source baseline has 419 route declarations, compared with 401
operations in the committed OpenAPI snapshot, and 351 frontend callable entries
plus 62 pages. Source discoveries include websocket/association/callback routes
and business operations missing from the snapshot, including document follow-up,
room creation/allocation/edit/order, and WhatsApp recipient-detail edits. New MCP
routes are separately included as their source becomes available.

Run `python scripts/mcp_inventory.py --check` from the repository root. CI runs
this before backend qualification. `--output <path>` writes discovery only; it
does not approve or classify anything. Review a changed surface's behavior, then
update its exact `surface` object and its disposition, workflow, phase and adapter
requirements. New/removed routes, signatures, router constructor/prefix changes,
registration loops, API-facade changes and browser pages require review. Facade
fingerprints cover aliases and non-async methods that the callable-name index may
not recognize. This static inventory is not an end-to-end browser flow analysis.

Each allowed entry stays `planned` until a concrete adapter exists. Use
`implemented_unverified` while its execution evidence is outstanding. `verified`
requires an adapter identifier and retained evidence files, whose actual scope
must support the claim. A path existing is only a bookkeeping check: the
coordinator still reviews the test result and phase gate. An HTTP handler or a
passing inventory check is insufficient evidence of MCP implementation.

Internal dependencies include browser pages, authentication/device protocols,
provider callbacks, public upload protocols and real physical-event evidence.
The related administration workflows remain implementation obligations. Only
record/file/member removal, archive/purge/destructive cancellation and server
control qualify for the agreed exclusions. Operations with unsafe current
implementations remain planned with a required safe adapter; they are not silently
excluded to shrink the scope.

## Shared policies and effect review

Every business adapter must first enforce active-superadmin MCP authority, then
reuse the application's agency/group authorization and validation policy.
Relevant policies live in `backend/app/application/security/authorization_policy.py`,
`backend/app/presentation/dependencies/auth.py` and
`backend/app/presentation/dependencies/csrf.py`. Sensitive identity actions retain
the existing recent-MFA requirements. Browser roles and tokens are not MCP grants.

The matrix records confirmed dangerous effects for particular workflows:

- Manager/staff assignments delete existing access rows before replacement;
  safe adapters add grants while preserving existing membership/history.
- Client-group WhatsApp linking removes omitted links and can cancel queued
  private delivery; safe adapters add links under a lock.
- Broadcast updates replace support-contact rows; new contacts must be additive
  or versioned.
- Rooming add, generation and allocation can clear plans and assignments; safe
  adapters require retained versions, not just a ban on `mode=remove`.
- Menu regeneration deletes current meal entries; create a separate retained plan.
- Document reupload/save can remove old rows and schedule source-file cleanup;
  retain the original documents and files before enabling these adapters.
- Announcement edits delete drafts; retain previous drafts and published versions.
- GC App disable/revoke can schedule purges, and retention settings can schedule
  archiving; reject these variants through MCP.
- Physical attendance/check-in scans require authentic device/runtime/event
  evidence; conversational instructions cannot manufacture that evidence.

## Export and transfer contract

Passport Excel generation creates pending history; delivery completion is a
separate authorized operation in `passport_routes/export_history.py`. MCP must
only complete it after an authenticated local/direct transfer has verified size
and checksum. Interrupted transfers, expired grants and denied downloads must not
create a successful history checkpoint. The matrix includes group, selected,
incremental/extra-field Excel; passport images/ZIP; WhatsApp tracking/broadcast;
document assignments; rooming/check-ins; meals; ECR; renamed documents; audit CSV;
and GC/mobile document content dependencies.

## Diagnostic sources

The current structured logger writes API and worker application events to stdout.
Request middleware adds `request_id`; frontend errors enter the bounded
observability endpoint; providers and jobs write through their application
modules. Nginx has access/error logs with `request_id` in its configured format.
These are source locations, not proof of a readable retained log collector.

Allowed diagnostic adapters need separately configured bounded sources for API,
worker, frontend reports, integrations and proxy logs. They must report unavailable
when a source cannot be accessed, and redact credentials, raw documents and
unnecessary personal details. No Docker socket, arbitrary file path, command,
SQL or unrestricted HTTP tool is an acceptable logging adapter. Job-to-request
correlation now has a tested initial service: `MCPDiagnosticService` reads selected retained audit and passport-job fields, while the production `SealedMCPLogReader` accepts only five fixed JSON-lines sources in a fresh, digest-verified exclusive run under an operator-configured dedicated read-only mount. The separate Linux operator collector uses bounded read-only Docker logs and persists only the shared safe projection; see `mcp-diagnostic-collector.md`. The default reports collector-not-configured. Each tail is limited to 512 KiB, 2,000 records and 16 KiB per record; tool results cap at 100 per source. Unknown/free-text fields, exception messages, paths, headers, raw documents and personal metadata are omitted. Runtime retention/access evidence remains open. Full correlation is not universal: passport jobs do not store request/event/audit IDs, and the service states that limitation.

## Production baseline and release gate

The [baseline receipt](mcp-production-baseline.json) separates repository settings,
historical observations and current unavailable measurements. Docker's local Linux
engine is currently unavailable. The usable local interpreter is CPython3.11.15
in the primary `.venv311`; the broken default virtual environment is not used.

The current code-update procedure deliberately does not migrate databases. MCP
grants and workflows need a separately reviewed migration-aware qualification.
The recorded KVM4 profile and prior synthetic workload do not measure MCP overhead,
the actual current production deployment, or simultaneous host peak capacity.
Current authenticated read-only schema/resource/runtime/default-grant evidence is
recorded in the baseline receipt. Live collector activation, candidate behavior
and combined MCP capacity remain open; implementation may continue meanwhile. The user's deferred Hostinger
container cleanup remains outside this work.
