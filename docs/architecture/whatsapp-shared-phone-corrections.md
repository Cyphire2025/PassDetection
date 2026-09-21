# Shared WhatsApp number corrections

Editing a broadcast contact to an existing number joins its delivery destination
instead of rejecting the edit. The database retains one active canonical delivery
recipient per broadcast and normalized phone. The old recipient and frozen message
logs remain historical records; separate manual contact snapshots preserve names
and imported details even when a former phone is later reused. Source-group travellers retain their independent source
contact rows. Shared contact names remain searchable and manual contact details are
included separately in delivery-filter exports.

Migration `0105_whatsapp_phone_overrides` adds the merge pointer and exact traveller
phone overrides. An override binds a broadcast, source group and passenger to the
corrected recipient. The source phone fingerprint expires the correction when the
traveller's source phone or its provenance changes. Name edits and document uploads
do not erase the correction. Unlinking the broadcast removes its authority to supply
that destination. Conflicting valid corrections across linked broadcasts block
private delivery rather than select a number arbitrarily.

Corrections never modify passport contact fields, imported source metadata, or OTP
and mobile login authority. Exact source associations or established unambiguous
private-delivery matches determine which travellers receive the override. The phone
edit locks affected groups before the broadcast and its recipients, fences active
or uncertain private delivery, and cancels queued private deliveries that need a
new preview. A document worker revalidates the exact passenger, document, broadcast,
recipient and phone immediately before sending.

Welcome, group-invite and normal passport-link sends retain phone-level duplicate
protection. Deliberate passport-link resends retain their existing separate action;
one shared destination receives one copy for that action. Moving a contact onto an
existing destination does not clear that destination's delivery history.

Document delivery uses one ledger entry per assigned PDF. Two travellers at the
same number receive both of their assigned PDFs; neither traveller is skipped
because the phone is shared. The same accepted or uncertain PDF is still protected
against accidental duplicate sending. No welcome message is required for PDFs.

Deploy the schema before the new API and worker code. Update an explicit
`EXPECTED_DATABASE_SCHEMA_REVISION` override to `0105_whatsapp_phone_overrides`,
and deploy the backend, worker-image consumers and frontend consistently. The UI
invalidates broadcast contact lists and document previews after a phone edit.

This change was reviewed in source only. Tests, builds, lint and runtime checks
were not run at the user's request. No production messages were sent as validation.
