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

The final source was deployed as a retained backend/proxy update on the existing
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

Production verification completed on 1 October 2026. The serving backend revision
is `1772e6c6f12c82df837c90d3de595281e9fae71f`. The guarded cutover completed at
12:09:24 UTC on the same schema. Its 14,922,235-byte PostgreSQL archive passed
full `pg_restore` decoding before the switch; restoration into a second database
was not rehearsed. A subsequent read-only server observation confirmed all
20 running services healthy, zero restarts or OOM events, and preservation of all
330 prior containers, their configurations and 187 prior images. The three
previously approved stopped historical reference anomalies remain unchanged.

After the cutover, the authorized Superadmin session enabled My Tour, Audit Logs
and Settings through the normal website and received “Read access saved and
confirmed.” Fresh authenticated MCP responses confirmed all 18 read sections,
34 observational tools and all 89 catalog views enabled. There was no grant
expansion beyond `mcp:read`; export authority returned HTTP 403 and the empty
write-tool request was denied.

The live SDK probe performed 32 detail observations covering 23 distinct views
and every supported section. It verified all seven saved broadcast record kinds,
the sample recipient's 16 imported headings and their continuation, passport
staff-code/expiry fields, warmed roster page two, QR metadata continuation,
business settings/audit and document/rooming/menu/GC/email observations. All four
delivery-history queries succeeded. The selected agency contained a broadcast
attempt sample; its full saved detail, provider-receipt view and history cursor
were read successfully. Document, QR and welcome histories were empty in that
selected live sample; populated examples of all four kinds passed the isolated
PostgreSQL tests. Live observations do not claim to exercise every possible
resource, role or all 89 views with nonempty customer data.

A fresh actual Codex run discovered `list_dashboard_read_views`, then used
`read_dashboard_view` to read one of the sample recipient's 16 imported fields.
It verified the production revision and all 18 section permissions. The receipt
retains only counts and audit/envelope metadata; customer field names, values,
raw model text and credentials are not saved. Existing chats may need a fresh
MCP session to discover the three newly added tool definitions.

Final local qualification passed 38 detail tests, 37 isolated PostgreSQL replay
cases and 190 retained deployment/operator cases. Both local PostgreSQL test
servers started for this work were cleanly stopped after qualification; their
data and all release evidence were preserved.
