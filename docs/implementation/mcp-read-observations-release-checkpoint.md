# Attendance, document rename and email overview read release

Accepted selected release observations, 2026-09-30 **01:56:32 UTC**. This
documentation is based on safe retained receipts. The release owner independently
validated the accepted event transcripts and their named-connection status
bindings. This acceptance covers the bounded observations below, not completion
of any broad phase.

Backend `1f4177cb02006a4980022715ffa3b90eba76958b` completed its production
cutover on 2026-09-30 UTC. The independent runtime probe passed at
**01:29:35 UTC**. The frontend remains
`1d77c9ddb16439e62d29f85067377f23070552b6`, the worker/scheduler lineage remains
`efea4e4ac199b65fbf4f3b76a1ed59c4c963bd7e`, and the schema remains
`0122_mcp_gc_push`. This release is separate from the later analytics,
administrative overview and retention-read source batch. All broad phase and
combined-capacity gates remain open. Production capabilities remain read/export
only, with `passport_excel`, 100 source rows and a 1 MiB source budget. No
acknowledgement or communication capability was enabled, and no additional
customer messages were sent.

## Implementation and local qualification

The [attendance](mcp-attendance-read-checkpoint.md),
[document rename](mcp-document-rename-reads-checkpoint.md) and
[email overview](mcp-email-overview-checkpoint.md) component checkpoints define
the canonical shared website seams, current authority, bounded response/query
contracts and independent PostgreSQL evidence. The integrated non-service
backend regression passed **6,132 tests, three skips, 438 deselected and 162
subtests** in 1,219.84 seconds. The JUnit receipt contains 6,297 cases including
the subtests and skips, with zero errors or failures; these are not additional
independent tests. Service integration was excluded from this aggregate and is
recorded separately in the component checkpoints.

The source ledger at the deployed full revision contains **1,507 surfaces and
82 tools**. Existing frontend and OpenAPI representations remain canonical;
these read adapters do not authorize attendance closure, rename analysis or
download, email authorization, synchronization, provider activity or messages.
The later administrative overview source and its prepared readback helper do
not constitute deployed functionality in this checkpoint.

## Retained release and independent runtime observation

The immutable read-observations-v1 operator replaces only backend and proxy.
It preserves the frontend, eight worker containers, email scheduler and eight
infrastructure services. Its lineage check verified 33 retained receipt/lock
bindings and all twelve application bindings against the prior backend
`ee648457fad7273486bad5cd5f58ebe6fd308158`. It retains the original backend base
and matching lock, enforces an 8 GiB disk floor, admits sequential bounded
builds, drains/resumes the existing workers and retains prior/intermediate
resources. The operator preparation manifest records 179 mocked flow cases;
root's final independent mocked receipt is retained separately.

- Operator SHA-256:
  `1d67dbca209127b90aea7798cc120f0bb1639696c12af79316cd35090aac6a5a`.
- Wrapper SHA-256:
  `d4eeff0fc9133da79417a21ea0ae7c8b5e8b8fefb6a19f34135603574383a637`.
- New backend image:
  `sha256:42b4b8b433d54bcaaaeed44a4a7edc844096fe51c638c391f0d7cee2833438d2`.

Safe phase receipts show prepare, build, stage and cutover each exited zero with
no timeout or automatic retry. They began at 01:25:56, 01:26:47, 01:28:07 and
01:28:21 UTC respectively. The independent observation then confirmed:

- Exactly 20 running services: twelve application services and eight
  infrastructure services. All ten configured application health checks passed;
  frontend and proxy do not have configured Docker health checks.
- No new application OOM event or restart. Continuous service bindings were
  unchanged; prior backend and proxy were stopped. All prior and intermediate
  resources remained retained.
- Public live/ready health and OAuth protected-resource metadata returned 200.
  One anonymous management request returned 401 and produced exactly one matching
  durable denial audit, with null actor/entity, no credential/request data and an
  assigned integrity sequence.
- The preserved frontend build ID and all seventeen shell-referenced scripts
  (1,136,074 bytes), compiled full revision and revision-asset digest matched.
  The anonymous protected route retained its exact 307 redirect to the session
  restore shell. This checks the shell/build and does not by itself qualify the
  authenticated application page.
- Container memory limits remained 14,562,623,488 bytes. Observed host
  MemAvailable was 10,839,130,112 bytes. These are idle/startup observations,
  not combined-load or production-capacity evidence.

