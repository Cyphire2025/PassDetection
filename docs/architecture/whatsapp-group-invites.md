# WhatsApp broadcast group invites

An active broadcast's actions menu includes **Send group invite**. The composer
lets staff choose a photo, edit the invitation, paste an official
`https://chat.whatsapp.com/<invite-code>` link, choose recipients, and review the
same server-rendered template content that is saved for delivery. Share-link query
parameters are retained. The link's format is checked; its expiry or membership
settings are not checked remotely.

The template is `whatsapp_group_invite_v1`, with this exact body:

```text
Dear Delegates

Greetings from Global Connect Travels

{{1}}

{{2}}

Regards
Team Global Connect Travels
```

The template has an IMAGE header; the ordered BODY parameters are `message_content`
and `group_invite_link`. Staff must supply an image for a new send. Saved text-only
failed invites can be opened in preview, but need an image before retrying. A welcome
image is never substituted. The invitation paragraph has the
same 600-character editing limit as the other broadcast composers. Meta must have
approved and enabled the matching template before real sends can succeed.

Configuration defaults:

Super administrators can override this name in Settings without a restart; see
[WhatsApp template-name settings](whatsapp-template-settings.md). ENV remains the default.

```dotenv
WHATSAPP_GROUP_INVITE_TEMPLATE_NAME=whatsapp_group_invite_v1
WHATSAPP_GROUP_INVITE_TEMPLATE_LANGUAGE=en
```

The invite language is independent of `WHATSAPP_TEMPLATE_LANGUAGE`, so existing
templates may continue using `en_US`. To replace the invite with another approved
template of the same shape (one IMAGE header, the same two BODY variables and `en`),
change only `WHATSAPP_GROUP_INVITE_TEMPLATE_NAME` to its exact Meta name in the VPS
`.env`, then recreate the backend and WhatsApp worker containers. Their Compose
services load `.env`; a process restart alone does not update a container's environment.
Template category is managed by Meta and is not a field in the send payload. A
Marketing-to-Utility name change therefore needs no application category setting.
Only switch after approval and only when the new template has the same contract.

New sends and retries of failed invites use the currently configured template name,
including bulk retries with unchanged content. Existing queued jobs keep their frozen
template name and language. Saved retries preserve their original language (or the
configured invite language for legacy null snapshots). This change needs no migration.

Invites reuse the broadcast queue, delivery state, receipt handling and opt-in
checks. They do not require a prior welcome and do not create welcome delivery state.
An invite goes only to destinations without another accepted, active or uncertain
invite in this broadcast. The policy considers all original and retry logs for the
current normalized phone, regardless of the template name or recipient row. It
applies to previews, ordinary sends, single retries, bulk retries and the worker's
final check before contacting Meta. Different broadcasts keep independent history.

`submitted`, `sent`, `delivered` and `read` block another invite. `queued`,
`processing` and `delivery_unknown` also block it; an old queued invite is not
automatically reclaimed by another send. A terminal `failed` attempt can be retried
if no blocking sibling remains. This includes a Meta `131049` failure after initial
API acceptance: an old provider ID or submission timestamp alone does not count as
success. The UI projects destination history into invite status and retry eligibility.
Bulk request identities still include edited invitation links. Other message types
retain their existing welcome and resend policies.

Archived broadcasts start collapsed. Their count remains visible, expansion
survives searches, and collapsing closes any open row menu. They remain read-only
until restored.

The recipient workspace displays one selected message type at a time. Delivery
filters and counts use that type, including original and explicit resend states;
switching type clears the selection. Search and filter changes preserve selection
with an explicit notice for selected numbers outside the current view. First sends
remain in the broadcast composer; the selection bar reviews saved retries/resends.
The shared-number filter counts delivery destinations, with all associated source
travellers available under the recipient name and included in search.

The Travellers view retains every source row with All, Ready, Needs review and
Shared filters. Ready includes valid shared contacts, so these counts overlap.
Shared view groups by normalized phone and labels the first source row as Primary
contact; this records source order, not verified ownership of the number. Searching
for any member retains the entire group, and pagination never splits its members.

The existing browser tests intercept API requests and never contact WhatsApp.
