# Live Codex connection and export qualification

## Current state — 29 September 2026, 22:22 UTC

The active superadmin completed MFA and enabled MCP in Administration, then
authorized the named `Nipun’s Codex desktop` connection. The connector completed
OAuth authorization-code/PKCE sign-in and stored its refresh credential in
Windows Credential Manager. The permanent `global-connects` Codex configuration
uses the installed connector under the user's LocalAppData directory and the
approved download directory `Downloads/GlobalConnects`.

Actual Codex resumed the saved export successfully against production backend
`cd0e538f3e967074606b6cc523203f691aea555d`, with only `mcp:read` and `mcp:export`
authority. The original queued operation succeeded, the connector downloaded and
checksum-verified the workbook, and the server acknowledged verified delivery.
Independent local ZIP integrity and openpyxl parsing also passed. This closes
the first actual-client Excel recovery/delivery example; it does not close any
complete phase or establish source-row parity for every export family.

The correction and its test/operator follow-ups are pushed to main through
`45dded23`. The public backend uses the exact `cd0e538f` application source;
frontend, workers and scheduler retain `efea4e4a`. Schema0122 and existing MCP
controls, grant and resource limits were preserved. All prior containers and
images remain retained. The clean broad backend rerun passed: **5,822 passed,
3 skipped, 294 service-integration deselected and 162 subtests passed** in
863.68 seconds, exit zero. The three skips require Linux-specific semantics.

## Actual client evidence

Evidence is retained privately under `outputs/mcp-live-codex-20260929`.
`codex exec --ephemeral` uses the same configured model/effort and the installed
connector, with shell disabled and an explicit bounded MCP tool allowlist.
The standalone CLI cannot load the desktop-only `codex_app` transport; the
verification process therefore ignores that user configuration and explicitly
supplies the Global Connects server. The persistent desktop configuration is
unchanged by this workaround. CLI process success is not interpreted as business
tool success.

- Run 2, beginning `2026-09-29T21:24:10.376339+00:00`, passed `connection_status`
  and `list_groups`. The active group's source counts exceeded the initial export
  admission envelope, so the client stopped without preparing an export.
- Run 3, beginning `2026-09-29T21:26:52.269984+00:00`, read a bounded ten-group
  page and selected one retained group. `inspect_excel_export` passed with
  35 passengers and 22 pending recipients, `selected_groups`, `all`, and no
  supplemental fields. `prepare_excel_export` returned `export_failed` while
  preserving operation `13ffbc2f-34b1-434b-b432-3513e74cd8c7`.
- Run 4, beginning `2026-09-29T22:11:16.232749+00:00`, completed in103.781 seconds.
  Exactly four business/transfer calls ran: `connection_status`,
  `inspect_operation`, `resume_excel_export`, and `local_download_export`.
  The status reported production revision `cd0e538f`; inspection found the same
  queued operation, and resume returned `succeeded` with complete artifact data.
  No new operation or idempotency key was created and no call was retried.
- The retry key remains `mcp-live-codex-export-20260929-first-proof`. The verified
  local file is `Downloads/GlobalConnects/global-connects-live-selected-export-20260929.xlsx`:
  **14,863 bytes**, SHA-256
  `e64c42a8c87b70b043c2ff20a5262bc754919076b82680bbbf1e3b22c0d51dac`.
  `server_delivery_acknowledged` is explicitly true. Independent local verification
  matched that size/hash, passed ZIP CRC for all11 members, and parsed one sheet
  with61 rows,24 columns and60 nonempty rows. Contents were not printed.
  The safe receipt is `outputs/mcp-live-codex-20260929/verified-delivery-4.json`.
  Workbook parsing and checksum checks are distinct from source-row parity.

## Direct forward deployment evidence

The retained forward release root is
`/opt/GlobalConnectsDashboard/tmp/mcp-direct-cd0e538f3e967074606b6cc523203f691aea555d`.
Its final journal is `journal/0041-forward-complete.json`; exact current container
bindings are in the private `forward-live.private.json` receipt. Image
`sha256:8ad2af480a4bda0ef9329f2d6af91529b6d6a10566b4eaede0d61d019159ce24`
passed the UID1001 runtime probe, all1,021 committed source-file hashes, the
installed SDK conditional-write contract, schema and existing capability checks.
Only backend and proxy were replaced. All workers resumed, and the previous
current-schema backend/proxy were stopped gracefully and retained.

The first post-build guard rejected Docker's omitted unset Entrypoint metadata.
The retained image already had the intended command and inert entrypoint; the
guard now accepts documented omitted/null/empty forms while rejecting executable
or malformed values. It requalified that exact retained image without another
image commit. All67 joined operator-helper tests pass, including25 build/container
checks. The later main commits change only operator validation and a test.

A read-only observation at `2026-09-29T22:12:26.228818+00:00`, retained in
`outputs/mcp-forward-live-20260929.json`, verified all20 services running, all10
configured application health checks healthy, zero new application OOM/restarts,
and every prior container and image retained. Public liveness/readiness, OAuth
protected-resource metadata and `/admin/mcp` all returned200; both health routes
reported `cd0e538f`. Backend memory was1.222GiB of2.5GiB. The unchanged summed
container limits were13,888MiB. This is startup/readiness evidence, not a
combined-load capacity measurement.

