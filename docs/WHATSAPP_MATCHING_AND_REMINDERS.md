# WhatsApp identification fields and reminder audiences

## Staff workflow

1. Import the contact workbook into a WhatsApp broadcast. Accepted and rejected
   contact rows retain their imported details. The broadcast also stores its
   selectable heading catalog, including headings whose cells are all blank.
2. In Create Upload Link, or the upload group's linked WhatsApp broadcasts panel,
   link the broadcast and choose its identification fields. The searchable
   selector supports one or more fields (up to 32 per linked broadcast).
3. Make sure the public upload form collects the information you selected. Custom
   questions/details are compared using their saved question labels; professional
   fields also support their configured display labels and standard aliases.
4. Open the reminder editor and select either **Send to everyone** or **Only people
   who haven't submitted**. When a broadcast has several active linked upload
   groups, choose which group's submission status should define that audience.
5. Review/edit the message and check the current eligible recipient count before
   sending. Every deliberate reminder still goes through this review step.

## Identification rules

Explicit selections use OR, not AND. With Name, Mobile, and Producer Code selected,
a matching producer code identifies the submission even if its name and mobile
differ from the spreadsheet. Unselected columns cannot independently identify it.

Matching is exact after field-appropriate normalization: phone formats, case,
whitespace, identifier separators, and common date formats are handled. Blank and
placeholder values are not identity evidence. Corrected submission fields take
precedence over stale extracted values. This is identity matching, not fuzzy text
search.

Evidence that points to competing roster recipients stays in **Needs review**
rather than being assigned to the wrong person. Staff should prefer specific identifiers over
common values such as a shared location. Linked copies of the same normalized
WhatsApp phone are treated as one logical recipient, preserving existing roster
behavior across broadcasts.

A selected field other than name or phone can identify several travellers under
one qualifier when its value belongs to just one logical roster recipient. It does
not need to occur in only one upload. For example, a qualifier and a travelling
family member may share a producer code while keeping their own names, phone
numbers, and passports. Both stay **Identified**. Values that point to different
roster recipients remain reviewable; matching candidates are never silently
discarded just because that recipient already has an identified upload.

**Duplicate uploads** is separate from sharing a qualifier. A repeated normalized
passport number with no conflicting known birth dates flags repeated passenger
uploads. Distinct passports or missing passport evidence do not create duplicate
flags merely because selected details match. On a row containing both duplicates
and other travellers, only the affected links carry a Duplicate badge. The
backwards-compatible API status remains `multiple_submissions`, with
`duplicate_submission_ids` identifying the affected uploads. No record is deleted
or merged by this classification.

Roster identification is separate from authorization to deliver private items.
Name, location, producer code, or other newly configurable evidence alone does not
authorize private-document/QR delivery or grant a mobile account the roster
phone's identity. Those paths retain phone, email, passport-number, or staff-code
evidence checks in addition to the current match and existing approval/opt-in
requirements. Selected strong evidence must itself be unique; a shared email
cannot authorize a private item merely because a separate location matched.

Existing links with no saved selection retain legacy smart matching. Editing an
unrelated link setting does not silently change their matching policy. New
explicit policies are stored per broadcast/upload-group link, not globally on the
broadcast.

## Correcting client-provided details

Authorized staff can use **Edit** on the passport detail page's **Client-provided
group details** card. The editor covers saved contact and professional fields,
airports, meal preferences, and custom question/detail answers using the saved
labels and configured options. Only changed values are sent; custom fields retain
their stable IDs and cannot have their labels rewritten through this endpoint.

Matching remains exact: `AIG12345` does not automatically equal `12345`. Staff can
correct such an entry deliberately. Saving refreshes the submission, roster
tracking, and reminder-related caches. The backend re-evaluates matches from the
corrected data; no re-upload or bulk backfill is required.

GET/PATCH `/api/v1/passports/{id}/client-details` are authorized and tenant scoped.
PATCH checks `expected_updated_at` under a row lock and rejects stale edits with
HTTP 409. Corrections, the changed-field audit, and mobile invalidation are saved
atomically. Passport documents, approval status, and verification revisions are
preserved; saving does not send messages or enqueue passport verification.

Corrections reuse the private-delivery identity-change guard. Queued private
document/QR deliveries in the affected group are cancelled transactionally and
need a fresh preview before resending. Processing or unknown-outcome private
deliveries block the correction with HTTP 409. Ordinary reminders and welcome
messages are not cancelled by this operation. A no-op correction does not change
timestamps, write an audit, or cancel queued private deliveries.

## Reminder safeguards

- The targeted audience contains only rows categorized as **Not submitted** by
  the same authoritative matching engine used for the roster. Identified,
  multiple-submission, and Needs review rows are excluded.
- The server matches the chosen upload group's full linked roster, then limits
  the result to the active recipients in the current WhatsApp broadcast.
- Audience selection is validated on both preview and Send. The server recomputes
  the audience when Send is requested; it does not trust a list of recipient IDs
  retained by the browser.
