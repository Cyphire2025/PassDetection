# WhatsApp broadcast group invites

An active broadcast's actions menu includes **Send group invite**. The text-only
composer lets staff edit the invitation, paste an official
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

The ordered BODY parameters are `message_content` and `group_invite_link`. There is
no header, image, footer, or button component. The invitation paragraph has the
same 600-character editing limit as the other broadcast composers. Meta must have
approved and enabled the matching template before real sends can succeed.

Configuration defaults:

```dotenv
WHATSAPP_GROUP_INVITE_TEMPLATE_NAME=whatsapp_group_invite_v1
WHATSAPP_GROUP_INVITE_TEMPLATE_LANGUAGE=en
```

The invite language is independent of `WHATSAPP_TEMPLATE_LANGUAGE`, so existing
templates may continue using `en_US`. Migration
`0103_whatsapp_template_language` adds nullable language snapshots to
`whatsapp_message_logs`. Apply it before starting the new backend and workers.
New invites retain their language with their saved text and positional parameters;
individual and bulk resends preserve that language. Existing null snapshots use
their message type's configured language.

Invites reuse the broadcast queue, per-recipient delivery state, receipt handling,
opt-in checks, and confirmed-welcome prerequisite. Successful initial invites are
skipped on another initial send; staff can explicitly resend saved invites from
the recipient list. In-progress and uncertain deliveries retain their existing
blocking rules. Bulk resend request identities include edited invitation links.

Archived broadcasts start collapsed. Their count remains visible, expansion
survives searches, and collapsing closes any open row menu. They remain read-only
until restored.

The browser tests intercept all API requests and never contact WhatsApp. Backend
tests verify the two-parameter transport, saved snapshots, English language,
link validation, initial sends, retries, and archive/welcome restrictions.
