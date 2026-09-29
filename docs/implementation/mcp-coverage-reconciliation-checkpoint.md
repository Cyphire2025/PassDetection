# Finite MCP coverage reconciliation

Reviewed and applied against clean source
`aca242ce13ed56a39f6e1974ec241acb8a5e6d9e` on 2026-09-30. Root authorized this
finite correction independently of the pending real-Codex acceptance gate. The
[workflow matrix](mcp-workflow-coverage.json) remains a coverage ledger, not a
runtime permission list. No workflow is newly enabled by these changes.

Exactly 44 existing rows changed: 27 source/OpenAPI/frontend export surfaces now
map to executable adapters as `implemented_unverified`; 14 audited client helpers
or UI components are `internal_dependency` with null phase and `not_applicable`
implementation; three existing document-export tool rows gained evidence paths.
No row became `verified`, no discovered surface was removed, and no exclusion
was added or broadened. All source fingerprints, adapter requirements, effect
reviews and exclusion boundaries were preserved, including the requirements
recorded alongside the client helper rows.

## Export mappings

Each business variant has three matrix representations: its source handler,
OpenAPI operation and frontend callable. These surface counts are not tool counts.

| Business variants | Surfaces | Adapter under `backend/app/presentation/mcp/` | Retained evidence |
| --- | ---: | --- | --- |
| Passport XLSX: group all/incremental, selected groups, exact selected passports | 9 | `export_tools.py` | [Excel contract](mcp-excel-exports.md), relational/parity tests, PostgreSQL races and connector TCP delivery |
| Passport image ZIP: group all/incremental, exact selected passports | 6 | `image_export_tools.py` | [Image contract](mcp-image-exports.md), crop/zone byte parity, PostgreSQL races and connector TCP delivery |
| Group WhatsApp submission-tracking XLSX, eight filters and optional linked broadcast | 3 | `tracking_export_tools.py` | [Tracking contract](mcp-tracking-exports.md), canonical filter parity, PostgreSQL races and connector TCP delivery |
| Hotel rooming-list and check-in-control XLSX | 6 | `rooming_export_tools.py` | [Rooming contract](mcp-rooming-exports.md), both canonical workbook kinds, PostgreSQL races and connector TCP delivery |
| Document-assignment review XLSX, exact group/document type, six filters and search | 3 | `document_export_tools.py` | [Document contract](mcp-document-assignment-exports.md), canonical review parity, PostgreSQL races and connector TCP delivery |

Each mapped row names its adapter and four concrete evidence files: the contract
document, integration tests, PostgreSQL tests and connector TCP test. Existing
`inspect_document_assignment_export`, `prepare_document_assignment_export` and
`resume_document_assignment_export` tool rows received the same four evidence
paths without changing their `implemented_unverified` status. Evidence paths were
checked to exist; business suites were not rerun for this bookkeeping correction.

## Client dependencies

The five `auth/services/session-state.ts` functions coordinate browser account
ownership, privacy cleanup, cookie-session logout and reset events/subscriptions.
Their cleanup preserves the owner-scoped attendance queue. They are browser
authentication dependencies, not separate administrator business operations.

The remaining nine dependency rows are the pure WhatsApp `rosterItemForExport`
selection mapper; the managed document-thumbnail loader; the public-upload
`isPdfUpload`, `publicUploadFileError` and token/session-bound
`preparePublicUploadFile` helpers; bounded `renderErrorMetadata` and
`reportRenderError` telemetry; and the `PlatformSettingsPanel` and
`WhatsAppTemplateSettingsPanel` React components.

This correction follows their inspected behavior and callers. Standalone
broadcast exports, authorized image/document reads, permitted upload/processing,
diagnostic reading and safe settings operations remain business obligations on
their actual API surfaces. The platform component's purge action retains its
existing destructive boundary. Attendance/offline queue helpers were not
reclassified by this pass.

## Eighteen explicit residual surfaces retained unchanged

The following six source/OpenAPI/frontend triads remain `planned`, with their
previous requirements and exact source fingerprints unchanged:

| Website workflow | Remaining MCP gap |
| --- | --- |
| `get_passport_group_export_fields` / `getGroupExportFields` | Inspection returns the column catalog but lacks complete grouping/default-selection metadata, agency-match enablement and available matching-field discovery. Accepting generation options does not establish complete option discovery. |
| `get_selected_groups_export_fields` / `getSelectedGroupsExportFields` | Combined catalog exists, but the full grouping and default-selection projection still needs parity coverage. |
| `list_passport_group_export_history` / `getGroupExportHistory` | Paginated completed histories, compatible incremental-baseline discovery and new-submission counts are not supplied by single-operation recovery. |
| `get_passport_group_export_history_detail` / `getGroupExportHistoryDetail` | The frozen exported-person detail page remains missing. |
| `complete_passport_group_export_history` / `completeGroupExportHistory` | Verified MCP artifact download/acknowledgement invokes shared completion, but does not authorize arbitrary website-history IDs or model-asserted delivery. This narrower implemented delivery path must remain explicit. |
| `export_broadcast_filter` / `exportWhatsAppExcel` | Standalone broadcast roster/filter export is distinct from the implemented client-group submission-tracking workbook. Reclassifying its pure selection mapper does not remove the export obligation. |

Meal-plan, audit CSV, ECR and renamed-document exports are also outside the mapped
families. These gaps are not converted to exclusions.

## Validation and limits

- `python scripts/mcp_inventory.py --check`: passed; 1,493 surfaces, 68 tools,
  423 OpenAPI operations, 442 source routes and 361 frontend callables unchanged.
- `python -m unittest discover -s scripts -p test_mcp_inventory.py -v`:
  all 12 existing drift/truthfulness tests passed.
- Exact-change audit against the baseline: 44 expected row IDs only; all 18
  residual rows unchanged as parsed JSON; all surface fingerprints, effect
  requirements/reviews and exclusion boundaries unchanged; every new adapter
  and evidence path resolves to a retained repository file.
- Allowed surface states are now 872 `planned` and 154
  `implemented_unverified`; there are 386 internal dependencies and 81 unchanged
  manual-removal boundaries. These are representation counts, not business
  completion percentages.

This correction supplies no new production behavior or test result for an export
family. Public metadata/liveness/readiness checks establish only the separately
recorded deployment checkpoint. Real Codex, live verified transfer, remaining
workflow coverage and combined-load qualification remain distinct gates; no
whole phase or full-goal completion is claimed.
