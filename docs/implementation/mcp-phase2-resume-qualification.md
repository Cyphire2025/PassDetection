# Phase 2 resumed qualification — 30 September 2026

Phase2 remains **open**. The latest user order is2 →1 →6 →4 →5 →3 →7 →8,
followed by pushing and direct VPS deployment without CI. This checkpoint
records completed local work and the deployed acceptance still required.

## Reproduced callback defect and narrow fix

The actual sign-in consumer started an exclusive loopback callback listener,
then awaited unshielded asynchronous shutdown in `finally`. AnyIO cancellation
could interrupt that await and leave its thread/socket alive. The new consumer
test reproduced this before editing:7 passed and1 failed. Teardown released
only the test-owned ephemeral socket.

The fix shields shutdown, socket close and listener-thread join. A cancellation
checkpoint after cleanup prevents a queued callback from reaching token exchange
when cancellation is pending. The absolute300-second deadline, state/PKCE,
client/resource/callback checks, requested scopes and vault policy are unchanged.

Ten new consumer cases cover timeout, three AnyIO cancellation timings, asyncio
task cancellation, browser false/exception, occupied port, denial and success.
Failure checks include thread termination, immediate exclusive port rebinding,
no exchange/vault writes and no callback values in logs. These use real isolated
loopback sockets with synthetic browser/discovery/credential boundaries.

| Qualification | Evidence and scope |
| --- | --- |
| Root connector regression |136 passed in36.70s, exit0; `outputs/mcp-connector-oauth-root-20260930.xml`. |
| Root full backend |6,248 passed plus162 subtests;3 platform skips/509 service exclusions; exit0 in1,381.12s. Backend application tree `e1a8d0f33a31b01643b975bc71c4cb100618ac9f`. |
| Installed0.2.2 consumer qualification |28 passed in5.57s in a separate test environment; source path injection disabled. |
| Package binding |14 modules, CLI/help and SDK legacy/auto initialization pass; exact tested owner bytes and canonical MAIN source bound, checkout line endings distinguished. |

Wheel:35,923 bytes, SHA256
`d47969e3e789cfa70483082414b56b6e68a4f4bc6e9bf596cd0a658d6da7ccad`.
Root artifact/source receipt:
`outputs/mcp-connector-022-root-retained-20260930.json`. The runtime lock content
is unchanged; canonical Git and owner CRLF hashes are recorded separately. The
active desktop connector remains0.2.0. No actual browser sign-in, vault/grant
mutation, Codex configuration or production activation occurred for this package.

## Acceptance register

| Gate | Established | Still required |
| --- | --- | --- |
| P2.1 SDK/transport | Pinned SDK, local HTTP/TCP/lifespan/host tests; actual deployed Codex calls. | Production host/origin matrix and multiprocess quota evidence. |
| P2.2 OAuth/MFA/CSRF | Actual user MFA/consent/PKCE and local binding/stale-factor/CSRF tests. | Fresh-factor dashboard refresh after the durable assurance fix; simple UI deployment/readback. |
| P2.3 credentials | Local HTTP and actual PostgreSQL code/refresh/revoke races; Windows vault/mutex tests. | Production valid expired/revoked credentials and permanent0.2.2 client acceptance. Do not replay a working consumed refresh credential as a harmless probe. |
| P2.4 binding/callback/quota | Existing handler Host/state/replay tests plus consumer lifecycle fix. | Prepared synthetic production probe, live valid-code binding/reuse, quota and authenticated transport cases. |
| P2.5 current authority | Local actor/security-version/expiry/revoke/MFA/emergency/narrowing operation and dispatch fences. | Controlled live cases under an explicitly approved isolated identity/grant; do not mutate current working authority for qualification. |
| P2.6 Administration | Earlier live pages; new simple UI49 component/9 browser fixture cases. | New UI live readback and controlled pause/disconnect/narrowing. These remain manual Administration actions. |
| P2.7 private durable audits | Local denial/rollback/privacy and one verified production management denial. | Broader token-denial window and other live branches; assigned chain fields are not recomputed-chain proof. |
| P2.8 actual Codex/HTTP | Saved Codex bounded reads/Excel delivery and four earlier public negatives. | Deployed valid expired/revoked/non-Superadmin/role-loss cases. Grant binding occurs at connection status; later business payloads do not echo it. |

## Prepared probe and release boundary

The frozen credential-free HTTP helper contains twelve synthetic denial cases,
fifteen fixed-origin requests with liveness/metadata bracketing and five expected
normal security-audit writes. Root mocks pass15 tests plus73 subtests. It has
**not been executed in production** at this checkpoint.

Review found three executable audit-helper gaps: discarded failure exit status,
no explicit schema0122 assertion and no consumption of the successful full HTTP
receipt. Separate v2 files/tests/manifest are being completed locally, preserving
v1 bytes. Root must review exact code/source/runtime binding, read-only SQL,
window limits, complete HTTP receipt and failure behavior before execution.
Unissued synthetic credentials cannot close real expiry/revocation/role/MFA,
valid-code/refresh/reuse, controls, quotas or authenticated Host/Origin gates.

Last production observations were13:47–13:49UTC: backend1f4177cb,
frontend1d77c9dd, schema0122,20 services running and18 configured healthchecks
healthy. These are dated observations. Authorized month SSH access expires
30 October13:17:27UTC.

The exact original33 missing-image allowance is approved. Three stopped
historical container-reference anomalies remain separately unapproved. Frozen
v3 proposal code passes317 root mocks and independent review;19 manifest hashes
match. No remote phase is performed. All current/intermediate resources remain
strictly preserved; access renewal does not authorize a broader exception.
