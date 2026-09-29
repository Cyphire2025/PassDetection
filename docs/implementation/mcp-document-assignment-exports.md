# MCP document-assignment spreadsheets

Qualified local checkpoint:25 SQLite/canonical generator tests,3 PostgreSQL source/recovery races, and1 official SDK connector-to-loopback-HTTP generation and verified delivery test passed. Scoped Ruff, mypy4 and backend module budgets pass. Server registration and deployment family enablement are owned by the coordinating agent.

The adapter exposes the existing website document-assignment review workbook for
one exact agency/group/document-type tuple. The six canonical document lanes are
accepted. Filters are `all`, `assigned`, `missing`, `sent`, `not_sent`, and
`multiple_pdfs`; optional passenger-name search follows the website's trimmed,
case-insensitive matching. No combined all-agency or all-group export is exposed.

`document_export_tools.py` composes the canonical passenger reader, pure document
response calculation, passenger review grouping, row filter and filename helper.
The existing document response's presigned URL step remains on the web path;
MCP does not initialize that storage client or create PDF URLs. The canonical
workbook generator is shared. A later failed send does not erase an earlier
accepted delivery in the review. Distinct storage identities determine the
physical PDF count. Provider message/media IDs, template bodies, error text,
document storage keys and PDF URLs are not spreadsheet columns or tool results.

Preparation requires current MCP export authority, exact live group association
and the existing group export permission. Group UPDATE precedes passport SHARE,
document UPDATE and delivery SHARE locks, using NOWAIT to avoid cycles with older
writers. Parent locks fence inserts through foreign keys. Source rows, retained
document details, and projected delivery status/phone/timestamp fields are
re-read for revision fences before rendering, before storage and after storage.
No unmatched or unauthorized passenger from another group can be silently
included; a malformed cross-group assignment rejects the request.

The shared container export admission gate is held before bulk preparation and
through cancellation-drained rendering and storage. Limits reject whole scopes:
1,500 total group passport rows, 3,000 retained assignments for the selected lane,
6,000 delivery-history rows, 16 MiB canonical snapshot, 32 MiB XLSX output and a
120-second render deadline. The fixed 13-column workbook has at most 1,500
passenger rows. Joined cell text exceeding 32,767 characters is rejected before
rendering so Excel cannot silently truncate a long list of document filenames.
The snapshot bound follows ORM loading and does not independently
prove a peak-memory ceiling for unusually large retained source JSON/text.

A committed DB-only operation receipt precedes separate generation. Retry uses
the same original idempotency key; successful recovery uses the same unexpired
artifact. A newly authorized grant for the same actor receives its own locator
after current scope checks. Expired or missing successful files never regenerate.
The purpose is `document_assignments_excel`, using the existing group-bound
artifact schema and fixed authenticated download transport. Local checksum/size
verification precedes delivery acknowledgement.

The workflow creates only operation/audit records and a protected transfer copy.
It does not alter assignments, batch state, document approval, original files,
delivery records, passport history, or WhatsApp messages. There is no export
history checkpoint because the website review export has none. Rollback can leave
a private transfer object after a completed conditional PUT; the transfer-copy
TTL lifecycle must clean those copies without touching originals.
