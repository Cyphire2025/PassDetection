# Excel options and dashboard backend release

Historical release checkpoint: backend `27afeb4ce0bb427eb4a87eb0913f92f36f2b3e59`
was replaced by the later [read expansion release](mcp-read-expansion-release-checkpoint.md).
Its backend-only cutover completed on 2026-09-29 UTC; independent verification passed at
**23:57:02 UTC**. The frontend remained continuously on
`1d77c9ddb16439e62d29f85067377f23070552b6`, and workers/scheduler retain
`efea4e4a`. Schema `0122_mcp_gc_push`, the named connection, read/export-only
capabilities, `passport_excel`, 100 source rows per family and the 1 MiB source
limit are unchanged. All eight overall phase gates remain open.

## Qualified implementation

The [Excel options checkpoint](mcp-excel-options-checkpoint.md) and
[dashboard summary checkpoint](mcp-dashboard-summary-checkpoint.md) describe
their shared website projections, precise scopes, limits and separate PostgreSQL
evidence. Integration passed 56 focused cases. The full combined regression
passed **5,921 tests, three skips, 318 deselected and 162 subtests** in 998.28
seconds. Inventory checking reported 1,495 surfaces and 70 tools; the architecture
contract and all 87 quality budgets passed. The exact qualified source was pushed
directly to `main` with hosted CI skipped.

## Release and independent runtime evidence

The immutable backend-only v2 operator was reviewed independently; all 96 mocked
flow cases passed. It requires the successful management-v3 release and its
frozen operator/source/image lineage, preserves the frontend, replaces only the
backend and proxy, and drains/resumes the existing eight workers. It retains all
prior resources, verifies original memory/restart policies and exact application
script/revision assets, and accepts only the previously observed optional
Cloudflare beacon. An 8 GiB disk floor is required before preparation and build.
The earlier operator remains retained and was never executed on the VPS.

Operator SHA-256:
`e0c832d234080ba1bf7f8c1bddfc81c572663f2da7c98dc2fec5b59a91664641`.
Wrapper SHA-256:
`4af4e937d6115ee1986f48a2986a186c07dbbd87f7a6ed20cfb5a01d53041e18`.
The staged archive contained 3,976 files and 191,907,840 bytes; its SHA-256 was
`7953913e05506cb0db244521c01383f6897341221c008b6d85575e90ba133390`.
Preparation, build, stage and cutover each completed once with exit zero. The
exclusive journal terminates at `0037-options-backend-v2-complete.json`.

The independent probe confirmed:

- Exactly 20 running services, including 12 application services and all ten
  configured application health checks healthy. Frontend and proxy have no
  configured Docker health check; they are not counted as healthy checks.
- No new application OOM event or restart. Continuous frontend, infrastructure
  and scheduler identities were unchanged. Prior backend/proxy containers were
  stopped; all prior and intermediate resources remained retained.
- Public live/ready health and OAuth resource metadata each returned 200.
  One anonymous management request returned 401 and retained exactly one matching
  fixed denial audit, with null actor/entity, no credential/request data and an
  assigned integrity sequence.
- The existing frontend build ID, all 17 scripts (1,136,074 bytes), compiled full
  revision and public revision-asset digest matched the preserved baseline.
- Container limits still total 14,562,623,488 bytes. Observed host MemAvailable was
  10,833,920,000 bytes. This is a startup/read observation, not combined-load proof.

The new backend image ID is
`sha256:54fbfaa6ce2993e78d4870501d1db725b9cbc11b4a7cade4f221dfd29c4535af`.
Safe local evidence is retained in
`outputs/options-dashboard-live-independent-20260929.json`; private deployment
receipts remain in the revision-specific VPS directory. No schema/configuration,
grant, credential, MFA, expiry, cleanup or customer-message action was performed.

## Actual Codex and browser observations

The saved Windows-vault connector passed exactly three actual Codex calls:
`connection_status`, then `inspect_excel_export_options` for group and
selected-groups mode in the same explicit agency/group scope. The run started at
**23:57:06 UTC** and completed in 132.265 seconds, exit zero. A deterministic
validator checked actual paired tool events, exact arguments, structured/text
agreement, full production revision, audit/time envelopes and unchanged
capabilities. Both modes returned 12 fields, 13 grouping choices and one default
field. Group mode exposed 15 agency-match choices; selected-groups mode correctly
reported agency-match unsupported with zero such choices. Catalog membership and
configured-limit checks passed. No workbook, operation, artifact, history entry,
download or message was created. Safe receipt:
`outputs/mcp-live-codex-20260929/options-readback-run.json`.

The separate dashboard run started at **23:59:38 UTC** and passed in 103.703
seconds, exit zero. Exactly two calls, `connection_status` and
`get_dashboard_summary`, passed the same event/envelope/revision checks plus
the exact six-column, five-row preview schema and explicit non-atomic consistency
contract. The current user's agency returned 3,356 passport submissions, zero
pending review, 563 confirmed, one active link and five recent rows. A separate
authenticated browser observation of `/dashboard` showed those same four counts
and five cards; at the observed 650-pixel viewport there was no horizontal
overflow. Names, emails and other row content are omitted from safe evidence.
This is current-user/count equality at adjacent live observations, not a claim
of an atomic snapshot, every row's value equality or other role/scope variants.
Safe receipts are `outputs/mcp-live-codex-20260929/dashboard-readback-run.json`
and `outputs/options-dashboard-browser-evidence-20260930.json`.

The independent event validators passed 44 local synthetic cases. They reject
extra/unexpected tools, incorrect ordering/arguments, unpaired or incomplete
calls, nonzero CLI exit, timeout and mismatched structured/text results; a model's
final answer cannot establish success. Raw bounded events/stderr remain private.
The permanent connector/configuration and Windows-vault authority were reused.
Broad role/data variants, remaining live security cases and combined Linux/VPS
capacity remain separate open gates.
