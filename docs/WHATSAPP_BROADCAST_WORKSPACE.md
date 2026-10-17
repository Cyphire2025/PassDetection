# WhatsApp broadcast workspace

The broadcast section uses dedicated routes and a shared composition system. Opening a broadcast establishes the group context for every section. The index contains search, Active and Archived lists, creation and an explicit Open broadcast link; it does not contain the old overview metrics or a growing menu of send actions.

## Navigation and responsibilities

| Route | Responsibility |
| --- | --- |
| `/whatsapp` | Find, create, open and restore broadcasts |
| `/whatsapp/[broadcastId]` | Search the message catalogue and compose a message |
| `/whatsapp/[broadcastId]/history` | Find each individual send and open its delivery report |
| `/whatsapp/[broadcastId]/documents` | Review and send documents for passengers proven to belong to this broadcast |
| `/whatsapp/[broadcastId]/recipients` | Search and sort people, correct numbers, add recipients and compare details |
| `/whatsapp/[broadcastId]/details` | Edit broadcast information and support contacts; archive, restore or delete |

The workspace navigation, spacing, surfaces, field styles, status badges, searches, tables and pagination are shared. Message content is edited before recipient selection, with the live WhatsApp preview beside the editor on wide screens. Narrow screens stack those areas. Motion respects the operating system and existing dashboard reduced-motion preference.

## Composition

`frontend/features/whatsapp/workspace/` contains the new workspace. `composer-primitives.tsx` supplies the common text editor, WhatsApp bold formatting and message preview used by both broadcast messages and document messages. `use-message-composer.ts` owns audience state, server preview freshness and normal dispatch. Sending requires a current server preview, valid fields, a nonempty selection, required media, opt-in and the existing welcome prerequisite where applicable.

`GET /whatsapp/message-catalog` describes the available forms. The catalogue uses stable entry IDs, categories, delivery types, typed fields and audience variants. Searching and pagination accommodate a large catalogue without adding navigation tabs or action-menu entries. The browser suite exercises 100 entries. Adding a new provider template still requires an explicit server-side delivery contract and registration; the UI does not invent approved templates or accept arbitrary provider payloads.

Reminder retains Everyone and Only people who haven't submitted, with an explicit linked submission-group choice when multiple groups exist. Trip update combines submission, document-delivery and document-type filters on the server. A multi-PDF assignment counts as sent only when every assigned PDF has an accepted delivery. Missing, failed and partial deliveries remain pending.

Passport-link composition can deliberately include previous recipients for a new message. Pending and unconfirmed outcomes remain blocked. Each new send gets its own batch and immutable message-log records. Preview-only recipient-sampling fields are removed before the strict dispatch request is bound to an idempotency key.

Normal sends reuse the existing durable send-intent/outbox pipeline. A lost response is checked with the same request identity. The review screen retains the earlier send's content during recovery. A different draft with an unresolved earlier intent requires inspecting delivery history before explicitly preparing a separate message. Only opaque identities and fingerprints are retained in the existing session storage mechanism.

## Delivery history

The history API groups immutable message logs by batch, falling back to a log ID for older records without a batch. Repeated updates or passport-link messages are separate history entries. Search applies to whole batches so it does not reduce a batch's delivery counts merely because only one personalised body matched.

Filters are All, Sent, Not sent, Delivery left and Failed. Sent means accepted by WhatsApp and includes delivered/read outcomes. Not sent covers active queued/submitting records. Delivery left means provider acceptance exists but recipient delivery is not confirmed. Failed also contains unresolved outcomes with a visible Unconfirmed badge. The underlying outcome is preserved and unconfirmed records cannot be blindly resent. There is no Need Review tab.

Each report supports search, inline number editing, saved message content and recipient-specific retry/resend. A historical resend selects the exact original message-log ID, freezes its saved template and parameters and uses a stable request ID. Repeating that HTTP request returns the existing attempt. History shows both the original destination and the current number after an edit. Removing a recipient retains the existing soft-removal and history semantics.

The history endpoints describe broadcast-template sends. Document deliveries retain their separate document-delivery pipeline and their delivery information in Documents.

## Documents and recipients

Documents uses the open broadcast's linked groups without a redundant group dropdown. A server-resolved passenger-link projection excludes unrelated passengers from a linked client group. All, Multiple PDFs, Shared PDF, Assigned, Missing, Sent and Not sent remain available alongside document-type selection and passenger search. Document sends use the existing frozen preview tokens and selected document IDs; targets belonging to another broadcast are excluded. Assignment management remains available through the existing document workspace.

Recipients offers A–Z, Z–A and import order, plus welcome-failed and welcome-not-sent filters. Welcome failure is a delivery result, not proof that a number is absent from WhatsApp. Delivery history provides the recorded reason. View details opens a modeless comparison rail with multiple independently closable cards. Source-managed people sharing a number retain their individual details. Source contacts without valid delivery identities remain visible under Contact issues with a link to correct their source record. Manual/Excel imports retain the original-workbook provenance and rejected-row recovery mechanisms.

## Configuration and validation

Trip update is a new template slot in this checkout. Configure an approved text template with one body variable using the existing administrative template settings or `WHATSAPP_UPDATE_TEMPLATE_NAME`. Its environment default is intentionally empty. No approved Meta template name is assumed.

Verification uses synthetic browser data and isolated database fixtures. It does not send live WhatsApp messages. The browser suite covers the complete route flow, 100-entry catalogue, common editor ordering, reminder/passport audiences, failed-number correction, stacked details, archive/restore, manual/Excel import provenance, image sends, lost-response recovery, exact historical resend identity, document scoping and document dispatch. Backend integration tests exercise per-send history, immutable destinations, tenant scope, full saved bodies, unresolved outcomes, request canonicalisation, repeat passport eligibility and combined document filters.

The local production build and TypeScript checks pass. Focused backend and frontend tests pass. The repository-wide frontend maintainability check currently reports an unrelated existing budget violation in `features/upload/components/upload-flow.tsx`. A broader backend run also encounters existing client-group tests missing the newly required company field. Those files were not changed as part of this workspace implementation.

Design reference: [Carbon's data-table guidance](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) informed the consistent placement of table-level search, filters and actions. Business semantics and send safeguards follow this repository's existing delivery policies.
