# Private passport and upload-link mutation checkpoint

All 28 actual private hook regressions first failed because the private API was
called after the initiating actor changed while a global `onMutate` callback was
suspended. The baseline receipt is `.tmp/passport-private-mutations-before.json`.
The existing shared `usePrivateMutation` wrapper now captures the initiating
actor and authority at invocation, before that scheduling boundary.

Private APIs accept optional trailing owner metadata outside their request
bodies. Existing callers without that metadata retain their HTTP argument shape.
Multi-step re-extraction, chunked uploads and exports validate the initiating
authority before beginning and retain their existing continuation guards. Late
preview progress is ignored after authority changes without throwing from the
browser transport callback. A shared export transfer owner removes four repeated
picker/body/final-authority sequences while preserving the separate group export
history completion handshake.

The large `use-passports.ts`, `use-upload-links.ts` and `upload-links.api.ts`
entry points now delegate to cohesive query, review, bulk, import, export, CRUD,
roster and public traveller owners. Public token lookup, telemetry, keepalive and
qualifier transport retain their existing bodies, headers and proof boundaries.
The movement origin manifest identifies post-fix originals; it is separate from
the deliberate ownership changes and is not claimed as a before-fix body identity
proof.

Final affected checks passed: 89 focused tests in seven files, 39 compatibility
tests in three fixture files, 59 Node contracts in seven files, TypeScript and
scoped ESLint. All 55 existing passport module budgets pass. The wider affected
feature run is retained honestly as a historical result: 255 of 272 passed;
its 17 failures were confined to the three subsequently corrected fixture files.
Those fixtures now establish a synthetic staff actor and preserve their existing
payload, revision, retention, conflict, retry and pending-action assertions while
adding separate owner metadata assertions.

The exact current 26 runtime hashes and test records are in
`passport-private-mutation-reviewed-files.json`. Verification receipts are in
`passport-private-mutation-verification.json`; additive or lowered ratchet
candidates are in `passport-private-mutation-budget-candidates.json`. The shared
budget remains parent-owned. No whole application build or suite was run for this
batch. The other 16 oversized passport/upload owners remain queued; this is a
coherent private invocation checkpoint, not whole-audit completion.
