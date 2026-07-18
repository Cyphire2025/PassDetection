# Approved WhatsApp Template Contract and Rollout

## Runtime configuration

The two active Meta template names are configured only through the backend settings loaded
from the repository-root `.env` file:

```dotenv
WHATSAPP_WELCOME_TEMPLATE_NAME=<exact approved welcome template name>
WHATSAPP_PASSPORT_LINK_TEMPLATE_NAME=<exact approved passport template name>
WHATSAPP_TEMPLATE_LANGUAGE=en_US
```

The template names are intentionally blank in code and `.env.example`. Enter the exact names
shown in WhatsApp Manager. The language code must also exactly match the language attached to
the approved templates; retain `en_US` only if that is the approved language.

Both the `backend` and `worker` services load the root `.env`. Restart both services after
changing this configuration.

## Approved component contracts

Both templates have the fixed header `Dear Delegates`. The API must not send a dynamic
`header` component. Neither template has a dynamic button component.

The welcome template has exactly two body parameters:

1. Editable trip statement. Its default is derived only from the saved group name:
   `This message is regarding your upcoming trip to "<group name>".`
2. Support contacts, one `Name: number` entry per line.

The fixed welcome body text is:

```text
Greetings from Global Connect Travels.

{{1}}

This is an automated notification sent individually to you. Replies to this WhatsApp message are not monitored and will not be treated as support requests.

For assistance, please contact:
{{2}}

Regards,
Team Global Connect Travels
```

The passport template has exactly four body parameters:

1. A secure-document introduction derived only from the saved group name.
2. The validated `http` or `https` passport upload URL.
3. Editable instructions, defaulting to:
   `Please fill in all required details, upload clear copies of the requested documents, and review everything carefully before submitting.`
4. Support contacts, one `Name: number` entry per line.

The fixed passport body text is:

```text
Greetings from Global Connect Travels.

{{1}}

{{2}}

{{3}}

The information and documents submitted through this link will be used to make your travel arrangements. Please ensure all details are accurate and complete, as incorrect or missing information may delay the application process. Kindly complete the form at your earliest convenience.

For assistance, please contact:
{{4}}

Regards,
Team Global Connect Travels
```

Recipient names and the legacy organising-company field are not Meta template parameters.

## Compatibility and data migration

No database migration is required for this template change. The existing
`whatsapp_broadcast_groups.organizing_company_name` column remains non-null for compatibility.
New clients may omit the field and the backend stores an empty string. Older clients may
continue to send and receive the field, but it is not used to render either approved template.

Existing message logs retain the exact template name selected when a batch was queued.
The per-recipient delivery ledger remains keyed by `(recipient_id, message_type)`, so a
recipient who already received a welcome or passport-link message remains suppressed even
after the configured Meta template name changes. Do not clear that ledger merely to test the
new templates; use a controlled test group and test recipient.

Old usage maps to the new configuration as follows:

| Existing message type | New runtime configuration | New body parameter count |
| --- | --- | ---: |
| `welcome` | `WHATSAPP_WELCOME_TEMPLATE_NAME` | 2 |
| `passport_link` | `WHATSAPP_PASSPORT_LINK_TEMPLATE_NAME` | 4 |

## Mixed-version queue warning

Do not deploy the API and worker at different template-contract versions while WhatsApp jobs
are queued or processing. A queued log snapshots the template name, but the worker builds the
parameter array with its currently deployed code. An old queued template name processed by a
new worker could therefore receive the new 2/4-parameter shape and be rejected by Meta.

Safe rollout:

1. Temporarily prevent staff from starting new WhatsApp sends.
2. Wait until every existing WhatsApp batch is terminal; reconcile any `processing` or
   `delivery_unknown` outcome before proceeding.
3. Set both approved template names and verify the approved language code in the root `.env`.
4. Deploy/restart the backend and WhatsApp worker from the same source revision.
5. Preview both messages and verify zero header parameters plus body counts of 2 and 4.
6. Send each template to one controlled recipient and confirm the provider/webhook lifecycle.
7. Re-enable staff sends.

Safe rollback:

1. Stop new sends and drain/reconcile the WhatsApp queue again.
2. Restore the previous backend and worker code together.
3. Restore the previous template names and matching language code together.
4. Restart both services and run a controlled preview/send.

Changing only the template names is not a valid rollback because the old and new templates
have different parameter contracts. There is no schema downgrade for this rollout.
