# Dashboard detail reads — 1 October 2026

This update adds read-only access to the dashboard details that the original
31-tool release could not return. It exposes 34 observational tools, including
an explicit catalog of 89 reviewed dashboard views, and supports all 18 business
sidebar sections. Current website section permissions remain authoritative.
My Tour, Audit Logs and Settings require explicit activation through the normal
Superadmin permissions screen; deployment does not change that screen's values.

The failed questions in “Get live group via MCP” are covered by saved staff-code
fields and their provenance, canonical passport-expiry alerts, full WhatsApp
recipient/match/unidentified-upload tracking, and hydration of identity-only
cached passport pages. An unidentified upload is an unmatched passport upload,
not an active imported broadcast recipient.

WhatsApp detail reads retain original import headings and values, empty fields,
removed recipients, merged contacts, rejected rows with file/sheet/row provenance,
source contacts, support contacts, group links, phone overrides and saved message
states. Exact imported-field filtering and literal text search are supported.
Delivery reads cover document, QR, broadcast and welcome attempts, complete saved
message/template/error details and verified retained provider receipts. Submitted,
sent, delivered and read retain distinct meanings.

The catalog also covers document review/matching and delivery eligibility, group
configuration and custom answers, roster/expiry fields, stored image-library and
AI-job metadata, rooming/hotels/check-ins, menu plans, tour/attendance/closeout,
coordinator assignments, GC App content and notifications, account directories,
business audit, platform settings, personally owned email data and global search.
Existing views with latest-200/250 caps now provide bounded continuation. Large
objects, imported fields and text expose complete navigable references rather
than silently dropping data. The caller must follow every indicated continuation
and reference before describing results as complete.

Each fixed view uses reviewed website read semantics or a dedicated stored-data
adapter. No caller-controlled route, SQL, table, module, function or authority is
accepted. Live role, section union, tenant/resource and personally owned mailbox
checks remain in force. Dashboard reads reject business DML, deferred ORM edits
and inner commits; only audit-ledger maintenance is permitted. Observational
adapters avoid website GET workflows that issue QR codes, recover stale delivery
jobs, insert original image-library records, dispatch AI jobs or sign file URLs.
Credentials, storage keys and protected file capabilities are withheld. Writes,
sends, retries, uploads, downloads and exports remain denied.

The final source is intended for a retained backend/proxy update on the existing
`0123_mcp_read_sections` schema. No migration or permission SQL is required.
The deployment operator takes and fully decodes a custom PostgreSQL backup,
binds the actual prior serving containers and all present resources, uses the
previously approved exact historical resource exceptions and preserves the
frontend/workers with their truthful previous revision. Failed candidates remain
retained; recovery restores the previous backend/proxy on the same schema.

The valid deployment credential is the one-month key already enabled by the
user, ending on 30 October 2026 at 13:17:27 UTC / 18:47:27 IST. A strict SSH read
on 1 October confirmed it works. The earlier 12-hour key is a separate expired
credential and must not be used to infer that the one-month grant expired.

Local evidence is kept under `outputs/mcp-dashboard-details-*`. A deployment
claim requires a completed retained operator receipt and fresh authenticated SDK
and actual Codex verification. A local passing test or source commit alone does
not establish production availability.