Three subsequent passive samples from22:19:01 through22:19:33UTC bound all20
application/infrastructure services to their exact receipts and host cgroups.
Container identities, restart counts and OOM counters remained unchanged.
Backend current memory stayed between1,312,694,272 and1,312,780,288 bytes;
lifetime cgroup peak was1,369,534,464 bytes, not an isolated export peak. The
database had18 total connections and13 to the application database, against a
100-connection limit. The schema and read/export-only runtime were unchanged.
Evidence: `outputs/mcp-forward-stability-20260929.json`. No synthetic traffic,
resource changes, queue operations or provider actions occurred. No achieved
request rate or broker backlog was measured, so this is stability evidence only.

Bounded public HTTP checks at22:21–22:22UTC rejected anonymous MCP requests,
an unissued bearer and anonymous Administration access with401; both MCP denials
included the correct protected-resource challenge. A synthetic authorization-code
exchange with the registered redirect but a wrong resource returned400
`invalid_target` with `no-store`. It used no live credential and changed no grant.
The confirmed receipt is
`outputs/mcp-production-http-negative-confirmed-20260929.json`. Earlier operator
probes used a nonexistent overview suffix and an unapproved callback port,
returning404 and `invalid_client`; those probe mistakes are retained separately.
This does not establish live expired/revoked/demoted-user negative cases.

## Diagnosed failure and qualified correction

A bounded operator diagnosis inside the existing backend container revalidated
the original live grant, prepared the exact saved selection, rendered its
14,864-byte workbook in memory, and rolled back. It created no stored artifact,
export history, new operation or credential. The operation remained queued at
revision1 with zero created entities.

Production Boto3/Botocore `1.34.131` lacks `IfNoneMatch` in the `PutObject` model.
The actual installed-SDK regression reproduced the parameter-validation failure.
The pinned correction uses `1.35.2`, the first model release with conditional
writes according to the [official Botocore changelog](https://raw.githubusercontent.com/boto/botocore/1.35.2/CHANGELOG.rst).
The two regenerated hash locks change only these two packages. Conditional
creation remains mandatory; the adapter never retries with an unconditional
overwrite.

Eighty-one focused SDK, storage, Excel export, AWS provider and audit tests pass.
They exercise actual SDK validation, serialization and signing with synthetic
credentials; HTTP409/412 conflicts preserve the existing object. Eight additional
export diagnostics tests verify that logs contain only operation/tool identifiers
and exception types, while raw exception secrets, tracebacks and payloads remain
absent. Rollback leaves the original queued receipt intact.

The second MFA prompt during OAuth was separately traced to dashboard refresh
restoring an older assurance timestamp. The correction persists newly verified
assurance only in current credentials of the same existing session, preserves
the original effective deadline, and commits before publishing a cookie.
Ordinary refresh does not renew MFA freshness. PostgreSQL reproduced a related
lock inversion (`40P01`); account-first locking and post-lock expiry checks now
pass nine PostgreSQL races. The final targeted HTTP/expiry/rollback lane passes
seven cases; an earlier overlapping affected identity suite passed77 cases.
Mypy, Ruff, architecture, module budgets and inventory checks passed.

The first broad backend run returned5,821 passed,1 failed,3 skipped,
294 service-integration deselections and162 passing subtests in814.38 seconds.
The failure exposed a pre-existing test ordering assumption: tied delivery
timestamps were ordered by random UUID instead of the exact action-token link.
The test now binds old/new deliveries to their corresponding token hashes and
foreign keys, forcing tied timestamps and reversed UUID order. Its complete
six-test recovery file passes. The clean full rerun then passed5,822 tests,
with3 Linux-only skips,294 service-integration deselections and162 passing
subtests in863.68 seconds. Log/JUnit are retained as
`outputs/backend-regression-sdk-mfa-confirmed-20260929T2206Z.log` and its `.xml`
sibling. The first broad run is not recorded as green. The application code did
not change for the ordering fix. A further separate15-test actual local HTTP
authority lane and six mocked-API UI state tests also pass; they were added after
aggregate collection and are not included in its count.

## Overnight execution constraints

The user authorized continuing the accepted phases1–8 in dependency order while
they sleep, with main pushes and direct VPS deployments after each qualified
implementation. Each phase needs its main commit, deployed revision and relevant
live behavior recorded before its gate closes. Local tests alone do not close a
phase. Hosted CI deployment is not used for this authorized operator path.

Reuse existing authenticated access without routine MFA, login or approval
requests. Do not bypass MFA, change credentials/security controls, extend the
temporary SSH key, delete retained resources or send additional customer
messages. The key retains its original expiry at 30 September06:19:11UTC
(11:49:11IST). If a genuine user-only step or expiry blocks deployment, preserve
the precise blocker and continue independent implementation/testing.

All eight phase gates remain open. The first real Codex Excel recovery, verified
live delivery and local openability now have evidence. Combined-load capacity,
the remaining file families/workflows and complete phase acceptance are still
required. A fresh-factor live dashboard refresh roundtrip has not been run after
the assurance fix; its local HTTP/PostgreSQL evidence does not imply another
user MFA event.