- Sending is asynchronous. The recipient list is a snapshot at queue time; a new
  submission after that point does not recall a reminder already queued.
- Existing opt-in, tenant authorization, removed/replaced-recipient checks,
  active-delivery duplicate prevention, and batch-scoped reminder receipt handling
  remain in place. Deliberate later reminders remain repeatable.
- A targeted send is refused if there is no eligible Not submitted audience, if
  no active group is linked, or if an ambiguous group choice has not been made.

## Upgrade and compatibility

Apply Alembic revision `0092_whatsapp_matching_fields` before serving this code.
It adds `whatsapp_broadcast_groups.imported_field_keys` and nullable
`client_group_whatsapp_broadcast_links.matching_field_keys`, and backfills old
broadcast heading catalogs from retained row data. Existing matching policies are
not rewritten. Entirely blank headings from historical imports cannot be
reconstructed if they were never retained; re-import the workbook to capture them.

Readiness and Compose schema expectations are updated to `0092_whatsapp_matching_fields`.
Update any explicit deployment override accordingly. Deploy backend and frontend
from the same revision, and recreate workers against the upgraded schema. This
implementation does not itself perform a production migration or send messages.

The database-backed regression in
`backend/tests/unit/presentation/test_whatsapp_matching_reminder_flow.py` exercises
real XLSX parsing, saved per-link policy, producer-code-only identification from
three submission sources, both reminder audiences, and a submission arriving
between preview and a later audience resolution.

The shared-qualifier, duplicate-classification, and client-details correction
changes need no additional database migration beyond revision 0092.

## Verification recorded for the original configurable-matching release

- Full backend regression run: 2,960 passed, 16 skipped, 131 subtests passed.
- Frontend unit tests: 343 passed across 67 files.
- Frontend Node contract tests: 712 passed.
- Optimized frontend production build, TypeScript, backend mypy, Ruff, changed
  frontend ESLint checks, and existing backend/frontend maintainability budgets
  passed without increasing their limits.
- Alembic topology, offline PostgreSQL migration SQL, Compose runtime contracts,
  and WhatsApp schema generation under Pydantic 2.7.4 and 2.13.4 were checked.

These are local automated checks, including database-backed tests; they are not
a live WhatsApp provider test or a production deployment. No real messages were
sent and no production database migration was performed.

## Verification recorded for shared qualifiers and client-details corrections

- Full backend regression run: 3,028 passed, 16 skipped, 131 subtests passed.
- Frontend unit tests: 361 passed across 70 files.
- Frontend Node contract tests: 713 passed.
- Three isolated Playwright scenarios passed: desktop and mobile corrections,
  plus cancellation and stale-save handling. Screenshots were visually reviewed;
  unexpected API calls and browser/React errors fail the tests.
- The database-backed matching/reminder regression covers one or two travellers
  sharing a producer code, three answer sources, and a manually corrected prefix.
- Optimized frontend production build, TypeScript, backend mypy (560 source
  files), changed-file Ruff/ESLint, whitespace checks, and existing backend/frontend
  maintainability budgets passed without increasing their limits.
- Route tests cover authorization, tenant isolation, cookie CSRF wiring, fresh
  locked reads, stale timestamps, private-delivery mutation guards, no-op edits,
  and rollback of correction/audit/mobile invalidation failures.

Browser tests use synthetic intercepted API responses, and database-backed tests
use isolated SQLite fixtures. Locking and concurrency contracts are tested; this
is not a live PostgreSQL contention test, production-data audit, deployment, or
WhatsApp provider send.

## Client-details save regression: PostgreSQL targeted matching

The PostgreSQL-only targeted matching loader used an invalid SQLAlchemy
`not_in_` method in its recipient and submission exclusion queries. Client-detail
corrections could therefore raise an `AttributeError` before commit while
reconciling GC App passenger identity. Both queries now use `not_in`.

SQLite takes the full-matcher fallback and did not expose this defect; the earlier
route tests also mocked the propagation helper. The added HTTP transaction test
uses real repositories, audit persistence, identity propagation, and response
building. It covers GC passenger access enabled/disabled and unlinked, legacy,
and explicitly configured broadcasts. Against PostgreSQL it also retains an
existing active QR token. Set `CLIENT_DETAILS_TEST_DATABASE_URL` to an isolated
local PostgreSQL database to run that variant; the fixture creates and removes
only its own unique test schema. Six scenarios were verified on PostgreSQL 18.3.
Additional SQL-construction regressions cover both exclusion queries across
multiple rounds while retaining tenant scope and cluster limits.

After the correction, the full backend suite passed: 3,036 tests, 16 skipped,
and 131 subtests. Strict mypy, scoped Ruff checks, and backend quality budgets
also passed. The isolated PostgreSQL test cluster was stopped after verification.

This is a backend query correction, with no schema or frontend change required.
Production causation must still be confirmed against the failing request's
server traceback; a browser HTTP 500 alone does not identify its exception.
