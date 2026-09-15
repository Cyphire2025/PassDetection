# Passport collection, WhatsApp receipts and GC App reliability release

## Changes included

- Withdrawing an announcement, itinerary or common document removes that content. Historical withdrawal events are translated when the server returns them, preserving their sequence numbers. Actual trip/role access removal remains effective.
- The updated mobile client rejects unsupported removal events with a recoverable sync error and preserves saved trip data and the committed cursor.
- Signed WhatsApp confirmations enter a durable database inbox before acknowledgment. Immutable provider-message bindings identify the original sending attempt across broadcasts, traveller welcomes, documents, QR messages and OTPs. The scheduled reconciler updates delivery evidence without sending again.
- Public collection, family contacts, staff contact corrections and WhatsApp preparation share the same backend phone-number rules. Existing records remain readable; formatting-only replay differences are accepted.
- A current, recorded AI service failure permits manual submission of the required uploaded passport documents for staff review. This path remains **Needs review** until an authorized staff approval. Wrong documents and unreadable images still require correction.
- Normal staff cannot archive groups or delete passport submissions. Managers retain their existing scoped archive/passport-delete permissions. Permanent whole-group deletion remains restricted to administrator roles.
- Deliberately closed collection links say **This link is closed.** A connection failure preserves the saved upload. Missing draft recovery checks the group link before replacing an unusable recovery reference.
- Family instructions explain that each traveller's entered WhatsApp number is their destination. The family head's number is not silently substituted.
- Announcement management includes separate recipient/device notification evidence. App settings show permission and registration state, with retry or system-settings actions.
- The coordinator app accepts the server's existing relationship-label limit of 100 characters. The reviewed mobile API snapshot includes the already-implemented journey destination endpoint; this corrects existing contract drift without adding another feature.

## Release order

Deploy the compatible server change before relying on the updated mobile build. The single server release includes the historical-event correction and the additive `0094_whatsapp_receipt_inbox` migration. Already-installed clients benefit from the server translation.

Only use the full, verified pushed revision supplied in the implementation handoff. The helper rejects a different checkout, missing preparation evidence, changed image tags or unexpected schema.

### 1. Prepare while the current site is running

```bash
cd /opt/GlobalConnectsDashboard || exit 1
git pull --ff-only origin main &&
python3 scripts/release_reliability.py prepare --revision FULL_VERIFIED_COMMIT_SHA
```

Preparation preserves the previous running application images under recovery tags and builds/pins the new images. It does not activate the new services.

### 2. Activate in a quiet window

Pause new uploads and deliberate message sends before running this block. If the helper reports busy workers or another failed gate, stop and inspect the result before retrying.

```bash
cd /opt/GlobalConnectsDashboard || exit 1
python3 scripts/release_reliability.py activate --revision FULL_VERIFIED_COMMIT_SHA --traffic-paused
```

Activation verifies all seven workers, saves a private PostgreSQL custom-format backup, fully decodes the archive to verify readability, verifies its checksum after copying, applies migration 0094, activates the workers/Beat/backend/frontend, and checks revisions, Nginx and public health. The success marker is:

```text
RELEASE VERIFIED: FULL_VERIFIED_COMMIT_SHA; schema 0094_whatsapp_receipt_inbox; backend, frontend, seven workers and beat.
```

Keep the private evidence under `tmp/reliability-release/` and the tagged previous images. The backup contains private company data. The helper performs no automatic rollback, downgrade, queue purge or Git reset. A code rollback must retain the historical announcement compatibility correction. Do not downgrade 0094 to roll back application code: that discards the receipt history.

## Read-only notification diagnosis after activation

```bash
cd /opt/GlobalConnectsDashboard || exit 1
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
  python scripts/diagnose_mobile_notifications.py
```

Optional `--group-id UUID` and `--announcement-id UUID` narrow the latest-ten announcement list. The output includes deployed revision/schema, configuration flags, aggregate registration inventory and announcement recipient/device counts. It excludes traveller names, phone numbers, announcement text, device tokens and credentials. It runs inside a PostgreSQL read-only transaction.

The registration inventory is server-wide and does not prove that a particular traveller has an authorized device. The diagnostic does not publish content, send notifications, enable a provider, change account access or repair a token by itself.

Check scheduled execution separately:

```bash
docker logs --since 15m passdetection-email-beat 2>&1 \
  | grep -E 'reconcile-whatsapp-receipts|dispatch-mobile-push-notifications|reconcile-mobile-push-receipts'
```

A missing matching log line is inconclusive if Beat logging is filtered. Confirm worker-side task completion and the dashboard's refreshed evidence. Do not treat provider receipt acceptance as proof of a visible phone banner.

## Recover the affected GC App account

1. Verify the server release marker and schema first.
2. Open the app with the existing account and refresh its authorized trip list.
3. Open the affected trip and let synchronization finish. Historical content withdrawals should now be returned as content deletion and the cursor should advance.
4. Close and reopen the app, then confirm the trip remains accessible.
5. Sign in again only if the existing session requires it. Do not default to reinstalling, clearing app data, changing the phone number or granting additional access.

Server data can be fetched again. Previously erased local work that never reached the server cannot be assumed recoverable.

## Notification evidence to collect

Use a dedicated test group/account for a publish A → unpublish A → publish B check. Confirm the trip remains accessible and only B is visible. Record the installed app build and role, notification permission/channel state, and registration result. In announcement management, expand **Notification delivery status** and check recipient and device counts separately.

- Disabled provider: validate project/build credentials before enabling it.
- No registered device: use the app's retry/settings action and recheck registration.
- Queued or awaiting receipt: verify background dispatch and receipt collection.
- Provider rejection: use the bounded recorded error code to identify the failing stage.
- Provider confirmation without a banner: inspect device presentation settings and foreground/background behavior.

Emergency priority does not override device notification permissions. Local emulator launch/sync tests and mocked provider tests do not establish visible delivery on the production phone.

## Receipt operation and limits

Reconciliation runs every 60 seconds with at most 200 receipts per sweep. Temporary errors back off up to one hour. Pending receipts older than 24 hours generate an attention signal. Pending receipts expire after 30 days and retain an additional seven-day diagnostic record; completed receipts have 30-day retention. Current-source and pending-receipt bindings are preserved.

Observe `whatsapp.receipts.pending`, `whatsapp.receipts.oldest_pending_seconds`, `whatsapp.receipts.retry_failures`, `whatsapp.receipts.last_success_timestamp` and the reconciliation logs. The last-success timestamp describes a completed sweep; retry counts still need checking.

Only confirmed `delivered` or `read` welcomes unlock dependent delivery. Successful welcomes remain one-time; reviewed reminders remain deliberately repeatable. A provider acceptance followed by an immediate process death before any message reference is saved can still leave an uncertain outcome. The system preserves uncertainty and does not automatically send again.

## Operational acceptance still needed on the VPS

- Exact release revision, schema and service-health evidence.
- Existing affected account's trip restored and retained after reopening the app.
- One deliberate WhatsApp test with actual provider delivery evidence and no duplicate send.
- Notification chain evidence for the affected build/account, including a visible device notification where supported.

The local verification report records automated tests, PostgreSQL transaction/rehearsal results and emulator evidence separately. Internal-platform and enterprise-readiness ratings also require sustained use, measured workload performance and operational recovery evidence.
