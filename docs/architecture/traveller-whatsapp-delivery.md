# Traveller WhatsApp welcome and document delivery

Private visas and flight tickets use the traveller destination resolver described
in [Document distribution lanes](document-distribution-lanes.md#whatsapp-destination-contract).
Submitted contacts take precedence over explicit imported group numbers. A
linked broadcast fallback requires an unambiguous, strong identity match.
Welcome messages are optional for document delivery.

## Operator workflow

1. Link an opted-in WhatsApp broadcast to the client group and confirm each
   traveller's submitted or explicitly imported WhatsApp number.
2. Upload, assign and save the PDFs in the correct document section.
3. Open the document delivery preview. Only travellers with assigned PDFs appear;
   travellers without PDFs are excluded, not counted as blocked recipients.
4. Review the destination and PDF for each selected row, then send. No prior
   welcome or welcome-delivery receipt is required. If a family deliberately
   shares one number, each person still receives their own assigned document.

The separate **Traveller welcomes (optional)** review loads a saved original
welcome from a linked broadcast.
If several broadcasts are linked, select the intended source. A source with a
usable welcome is selected automatically when no source is specified.
Review the numbers and message, then send the welcome to the remaining numbers.
A review can queue up to 1,500 distinct numbers; subsequent reviews expose the
remaining numbers. Shared numbers receive one welcome.
Sending a welcome never automatically sends a document or passport-link message.

Already welcomed numbers are excluded across all lists in the same agency.
Numbers with a pending or uncertain welcome are also excluded from another send,
without blocking document delivery. Refreshing the review fetches the current state;
it does not send anything. A failed welcome may be reviewed and retried.

For a media welcome, the original image reference is reused. The review supports
uploading a replacement and shows the selected welcome message before sending.

Missing or invalid traveller numbers are blocked with a correction instruction.
An invalid or cleared higher-priority contact cannot fall back to older data.
Correct the authoritative contact details and refresh the document preview before
sending to the corrected destination.

## Enforcement and durable state

`whatsapp_phone_welcomes` stores one prerequisite per agency and normalized phone.
`whatsapp_phone_welcome_attempts` is a separate durable outbox for traveller
welcomes. It does not add parents or other nominees to the imported company list.
Original broadcast logs also snapshot the exact normalized destination.

| Welcome state | Another welcome | QR, passport links and reminders |
| --- | --- | --- |
| No attempt / definitively failed | Review and send allowed | Blocked |
| Queued / processing / submitted / sent | Suppressed | Blocked |
| Delivery outcome unknown | Suppressed | Blocked |
| Delivered / read | Suppressed | Allowed, subject to normal permissions and document checks |

The API and provider workers enforce the prerequisite for QR delivery, passport
links, and reminders, including explicit and bulk resend paths. Documents and
group invites are exempt from that prerequisite.
Authentication OTP delivery keeps its separate authentication workflow.

An atomic phone claim prevents two operators, two lists, or repeated requests from
queuing duplicate welcomes. A preview fingerprint binds the group, source,
template parameters, and current passenger-to-phone mapping. Changed contact or
roster details require a new review. A mixed explicit document selection containing
blocked rows is rejected before publication.

Before calling the provider, workers revalidate tenant, active group, operational
roster, source opt-in and exact current destination. Document workers do not check
welcome state; QR workers retain that check. Rows are
locked across that final validation and provider call so a concurrent contact edit
cannot redirect an already approved send. Documents retain their passenger binding
even when several passengers explicitly share the same destination.

Provider receipts update the original frozen phone. Late receipts cannot confirm
a newly edited number. Delivery confirmation is monotonic and agency scoped;
another agency's history never unlocks a destination.

Stale welcome recovery runs through Celery Beat every five minutes with a
30-minute age threshold. Known-unsent queued attempts become retryable failures;
interrupted processing becomes an unknown outcome. Recovery does not send a
message. An unknown outcome requires reconciliation with provider evidence and
must not be blindly resent.

## Current document-only update

Deploy the backend, main worker and frontend together. This change has no
migration or backfill. It preserves the exact document-to-passenger mapping and
requires a fresh preview after assignments or destinations change. Accepted and
uncertain document deliveries remain protected against automatic duplicate sends.
This update was manually reviewed; tests and builds were not run at the user's
request. The historical evidence below does not validate the new exemption.

## Historical welcome-ledger migration and rollout

Migration `0093_phone_welcome` adds the ledger, traveller outbox, and immutable
destination snapshot. It conservatively adopts legacy original-welcome history
only when the current recipient state and non-null batch match the actual log.
Edited numbers with ambiguous historical logs are not marked welcomed. Existing
accepted-but-unconfirmed attempts suppress duplicate welcomes without satisfying
the prerequisite for message types that still require one.

This is a backend, worker, scheduler, and frontend release. Apply the migration
from the newly built backend image before activating the new code. Pause new
broadcasts and uploads and verify all seven Celery worker nodes have empty active,
reserved, and scheduled task lists before worker recreation. Activate all services
sharing the backend worker image, including `email-beat`, then backend and frontend.
Verify the image revision, migration head, Nginx configuration/reload, readiness,
and service health. Do not run a database downgrade to roll back application code:
the additive tables may be retained while restoring a compatible previous image.

The readiness expectation is `0093_phone_welcome`. Update an existing explicit
`EXPECTED_DATABASE_SCHEMA_REVISION` environment override along with `APP_REVISION`;
an older `.env` value takes precedence over the new source and Compose defaults.

The release helper keeps VPS commands short. From the exact pushed checkout, run
`python3 scripts/release_traveller_whatsapp.py prepare --revision <full-commit-sha>`.
After pausing new uploads and message sends, run
`python3 scripts/release_traveller_whatsapp.py activate --revision <full-commit-sha> --traffic-paused`.
Preparation builds and records verified image IDs without replacing running
containers. Activation checks all seven worker nodes both before and after the
migration, pins prepared images, and verifies workers, scheduler, web services,
Nginx and public readiness. A changed configuration or image requires preparation
again. An activation failure stops with its phase and does not automatically
downgrade the database or purge jobs. The helper stores a private `.env` backup and
release manifest under `tmp/traveller-whatsapp-release/`.

## Historical welcome-ledger verification evidence

The automated checks cover real authenticated HTTP review/send requests, every
document lane, existing welcomed qualifier numbers, separate parents' numbers,
explicit shared numbers, missing numbers, stale previews, and all unconfirmed
welcome states. PostgreSQL tests exercise atomic competing claims and actual
blocking of concurrent phone/roster edits, plus migration upgrade/downgrade and
legacy phone-history adoption.

The PostgreSQL HTTP-to-worker scenario sends two synthetic welcomes, submits signed
delivery receipts to the real webhook route, then runs the actual document worker
for visas and flight tickets. Only external WhatsApp/storage calls are substituted;
the application, authorization, database, receipt processing, and routing are real.
Desktop and mobile browser checks use fixture-backed API responses. These checks
do not send real messages or prove a production Meta account's template/media
availability; production activation and controlled operator testing remain separate.
