# Email Integrations

Email Integrations is an opt-in, server-side mailbox monitoring feature for
Gmail and Microsoft Outlook/Microsoft 365. It uses OAuth 2.0 authorization code
flow with PKCE and offline access, read-only mailbox scopes, incremental
provider cursors, tenant-scoped storage, deterministic relevance and matching,
and a staff review queue.

All feature flags default to `false`. Applying migration `0061` does not start
mailbox access by itself.

## Current provider boundary

- Gmail OAuth with incremental Gmail history synchronization
- Microsoft OAuth for organizational Microsoft 365 and personal
  Outlook/Hotmail accounts, using immutable Graph message IDs and per-Inbox
  delta synchronization
- Near-real-time bounded history polling every 15 seconds by default, with
  five-second due-work dispatch and duplicate-safe connection leases
- PDF visa and flight-ticket retrieval through the existing document
  distribution pipeline
- Deterministic exact passport-number evidence can support passenger matching;
  ambiguous names, groups, conflicts, and revisions require staff review
- Non-PDF attachments and provider links are recorded for review, not fetched
  automatically
- Passport images are never locally parsed by this feature. They remain in the
  existing Gemini-only passport upload workflow

## Google Cloud setup

Create a Google OAuth web application and register this exact backend callback:

```text
https://YOUR_DOMAIN/api/v1/email-integrations/oauth/gmail/callback
```

The configured URI must exactly match `GMAIL_OAUTH_REDIRECT_URI`. Configure the
OAuth consent screen for the read-only Gmail scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

Google classifies Gmail scopes separately from ordinary sign-in scopes. Complete
the consent-screen, verification, and security requirements that apply to the
organization before enabling production users.

## Microsoft Entra setup

Register a web application that supports **Accounts in any organizational
directory and personal Microsoft accounts**. Register this exact callback:

```text
https://YOUR_DOMAIN/api/v1/email-integrations/oauth/outlook/callback
```

The URI must exactly match `OUTLOOK_OAUTH_REDIRECT_URI`. Add these **delegated**
Microsoft Graph permissions:

```text
Mail.Read
User.Read
offline_access
openid
profile
```

Do not add `Mail.ReadWrite`, `Mail.Send`, or application permissions. Create a
client secret, copy the one-time **Value** (not its Secret ID), and store it only
in the deployment secret environment. `OUTLOOK_OAUTH_TENANT=common` enables
both business Microsoft 365 and personal Microsoft accounts. Some business
tenants may require their own administrator to approve user consent.

Track the Microsoft client-secret expiry in the operations calendar. Rotate it
before expiry by creating an overlapping secret, updating
`OUTLOOK_OAUTH_CLIENT_SECRET`, recreating the backend, email worker, and email
Beat services together, verifying readiness and one mailbox sync, and only then
deleting the previous secret. Never place either secret value in source control
or logs.

## Required configuration

Generate a dedicated Fernet key for email credentials. Do not reuse
`APP_SECRET_KEY`.

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set:

```dotenv
EMAIL_TOKEN_ENCRYPTION_KEY=<dedicated-fernet-key>
EMAIL_TOKEN_ENCRYPTION_KEY_VERSION=1
EMAIL_TOKEN_DECRYPTION_KEYS={}
EMAIL_OAUTH_FRONTEND_RETURN_URL=https://YOUR_DOMAIN/email-integrations
GMAIL_OAUTH_CLIENT_ID=<google-client-id>
GMAIL_OAUTH_CLIENT_SECRET=<google-client-secret>
GMAIL_OAUTH_REDIRECT_URI=https://YOUR_DOMAIN/api/v1/email-integrations/oauth/gmail/callback
OUTLOOK_OAUTH_CLIENT_ID=<microsoft-application-client-id>
OUTLOOK_OAUTH_CLIENT_SECRET=<microsoft-client-secret-value>
OUTLOOK_OAUTH_REDIRECT_URI=https://YOUR_DOMAIN/api/v1/email-integrations/oauth/outlook/callback
OUTLOOK_OAUTH_TENANT=common
EMAIL_CONTENT_RETENTION_DAYS=30
EMAIL_STORAGE_ORPHAN_GRACE_HOURS=24
```

ClamAV is optional defense-in-depth for email PDFs. When it is disabled, email
PDFs still undergo strict byte-size, extension, MIME, PDF-signature,
encryption, readable-structure, and page-count validation before duplicate
detection, classification, matching, and review. To use ClamAV,
`MALWARE_SCANNER_HOST` must resolve and port `3310` must be reachable from both
the `backend` and `email-worker` containers:

```dotenv
MALWARE_SCANNER_ENABLED=true
MALWARE_SCANNER_HOST=<clamav-host>
MALWARE_SCANNER_PORT=3310
MALWARE_SCANNER_TIMEOUT_SECONDS=2.0
```

If malware scanning is explicitly enabled, the email PDF boundary fails closed
when that scanner is unavailable or rejects a file.

### Encryption-key rotation

Rotate without downtime by keeping the prior version in the decryption keyring
while making a new version active on every backend, worker, and Beat process:

```dotenv
EMAIL_TOKEN_ENCRYPTION_KEY=<new-fernet-key>
EMAIL_TOKEN_ENCRYPTION_KEY_VERSION=2
EMAIL_TOKEN_DECRYPTION_KEYS={"1":"<prior-fernet-key>"}
```

