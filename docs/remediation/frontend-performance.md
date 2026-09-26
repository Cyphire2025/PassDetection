# Frontend and duplicate-roster remediation

Date: 2026-09-26. Scope: PERF-02, web QUAL-01, UI-03 / QUAL-05, and family-size constants.
No mobile or coordinator Android shell sources, database migrations, stored rows, or stored files are changed by this work.

## Duplicate response and business behavior

`submission_view.py` retains the existing identity normalization, cautious fallback matching,
search expansion, member-level status filters, ordering and full selection order. It still
uses the shared membership tuple internally. Pagination now splits only blocks larger than
`page_size`. Ordinary duplicate sets remain together, including the existing 99 singles +
two-member duplicate-set boundary case. Every result row remains reachable through the
numbered pages; the detail and crop queries hydrate at most `page_size` rows (HTTP maximum 200).

The response adds `duplicate_metadata_version: 2` and `duplicate_clusters`. Each visible set
has its original `total_members`, filtered `matching_members`, current-page
`visible_member_ids`, and inclusive `first_page` / `last_page` range. These bounds apply to the
current filter, sort, search and page size. `cluster_boundaries_preserved` is false when any
matching set needs continuation pages. The web roster describes continued sets and retains
its existing Previous / Next controls. Search copy no longer implies that every set member
must be visible on the current page or survive the status filter.

The legacy per-row `duplicate_cluster_member_ids` field remains complete for sets of at most
20 members. Larger sets return an empty array and
`duplicate_cluster_member_ids_complete: false`. That flag means **omitted**, not empty
membership. Consumers must use normalized page metadata and continuation pages for larger
sets. `duplicate_cluster_size` remains the original set size in every row. Membership
serialization is now at most 20 IDs per row plus each visible duplicate ID once in metadata,
instead of repeating the complete arbitrary-size set for every row.

Rolling deployment: the existing web consumer uses `duplicate_cluster_size` for its badge,
numbered-page counts for navigation, and `ordered_submission_ids` /
`ordered_selection_snapshot` for bulk selection. It does not use per-row membership arrays
to build action requests, so it can consume the new response before the UI update. The new
web metadata fields are optional to tolerate an older server during rollout. Repository
inspection found no native mobile consumer of the dashboard submissions-view endpoint or
its duplicate metadata. This is not a claim about unknown external API clients.

The existing 1,500-record bulk-selection maximum and per-record extraction revision checks
remain in place. Selection and approval operate on source records, never on a representative
duplicate. The projection-to-hydration revision/update race continues to return HTTP 409.
No duplicate is merged, deleted, or silently excluded by this change.

Limits: full-group identity projection, filtering and expiry alerts remain linear in group
size. This is a bound on hydrated page rows and duplicate membership amplification, not a
fixed byte cap on the entire response or a solution for arbitrary-size group projection.
Page ranges are not immutable snapshots across independent requests; concurrent edits may
change the ordered result, as before. PERF-04 remains a separate scalability concern.

## Web quality and resilience

- Appearance settings and their control primitives moved into `appearance-settings.tsx`.
  The settings shell remains responsible for section navigation and preserving hidden drafts;
  template settings retain their visited-once behavior and user-keyed remount.
  The existing settings budget now passes at 167 lines / maximum function complexity 6
  (previously 336 / 8); no budget was relaxed.
- Manual PDF preview effects synchronize the anchor with its object URL directly. Cleanup
  removes the old URL and revokes its blob on file replacement and unmount, without a state
  update inside an effect. The review consent state and upload workflow are unchanged.
- The two web scanner callers share `getCoordinatorDeviceId`. Browser storage read/write
  denial or quota failure retains a stable in-memory correlation ID for the tab, instead of
  crashing a hotel scan or creating a different ID for every scan. The identifier is not an
  authorization credential. The API's server-side-rendering omission remains intact.
- Family member bounds now use `MIN_FAMILY_MEMBERS` and `MAX_FAMILY_MEMBERS` consistently in
  initialization, clamping, validation and number-input constraints. Values remain 2 and 20.

## Validation

Python 3.11.15 environment `backend/.venv311`, Ruff 0.16.0:

