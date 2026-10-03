# Dashboard MCP read and write access

This change adds typed dashboard write workflows to the existing native MCP endpoint, with separate global and per-connection Read and Write allowances. It uses the current Superadmin identity, existing tenant rules and canonical business operations. New permissions do not expand an existing OAuth grant.

## Administration

- The Administration sidebar label is **MCP**. Devices, Requests, Settings and Connection setup remain the four pages.
- Settings contains Read settings and Write settings, each with its own allowance and section selections. Disabling an allowance preserves its saved selections.
- Device Manage independently saves Read and Write. A device's selections are intersected with current global settings, the deployed code capability ceiling and its originally approved OAuth scopes.
- Existing connections keep their current enabled/revoked state, read authority and exact scopes. Global Write and old device Write start disabled. A connection approved without effect scopes needs a new request and explicit approval before Write can be enabled.
- Policy saves require the existing recent-MFA Superadmin session and the inspected revision. Conflicting saves do not silently overwrite another administrator's choices.

## Implemented workflows

| Section | Reviewed operations |
| --- | --- |
| Group links | Create a new group with the canonical collection fields, accepted upload methods and custom questions; configure an existing group's selected fields; add an explicit broadcast link. Ask for the user's collection choices before creating/configuring. |
| Group Excel imports | Transfer an original XLSX to an exact agency/group, scan and parse it, preview canonical create/update/duplicate outcomes and import the reviewed source. Retain the original workbook and parsed checkpoint. Ambiguous matches require correction. |
| WhatsApp broadcasts | Create/configure a broadcast, add contacts, inspect and import original contact workbooks, prepare exact messages/reminders and confirm the reviewed audience/content only after final chat approval. Creation/import never sends a message. |
| Rooming lists | Create/configure hotels, add selected operational passengers, set VIP choices and allocate rooms with current canonical selection/revision checks. Existing history is retained. |
| Menu | Create/edit categories and dishes, create/edit meal plans and edit individual entries using canonical validation. Omitted edit fields retain their saved values. |
| Document delivery | Transfer original PDFs to an exact group/document lane, scan and ingest them through existing classification/matching, inspect the full assignment preview and save it after review. Unresolved documents remain unassigned. Prepare saved passenger PDFs with exact recipients, messages and exclusions; confirmation requires final approval of the unchanged preview. |
| Workforce administration | Create invited coordinator, staff and manager accounts in the current administrator's agency. Credentials and activation links are not returned through MCP; complete activation through the existing dashboard account flow. Add explicitly selected group access. |
| Tour Ops | Add coordinator assignments and create attendance activities. Read existing operational attendance and return a person's existing canonical QR PNG without creating a new token. |
| GC App | Create invited client managers with explicit organization/groups; configure group access, photo settings and itinerary publication; retain the existing announcement/push draft and prepare/confirm flows. |
| Exports | Enable the five previously implemented export families as deployed code availability: passport Excel, passport images, tracking Excel, rooming Excel and document assignment Excel. Export still requires current Write/section/device/OAuth authority and exact source/revision/transfer checks. |

## Files and confirmations

Native Streamable HTTP clients use a short-lived browser file handoff without signing the requester into the dashboard. The handoff binds one original connection, current security version, exact target, filename, MIME type, byte size and SHA-256. Its limited credential is carried in the URL fragment, removed from browser history immediately, held in memory and sent only in the authorization header. It is not retained in operation receipts, audit records or query strings.

A server cannot read a folder on another computer merely from its path. The connected AI/client must transfer each selected file through the handoff (or the protected content endpoint). Files are staged first; passenger import, document ingestion, assignment save and outgoing delivery are separate reviewed actions.

Completed upload handoffs remain inspectable while their staged source is valid. The ten-minute transport credential lifetime does not shorten the original one-hour staged-source lifetime. Browser download success requires verified content and a completed save or explicit saved-copy confirmation; a download click alone is not proof.

Outgoing sends follow **prepare → display exact preview → final user approval → confirm → current worker authority check → provider submission**. `user_confirmed=True` is an explicit tool contract and client instruction, not cryptographic proof of a human gesture. Every send requires final approval after the preview; earlier intent to send cannot substitute for it. Unknown provider outcomes are retained and are not automatically retried. A verified later provider receipt may resolve the outcome without a new send.

Document source previews bind immutable saved object references and database revisions. A digest of the private storage reference is metadata binding and does not claim to be a PDF-byte SHA-256. Original native uploads independently verify their actual bytes.

## Transaction and expansion boundaries

Code-owned tool/section registration determines which adapters are eligible. Adding a registry entry alone never grants a capability: deployment, OAuth, global policy, device policy, current identity and tenant/resource checks must all pass. Dynamic workforce roles and file lanes resolve their exact required section before execution and receipt replay. Unknown tools fail closed.

Database effects, retained audits and idempotent receipts commit together. Current revisions and source bindings prevent changed retries from silently overwriting records. Storage/parsing I/O occurs outside receipt transactions; current authority and immutable source/roster bindings are rechecked afterward. Provider workers lock and recheck original authority before upload and message submission, so disabling a device blocks remaining unsent work.

The implementation admits bounded complete results instead of truncating them or guessing. Current deployment export limits remain **100 source rows and 1 MiB**, unchanged from the live read-only baseline. Document sends admit 1–100 explicitly chosen saved documents, assignment inspection admits at most 1,000 batches/documents, previews expire after 15 minutes, and file transfers enforce their configured original-size bounds. Larger work must be split explicitly; no arbitrary performance or unlimited-domain guarantee is made.

## Qualification and deployment

The retained local evidence covers real OAuth/SDK HTTP discovery, current global/device settings, typed operations, retry/conflict/rollback cases, original file scans and bindings, partial-edit preservation, outgoing final approvals, worker unknown outcomes and separate PostgreSQL contention/migration preservation. Frontend qualification covers desktop and mobile administration/file journeys, unit checks and an isolated production build.

No production passenger, group, account, upload or outgoing message is created for qualification. Source/tool inventory remains an implementation ledger; local test success and a deployed tool do not establish unrestricted business-domain qualification. The additive release is schema `0125_mcp_connection_requests` through `0128_mcp_document_delivery`, with all existing records/resources preserved and all application workers updated together. The [3 October 2026 live checkpoint](mcp-dashboard-write-live-2026-10-03.md) records the successful immutable release, independent read-only verification, activation steps and qualification limits.
