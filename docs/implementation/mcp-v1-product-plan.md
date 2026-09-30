# Codex access V1: a simple connection screen

Product direction updated on 2026-09-30. The immediate release should make the
existing, restricted Codex connection easy to understand and use. The full
eight-phase objective and all retained implementation/evidence remain in place;
this V1 is not a claim that those phases are complete.

The current serving backend is `1f4177cb` and the frontend is `1d77c9dd`, with
schema `0122_mcp_gc_push`. The enabled business permissions are read and export.
The enabled export family is passport Excel, with the existing 100-source-record
and 1 MiB source admission limits. The later analytics, administrative overview
and retention-read candidate remains separately retained and does not need to be
deployed to simplify this screen. Current API compatibility is the release
boundary for the UI change.

## Essential V1 experience

The initial screen should answer four practical questions without requiring MCP
terminology: is Codex access on, how do I connect, what can I ask it to do, and how
do I stop its access? Use the page title **Codex access** and an obvious
**Connect Codex** action. A short guided setup must use the real supported
connector/browser sign-in path. It must not imply that copying an endpoint or
clicking a website button has installed the connector or connected the Codex app.
Any currently required local installation step stays visible in that guided path,
with copyable instructions and a truthful completion state.

Show the website's access state and the named connection's authorization state
separately. An active authorization does not prove that the Codex desktop is
currently running or connected. Use plain states such as **Access on**,
**Access paused**, **Not connected**, **Authorization expired** and
**Disconnected**, based on actual server responses. Retain readable connection
names, last-used information and expiry where they help the user decide what to
do. A failed status fetch must show an unavailable/retry state rather than a false
success or an enabled action based only on cached data.

Keep the permission explanation short and based on the enabled deployment and
this connection's actual permissions:

| Plain-language group | Supported V1 examples | Boundary |
| --- | --- | --- |
| View business information | Find a group; inspect its passenger roster; ask for a dashboard or attendance summary; inspect existing export history. | Current website authorization and bounded pages remain in force. Attendance metadata is not physical proof or permission to close a session. |
| Export passport spreadsheets | Review available spreadsheet fields; prepare a supported selected passport export; save the protected result through the connector. | Only the currently enabled passport Excel family is offered. Existing size/selection limits still apply. A prepared result is not called delivered until verified download and acknowledgment succeed. |

Offer a few copyable prompts, for example “Find my group and show its passenger
summary,” “Show the attendance summary for this group,” and “Export these selected
passports to a spreadsheet.” Codex must resolve ambiguous group names and ask for
the relevant selection. Examples should not embed customer names, IDs or private
records. They must not promise uploads, data edits or sending messages in this
read/export-only V1.

Expose **Pause Codex access** and **Disconnect** in the normal user flow.
Pause uses the existing global access control: clearly say that it affects all
Codex connections to this website. It does not revoke a connection or claim to
cancel work already completed or handed off. Disconnect revokes the selected
named connection and requires sign-in to connect again. Preserve existing
confirmation, current authorization, recent-MFA and CSRF requirements. Failed
actions retain a truthful error and refetch state; a label change alone is not
evidence that access stopped.

## Optional Advanced content

Keep the existing technical material available behind a closed **Advanced**
disclosure or explicit secondary navigation. This includes raw tool names,
protocol scopes, endpoint/client identifiers, workflow/file records, revision
and audit identifiers, detailed activity, deployment qualification and diagnostic
information. Preserve these records and their functionality. They should not
occupy the initial screen or be required to understand a routine connection.

Show short actionable failures in the main flow. Detailed diagnostics and
qualification records can remain in Advanced. This presentation change must not
hide a failure that prevents connection or a restriction that affects the user's
requested action. The simple permission summary is not a claim that every
workflow in a technical category is implemented.

## V1 acceptance

| Acceptance | Required evidence |
| --- | --- |
| Initial comprehension | The first screen visibly provides access state, Connect Codex, the two actual permission groups, supported examples, pause and selected-connection disconnect. Raw scopes, tools, IDs and qualification records are closed by default. |
| Honest setup | The guided path leads to the existing supported connector and browser consent. Cancel, expired sign-in and failed setup never become “connected.” Current authorization alone is not presented as a live desktop connection check. |
| Existing safeguards | Non-Superadmin access remains denied; role/session loss hides cached protected content. Current consent, MFA, CSRF, capability narrowing, emergency fencing, revoke and protected-transfer checks remain unchanged. No new grants or broader permissions are created for UI verification. |
| Truthful controls | Pause states its global scope; disconnect names the selected connection. Requests preserve pending/error handling, confirmation and authoritative refetch. No action is reported successful before the server accepts it. |
| Supported examples | Examples map to the current read/export deployment. No uploads, business edits, acknowledgments or communications are advertised as enabled. Pagination and export admission failures remain understandable and honest. |
| Usable layout | Focused component tests plus keyboard and pointer browser checks at desktop and narrow/mobile widths. No overflow, inaccessible primary action or dependence on opening Advanced for a routine connection. |
| Deployment | Frontend-only compatibility checks against the unchanged current API; retained frontend/proxy replacement, preserved backend/workers/infrastructure, exact build/public asset proof, bounded resource admission and verified rollback/recovery. No new stack, grants, deletion or uncontrolled retry. |

## Remaining essential business V1 and later enhancements

This immediate UI simplification releases the useful read/export permissions
already enabled. It does not fulfill the whole requested business V1. The
originally requested business tasks, including safe creation and updates,
uploads, supported exports and Excel-to-message workflows, remain essential V1
acceptance work. They must be implemented and qualified before their permissions
and examples are enabled; this UI release does not make them optional or change
the accepted safety boundaries.

Later enhancements may include richer technical administration, diagnostics,
catalogue presentation and operator records. These can grow behind Advanced
without expanding the beginner screen. They are distinct from the remaining
essential business workflows and are not prerequisites merely to simplify the
currently working connection experience.

The full Phase 1 contract map, remaining Phase 2 controls, comprehensive business
coverage, recovery/security cases and combined Linux workload/capacity evidence
remain internal acceptance obligations under the original goal. Keep their exact
status in the phase register and component evidence. Neither hiding technical
details nor shipping this immediate read/export UI release completes those gates
or the remaining essential business V1 acceptance.

Source references: `frontend/features/mcp/components/mcp-admin-page.tsx`,
`mcp-connection-card.tsx`, `mcp-consent-page.tsx`, `mcp-connector-setup.tsx`,
`backend/app/presentation/api/v1/routes/mcp_admin.py`, and the retained
`mcp-read-observations-release-checkpoint.md`. This document is an implementation
plan and acceptance boundary, not proof that the redesigned UI has shipped.
