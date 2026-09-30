# Management audit and workflow presentation release

At this management release checkpoint, production backend and frontend used
`1d77c9ddb16439e62d29f85067377f23070552b6`. The corrected recovery cutover
succeeded on 2026-09-29 UTC; independent runtime and durable denial-audit
verification passed at **23:36:08 UTC**. The authenticated browser shows the new
workflow fields and qualification copy. Actual saved Codex readback also passed.
This record does not authorize a phase-completion claim.

The later [Excel options/dashboard release](mcp-options-dashboard-release-checkpoint.md)
advances only the backend to `27afeb4c`; the verified frontend remains `1d77c9dd`.

## Application changes

Management endpoints now retain a fixed denial/failure audit after their request
transaction has exited. The dedicated transaction cannot commit pending business
data from the rejected request. The event is `mcp.management_rejected`, with a
code-owned operation, reason and HTTP status, plus validated actor and connection
identifiers when available. It does not copy request bodies, query parameters,
credentials, IP addresses, emails or exception text. Successful-handler audits
and existing authorization/MFA/CSRF decisions remain authoritative. Audit-store
failure preserves the original HTTP outcome and emits a fixed diagnostic event;
durable auditing during a database outage is not guaranteed.

Workflow cards show server stages, separately labelled operation/workflow/owning
connection IDs, revision and observation time. A completion time requires a
server value. Communication dispatch completion does not become a delivered
receipt, and an unknown outcome remains uncertain. Connector setup now correctly
says full workflow qualification remains in progress. These changes do not make
Administration controls remotely callable MCP tools or widen a grant.

The [Administration coverage checkpoint](mcp-administration-coverage-checkpoint.md)
records the exact 14 implementation-status corrections and two router
registration fingerprints. No matrix record was promoted to verified.

## Qualification before cutover

- The affected backend authentication/audit checks passed 83 distinct cases;
  48 MCP React cases and five intercepted browser scenarios passed. Strict
  TypeScript, scoped lint, architecture/module budgets and inventory checks passed.
- The first broad run completed with 5,867 passes, one failure, three skips,
  299 service-integration exclusions and 162 passing subtests. The failure was
  an existing device-session expiry fixture whose decision clock could precede
  its persisted creation time; the production application was unchanged by its
  correction.
- A test-only follow-up binds a separate local audit database in the shared HTTP
  and MCP fixtures, and prevents their module-global production session factory
  from opening a connection. Actual HTTP regressions preserve business rollback
  while retaining the separate denial audit. The focused combined run passed
  105 cases. This establishes local isolation, not PostgreSQL assurance.
- A subsequent broad rerun was stopped after reproducing a temporary-directory
  collision: the supporting audit database was placed inside a diagnostic test's
  sealed log root, which the reader correctly rejected. The audit fixture now
  owns a separate temporary directory. All 20 affected diagnostic, isolation and
  dispatch cases passed, including a regression preserving the consumer's empty
  temporary root. Application source remains the frozen candidate. The final
  broad rerun passed: **5,873 passed, three skipped, 299 deselected, 162 subtests**
  in 972.23 seconds, exit zero.

The test-only changes are retained in `c1164415` and `5e0c1d5b`; they do not change
the built runtime source or dependency lock. The three platform skips and the
separately selected PostgreSQL lane must remain explicit in broad-run reporting.

## Retained deployment lane

The first operator's preparation rejected the valid anonymous `307` redirect
from `/admin/mcp` to `/session-restore?from=%2Fadmin%2Fmcp`. It failed before a
baseline write, build or worker drain. Its source and failed receipt are retained.

The separate v2 operator checks exactly that same-origin redirect, then prohibits
redirects for the anonymous shell, assets, health and OAuth metadata. It verifies
compiled revision bytes against the container and public asset, while recording
whether the revision asset is actually referenced by the shell. Read-only
preflight on the prior EF build matched all 17 shell scripts (1,136,074 bytes),
including its full revision; the fallback scan of retained static assets was not
needed. Authenticated Administration behavior remains a separate browser gate.

Forty-eight mocked Python/Node flow cases passed locally and independently. They
cover graceful recovery, exact candidate restart fencing, original web and
continuous infrastructure memory counters, attempts to resume every worker, and
restoration of prior web service even if a worker recovery reports an error.
This component evidence is not a deployment or load result.

Frozen operator hashes:

```text
8a3947573bcf033020e1e3286ad0e97198528e82158822889a7fe6234202fd1d  forward-mcp-management-v2.py
726b2d71fc2851db885964a550ea4fe00aa9e02f08fb73310faf2c9ecab73f83  run-forward-mcp-management-v2.py
```

The candidate source archive is bound to SHA-256
`1e1cede67188e524f0d52e1931a2f401e7429c3d909420ba547427df244a92f8`.
Backend dependencies are built against the original a18 image and its exact
archived lock; the frontend uses the retained current runtime base and freshly
compiled source. Sequential builders pass whole-host cap admission with the
2 GiB host reserve. The eight workers are resumed after the build; Beat and
infrastructure identities remain continuous. All prior and intermediate images
and containers are retained. The declared deployed scope remains read/export,
`passport_excel`, 100 rows per source family and 1 MiB cumulative source data.

The v2 cutover on 2026-09-29 at 23:15 UTC rejected
`public_frontend_bundle_changed`. Its exact all-script comparison treated the
Cloudflare analytics beacon injected into public HTML as an application mismatch.
A bounded diagnostic subsequently proved that all 17 internal/public Next.js
script paths matched, with no missing application scripts and exactly one extra
script: the observed `static.cloudflareinsights.com` beacon. Because this same
check also ran during fallback acceptance, that fallback did not produce a
verified v2 receipt even though it had restored the prior web containers.

