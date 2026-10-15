# Company and traveller UI contracts

`api` owns typed transport; hooks own tenant-scoped cache keys and invalidation;
components own short-lived display/edit state. Company identity and authorisation
are enforced by the backend. A selected company reference is retained in the
picker even when inactive or outside the current lookup page. New selections
come only from the active, authorised lookup endpoint.

## Interactive budgets

- Company picker: 20 results per request, 250 ms search debounce, cursor
  pagination. Directory, groups, travellers and expanded trip history: 25 rows
  per page. Changing pages replaces rows instead of accumulating the dataset.
- Rendering and page-local operations are O(p), with O(p) retained result memory,
  where p is the bounded page size. One traveller history can be expanded at a
  time; history is not fetched for every list row.
- Search requests consume the query AbortSignal. Stale search results are hidden
  while the debounce settles. Query keys include agency, company and query scope.
  Identity queries use `staleTime: 0` and `gcTime: 0`; they are not persisted.
- Company mutations invalidate company, GC App and group-link caches as
  appropriate. Revision checks protect concurrent company, assignment, policy
  and group configuration edits. Errors retain unsaved inputs.
- Reuse policy and per-group settings load only after the user opens them. The
  group table does not issue per-row configuration requests.
- Accepted enrollment sources and operational review tasks are 25-row cursor
  pages. Sources are loaded only after an enabled policy is checked. A source
  needs explicit document-context review and a recorded permission reference;
  a verified replacement candidate also requires an association acknowledgement.
- The masked passport inventory loads only from an expanded traveller's explicit
  Manage passports action (server cap 50). A lost/cancelled/compromised declaration
  binds both profile and passport revisions and never requests document images.
- Group matching preview is dynamically loaded on request and shows one 25-case
  cursor page. Queue requests retain their idempotency key after uncertain
  responses; operators refresh progress explicitly rather than polling forever.
  Decisions require an explicit proposed/known UUID selection, reviewed evidence,
  reason, case revision and group revision. A saved decision establishes roster
  inclusion only; the UI does not describe it as consent or completed collection.
- Returning verification is a separate dynamically imported module. Proof and
  historical review state stay in memory. Claim/grant secrets are httpOnly
  cookies; the UI does not create bearer tokens or store passport fields.
- Document images are requested only after an explicit preview action. One
  authorised blob is mounted at a time, with an allowed MIME type and a 20 MiB
  encoded-size ceiling matching the API. Closing/replacing a preview aborts the
  request and releases its object URL. Decoded image memory still depends on
  source dimensions; a browser pixel-memory capacity claim has not been tested.
- Mutating returning steps have a single in-flight request and AbortSignal.
  Completion retains one idempotency key across transient retries. Current
  requirements come from the authenticated history response. Only server-approved
  unchanged answers from the same current trip are seeded; earlier trips cannot
  satisfy current requirements. A revision conflict requires an updated review.
- Accepted passport selection is bounded by the server (20), changes only this
  trip, and requires renewed image/field confirmation. Each submission forwards
  the opaque review digest for the exact documents and requirements shown.
- Explicit updated-document collection keeps its selected-person binding only in
  memory and links the actual saved submission using the existing upload-session
  proof plus the history grant. A generic fresh/family path clears that binding.
  Reload/expired grants can leave the new upload saved without an association;
  the UI explains the pending/manual review path and never promotes it itself.
- Large shared-number workbook imports retain the original `File` in the open
  dialog when the 500-row rejection preview is truncated. Recovery is allowed
  only when the server's full rejection summary confirms duplicate-phone rows
  exclusively; incomplete or invalid summaries fail before changing the list.
  At most 10 original files are retained. The API additionally bounds their
  combined source entries at 2,000. Original files recover source records only;
  the operator's edited delivery contacts remain authoritative. File references
  are cleared on reset/unmount and are never persisted in browser storage.

## Verified scope

Local Chromium tests cover 320 px and 1440 px viewports, all three returning
proof sequences, lazy document fetching, current trip answers, failure/fresh
fallback, company directory operations, role denial, cursor selection beyond
the former fixed company cap, lazy history, and reuse setup. Unit tests cover
request cancellation, revision-safe reassignment, completion retries,
new-contact OTP confirmation, same-trip answer preservation, alternate passport
selection, explicit enrollment/renewal, passport blocking, bounded matching
review with role/revision denial, and operational review
resolution. Browser API responses and document bytes in these
tests are synthetic and loopback-isolated.

Large-import tests exercise a 700-person fixture with one delivery contact and
699 shared-number source rows, of which 500 are returned in the preview. Hook
and transport checks cover retention, edits, stale requests, invalid summaries,
reset and file-count bounds. Two 390 px browser flows verify that create/add
submit the original bytes in `duplicate_source_files` while retaining edited
delivery JSON. Browser fixture bytes are not a parsed production workbook;
workbook recovery and deduplication require the separate backend tests.

These are UI correctness and bounded-request checks. They do not measure
millions of records, production API latency, WhatsApp delivery, storage speed,
or sustained concurrency. Database and service capacity require separate
representative load evidence. Browser test wall time is not an end-user latency
SLO or backend capacity result.
