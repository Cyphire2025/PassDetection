# Email dashboard review

The root reviewer read every current runtime TypeScript/TSX source file under
`frontend/features/email-integrations`, including DTOs, API calls, polling hooks,
role gates, callback handling, all decision dialogs and their current owners.
`email-frontend-reviewed-files.json` binds the exact reviewed content hashes.

Implemented during review:

- Separated connection orchestration, account cards, account confirmations and
  summary rendering. The entry screen is 133 lines instead of 744.
- Added synchronous action admission while React Query's pending state catches
  up. Removal also checks the confirmation address inside its handler. Failed
  mutations release admission for an explicit retry; confirmations stay open.
- Separated inbox view metadata and result cards from pagination/filter state;
  reused the existing definition component instead of its identical duplicate.
- Separated review cards and assignment dialog from queue/filter state. Original
  captured item revisions and source-email-wide unrelated confirmation remain.
- Separated correction fields, passenger choices and deadline controls from the
  feedback shell. Passenger membership uses one Set per render instead of an
  array search per row; outgoing selected-ID ordering is unchanged.
- Separated rollout state/mutations, role-gated view, target presentation,
  confirmations and display model. Explicitly confirmed versions remain frozen
  across background refreshes and conflicts close stale decisions.
- OAuth callback notices now reject inherited object keys such as `constructor`
  and `__proto__`; only defined statuses become notices.
- Centralized bounded action-error display with the old message helper retained
  as a compatibility export. Removed the unused disconnect client/hook, unused
  badge type alias and test-only page-budget constant after complete caller
  searches. The real shared history-feed retention behavior remains unchanged.
- Added 19 size/complexity ratchets and lowered the existing feedback ceiling.
  Existing checks and coverage thresholds were not relaxed.

Verification at this checkpoint: 11 behavior tests in 3 files, 30 existing/extended
Node contracts/utilities, scoped ESLint and the full TypeScript check passed.
Formatter output was admitted only after equivalent emitted JavaScript syntax
and literal values were verified, including JSX text. Final integrated checks
are recorded in the main tracker after all parallel lanes freeze.

This read did not find evidence of frontend token storage or HTML execution in
this feature. Provider secrets remain outside the DTOs and source email/AI text
renders as text. Backend ownership/revision enforcement has its separate review.
Large contract/hook registries contain short independent declarations; this
review does not infer frame times or network latency from their line count.