Safe receipts are `outputs/read-observations-live-independent-20260930.json`,
`outputs/read-observations-lineage-readonly-v2-20260930.json` and the four
`read-observations-v1-remote-*-outcome.json` files. Private deployment receipts
remain under the exact release's retained directory. The final acceptance
receipt `outputs/read-observations-acceptance-20260930.json` supplies the
authoritative release/evidence hash bindings.

## Actual saved-Codex observations and website comparison

The bounded runners use the permanent saved connector, exact tool allowlists
and deterministic event validation. CLI exit status or model prose alone does
not establish acceptance. Validation checks the production revision, paired
calls, exact arguments, structured/text agreement, count/schema bounds and
observation/audit envelopes. Only `connection_status` echoes the expected named
grant; later business responses do not independently attest per-call grant
continuity. No cross-query equality or atomic-snapshot claim is inferred.

- **Attendance:** started at 01:29:42 UTC and passed in 201.766 seconds, with
  three calls. The group summary observed three activities. The selected
  session summary reported four present and 31 missing; its first missing page
  returned five rows and indicated more pages. This qualifies the summary and
  bounded first page only, not full missing-person enumeration, physical
  attendance, closure permission or a mutation.
- **Document rename:** started at 01:33:37 UTC and passed in 67.297 seconds,
  with two calls. The current account's own-agency first batch page was empty
  with no further page, so no detail call was made. No extracted identifiers
  were requested, no files accessed and no sensitive-identifier audit requested.
  This empty observation does not qualify a populated detail page, filename
  ordering, generated-file availability, download authority or rename execution.
- **Email overview v2:** started at 01:51:34 UTC and passed in 133.281 seconds,
  with exactly three calls: connection status, email integration status and the
  personal email summary. All six readiness flags and both provider
  configuration-presence flags were true. All seven personal counts were zero
  and matched the earlier loaded website. Configuration presence does not prove
  credential validity, mailbox connection, worker/provider health or delivery.
- **Authenticated browser comparison:** the 650-pixel viewport had no horizontal
  overflow or alerts on these observed pages. Attendance showed three activities
  with present counts 4, 0 and 12 and missing counts 31, 35 and 23; the selected
  summary matched Codex. Keyboard Enter opened the selected missing-passenger
  dialog, which loaded all 31 rows, and keyboard close worked. Automated pointer
  clicks had no visible effect; the cause was not established. Codex returned
  only its first five missing rows, so full dataset equality is not claimed.
  Rename displayed “No rename batches yet.”, matching the empty MCP list; a
  populated detail page was not observed. Email displayed seven zero metrics and
  no connected accounts. These were separate live observations, not an atomic
  cross-interface snapshot.

Received safe readback receipts are
`outputs/mcp-live-codex-20260929/attendance-readback-run.json` and
`outputs/mcp-live-codex-20260929/rename-readback-run.json`, plus
`outputs/mcp-live-codex-20260929/email-overview-v2/email-overview-readback-run.json`.
The browser and named-status proofs are
`outputs/read-observations-browser-check-20260930.json`,
`outputs/read-observations-browser-email-comparison-20260930.json` and
`outputs/read-observations-named-grant-check-20260930.json`. This document omits
their connection, agency, group, session and audit identifiers and any returned
personal content. Private raw events and stderr remain retained.

## Retained incomplete attempt and remaining gates

The first email attempt exited zero after 82.235 seconds but failed validation
with `missing_call`: only connection status and email status completed, both with
valid schemas. The personal summary was not called. The reason the agent stopped
is unknown; no backend or prompt defect was established. Its original receipt,
events and stderr remain retained, together with the safe diagnosis
`outputs/email-overview-incomplete-diagnostic-20260930.json`.

The separate immutable v2 runner clarified that false readiness/configuration
flags and zero counts are valid observations, while keeping the same frozen
validator, protocol, exact three-call allowlist and revision requirement. Its
110 mocked checks passed before the release owner ran one new read-only attempt
in a distinct evidence directory. Successful v2 acceptance does not erase the
first incomplete attempt or explain its cause.

The final acceptance receipt binds the successful readbacks, initial failure,
runtime, browser and named-grant checks by hash. All accepted `connection_status`
events matched the expected named grant and read/export profile; later business
payloads do not echo that grant and therefore do not independently prove
per-call grant continuity. No acknowledgement or other business mutation was
performed. All eight broad phase gates remain open, including comprehensive
negative/security/recovery coverage and combined Linux-load/capacity evidence.
Component ledger dispositions remain unchanged by this documentation commit.
