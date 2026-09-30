# Minimum read-only Codex access

This guide describes the minimum candidate that replaces the earlier eight-phase completion plan. It does not establish that this candidate is deployed. Production deployment and a real Codex read must be recorded before announcing it as working on the main website.

## Website controls

Open **Codex access** on the main website. The **What Codex can read** panel lists the website's 19 sidebar sections. Fifteen sections have supported reads and an Allow checkbox. Change the checkboxes and choose **Save read access**. These settings apply to every MCP connection; normal website permissions and business features continue to use their existing rules.

The page confirms a change only after the server saves it. A second administrator's change causes a conflict: choose **Reload saved settings**, review the current choices, and save again. Saving requires an active superadmin session and recent MFA. An expired session, missing MFA, or unavailable policy must not be presented as a successful save.

Several reads combine information from more than one section. Expand **Required sections for these reads** to see the dependencies. Every required section must be allowed. For example, group discovery also includes WhatsApp counts and retained group information, so it needs All Groups, WhatsApp, and Old Data. Dashboard summary needs Dashboard, All Groups, Group Links, and Old Data.

**Pause Codex access** remains the shared emergency switch for all connections. Connection status is available independently of business section choices, but still requires valid authenticated MCP read access.

## Available coverage

The server admits 31 explicit observational tools: one connection-status tool and 30 business reads. The section names do not imply complete parity with each website page.

| Section | Minimum available reads |
| --- | --- |
| Dashboard | Passport counts and a short preview; retained totals and active-link counts require their related sections. |
| All Groups | Group discovery, passport rosters, processing/OCR/ECR observations, and shared group projections. |
| Group Links | Active-link count through Dashboard summary. No complete link inventory or credentials. |
| WhatsApp | Stored broadcasts, audience, and batch status. Broadcasts and audience also require All Groups. |
| Operations Inbox | Integration readiness and retained metadata for the signed-in owner's mailbox. No provider fetch or synchronization. |
| Documents | Stored document metadata, distribution/rename history, and publication metadata. |
| Coordinators | Stored assignments and organization directory identities through shared reads. |
| Rooming Lists | Stored hotels, rooms, selections, allocations, and check-in evidence. |
| Menu | Stored categories, dishes, plans, and entries. |
| Tour Ops | Stored assignments, activities, attendance, and itinerary metadata. |
| GC App | Stored access, publication versions, and authored notification history. |
| Manager | Administrative counts and organization directory metadata. |
| Staff | Directory identities and administrative user counts. |
| Analytics | Passport analytics using group data. |
| Old Data | Retained/deleted-capable projections, export-history metadata, and stored retention schedules. |

My Tour, Audit Logs, and Settings have no dedicated business read in this release. Codex access itself provides connection metadata, rather than an additional business-section permission. The panel explains these four entries and does not offer a misleading Allow checkbox.

## Connecting Codex

The connector candidate is **0.2.4**. Its launch command uses `serve --read-only`. This mode exposes advertised read tools, checks the current read-tool catalog before each call, and refuses direct file-tool or write-tool calls. It does not construct the local upload/download tools.

The matching backend enforces the stronger boundary: its explicit observational registry excludes tools that refresh durable workflow progress even when their older annotations called them reads. The desktop connector alone cannot certify that an older backend is observational. Activate the 0.2.4 binding only after the matching backend is deployed and checked.

Existing login/grant state can be reused when it is still valid. Read-only mode never expands an existing grant. If login is required, the consent page offers only the effective read capability. Section permission changes take effect at the backend for subsequent calls, independently of capabilities stored in an older access token.

## First verification

1. Ask Codex to check the connection and report the website environment and backend revision.
2. With the required sections allowed, ask it to list a small number of existing groups, or inspect existing menu records. Check the answer against the website.
3. Deny a required section, save, and repeat the same read. The server must refuse it before the business service runs.
4. Restore the desired section choices and confirm the read succeeds again.

Targeted integration checks exercise direct denied write and file requests without contacting customer providers. Do not use a customer send or a business mutation as a live acceptance probe.

Creation, editing, uploads, downloads, file generation, exports, workflow preparation/execution, sending, notification acknowledgement, and progress-refresh workflows are deferred. Their implemented source remains retained, while read-only MCP controls and tools do not expose them. Ordinary website features remain available through their existing customer-facing paths.

## Deployment boundary

The candidate adds only the `0123_mcp_read_sections` migration above `0122_mcp_gc_push`. It retains existing grants and the enabled/paused state. An existing enabled control row receives the reviewed section set only if an unrevoked, unexpired read grant already exists; new or disabled rows start with no business sections allowed. Recovery must preserve the target schema, use compatible retained containers, and avoid a destructive downgrade.

The candidate backend, workers, and scheduler must use the new backend image with the read-only configuration. Its publication loop leaves queued MCP plans intact before broker reservation. Previously brokered MCP jobs can still reach the existing denied-authority handling and update their failure/progress records; they cannot gain permission to send. A release must drain and observe existing work without purging queues. An older recovery worker image must explicitly disable MCP and can mark retained MCP work blocked, so recovery cannot be described as freezing every workflow row.

The last retained-resource observation found 301 containers and 184 images, with 20 running containers and all 18 configured health checks healthy. Three stopped historical containers still fail the strict reference guard separately from the 33 previously approved missing-image IDs. Those three have no new exception approval. This candidate must not bypass that stop condition or remove any resource to make the check pass.
