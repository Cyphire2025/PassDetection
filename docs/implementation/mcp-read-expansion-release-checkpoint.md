# Export history, personal notifications and ECR read release

Backend `ee648457fad7273486bad5cd5f58ebe6fd308158` completed its production
cutover on 2026-09-30 UTC. Independent verification passed at **00:55:30 UTC**.
The frontend remains `1d77c9ddb16439e62d29f85067377f23070552b6`, workers and
scheduler remain `efea4e4a`, and the schema remains `0122_mcp_gc_push`.
The named saved connection still has only `mcp:read` and `mcp:export`, with
`passport_excel`, 100 source rows per family and a 1 MiB source limit. All eight
overall phase gates remain open.

## Implementation and local qualification

The [history](mcp-export-history-checkpoint.md),
[personal notification](mcp-personal-notifications-checkpoint.md) and
[ECR](mcp-ecr-read-checkpoint.md) checkpoints define their shared website
projections, authority, bounded queries and separate PostgreSQL evidence.
The integrated full backend regression passed **6,029 tests, three skips,
369 deselected and 162 subtests** in 1,098.52 seconds. The JUnit total of 6,194
includes the 162 subtests and three skips; it is not an additional test count.
Service-integration tests were excluded from that aggregate and qualified in
the independent PostgreSQL runs recorded in the component checkpoints.

Architecture checking, all 87 backend quality budgets, the 1,501-surface /
76-tool inventory and all 12 drift tests passed. The source was pushed directly
to `main` with hosted CI skipped. Notification acknowledgement code is present
but remains disabled by the unchanged production capability profile.

## Release and independent observation

The immutable read-expansion-v1 backend/proxy operator passed 124 mocked flow
cases under both author and independent root execution. A separate lineage
review checked its dependencies. Before execution, the live read-only admission
verified the 25 retained receipt/lock bindings and all 12 application bindings.
The operator follows the successful options-v2 and management-v3 lineage,
including the retained failed management-v2 candidates and original release
locks. It retains the continuous frontend, drains/resumes the existing eight
workers, replaces only backend/proxy, enforces the 8 GiB disk floor and retains
all prior resources.

- Operator SHA-256:
  `82c0fd9239ddf3a6296a8c3a7fbf87da0b768367922697bb385ffd86694a09e7`.
- Wrapper SHA-256:
  `7eb09e3feacfbc7d0380c162f8bf2569b0d12009d723c3ba622b7bd6ab160c7c`.
- Source archive: 4,004 files, 192,184,320 bytes, SHA-256
  `92d024a0ad05ca320f2a3d04e37811cfb72de17b736ff2ddd59344a0ebe43a27`.

Preparation, build, stage and cutover each ran once and exited zero. Cutover
started at **00:54:09 UTC**, and the exclusive journal ends at
`0037-read-expansion-v1-complete.json`. The independent probe then confirmed:

- Exactly 20 running services: 12 application services and eight infrastructure
  services. All ten configured application health checks passed; frontend and
  proxy have no configured Docker health checks.
- Zero new application OOM events or restarts. Frontend, scheduler and
  infrastructure identities remained continuous. Prior backend/proxy containers
  were stopped, and all prior/intermediate resources were retained.
- Public live/ready health and OAuth resource metadata each returned 200.
  One anonymous management request returned 401 and produced exactly one matching
  fixed durable denial audit, with null actor/entity/email/IP and no credentials
  or request data; its integrity sequence was assigned.
- The preserved frontend build ID, all 17 scripts (1,136,074 bytes), compiled
  full revision and revision-asset digest matched the retained baseline.
- Container limits still total 14,562,623,488 bytes. Host MemAvailable was
  10,837,331,968 bytes. This observation qualifies startup and the recorded reads;
  it is not combined-load or production-capacity evidence.

Backend image identity is
`sha256:ece9508f9f00e9e92e5a26299d29843815ca234173cb58ff2245d34175c978a8`.
The safe probe is `outputs/read-expansion-live-independent-20260930.json`;
private deployment receipts remain under the exact revision's VPS directory.
The release preserved schema, configuration, grants, credentials, MFA, original
access expiry, files and business data. No customer message was sent.

## Actual saved-Codex observations

Each proof used the saved Windows Credential Manager connector, sequentially,
with a fixed tool allowlist and no shell/web tools. Deterministic validation
checked paired actual tool events, exact arguments, production revision,
structured/text agreement, schema, limits and audit/time envelopes. CLI exit
status and generated prose alone do not establish acceptance. Private raw
events and stderr are retained; public receipts omit personal text and files.

- **Export history:** started at 00:55:34 UTC and passed in 197.281 seconds.
  Exactly three calls performed connection status, a one-entry group
  `passport_excel` history page and its first five detail rows. The list observed
  19 retained entries and was partial; the selected checkpoint reported 35
  exported and 22 pending recipients. Five observed rows had current source
  records. Personal details were disabled. This does not establish full history
  enumeration, a link to the earlier delivered operation, or file availability.
- **Personal notifications:** started at 01:01:03 UTC and passed in 129.469
  seconds. Status followed by the five-row personal notification page returned
  five rows, zero unread and further pages. The expected recipient UUID had been
  independently bound to the active named grant. Zero acknowledgements occurred.
  The loaded website independently displayed zero unread.
- **Standalone ECR:** started at 01:03:44 UTC and passed in 186.188 seconds.
  Exactly three calls performed status, a one-batch list page and its first
  detail page. The selected completed batch reported one total/processed/ECR
  item and zero NA/review/failed items. The list had further batches; the detail
  page contained one completed item with no further item page. The authenticated
  website showed four saved checks, the same first-row counters and, after
  selecting that exact batch, one checked image and one ECR-result row. Both
  website observations had no alerts or horizontal overflow at 650 pixels.
  The proof does not establish full batch enumeration, processing execution or
  file availability; the runner conservatively makes no full-item-enumeration
  assertion beyond the observed page metadata.

Root independently extracted exactly one completed `connection_status` event
from each retained run and verified the expected named grant UUID, full revision
and absence of tool error. The raw-event SHA-256 values are retained in
`outputs/read-expansion-named-grant-check-20260930.json`. Later business-read
responses do not echo a grant ID; those payloads alone cannot independently prove
grant continuity. The runs use the same saved connector without grant changes.

Safe readback receipts are the `history-readback-run.json`,
`notification-readback-run.json` and `ecr-readback-run.json` files under
`outputs/mcp-live-codex-20260929/`. The bounded browser comparison is
`outputs/read-expansion-browser-check-20260930.json`. The immutable
`outputs/read-expansion-acceptance-20260930.json` binds the safe runtime,
named-grant, browser and actual-readback receipts by SHA-256. The component ledgers remain
`implemented_unverified`: selected live examples do not qualify every domain,
all negative security/recovery cases or capacity. All broad phase gates remain open.
