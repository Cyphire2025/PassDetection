# Current WhatsApp dashboard review

This lane is in progress. Frozen source batches0–15 of35 have been physically read,
with additional send/recovery/serialization helpers read in full. The JSON progress
file lists remaining original files; passing tests do not close those source reads.
The large979-line activity tracker and456-line roster views have been fully read
and remain explicit architecture follow-ups.

## Reproduced findings and fixes

- Three actor-change regressions reproduced dispatch after a reviewed payload or
  image finished preparing under a different account. The reviewed-send identity
  now binds the starting actor, checks before/after asynchronous preparation and
  supplies that expected actor to the final authenticated adapter. The single-
  recipient resend captures its actor before uploading media. Existing opaque
  recovery records, payload fingerprints, consent and uncertain-send retry rules
  remain. No real provider sends were used.
- Repeated update submissions before a pending render created distinct request
  identities. A synchronous admission guard now admits one request; settled
  failures allow the existing exact-request retry. Preview polling stops after a
  failed query and mutations do not add implicit retries.
- Corrupt finite out-of-range local timestamps caused Date.toISOString to throw
  while rendering progress. Current records now reject invalid timestamp entries;
  the legacy record uses a valid current timestamp. Valid records and supported
  Date boundaries remain. This is local-state resilience, not an authorization
  bypass finding.
- Recipient page buttons were implicitly submitting the enclosing message form.
  The existing pager is now a reusable shared component with explicit non-submit
  buttons; its compatibility export remains. Busy and page-boundary behavior is
  preserved. The default dialog height also follows the dynamic mobile viewport.
- The contact editor rendered two inputs for every imported contact. It now mounts
  at most50editable rows, with global list indices for edits/removals and the full
  original list retained for saving. A120-contact regression verifies102maximum
  textboxes including the add controls, correct row51callbacks and access to the
  last row. No frame-rate or production latency claim follows from this DOM bound.
- Two identical imported-heading label functions now share one pure helper with
  the existing public re-export retained.
- The source-import conflict handler understood raw Axios failures but missed the
  API client's normalized409failure. It now refreshes the changed source and asks
  for renewed confirmation using the existing status parser. Both normalized/raw
  conflicts pass, and unrelated409responses retain their distinct behavior.
- Structured normalized404errors now stop missing-batch retries even when their
  domain code is not HTTP_404. Private update audiences stop interval requests after
  denial instead of repeatedly polling cached queued rows; explicit refresh still
  recovers. The regression observed five requests in the old polling window versus
  two with the corrected error handling.

## API architecture checkpoint

The actor-fixed809-line API is now a20-line compatibility facade with seven
focused transport/helper owners17–142lines and three DTO owners. All27public
methods and29DTO declarations remain. Exact AST proof covers26object methods,
four shared helper bodies/parameters and all29DTO declarations; see
whatsapp-api-owner-mapping.json. Backend routes and native contracts are unchanged.
Twenty-one new frontend ratchets cover these owners and the other changed small
modules, without increasing any prior ceiling. The integrated ratchet count is207.

After modularization,217tests across22files passed. The later pager/contact combined
checkpoint passed220tests across24files plus TypeScript and scopedESLint;13Node
contracts passed after its test-helper naming fix. Later normalized conflict/status
and denial-polling changes have focused passing checks and remain separate from that
combined checkpoint. Preliminary expected-red receipts remain separate. Source-only contracts follow explicitly wired
facade owners so unrelated modules cannot satisfy a relocated responsibility.

## Still open

- All35frozen source batches are now fully read. New extracted owners were read
  separately; current physical-file hashes are in the source ledger.
- Trip-update chooser47lines, focused controller110lines, and pure view247lines
  replace the mixed composer. Four import responsibilities now live in focused
  owners37–175lines behind the original4line facade. Exact declaration AST proof
  covers the import hook, mapper and both types;21trip-controller statements and
  the rendered return remain identical during extraction. See
  whatsapp-current-extraction-proof.json.
- Three actual current trip-update regressions failed before repair: duplicate
  admission before pending render, send action remaining enabled after known
  acknowledgement, and denial polling using stale queued rows. Both update
  screens now share one request-retention/admission hook. Lost responses keep
  the exact request; known acknowledgements stop further submissions.
- Rejected spreadsheet review mounted120cards in the negative regression. It
  now mounts at most50, exposes every page, and retains all120in the verified
  save mapper. No draft rows or original workbook bytes are truncated by paging.
  The combined import/update run passed23tests across5files; both relocated
  source-contract suites also passed. Broader WhatsApp checks are being refreshed.
- The activity tracker now has a39line public provider and10cohesive source owners
  covering context, storage, query state, cache refresh, completion/cleanup timers,
  floating gesture handling, inline view, row/progress and deferred failure names.
  Current bodies/parameters for8moved functions,13selector declarations,
  11provider declarations and3effect callbacks are AST-identical to the post-fix
  checkpoint; rendered provider/row returns are unchanged. Stable parent refs are
  now explicit hook dependencies. New owners were fully read after assembly.
  See whatsapp-activity-extraction-proof.json. Twenty interaction tests and seven
  owner-bound source contracts pass; scoped lint passes without suppression.
- Actual activity-summary and failure-name403regressions each observed five
  requests in the old window, versus two and no further interval calls after the
  fix. Permanent4xxfailures stop automatic retries;408/429/network/server failures
  retain bounded retries. Missing404cleanup retains its existing meaning.
- Remaining roster and composer decomposition with workflow parity; method-level
  unused legacy hooks/transports are delegated with explicit test-porting first.
- Remaining active-method reachability, denied-query polling, page offsets after
  refreshed audiences shrink, document-send actor continuity and final browser checks.
- Final integrated lint/types/unit coverage, production build and synthetic browser
  flows after all frontend owners reach a coherent frozen checkpoint.

Real provider sends, private service/VPS qualification and deployment are outside
these local receipts.
