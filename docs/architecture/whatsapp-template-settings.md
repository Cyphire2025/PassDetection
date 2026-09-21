# WhatsApp template-name settings

Settings displays the seven template slots used by the running application:
Welcome, Passport Link, Reminder, Group Invite, Document Distribution, Passenger
QR, and WhatsApp OTP. With no saved override, each name comes from the corresponding
`WHATSAPP_<SLOT>_TEMPLATE_NAME` environment variable. Existing empty values remain
empty; viewing Settings does not create a row or alter runtime configuration.

An override is stored under `whatsapp_template_names` in the existing
`platform_settings` table. It does not modify `.env`, credentials, languages, the
shared `get_settings()` instance, message content, or recipients. This needs no
migration. Names allow lowercase letters, digits and underscores, with a
maximum length of 255 characters to match the existing frozen delivery columns.

`GET /api/v1/admin/whatsapp-templates` allows super administrators and agency
administrators to view defaults, overrides, effective names, and environment
languages. Only a super administrator can use `PUT` because all agencies share
the configured WhatsApp sender. PUT follows the existing recent-MFA and cookie-CSRF
rules, accepts an `expected_revision`, and applies only the supplied `overrides`
keys. A `null` value removes that slot's override and restores the ENV default.
Unknown keys, blank names, invalid names, and extra request fields are rejected.

Updates lock the settings row and compare its revision. Concurrent first writes
are serialized through its unique key; a stale writer receives HTTP 409 with
`WHATSAPP_TEMPLATE_REVISION_CONFLICT`. The update and audit record commit together.
The audit includes the actor, old/new overrides, effective names, and revisions.
Successful responses and reads use `Cache-Control: private, no-store`.

Runtime operations read a single small settings record and memoize it only in
their database session. New requests see committed changes without restarting
the backend or workers. Bulk planning reuses one settings snapshot for the entire
selection; OTP reads once for each code delivery and closes that read transaction
before contacting Meta. No template override is cached across processes or requests.

Preview and queue creation for broadcasts, document distribution, QR delivery,
and traveller welcomes use the effective names. Single and bulk retries also use
the effective name for current template formats. Already queued messages retain
their frozen template names and parameters; worker execution does not rewrite them.
Name changes do not clear sent/delivered history, grant opt-in, satisfy a welcome
prerequisite, or bypass Group Invite's existing destination deduplication.

The existing traveller-welcome preview token includes the effective name, so a
change between its preview and submission requires another review. Other existing
composers keep their current contract: queue creation resolves the current effective
name and freezes it in the new delivery; no new expected-template request field is
required. An already opened preview may therefore show the previous name until it
refreshes. The unused pure broadcast planner and legacy ENV-only compatibility
export remain isolated from live request paths.

The replacement must already be approved in Meta, in the displayed language, with
the same header and positional variables described for that slot. The application
does not fetch Meta template definitions or change template categories. Language
remains controlled by ENV: Group Invite and OTP have their own language variables;
the remaining slots use `WHATSAPP_TEMPLATE_LANGUAGE`.

Legacy headerless Welcome/Passport Link bulk snapshots keep their saved name when
no override is configured. An active image-template override requires a compatible
image before these old messages can be retried; preview can still show the saved
message so staff can attach one. Upgrading a legacy Welcome to an image template
uses its message BODY variable, dropping the obsolete extra support variable.
This protects existing saved text messages from malformed automatic conversion.

The existing OTP provider/credential startup validation is unchanged. Production
still needs a valid configured provider and ENV fallback to start; an override
changes the name used for subsequent actual OTP deliveries.