Active connections are re-encrypted with version `2` on their next claimed
sync. OAuth states created before the rollout can also be completed while the
prior key remains in the keyring. Keep each prior key until no token-bearing
connection uses that version and the OAuth-state TTL has elapsed. Paused
connections must be resumed once or reconnected before removing their old key.
Never reuse a version number for different key material.

## Safe rollout

1. Deploy the code and apply `alembic upgrade head`.
2. Configure OAuth and encryption while all email capability flags remain
   disabled. Optionally configure the external malware scanner.
3. Start exactly one `email-beat` service and one or more `email-worker`
   services.
4. Enable connections without monitoring:

   ```dotenv
   EMAIL_INTEGRATIONS_ENABLED=true
   EMAIL_SYNC_ENABLED=false
   EMAIL_ATTACHMENT_PROCESSING_ENABLED=false
   EMAIL_LINK_RETRIEVAL_ENABLED=false
   EMAIL_AUTO_ACTIONS_ENABLED=false
   ```

   After this and every later email configuration or flag change, recreate all
   three configuration consumers together:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d \
     --force-recreate backend email-worker email-beat
   ```

   If the email worker is scaled, append `--scale email-worker=<replica-count>`
   so the coordinated recreation preserves the intended worker count. Keep
   `email-beat` at exactly one replica.

5. Connect a test mailbox and verify the account identity and revoke flow.
6. Enable synchronization, then PDF processing, while leaving automatic
   actions off:

   ```dotenv
   EMAIL_SYNC_ENABLED=true
   EMAIL_SYNC_INTERVAL_SECONDS=15
   EMAIL_ATTACHMENT_PROCESSING_ENABLED=true
   EMAIL_AUTO_ACTIONS_ENABLED=false
   ```

   Gmail history and Microsoft Graph delta synchronization are polled rather
   than using provider push subscriptions. With the default dispatcher
   cadence, a healthy connection normally discovers new mail within about
   15–20 seconds while retaining the existing lease and idempotency controls.

7. Review activity, failures, duplicate detection, and review decisions before
   enabling exact-match automatic actions:

   ```dotenv
   EMAIL_AUTO_ACTIONS_ENABLED=true
   ```

`EMAIL_LINK_RETRIEVAL_ENABLED` should remain `false` in this provider release.
Links are intentionally review-only until a separate allowlisted, SSRF-safe
retrieval service is introduced.

## Rollback

Set all `EMAIL_*_ENABLED` flags to `false`, then recreate the backend, email
worker, and email Beat services together with the command above. This stops new
authorization, polling, retrieval, and automatic actions without deleting
connections, audit history, reviews, or canonical documents. Do not downgrade
migration `0061` as an operational rollback.

The daily retention schedule is independent of the capability flags and
continues during an operational rollback. It still scrubs expired body excerpts
and completed email-only staging objects according to
`EMAIL_CONTENT_RETENTION_DAYS`; this does not remove canonical documents already
admitted to the document distribution workflow.

Administrators can disconnect a mailbox from the Connections screen. Gmail
credentials are cleared after Google revocation succeeds or the provider
confirms that the credential is already invalid. Microsoft identity does not
offer an app-scoped token-revocation endpoint: Outlook disconnect atomically
blocks synchronization and deletes the application's encrypted local
credentials. The mailbox owner may additionally remove the app from Microsoft
Account privacy permissions or My Apps to invalidate Microsoft-side consent.
A transient Gmail revocation failure leaves the connection blocked with a
retryable Disconnect action.

## Operational notes

- Run exactly one Beat scheduler. Connection leases and generation checks still
  protect against duplicate worker delivery.
- Links are never relevance evidence by themselves. A link-only message enters
  review only when its envelope or text matches an active group/roster value
  such as a group token/name, passport number, passenger email, phone, or a
  unique passenger name. Legacy unrelated link-only reviews are cancelled by
  migration `0064_document_resends`.
- Recognized attachments are inspected in the bounded PDF pipeline, but an
  artifact with no active-group or passenger evidence is ignored instead of
  creating review noise. Ambiguous or conflicting roster evidence remains a
  human review item.
- Every accepted email document is copied into canonical document-distribution
  storage and its batch is marked saved in the same database transaction.
  Later email or dashboard uploads append new ledger rows; only the explicit
  document removal action deletes an assignment.
- WhatsApp delivery is idempotent per saved document. A prior successful or
  uncertain send is excluded from normal sending. Staff must choose Resend
  explicitly, which creates a new durable delivery attempt while preserving the
  earlier attempt for audit and tracking.
- The Activity screen exposes sanitized message, artifact, review, and failure
  state. Raw provider payloads, HTML, OAuth codes, access tokens, refresh tokens,
  and full signed URLs are not retained or returned by the API.
- A daily retention task scrubs stored body excerpts and removes completed
  email-only staging objects after `EMAIL_CONTENT_RETENTION_DAYS`. Canonical
  documents already admitted to the document distribution workflow are not
  removed by this cleanup. The same task reconciles email-owned storage
  namespaces and deletes only objects older than
  `EMAIL_STORAGE_ORPHAN_GRACE_HOURS` that have no durable artifact or document
  row; this safely resolves worker death and uncertain commit outcomes.
- OAuth state is single-use and short-lived. The callback returns only the fixed
  `email_oauth` status values expected by the frontend.
- Pausing or disconnecting a mailbox increments its synchronization generation,
  invalidating in-flight workers before they can persist additional changes.
- A stale Gmail history or Microsoft Graph delta cursor triggers a bounded
  lookback rescan. Message and artifact uniqueness constraints make the replay
  idempotent.
