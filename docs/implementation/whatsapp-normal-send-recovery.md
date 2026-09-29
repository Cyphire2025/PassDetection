# Normal WhatsApp send retry identity

Status: browser implementation locally qualified; joined backend/provider and
production qualification remain separate gates.

All four browser entry points—welcome, reminder, passport link and group
invitation—now supply the required `Idempotency-Key` to the existing group send
endpoint. Each uses the shared normal-send hook and controller. An ambiguous
response retains the exact request identity and payload. A selected image is
uploaded once and its resolved media ID is retained before any send request.
Bulk resend `requestId` remains its separate, existing protocol.

The first-party caller audit found those four hooks in the WhatsApp workspace
and their four API methods. Searching `mobile/src` for the method names,
`whatsapp.send`, and `/whatsapp/groups` found no mobile broadcast-send caller.
Mobile WhatsApp OTP, coordinator attendance and notification acknowledgement
protocols are independent and were not changed.

## Retained state and transitions

The controller writes a versioned session-storage record before sending. Its
storage key hashes the actor, agency, template mode and broadcast. Its value
contains only the opaque request key, SHA-256 reviewed-draft/file and final-body
fingerprints, resolved media ID, and pending/acknowledged/explicitly-superseded
state. It does not store plaintext message wording, recipient IDs, account IDs,
phone numbers, upload links, file names or file bytes. Recipient order is
canonicalized without mutating the caller's selection; support selections are
copied before asynchronous work begins.

- An uncertain request with the same reviewed draft reuses its key, final body
  and resolved media ID. Concurrent submission within the hook is coalesced.
- A same-tab page reload or hook remount can reconstruct the same request. If a
  file had been selected, reselecting the same named file with identical bytes
  and MIME type recovers the existing media ID without another upload.
- A changed or incompletely restored draft remains blocked while the earlier
  request is uncertain. The composer offers an explicit “I checked delivery
  history — start a separate send” choice. That choice queues nothing; staff
  must review the draft and press Send afterward. It does not cancel the first
  send, which may already have been queued or delivered.
- A known successful receipt acknowledges the intent. The next deliberate send
  receives a new key. A failed cache refresh does not turn a known receipt into
  a reported send failure. Failed acknowledgement persistence leaves the old
  request safely replayable instead of silently issuing a new key.
- No age-based expiry changes an uncertain key into a new request. Unreadable,
  unavailable or full session storage blocks before queue submission. Actor and
  agency are checked again before the final HTTP call. An upload finishing after
  account cleanup cannot recreate a cleared record or submit as the new actor.

The existing authentication storage contract clears the `passdetection` prefix
on logout, account/access-level changes and session cleanup. This implementation
uses that prefix. It therefore does not claim recovery after tab closure,
explicit storage clearing or authentication cleanup, or coordination between
independently opened tabs. A reconstructed draft cannot recover recipient IDs
that the UI no longer exposes without retaining private audience data; changed
audiences are blocked and delivery history remains the review path.

## Local evidence

- `frontend/features/whatsapp/hooks/use-whatsapp-send-idempotency.test.tsx`:
  42 real-hook/API tests cover four modes, response loss, media reuse,
  concurrent submit, explicit new sends, changed scope/content/audience/media,
  remount recovery, no expiry, no plaintext retention, storage failures and
  account changes during upload.
- Actual standard and invitation composer tests verify that the recovery choice
  does not itself call Send and requires a subsequent submission.
- Full WhatsApp React suite: 240 tests in 19 files pass. All 104 existing
  WhatsApp contract/utility tests pass. Global TypeScript, scoped ESLint and all
  40 frontend module budgets pass.
- `frontend/e2e/whatsapp-group-invite.spec.ts` includes an isolated HTTP fixture
  for lost response, actual page reload, identical photo reconstruction and
  equality of key/body with exactly one media upload. The actual browser recovery case passes, alongside desktop/mobile invitation
  cases and five Administration cases:8 total in34.9s. All effects use isolated
  API fixtures, not the real queue or provider.

The HTTP client already preserves the original Axios configuration during
authentication refresh and step-up retry; the request header therefore follows
the retained body through those paths. Normal-send mutations disable automatic
React Query retries. Server-side durable queueing, exact fingerprint conflicts,
live authority before replay and provider outcome handling belong to the backend
contract and require their own qualification evidence.