An independent read-only recovery probe at **23:17:23 UTC** confirmed backend
`cd0e538f`, frontend `efea4e4a`, all 20 expected services running, every configured
application health check healthy, four public endpoints returning 200, zero
application OOM/restart observations, and retention of all prior containers and
images. The three candidate web containers are stopped, with candidate-only
restart policies fenced to `no`. This is restored-runtime evidence, not a load
result or acceptance of candidate `1d77c9dd`. The original operators and failed
receipts remain unchanged. A separately reviewed recovery operator must preserve
exact application-script equality and full served revision-asset byte proof
while accounting explicitly for the observed edge beacon.

The separate v3 operator subsequently passed **95 mocked cases**, independently
rerun with the same result. It accepts zero or one instance of only the exact
observed Cloudflare beacon URL; missing, changed, duplicate or unrecognized
script sources still fail. The beacon is never fetched. Compiled full revision,
internal served asset bytes, public revision-asset digest and application-script
equality remain required. Preparation proved the corrected public contract
against the restored CD/EF release before any mutation. A separate stopped-only
phase restored the candidates' original restart policies using exclusive intent
receipts and inspection-only reconciliation of an uncertain response. Frontend
exit 143 is accepted only for its exact `node server.js` command and safe stopped
state. Infrastructure counters retain their historical baseline; application
counters still require zero. The recovery reuses the existing images and
containers, with no build, create, cleanup or schema/configuration path.

```text
f8de4f13e2b5f7717981ebadf6d1b7a92e756d9f0d758559d53f8d20a99e7568  forward-mcp-management-v3.py
9f3ca4658d539bcbf0dddbb6679c61302b9e62d2d7764fb0105e7c07bbf59e06  run-forward-mcp-management-v3.py
```

All three explicit phases exited zero. The retained journal records
`0068-management-v3-complete.json` and a real `management-v3-live.private.json`.
The independent post-cutover probe verified all 20 expected services, all
configured application health checks, zero application OOM/restarts, unchanged
continuous infrastructure/Beat counters, stopped prior web services and retained
prior/intermediate containers and images. Public live/ready/OAuth endpoints
returned 200 with the expected revision/resource. Backend image is
`sha256:a3a25b9612306fe69737daea1dc05617f7574e3f899d149f47be2cc1952086cc`;
frontend image is
`sha256:b2096d6e61b579e1099e12d3aec560625c9e17060c1e91ee7ab99f781ca5c91a`.
The frontend full revision appears in a shell-referenced asset, with all 17
script files and 1,136,074 bytes checked. Resource caps sum to 14,562,623,488 bytes;
this startup/idle observation is not combined-load qualification.

One anonymous HTTP request returned 401 and independently produced exactly one
matching durable `mcp.management_rejected` audit: fixed overview/authentication
required/401 metadata, denied outcome, null actor/entity/email/IP fields and an
assigned integrity sequence/hash chain. No raw request data or credentials were
stored in that audit. This tests one concrete denial, not every management or
database-failure branch.

The existing authenticated browser session loaded the release without new
credentials. Connection setup displays “Full workflow qualification remains in
progress.” Its saved export workflow shows “prepared for delivery,” succeeded
operation status, separately labelled Operation ID, Workflow ID and Owning
connection ID, revision two, update time and server-supplied completion time.
At the observed 650-pixel viewport the document width was also 650 pixels.
This accepts this populated workflow card and copy; it does not fabricate
communications/provider outcomes or qualify all Administration controls.

Actual saved Codex readback started at **23:43:51 UTC** and passed in 56.015
seconds, exit zero. It made exactly two calls through the permanent Windows
vault connector: `connection_status`, then `inspect_operation` for the previously
delivered Excel operation `13ffbc2f-34b1-434b-b432-3513e74cd8c7`. A deterministic
validator checked the actual paired tool events, exact arguments, matching
structured/text results, production/full revision, complete audit/observation
envelopes, read/export-only capabilities and the succeeded operation with a
persisted completion timestamp. The validator's 29 local parser/capture/wiring
tests passed separately. No export was generated, resumed or downloaded. Raw
events/stderr remain private and bounded; the safe receipt records the result.

All eight overall phase gates, combined-load capacity and remaining live
authorization and provider cases stay open.

## Separate product observation

A read-only live passport-link preview on the prior EF frontend showed zero
message-eligible recipients for the active 707-contact broadcast. The recipient
selector stayed empty and the send-to-zero control stayed disabled. The preview
was cancelled without submission and the temporary tab was closed. This verifies
empty-audience gating only; it cannot establish populated-recipient initialization,
delivery reconciliation or provider outcomes. Existing local async-selection
and receipt tests remain separately scoped evidence.

After the successful 1d77 release, the same active broadcast's Welcome preview
provided a nonempty case: one message-eligible recipient loaded asynchronously,
and the UI automatically showed one of one selected. The native preview selector
contained one option, selected index zero, exactly one selected option and a
nonempty value; its send-to-one control was enabled. The reviewer pressed Cancel,
confirmed the dialog closed and closed the temporary tab without activating
the send control. This verifies live initial selection for one eligible
recipient; multiple-recipient switching and provider delivery remain separately
scoped requirements. No new production message was submitted.
