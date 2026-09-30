# Excel export options checkpoint

Reviewed on 2026-09-30 in the isolated `codex/mcp-export-options` checkout,
based on `e62668af`. This slice adds `inspect_excel_export_options` and a pure
application projection shared by the existing website field-option routes.
It does not close Phase 3 or Phase 4 or establish production qualification.

## Contract and effects

The tool accepts an explicit `agency_id`, 1–100 unique `group_ids`, and either
`selection=group` (exactly one group) or `selection=selected_groups`. Names,
ambiguous matches, individual passport selections, incremental requests and
agency-field overrides are not accepted. It requires the current active
superadmin grant with `mcp:export` and the enabled `passport_excel` family.
The complete selected group scope is authorized before source materialization.

Results include the canonical supplemental field catalog, grouping choices,
default selected fields and default grouping. Single-group results additionally
expose the agency-match enablement and its separate canonical catalog; selected
groups explicitly report agency matching unsupported. Empty and imported-contact-only
groups participate in the website's exact catalog merge, including common-field
ordering, selected group order, Zone defaults and label disambiguation. Agency
matching intentionally permits imported fields excluded from the supplemental
catalog. No sample values are returned to discover names.

Options reuse the existing source-admission locks and per-family row/total byte
budgets, before full ORM hydration. The release profile and PostgreSQL evidence
use 100 rows per source family and 1 MiB total admitted source bytes. The response
reports the effective configured limits rather than assuming those values for
every deployment. Each supplemental or agency catalog is limited to 256 fields;
grouping allows 257 entries to retain the extra fixed International Airport
choice. Keys are limited to 180 characters and labels to 120. The serialized
response is capped at 512 KiB. Any invalid or oversized complete catalog returns
a fixed unavailable/limit error without partial fields or raw validation details.
Contended sources return a retryable busy result.

The shared projection is used by both website routes without changing their
HTTP shapes, role policies or source selection. Options do not prepare/render a
workbook, initialize storage, create durable operations, artifacts, messages or
export history, or return an export creation revision. Agency/ECR workbook
inputs and export-history baselines are not needed by catalog discovery. The
normal invocation envelope still contains its deployment revision and fixed
read-audit metadata; that is distinct from `expected_revision` obtained by the
subsequent export inspection.

## Explicit remaining scope boundary

The tool reuses the currently exportable MCP group scope, which rejects groups
with retained deleted status or deletion timestamps for every actor. The website
superadmin field routes can discover some retained deleted groups. A regression
asserts the MCP denial, and this slice does not broaden that policy or claim
retained-deleted-group discovery parity. Other export families and list/get
export-history adapters remain separate work.

## Finite coverage reconciliation

Exactly six existing matrix implementation records change from `planned` to
`implemented_unverified`: the source, OpenAPI and frontend-callable entries for
each of the two existing group/selected-group field-options routes. All existing
surface contracts, dispositions, phases, requirements and other workflow states
are preserved. Their evidence now points to the concrete options adapter,
shared projection and relevant local tests. A seventh row classifies the newly
discovered tool with read-only effects and the same implementation status.
No registration fingerprint changed in static discovery. This bookkeeping does
not imply that option discovery creates artifacts or needs a mutation receipt;
the inherited generation/delivery requirements on the existing export-family
rows remain applicable to their associated export workflows.

## Evidence

- An initial combined functional run passed 101 tests in 22.02 seconds: options,
  existing Excel generation, export capacity, release-family registration,
  selected-group catalogs and pending-contact helpers.
- After adding the maximum-field-plus-airport boundary, a final run passed 75
  tests in 15.01 seconds: all 31 options cases plus existing route decomposition,
  offload and export-history routes. These runs overlap; their counts are not
  additive. Actual local ASGI MCP calls cover token/capability boundaries,
  schema annotations, safe failures and fixed successful audit metadata.
- Independent PostgreSQL qualification passed 14 cases in 4.67 seconds using
  retained schema `mcp_source_216dc542f8e84b2eb70ea9b6be5ddaf5`. It covers canonical
  empty/import-only/multi-group results, 101-row rejection, oversized UTF-8
  group/broadcast/recipient/passport source rejection before ORM hydration,
  and lock contention followed by a fresh successful read. This is an
  ORM-created isolated schema, not migration or runtime-role qualification.
  Local receipts are retained under `outputs/mcp-excel-options-pg-20260930.xml`
  and `outputs/mcp-excel-options-pg-evidence-20260930.json`.
- Scoped Ruff, strict mypy on six affected source modules, the architecture
  validator, all 87 backend quality-budget ratchets and `git diff --check`
  passed. The six new infrastructure import edges have an explicit reviewed
  architecture entry; no general exemption or budget increase was added.
- Inventory drift checking passed with 1,494 surfaces and 69 tools; all 12
  inventory contract tests passed. The ledger changes exactly six existing
  implementation objects and adds one classified tool, without modifying
  existing surface contracts or the separate dashboard contract checkpoint.

The frozen options revision `60fa04916529b2a2d5c613b990a834314517a658`
subsequently passed the full backend regression: **5,904 passed, three skipped,
313 deselected and 162 subtests passed**, in 990.55 seconds, exit zero. The
three platform skips and separately selected service-integration lane remain
explicit; the 14 PostgreSQL cases above are independent evidence. This qualified
slice was pushed directly to `main` with hosted CI skipped. A later integration
with the dashboard read has its own aggregate qualification gate.

The integrated `27afeb4c` revision subsequently passed 5,921 tests and was
deployed through the reviewed backend-only release. Three actual Codex calls
verified both option modes and unchanged limits against that production revision;
see the [release checkpoint](mcp-options-dashboard-release-checkpoint.md) for exact
runtime, audit and client evidence. No workbook or new business record was
created. Provider and combined-load/capacity evidence remain separate. Coverage
stays `implemented_unverified` pending the broader acceptance gates.
