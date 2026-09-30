# Safe website and Codex verification guide

Use this guide to check your Global Connects access, compare existing work on
the website and in Codex, understand saved workflow and file outcomes, and
report a problem without accidentally creating work or sending a message.
The ordinary checks below inspect existing records. Export creation, download
acknowledgement, new sign-in grants and access controls have separate effects
and require the authorization described in their sections.

## Start with the known state

This guide was prepared on **30 September 2026** from source and retained
qualified receipts. Writing the guide performed no new website, Codex,
production, credential or provider verification.

The website currently permits MCP reads and passport Excel exports within a
small source limit. Use the existing saved Codex setup for the inspection walk.
The active connector is `0.2.0`; the separate `0.2.2` candidate and simpler
**Codex access** interface are still pending release. The current website page
is **Administration → MCP**. All eight broad acceptance gates remain open.
The [accepted release checkpoint](mcp-read-observations-release-checkpoint.md)
and [Advanced evidence below](#advanced-release-and-evidence) give the exact
versions, observed times and remaining limits.

Complete this four-step inspection walk:

1. [Check the existing website connection](#1-check-existing-website-access):
   refresh status and read the named connection's permissions and expiry.
2. [Check the same saved connection from Codex](#2-check-the-saved-connection-from-codex):
   run the bounded status prompt and compare it with the release record.
3. [Read one existing group](#3-compare-an-existing-group-without-changing-it):
   compare a small page with the same website scope, filters and observation time.
4. [Inspect saved workflows and files](#4-inspect-saved-workflows-and-file-history),
   then [check health if needed](#6-check-health-and-collect-a-safe-problem-report):
   record the literal outcome and any incomplete or unavailable evidence.

After a release, the release owner should supply the new expected backend,
frontend, schema, active connector version/hash, enabled profile and dated
acceptance receipt. Compare against that release record when it supersedes the
Advanced table below. A mismatch should be reported, not treated as permission to upgrade
or change configuration.

## 1. Check existing website access

1. Open [the website](https://tech.gctravels.com) and use your own existing
   superadmin account. Follow the normal login or MFA prompt if needed. Keep
   passwords, MFA codes and callback URLs out of chat and screenshots.
2. Open **Administration → MCP**, or use
   [the MCP page](https://tech.gctravels.com/admin/mcp). This page is restricted
   to superadmins. A denied or unavailable page is a result to record; using
   another person's session is not a verification step.
3. Select **Refresh status** once. Note the environment, checked time and
   enabled/paused state. Read any release qualification warning. An enabled
   switch describes server access; it does not prove that Codex is online or
   that every workflow works.
4. In **Connections**, find the existing named desktop connection. Record its
   name, status, creation time, last-used time, authorization expiry and
   permissions. Follow the connection page controls before concluding that it
   is absent. An empty first page is not a complete connection inventory.
5. Leave access controls alone during this check. **Enable MCP access**,
   **Disable MCP access**, **Edit access**, **Save access** and **Revoke** change
   authorization or connection metadata. They are not status tests. If no
   usable connection exists, record that finding and use the separately
   authorized setup procedure in section 7.

Authorization lasts at most seven days, while access tokens last 15 minutes.
The connector normally refreshes access tokens. An old last-used timestamp
does not prove that a desktop is offline; an active connection is saved
authorization, not a presence indicator.

## 2. Check the saved connection from Codex

Use the already configured Global Connects connection. Do not install the
candidate, replace configuration, clear the vault or start a new sign-in just
to perform this check. Ordinary authenticated reads may update invocation
audits and connection-use bookkeeping, and normal token refresh may rotate the
connector credential; they do not create business records or messages.

Paste this bounded prompt into Codex:

> Use only the existing Global Connects connection. Call connection_status
> once and report its environment, observed time, full backend revision,
> connection ID, permissions, qualification, export families and source
> limits. Inspect existing data only. Do not start sign-in, change access or
> configuration, upload, create an export, acknowledge delivery, change
> business records or send messages. If the connection is unavailable or
> denied, report the exact safe error and stop.

Compare the returned connection with the website entry, using the exact
connection ID where the deployed interface exposes it. Check the backend
revision against the release record. A successful `connection_status` establishes
that this connection worked at that observation time. Later business results
do not independently echo the same grant, so keep the status observation with
the subsequent result instead of claiming it proves every later call.

If authorization is expired, refresh is denied or its outcome is uncertain,
record the error. The connector can require fresh browser sign-in; repeated
tool calls or credential extraction are not a recovery method. Keep the
existing evidence and obtain an authorized setup/recovery plan.

## 3. Compare an existing group without changing it

1. Choose a group you are already authorized to view on the website. Record
   its agency/group identity privately, the displayed filters and the time.
   Group names are not unique. Resolve a duplicate name before selecting it.
2. Ask Codex for a small first group page, then choose the exact existing group.
   The following prompt does not authorize any action on that group:

   > Use authorized read tools only. Show a first page of at most five existing
   > groups and include their stable group and agency IDs. Keep passport
   > submission counts, operational passenger counts and WhatsApp recipient
   > counts separate. Let me choose the exact group before reading its passport
   > list. Report environment, observed time, revision, completeness and whether
   > another page exists. Do not export, upload, acknowledge, edit or send.

3. After selecting the group, use this prompt:

   > Read the selected existing group's first passport page with at most five
   > rows, the same website filter and search, and contact details omitted.
   > Include stable record IDs, observed time, revision, completeness and page
   > information. Do not open file contents, export, upload, change a record,
   > acknowledge anything or send messages. Stop after the first page.

4. Compare that page with the same website scope. Compare IDs and status/count
   meanings before comparing names. Passport submissions, operational
   passengers and communication recipients are distinct datasets and may have
   different valid counts.
5. Label this result **first page only**. If complete enumeration is needed,
   explicitly ask for the remaining read pages with unchanged agency/group,
   filter, search, page size and privacy options. Follow each returned
   `next_cursor` until `has_more` is false. Preserve the observation times.
   Do not change options while reusing a cursor.

A cursor rejection or revision-change result requires a new read walk; it is
not permission to merge old and new pages into a claimed snapshot. Website and
MCP observations happen at different times. Counts and rows may also come from
separate live queries. Record a difference with the exact scope and times;
do not assert atomic equality or silently correct data to make it match.

An empty result is valid only for its authorized scope and filters. A missing
capability, timeout, unavailable result or partial completeness is not zero.
For attendance, recorded counts and readiness metadata do not prove physical
presence or authorize scans, check-ins or closure. The accepted attendance
example covered a summary and first missing-person page only. The accepted
rename example was an empty list, and email readiness showed configuration
presence rather than credential validity or provider delivery.

## 4. Inspect saved workflows and file history

1. On the MCP page, open **Workflows**. Read the existing operation status,
   stage, progress, operation ID, workflow ID, owning connection ID, updated
   time, operation revision and created-entity references. Follow page controls
   for additional existing work. Do not create a new operation to populate the
   page.
2. If an operation needs inspection in Codex, copy its existing ID privately:

   > Inspect only the existing operation ID I provide using inspect_operation.
   > Report its current status, stage, progress, revision and retained entity
   > references. Do not resume, retry, cancel, recreate, export, acknowledge
   > delivery or send anything. If authority is insufficient, report that result.

3. Open **Files** and review existing transfer metadata: file kind, direction,
   byte size, status and expiry. An uploaded source, generated export and
   message header image have different purposes. Inspecting these records does
   not require downloading a file.
4. For an existing group's passport download history, use the website's history
   view without selecting a new generation/download action. Codex can inspect
   the corresponding completed metadata with the prompt below:

   > For the exact existing agency and group I choose, read the first
   > passport_excel export-history page and one selected existing history
   > detail page. Use list_group_export_history and get_group_export_history
   > only, with personal details and deleted records omitted. Report history
   > IDs, times, counts, compatibility, completeness and remaining pages. Do not
   > generate, recover, download or acknowledge a file.

History pagination and transfer availability are separate. Completed passport
history records are retained checkpoints; they do not expose a file handle or
prove that an old file can still be downloaded. `record_available` refers to a
current source row, not file availability or recovery authority. A history entry
must not be assumed to belong to a particular operation without an explicit
binding. Old artifacts may already have expired even when their history remains.

Use the reported state literally:

| State or evidence | Safe interpretation |
| --- | --- |
| Request received / source staged | The service received a request or staged bytes. Import, generation, message queueing and delivery need their own evidence. |
| Prepared / ready | Preparation finished for the stated purpose. It does not establish a local file or authorize a send. |
| Queued | Work is waiting for execution. A message is not delivered. |
| Running | The operation is executing. Progress is not an outcome receipt. |
| Operation succeeded | That operation's defined work completed. A successful dispatch does not itself prove recipient delivery. |
| Export delivered | The connected client acknowledged a download verified against the expected size and checksum. This does not prove full source-row parity. |
| Provider accepted / sent | Provider acceptance or a send receipt exists. Recipient delivery/read status requires its respective receipt. |
| Delivered / read message | The corresponding provider delivery/read evidence exists for that recipient. Do not infer it from aggregate operation success. |
| Failed | The reported stage failed. Preserve its identifiers and error before deciding on recovery. |
| Unknown / outcome uncertain | The outcome is unresolved. Inspect retained operation/provider receipts; automatic retry or a new retry key can duplicate work. |

## 5. Verify an Excel file only when a transfer is authorized

The saved live Excel example demonstrated generation recovery, an authenticated
stream, a checksum-verified local workbook and server acknowledgement. ZIP and
workbook parsing were also checked. It did not establish parity for every
export family, all source rows or today's artifact availability. See the
[live Codex checkpoint](mcp-live-codex-checkpoint.md).

The ordinary read checks can inspect existing delivery metadata and an already
saved local file without changing server history. When a new export or delivery
recovery is explicitly authorized, use a separate bounded transfer plan:

1. Confirm the exact existing group/selection, fields, filters and source
   revision. Inspect export options and admission first. The current profile
   admits only `passport_excel` within 100 source rows and 1 MiB of source data;
   exceeding those limits is a rejected request, not a partially complete file.
2. Preserve the existing operation/artifact identity and original retry key
   when recovering prior work. **Prepare** and **resume** can generate/store
   an artifact and update operation state. They are not read-only inspections.
   An expired artifact is a finding; do not automatically regenerate it.
3. Confirm the exact approved local download folder and a new filename.
   The connector must refuse an existing destination, including a concurrent
   conflicting file. Do not overwrite, rename or remove another file to force
   the test through.
4. Require the complete authenticated stream, expected byte size and matching
   SHA-256 before calling the local file verified. A partial transfer or
   `.part` file is incomplete. File bytes and private source contents do not
   belong in a support receipt.
5. Read `server_delivery_acknowledged` separately. A verified local file with
   `false` is saved locally but has no confirmed server delivery acknowledgement.
   Acknowledgement is stateful: it can complete the associated prepared passport
   history checkpoint. Recover it only for the exact authorized artifact and
   verified file, preserving that file rather than downloading over it.
6. Check the resulting website operation/file/history metadata by their linked
   identifiers. Content parity requires a separately approved comparison of the
   chosen source selection and workbook rows; a checksum alone cannot prove it.

These are acceptance requirements, not a copy-and-run export prompt. This
guide grants no new export, acknowledgement or local filesystem authority.

## 6. Check health and collect a safe problem report

Open these established read endpoints once in a browser when a current health
check is needed:

- [Backend liveness](https://tech.gctravels.com/api/v1/health/live): expected
  successful response is 200 with `status: alive`, environment and revision.
  This confirms that the process answered; it does not check all dependencies.
- [Backend readiness](https://tech.gctravels.com/api/v1/health/ready): expected
  healthy response is 200 with `status: ready` and the revision. A 503/degraded
  response retains check/capability information that should be reported.

Keep the observation time and full revision. Readiness, an enabled capability
and configuration presence do not prove an end-to-end workflow, provider
credentials, message delivery, throughput or combined website/MCP capacity.
Public health endpoints do not expose the complete container/worker inventory.
The dated 20-service/18-health-check receipt above is separate operator evidence.

For a problem, retain this small receipt privately and share only the fields
needed by the release owner:

| Field | What to record |
| --- | --- |
| Check and time | Website/Codex/health check, UTC or IST with timezone, start and end when relevant. |
| Release | Full backend revision; separately supplied frontend/schema/connector version; expected release record. Use `not reported` where absent. |
| Scope | Exact privately held agency/group/record/operation/history IDs and filters; keep customer names, contacts and documents out of the shared summary. |
| Observation | Exact safe status/error, stage, counts with their dataset meaning, completeness and qualification. |
| Pagination | First page or complete walk; page size, more-page indicator and any cursor/revision error. Keep raw cursors private. |
| File evidence | Artifact/operation binding, expected/actual byte size and SHA-256, local verification result, acknowledgement boolean and expiry. Omit local paths unless required privately for recovery. |
| Website comparison | Same scope/options, adjacent observation times, matching fields or the exact mismatch; state any incomplete page or non-atomic limit. |
| Effect | Inspection only, or the exact separately authorized transfer/control action. Report an interrupted or unknown result explicitly. |

Stop a failed check and preserve its receipt. Repeated retries, a new operation
or a changed identifier can conceal the original problem. No matching errors,
inaccessible logs and unavailable diagnostics are different findings.

## 7. Use setup and authority controls only with separate authorization

For the existing installation, section 2 is sufficient to check access. New
installation, active-version replacement, editing Codex configuration, choosing
local files/folders, clearing a saved credential and browser approval create or
change local/server authority. They are outside the ordinary inspection walk.

When a reviewed release and setup action are authorized, record these fields
before following that release's installation instructions:

| Setup field | Required reviewed value |
| --- | --- |
| Connector release | Released version, full source revision, exact package size and SHA-256 from the release owner. `0.2.2` above is currently a candidate only. |
| Platform/runtime | Windows and the release's qualified CPython 3.11 environment, separate from the server environment. |
| Application origin | `https://tech.gctravels.com` |
| Remote resource | `https://tech.gctravels.com/mcp`, compared with the deployed setup page. |
| Approved client/callback | `global-connects-desktop`; exact `http://127.0.0.1:8765/callback`, only if the deployment lists that approval. |
| Local transport/command | stdio; the approved installation's absolute `gc-mcp.exe` path. Do not substitute a candidate/test environment. |
| Server arguments | `--origin`, the reviewed application origin, `serve`; add an existing, expressly chosen `--download-directory` only for authorized transfers. |
| Selected upload files | Exact expressly chosen source files through the connector's selection mechanism. A Codex attachment does not automatically become an allowed local file. |
| Permission request | Only the approved currently enabled categories. Installation does not enable uploads, creates or communications. |
| Secrets in configuration | None. Windows Credential Manager stores the connector's dedicated authorization; do not copy credentials into chat or configuration. |

Review the connection name and permissions in the application's normal browser
MFA/consent flow. A new consent approval creates a grant. Return to the website
and repeat sections 1 and 2 with the newly authorized connection. The
[connector instructions](../../mcp-connector/README.md) define the release's
mechanics; the current website setup text still names `0.2.0` and must not be
used as proof that the candidate was released or installed.

After the frozen `020ddacc` interface is actually released and independently
verified, the same route is designed to show **Codex access**. Its basic view
explains saved authorization and lookups; **Advanced** contains **Connections**,
**Activity**, **Workflows**, **Files**, **Tools** and **Connection setup**. Use
those sections for the corresponding checks above only after the serving
frontend release is confirmed. A copied report example can authorize export
preparation; use this guide's inspection prompts for the ordinary verification
walk.

The manual controls have different scopes:

- Current **Disable MCP access**, or future **Pause access**, changes
  global MCP access for all connections. It blocks new MCP calls and protected
  downloads; it is not a desktop-presence test or a recall of provider-accepted
  messages.
- Current **Revoke**, or future **Disconnect** for a selected named connection,
  revokes that connection's server authority. It is not the global pause and
  does not remove application records. Reconnecting requires authorized sign-in.
- **Edit access / Save access** changes the selected connection's name or
  narrows its permissions immediately. Additional permissions require a new
  approved authorization; MCP cannot increase its own permissions.
- Clearing the connector's local credential changes its local authorization
  only. It does not revoke the server grant.

Do not click these controls to verify that they work during an inspection walk.
Reserve pause, revoke/disconnect, narrowing, expiry/replay and recovery tests for
a separately approved acceptance plan with an independent test identity and a
defined recovery arrangement. Never use the active user's only credential for
refresh replay or manufacture a test by changing roles, server time or services.

## 8. Keep unfinished acceptance explicit

New uploads, imports, group creation, business changes, contact-workbook
workflows and communication/provider acceptance remain pending in this guide.
They require a specifically approved test identity, exact synthetic files and
test scope; communications also require an approved recipient, actual consent,
final content/template/attachments and explicit send authorization. Merely
checking access, previewing work or preparing a plan is not send authorization.
Do not enable capabilities or run a customer workflow to fill an evidence gap.

A future authorized acceptance run must preserve operation/workflow/artifact
IDs and original retry keys, inspect unknown outcomes before repetition, prove
the resulting website records and verified local delivery, and use actual
provider receipts for queued/sent/delivered/failed/unknown claims. Physical
attendance/check-in evidence must come from the real supported event flow.
Combined load, comprehensive negative cases and full workflow coverage need
their own qualification; these steps cannot close them by inference.

The MCP boundary remains in force across releases: no record/file/member
removal, archive, purge, destructive replacement, arbitrary HTTP/SQL/shell or
filesystem access, server restart/deploy/reboot or infrastructure control.
Permission categories and tool counts do not override that boundary.

## Advanced release and evidence

The table below is the dated release comparison record used for this guide.
The [read observations release checkpoint](mcp-read-observations-release-checkpoint.md)
defines its accepted live scope. The
[Codex access UI checkpoint](mcp-codex-access-ui-checkpoint.md) records the later
production observation and the undeployed interface. The
[phase register](mcp-phase-register.md) records each remaining gate. Later source
for analytics, administrative overview and retention reads is not evidence
that those tools are available on the serving backend.

| Item | Last established state | What that evidence means |
| --- | --- | --- |
| Website | [tech.gctravels.com](https://tech.gctravels.com) | Use the established application origin. |
| Production backend | `1f4177cb02006a4980022715ffa3b90eba76958b` | Selected live reads are accepted on this revision. |
| Production frontend | `1d77c9ddb16439e62d29f85067377f23070552b6` | The serving interface is the Administration **MCP** page described above. |
| Workers and scheduler | `efea4e4ac199b65fbf4f3b76a1ed59c4c963bd7e` | A newer backend does not imply that workers changed. |
| Schema | `0122_mcp_gc_push` | Record this separately from application revisions. |
| Production observation | 30 September, 13:47–13:49 UTC / 19:17–19:19 IST | The 13:47 inventory had 20 running services and all 18 configured Docker health checks healthy. The twelve application services had zero restart counts and no reported OOM state. Public live/ready checks at 13:49 returned 200 with the backend revision above. These are dated observations, not a current guarantee or a capacity test. |
| Enabled production profile | Read and export; `passport_excel`; 100 source rows; 1 MiB source budget | A registered tool, an installed connector or a visible permission category does not enable another workflow. These export source limits differ from result page sizes and generated file sizes. |
| Active Windows connector | `0.2.0` | The existing installation and saved configuration remain the active setup. |
| Isolated connector candidate | `0.2.2`, source `3114d684e577bb480afa8ac08c433457e3818be3`; 35,923-byte wheel | Candidate SHA-256: `d47969e3e789cfa70483082414b56b6e68a4f4bc6e9bf596cd0a658d6da7ccad`. It was qualified in a separate environment and is **not installed in the active setup**. Its tests do not prove a fresh real Codex/browser sign-in. |
| Simpler Codex access interface | Frozen source `020ddacc14068337cb1d53a3c971f007068448e1` | Locally qualified, **not built or deployed**. Its labels must not be expected on the current website. |
| Overall acceptance | **All eight broad gates remain OPEN** | Selected successful reads and one verified Excel delivery do not establish complete access, upload, creation, communication, recovery or load acceptance. |

For release-owner diagnosis, use the source and retained receipt bindings
below. Some operator receipts are private local evidence and may not be present
in a repository clone. Missing or expired evidence must be reported; do not
regenerate, overwrite or widen an old acceptance record automatically.

- [Phase register](mcp-phase-register.md): eight open gates and the permanent
  non-removal/server-control boundary.
- [Read observations release](mcp-read-observations-release-checkpoint.md):
  accepted backend/profile, selected Codex and website observations, their
  timestamps, pagination/privacy limits and retained incomplete attempt.
- [Codex access UI checkpoint](mcp-codex-access-ui-checkpoint.md): frozen
  undeployed interface and 13:47–13:49 production observations. Supporting safe
  receipts: `outputs/retained-reference-readonly-20260930T134703Z-82fff967.json`
  and `outputs/retained-reference-detail-readonly-20260930T134858Z-4c0b0574.json`.
  Health success does not erase the documented historical retained-image and
  stopped-container reference gaps or qualify a new release.
- [Live Codex checkpoint](mcp-live-codex-checkpoint.md) and
  [export history contract](mcp-export-history-checkpoint.md): verified delivery
  versus generation, retained history semantics, file expiry and parity limits.
- Candidate receipt: `outputs/mcp-connector-022-candidate-20260930.json`;
  isolated installed qualification:
  `outputs/mcp-connector-022-installed-qualification-20260930.json`. The candidate
  receipt records 28 installed-wheel tests and no active installation,
  configuration, vault, sign-in or application calls. It retains the earlier
  136-test source regression as separate evidence.
- Source contracts:
  [connection and transport](../../backend/app/presentation/mcp/server.py),
  [group pagination](../../backend/app/presentation/mcp/group_tools.py),
  [operation inspection](../../backend/app/presentation/mcp/operation_tools.py),
  [export history reads](../../backend/app/presentation/mcp/export_history_tools.py),
  [health](../../backend/app/presentation/api/v1/routes/health.py) and
  [connector transfers and credentials](../../mcp-connector/README.md).
  Current interface labels were checked in the frontend source at the serving
  `1d77c9dd` revision; future labels were checked at frozen `020ddacc`.
