# Contact workbook correction messages

This local slice makes rejected contact workbooks recoverable without changing upload authority,
scanner policy, source limits, staging, broadcast creation or message dispatch. It is based on
`48c2ebdb1b638964b41cbc6e40cb33932588fad0`; deployment and the complete real-Codex Excel-to-message
journey remain separate acceptance work.

The contact upload endpoint returns HTTP 422 with exactly `code` and fixed `detail` for these
parser failures:

| Code | Correction |
| --- | --- |
| `contact_workbook_formulas_unsupported` | Select a separate values-only XLSX copy without formulas or defined names. |
| `contact_workbook_active_content_unsupported` | Select a separate plain XLSX copy without external links, macros, embedded objects or active content. |
| `contact_workbook_invalid_package` | Open the file in a spreadsheet app and save a new plain XLSX copy. |
| `contact_workbook_capacity_exceeded` | Reduce the copied workbook to the existing sheet, row, column, cell, text and package limits. |

Every correction tells the user to retain the original. Neither the API nor connector edits a
workbook, guesses mappings, retries the upload, creates a broadcast, or sends a message in response
to a rejection. The existing size/checksum/content-type/authentication validation remains separate.

The scanner still runs before parsing. A malicious workbook or unavailable/misconfigured scanner
keeps the existing security response, without a workbook correction code or a suggestion to bypass
scanning. Rejected parser input keeps the existing `XLSX_VALIDATION_FAILED` evidence; the request
transaction rolls back, then the existing safe failure audit commits once. Filenames, cells,
parser exceptions and provider details are not added to responses or failure audit metadata.

Only the contact-upload 422 OpenAPI alternative gains this schema. The connector accepts known
codes only on the configured origin's exact `POST /mcp/contact-imports/uploads` route and only with
HTTP 422. It reconstructs guidance from a local allowlist, ignoring the server's free-form detail.
Unknown codes, extra fields, malformed JSON, other routes/statuses, non-JSON and compressed error
bodies retain the generic failure. Error parsing retains at most 4 KiB; this is a parser-buffer
bound, not a total process memory claim. Authorization failures still clear cached tokens.

Local validation covers real HTTP uploads with scanner/storage fixtures and actual SDK calls to
the local connector with HTTP fixtures. The backend contract and connector guidance are checked
for exact equality. These tests exercise both rejection and a corrected-copy upload, with no staged
source or business/message rows on rejection; the corrected upload reports `business_import` as
`not_started`. PostgreSQL mutation behavior is unchanged by this error-only slice.

Local checks on 30 September 2026:

- Contact ingestion and streaming transport contracts: **56 passed**.
- Shared spreadsheet importer, WhatsApp ledger/facade and PDF/header transfer regressions:
  **143 passed** (distinct from the preceding suite).
- Connector corrective errors, contact uploads and artifact transport: **41 passed**, including
  actual local SDK dispatch with HTTP fixtures and hostile error payloads.
- Strict mypy: **6 production modules passed**. Scoped Ruff, architecture boundaries, all
  **87 backend module budgets**, inventory check and **12 inventory drift tests** passed.
- Backend OpenAPI snapshot regenerated and reviewed; the mobile projection remains unchanged.

The coverage ledger changes only the reviewed contact-upload decorator fingerprint required by
its response schema. All workflow dispositions, phases, statuses, requirements and tool counts
remain unchanged. No phase completion or provider-delivery claim follows from this change.
