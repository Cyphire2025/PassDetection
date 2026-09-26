# FK-enforced backend fixture repair

The shared SQLite test fixture now enables and verifies foreign-key enforcement.
The first complete Python 3.11 sweep exposed invalid synthetic graphs as well as
stale assertions. This note records the application/domain and non-WhatsApp
presentation repair lane. It does not replace the final full-suite coverage gate.

## Integrity and authorization remain enforced

- `tests.persistence.persist_graph` flushes explicitly supplied parent tables before
  children. `persist_mobile_access_graph` creates the explicitly requested synthetic
  agency, company and group scope, then persists the supplied access and child rows.
  It is a test helper, not a production fallback or an automatic global fixture.
- Realtime, passenger propagation and identity tests now persist the scope and source
  records their foreign keys require. The savepoint tests commit fixture parents before
  opening the transaction under test; they still verify that hints are withheld until
  the outer commit and discarded on rollback.
- Cross-scope passenger-identity mutation tests assert database rejection. They no
  longer depend on silently accepting an impossible foreign-key state. Deleting a
  passenger verifies that its queued notification is absent from the database after
  the cascade, rather than inspecting a stale identity-map object.
- Email tests create actual agencies and owners before connections/messages. Their
  private-mailbox, stale-session, owner-only notification and revision assertions stay
  intact. FCM registration and mobile authorization tests insert actors before device
  sessions; ECR inserts the user before its security-state row.
- Public contact OTP fixtures create the real agency/group/submission parent graph
  alongside their deliberately mocked business repositories. The family-head fixture
  updates that existing submission, and cross-group tests create a real second group.
  The phone-schema test supplies the required email and verification ID and checks that
  a blank required phone is rejected while a blank optional family phone normalizes.
- Passport deletion fixtures create the referenced QR token before the delivery row.
  In-progress and delivery-unknown safety checks still block deletion; queued delivery
  cancellation and the passenger cascade remain checked.

No production FK or validation was disabled, no failing case was skipped, and no
coverage or complexity threshold was lowered.

## Stale assertions corrected against the audited source and documentation

The audited `HEAD` version of `traveller_welcome_preview.py` and
`docs/architecture/traveller-whatsapp-delivery.md` already make document delivery
independent of welcome receipts. Document-preview and actual HTTP tests now exercise
that policy, including all unconfirmed welcome states, submitted-contact precedence,
shared family phones and explicit invalid/cleared contact rejection. The separate QR,
passport-link and reminder welcome prerequisites remain unchanged.

Welcome tests explicitly configure the current welcome template name. A legacy text
welcome can be upgraded with an image, but already queued welcomes remain ineligible
for another send; the updated assertion checks both facts. Completed-public-contact
fixtures include `client_reviewed_at`, so they actually exercise the authoritative
contact path they claim to test.

The document route contract includes the existing manual verification endpoint and
checks its actual module owner. The verification test reflects the existing per-file
manual-review response for unsupported documents (`reject_common_unsupported_format=False`),
while continuing to assert that rejected files are not staged. The upload-abort mock
provides the existing scalar audit lookup rather than trying to await a bare MagicMock.

## Targeted evidence

| Evidence log | Result and scope |
| --- | --- |
| `application-fixtures-batch1.txt` | 47 passed: dashboard realtime, passenger propagation, identity reconciliation, realtime hints |
| `application-fixtures-batch2.txt` | 34 passed plus one outdated phone-fixture email failure, subsequently fixed and verified below |
| `infrastructure-fixtures-batch1.txt` | 50 passed: email AI runtime, notification feed, passport image library and phone domain tests; infrastructure ownership returned after this run |
| `presentation-fixtures-batch1.txt` | 44 passed plus one missing email-owner fixture, subsequently fixed and included below |
| `presentation-fixtures-batch2.txt` | 130 passed plus nine family-head duplicate-ID fixture failures, subsequently fixed below; includes ECR, email inbox, passport deletion, document staging and upload abort |
| `public-otp-fixture-verified.txt` | 56 passed after the family-head fixture repair |
| `presentation-fixtures-batch3.txt` | 54 passed plus two stale route/legacy-welcome assertions, subsequently fixed below |
| `presentation-fixture-final.txt` | 5 passed, including both remaining assertions and document route contracts |
| `backend-integration-fixtures-final.txt` | All 43 integration tests passed with `--no-cov`; repaired the coordinator lifecycle and retention-admin fixture graphs |

Ruff passes for the owned repaired helpers/tests. Separate type-only repairs renamed
optional recipient variables, guarded an optional broadcast UUID, and used the same
Pydantic response validation at the platform-settings boundary; they do not change
authorization or business rules. The final repository-wide mypy, coverage, migration,
browser and service gates are tracked by the release qualification owner.

The full coverage run exposed five additional integration setup failures. Coordinator
expiry fixtures now contain the actual coordinator users and attendance sessions
referenced by retained history, including a separate historical coordinator. The
retention-admin fixture inserts the agency and user before the group referencing
them. Both use the explicit dependency-ordered persistence helper; production code,
foreign-key constraints, business expectations and history-preservation assertions
remain unchanged. Ruff 0.16 passes on both integration files.