```text
python -m pytest tests/unit/application/test_submission_view.py \
  tests/unit/presentation/test_passport_view_page_hydration.py \
  tests/unit/presentation/test_passport_submission_view_schema.py \
  tests/unit/presentation/test_passport_bulk_staff_approval_route.py -q --no-cov
35 passed
```

New regressions cover 303 identical records with page sizes 1, 50, 100 and 200; no missing or
repeated rows; member-truthful status filtering after search expansion; 3/303/603-record
response hydration, crop query bounds, serialized payload below 250 KB per tested page,
and all selection revisions. A 303-record duplicate selection from page two is submitted
to the real bulk approval route with mocked persistence: all 303 source records advance
revision and produce 303 audit records. Existing revision-race and ordinary-cluster tests
also pass. Ruff passes for the changed backend modules and tests. The query route remains
within its existing complexity ratchet after extracting response shaping.

Frontend:

- `npm run lint`: pass, zero errors.
- `npx tsc --noEmit`: pass.
- `npm run maintainability:check`: pass, all 24 ratcheted modules; thresholds unchanged.
- Focused Vitest: 6 tests across settings persistence/reset, PDF blob replacement and
  StrictMode cleanup, existing device IDs, denied storage reads/writes, missing randomUUID,
  and storage recovery.
- Existing Node source-contract suites: 28 passport group/bulk-delete checks and 25 upload
  boundary/recovery checks pass. These are source-contract checks, not behavioral substitutes.
- `npx playwright test e2e/passport-governance.spec.ts --grep 'large duplicate sets' --workers=1`:
  **1 Chromium test passed**. It renders 303 duplicate records as 50 rows, navigates to page
  two, selects all 303 and verifies the exact bulk approval request revisions, visits the
  final three-row page, checks disabled Next, and navigates back. Uses isolated local Next
  dev server and mocked API responses; this is not full-stack or production-build proof.

No live deployment, production data access, native build or mobile test was performed for
this scoped remediation. Root release validation owns full-stack and full-suite gates.

## Final frontend regression and measured coverage

The complete Vitest run passed **118 files / 789 tests in 173.50 seconds** after
repairing stale fixtures, with no production contact-verification or WhatsApp
send-policy changes. The final commands `npm run lint`, `npm run type-check` and
`npm run maintainability:check` also pass; all 24 original module limits remain.
See [the compact full result](frontend-expanded-coverage-final.txt) and
[sanitized coverage evidence](frontend-coverage-evidence.json).

The coverage configuration now measures nine explicitly selected files, up from
five. Added targets are the manual PDF review dialog, settings shell, appearance
controls and device-ID helper. The **nine-file** result is **95.15% lines / 90.26%
branches / 93.42% functions / 93.89% statements**. It is not coverage of the whole
frontend. All four new targets have 100% line coverage; the original per-file
floors (74 statements, 50 branches, 75 functions, 75 lines) are unchanged.

New behavior tests exercise explicit approval consent, pending action/close
blocking, server errors, empty selections, both progress phases and clamping;
settings tests exercise actual preference persistence, authorization changes,
lazy template mounting, preservation across sections and reset on user change.
Existing object-URL cleanup and denied-storage tests remain. These behavior
assertions would fail if those workflows regressed; they are not source-string
checks added to inflate the measurement.

The first full run exposed six animation fixtures that skipped the existing
contact proof, two archive expectations predating shared-contact disclosures
and abort signals, and seven duplicate-invite expectations. Tests now complete
the actual mocked OTP request/verification UI before review, inspect the current
fieldset boundary, preserve all linked travellers behind a collapsed disclosure,
and explicitly reject resending delivered invites while retaining failed-retry
and saved-photo behavior. The production rules were checked against `HEAD` before
these assertions changed. No obsolete expectation was used to relax a business
or security invariant.

Unbounded default jsdom concurrency starved several five-second user workflows
on the busy many-core host, then allowed timed-out actions to spill into later
tests. The same upload/link suites passed with two workers. Vitest now uses that
bound for reproducible memory/CPU use; the five-second test timeout is unchanged.
The successful final full run uses this configuration. Historical failure logs
remain locally for diagnosis and are not final or committed qualification proof.
