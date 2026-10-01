# Verified read-only MCP phone comparison

Production backend revision: `3e23f15a901b8fbe4888696b5f920d0af22fc48e`.
Observed on 1 October 2026 at approximately 15:06 UTC (20:36 IST).

The user's earlier comparison required approximately 134 small matching-page
requests and took 15 minutes. Every matching-page request recomputed the whole
group's canonical matches, and full matching records required additional nested
detail retrieval. The new `list_submission_phone_differences` MCP tool runs the
same canonical matcher once per request and returns only complete, compact phone
difference rows, with names, staff codes, both raw/normalized numbers, record
identities, match basis, evidence kinds and coverage counts. The shared matcher
now runs its materialized domain-data computation outside the API event loop.

No new identity heuristic is introduced. Only high-confidence submitted matches
with exactly one submission are compared. Formatting and country-code notation
are normalized; missing/invalid numbers are counted separately. Ambiguous,
review and manual replacement/rejection rows are excluded from phone comparison
and remain represented in canonical status totals. A difference does not establish
which number is correct. Multiple recipient records remain distinct comparison
pairs, and the unique-person count is separate.

## Production comparison evidence

The authenticated installed connector discovered all 35 read-only tools, with
all existing 18 supported read sections enabled. For the active Bluechip Dubai
October group and its linked broadcast:

| Observation | Result |
| --- | ---: |
| Active broadcast entries | 707 |
| Canonical submitted/matched records | 669 |
| Canonical not-submitted recipients | 38 |
| Compared submission/recipient pairs | 669 |
| Same normalized phone | 660 |
| Different normalized phone | 9 |
| Unique people with differences | 9 |
| Missing or invalid phone pairs | 0 |
| Ambiguous or review rows | 0 |

All nine staff identities from the prior supplied comparison remained in the
current difference list, with no additional staff identities. The live roster
had advanced from the earlier transcript's 666 matched records. All difference
rows arrived complete in **one MCP call**, without nested read references.
Three separately audited live reads took **1.531, 1.078 and 1.578 seconds**.
These are measured tool round trips; model reasoning and local Excel creation
are additional time. The full authenticated verification, including discovery,
three comparisons, a canonical dashboard count cross-check, and denied write/file
checks took 10.704 seconds. The canonical dashboard counts matched exactly.
Snapshot fingerprints were identical across these three observations.

A fresh actual Codex CLI session discovered and invoked the new tool using the
installed read-only binding. Its two ordered calls (connection status and complete
comparison) returned nine differences from 669 compared pairs. The complete Codex
run, including startup, model processing and final count validation, took
**50.938 seconds**. This independently verifies agent access rather than relying
only on direct SDK calls; it is distinct from the 1.08–1.58-second tool timings.

Read boundaries are checked on every request: current Superadmin authority,
agency/group visibility, broadcast linkage and both All Groups/WhatsApp read
sections. Encoded row pages are bounded to 24,000 bytes and keep rows complete.
Continuation requires the previous response's snapshot revision; changed matching
inputs require restart. This is a live multi-query read, not an atomic snapshot.
The observational session blocks business DML and deferred ORM writes; authorized
read-audit records remain permitted. No export or message preparation occurs.

## Qualification and rollout

- 54 phone comparison/shared matcher tests passed, including a synthetic 666-pair
  case with nine differences, formatting equivalence, missing/invalid numbers,
  ambiguous matches, bounded complete pages and changed-input continuation.
- 64 actual MCP SDK/read-section integration cases passed, including missing
  section denial and rollback of a deferred business write.
- 471 retained-release qualification cases passed.
- The complete HTTP API contract remained unchanged.
- Exact committed source was archived, uploaded and verified; guarded prepare,
  build, stage and cutover phases completed without automatic retries.
- Database schema remained `0123_mcp_read_sections`; permissions and their saved
  read-access revision were unchanged. Frontend, workers and email scheduler
  retain revision `99d24b74f6197117e0eaa1f86c74e4d70ecef4e2`.
- The 15,039,863-byte custom database backup was listed and fully decoded before
  cutover. This validation is not a restore rehearsal.
- All 20 running services were healthy with zero restart/OOM events. All 333
  prior containers/configurations and all 189 prior image IDs were retained.
  Final inventory: 336 containers and 191 images. Only the exact previously
  authorized three historical stopped reference anomalies remain tolerated.
- Write tool invocation was denied; file/export authority returned HTTP 403.

Local evidence, intentionally excluding customer response bodies and credentials:
`outputs/mcp-phone-differences-matching-20261001-v3.xml`,
`outputs/mcp-phone-differences-sdk-20261001-v4.xml`,
`outputs/mcp-phone-release-qualification-20261001.xml`,
`outputs/mcp-phone-comparison-live-20261001-v1.json`,
`outputs/mcp-phone-comparison-server-proof-20261001-v1.json`.
Actual Codex evidence: `outputs/mcp-phone-comparison-codex-20261001-v1.json`.

## Chat usage

Ask: “Use Global Connects MCP to compare submitted phone numbers with the linked
WhatsApp broadcast for Bluechip Dubai October. Use
list_submission_phone_differences and show only the different numbers, with
names and staff codes.”

The server and tool instructions prefer this compact path for phone comparisons.
For larger results, agents must follow `next_offset` with `snapshot_revision`.
An agent may create a local workbook from returned rows without enabling MCP
exports. An existing chat can retain an older tool catalog; a fresh chat/session
discovers the new tool.
