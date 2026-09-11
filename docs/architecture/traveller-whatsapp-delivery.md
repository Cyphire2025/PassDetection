# Traveller WhatsApp welcome and document delivery

The submitted traveller phone is the destination for private visas and flight
tickets. An employee or producer code can still identify the qualifying company
record, but it never redirects private documents to that record's phone number.

## Operator workflow

1. Import the company list and send the original welcome as usual. Link that
   opted-in WhatsApp broadcast to the client group.
2. Each traveller enters their WhatsApp number with their passport submission.
   If a family deliberately shares one number, enter that number for each person.
3. Open **Document Distribution** and the group's **Welcome new traveller
   numbers** review. It loads the saved original welcome from a linked broadcast.
   If several broadcasts are linked, select the intended source. A source with a
   usable welcome is selected automatically when no source is specified.
4. Review the numbers and message, then send the welcome to the remaining numbers.
   A review can queue up to 1,500 distinct numbers; subsequent reviews expose the
   remaining numbers. Shared numbers receive one welcome.
5. Once WhatsApp reports `delivered` or `read`, review and send the saved documents.
   Sending a welcome never automatically sends a document or passport-link message.

Already welcomed numbers are excluded across all lists in the same agency.
Numbers with a pending or uncertain welcome are also excluded from another send,
but remain blocked for documents. Refreshing the review fetches the current state;
it does not send anything. A failed welcome may be reviewed and retried.

For a media welcome, the original image reference is reused. If that image must
be replaced, the review supports uploading a replacement while preserving the
original template name and text. Legacy text templates retain their exact original
parameters and cannot be converted to a media template by adding an image.

Missing or invalid traveller numbers are blocked with a correction instruction.
There is no fallback to a qualifier number, family-head number, or imported match.
Correct the submitted contact details, refresh the review, welcome the new number
if needed, and send to the corrected destination.

## Enforcement and durable state

`whatsapp_phone_welcomes` stores one prerequisite per agency and normalized phone.
`whatsapp_phone_welcome_attempts` is a separate durable outbox for traveller
welcomes. It does not add parents or other nominees to the imported company list.
Original broadcast logs also snapshot the exact normalized destination.

| Welcome state | Another welcome | Later WhatsApp messages |
| --- | --- | --- |
| No attempt / definitively failed | Review and send allowed | Blocked |
| Queued / processing / submitted / sent | Suppressed | Blocked |
| Delivery outcome unknown | Suppressed | Blocked |
| Delivered / read | Suppressed | Allowed, subject to normal permissions and document checks |

The API and provider workers enforce the prerequisite for private documents, QR
delivery, passport links, and reminders, including explicit and bulk resend paths.
Authentication OTP delivery keeps its separate authentication workflow.

An atomic phone claim prevents two operators, two lists, or repeated requests from
queuing duplicate welcomes. A preview fingerprint binds the group, source,
template parameters, and current passenger-to-phone mapping. Changed contact or
roster details require a new review. A mixed explicit document selection containing
blocked rows is rejected before publication.

Before calling the provider, workers revalidate tenant, active group, operational
roster, source opt-in, exact submitted destination, and welcome state. Rows are
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

## Migration and rollout

Migration `0093_phone_welcome` adds the ledger, traveller outbox, and immutable
destination snapshot. It conservatively adopts legacy original-welcome history
only when the current recipient state and non-null batch match the actual log.
Edited numbers with ambiguous historical logs are not marked welcomed. Existing
accepted-but-unconfirmed attempts suppress duplicates without unlocking documents.

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

## Verification evidence

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
