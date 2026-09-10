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

Conflicting or shared identity evidence stays in **Needs review** rather than
being assigned to the wrong person. Staff should prefer specific identifiers over
common values such as a shared location. Linked copies of the same normalized
WhatsApp phone are treated as one logical recipient, preserving existing roster
behavior across broadcasts.

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

## Verification recorded for this change

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
