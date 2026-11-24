# Dashboard GC backend checkpoint

The GC administration/content batch is frozen at the source hashes in
`gc-admin-backend-verification.json`. The physical review ledger contains 37
current full reads and three explicit partial supports. This does not close the
repository-wide audit or qualify a live deployment.

The original 1,995-line account/group and 1,715-line content entry points are now
227-line and 206-line compatibility facades. Twenty-one focused resource/support
owners contain their actual work; the largest is 396 lines. All 42 handlers retain
their names, argument/return declarations, dependency decorators and ordering.
Legacy imports resolve to the same registered function objects. Test monkeypatch
paths follow the real owner; no runtime circular lookup or global proxy was added.

The extraction proof compares against source **after** the earlier eight boundary
regressions were fixed. It is not equivalence with the original checkout. Of the
76 complete declarations in that checkpoint, 73 remain AST-identical. The three
later deliberate changes tighten the joined manager tenant predicate and fix two
retained-assignment transitions.

Confirmed defects fixed in this batch:

- Manager creation and re-invitation could expose their one-time activation token
  before the database commit. Four real ASGI send/independent durable-read cases
  failed before the explicit commits; both success/failure flows now pass.
- Cancelled document PUTs could finish after compensation deleted the object.
  Two Event-controlled actual native-client cases failed before reuse of the
  existing shield/drain helper. Repeated cancellation is covered.
- Rollback failure/cancellation could skip cleanup of a staged private object.
  Two actual interruption regressions now prove the `finally` compensation path.
- A stale but valid-schema profile/user association could include a foreign
  tenant's manager name/email. One actual HTTP regression now checks the user
  agency predicate in the shared count/projection filters.
- Changing a manager's company left active/historical grants bound to the former
  organization, violating composite foreign keys. Grants are now atomically
  detached/revoked while preserving historical revocation dates and actors.
- Re-adding a detached historical assignment omitted its required organization.
  Reactivation now restores the validated current scope and clears former-scope
  privacy grants. Ordinary same-company reactivation retains existing flags.

The last two defects have genuine pre-fix FK-enabled HTTP failures. The additional
manager lifecycle and real PDF/private-object upload/order/replacement cases verify
ordinary behavior, stale revisions, unavailable document IDs, invalid PDF rejection,
tenant scope, unique immutable object keys, audits and journal effects.

Verification is recorded without relabeling historical failures:

- Original affected checkpoint: 183 passed, four test-owner retarget failures and
  one skip. After correcting those test-only ownership seams, a 25-case supplement
  passed. This is not reported as a new full-suite pass.
- Manager/document/native-cancellation supplement: 23 passed in 25.99 seconds.
  Two deeper retained-history actor assertions subsequently passed in 4.67 seconds.
- Coverage discarded the changed directory record before the first supplement and
  both changed manager records before the second; only exact-hash unchanged owner
  coverage was retained. New owner statement coverage is 76–100%; branch coverage
  is recorded separately in the JSON/XML and is not implied by statement coverage.
- Owned Ruff, four-entry/transitive mypy, architecture checks, unchanged complete
  API/mobile snapshots and 27 focused release/migration/inventory tests pass.
- Backend ratchets increased from 234 to 260 with 26 new owners and a tighter
  existing facade ceiling. Every other original module row, global floor and
  critical floor is unchanged. No global coverage qualification is claimed from
  a scoped report.

The shared storage cleanup helper has only an `Awaitable` result type annotation
correction; its entire runtime AST is unchanged. No model/schema, published
migration, HTTP payload, provider send or deployment identity was changed.

Pending supporting physical reads are explicit: `notification_service.py`, the
rest of `passport_whatsapp_matching_repository.py`, and the rest of
`minio_repository.py`. Whole-group identity reconciliation's discarded comparison
work and content reads after setup removal remain candidates requiring policy or
behavioral proof. No exploit or measured speedup is claimed for them. Real
PostgreSQL locking/concurrency, provider/object-storage services and VPS
qualification were not exercised.
