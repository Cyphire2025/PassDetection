# Passport workflow state machine

The platform has three related state machines. They are intentionally separate:
the traveller-facing submission state, the interactive extraction job, and the
post-submission verification job. Queue activity must not be encoded by inventing
additional submission statuses.

## Submission state

| Current state | Actor or event | Next state | Repeat and concurrency rule |
|---|---|---|---|
| `pending_extraction` | Durable upload commit | `extracting` | A unique upload idempotency key returns the existing submission and active revision. |
| `extracting` | Extraction finishes with usable fields | `ready_for_client_review` | Apply only when the expected extraction revision still matches. |
| `extracting` | Extraction cannot produce usable fields | `failed` | Images remain durable; a retry creates/claims only one active job for the revision. |
| `ready_for_client_review` | Traveller submits reviewed fields | `submitted` | The row is locked; a successful replay must not create another submission or verification revision. |
| `submitted` | Deterministic verification matches | `ai_approved` | Apply only to the expected verification revision and only while still submitted. |
| `submitted` | A meaningful difference, unreadable field, or low confidence remains | `needs_review` | Gemini supplies evidence; application code owns the final comparison. |
| `needs_review` | Authorised staff approval | `staff_approved` | Row lock, same-value replay is a no-op success, different replay is a conflict. |
| `needs_review` | Authorised staff correction without approval | `needs_review` | Increment extraction revision and invalidate stale AI evidence. |
| `ai_approved` or `staff_approved` | Delayed extraction or verification result | unchanged | Revision/status compare-and-set rejects stale completion. |

Legacy values remain readable for existing rows, but new code should emit the
canonical states above. `ai_approved` and `staff_approved` are operationally
approved terminal states. `failed` is terminal for the current extraction
revision, not for the durable uploaded images.

## Interactive extraction job

`queued -> running -> succeeded`

Retryable failures return `running -> queued` while `attempts < max_attempts`.
Terminal failures use `failed` or `dead_letter`; explicit cancellation uses
`cancelled`. A database row lock claims the job, and the tuple of submission and
extraction revision prevents two active jobs for the same work.

The durable job row is the outbox. A missing or stale broker delivery can be
redelivered, but only one worker may claim the revision.
If a recovery delivery arrives after its Redis lease expired but before the
database `running` claim becomes stale, it is deferred through a fresh broker
delivery without consuming a processing/provider attempt. A replacement
publish failure rejects and requeues the current message, preventing a fresh
`running` row from being stranded by retry exhaustion.

## Post-submission verification job

`queued -> running -> succeeded`

Provider retries happen only inside one bounded verification operation. When
those provider attempts are exhausted, the job succeeds with a conservative
review-required result instead of replaying a second provider retry chain.
Only worker crashes or other pre-decision infrastructure failures return the
durable job to `queued` within `PROCESSING_JOB_MAX_ATTEMPTS`; terminal delivery
failure persists review-required state. The unique submission/revision pair and
row-locked claim suppress duplicate Gemini calls. A verification completion may
update a submission only when both the expected verification revision and
`submitted` state still match.

## Priority invariant

Interactive extraction has strict priority over new post-submission verification
calls. A distributed coordinator, not process-local state, must track extraction
work that is waiting, being dispatched, or active. No verification may acquire a
new admission lease until those extraction sets are empty and the configured
quiet period has elapsed. Verification already sent upstream may finish; every
newly available slot goes to extraction.

## Failure ownership

- Browser/network failure before a durable upload response: retry with the same
  upload idempotency key.
- Queue or worker failure after persistence: keep polling the durable job; the
  outbox/watchdog may redeliver it.
- Gemini transient failure: bounded retry with the same job and revision.
- Staff approval response lost after commit: replaying identical values succeeds
  without another transition or audit side effect.
- Stale browser tab or delayed worker: reject by revision/status conflict; never
  overwrite newer traveller or staff data.

All transition audits and diagnostics must use submission/job identifiers and
bounded reason codes. They must not log passport images, full passport numbers,
contact details, raw prompts, credentials, or bearer upload-link tokens.
