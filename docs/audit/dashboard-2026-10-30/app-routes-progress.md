# App route and global style review

Read all121runtime files under `frontend/app` in seven frozen, bounded source
batches, including every route, layout, loading/error owner, metadata/manifest
and all global CSS. The content-bound ledger also includes the five new manager
administration source/test owners. Reading a thin route does not establish that
its imported feature implementation has been reviewed.

Changes made during the read:

- Moved the manager administration view and its three dialogs into focused
  feature owners. The route is now three lines. Added the shared modal boundary,
  accessible labeling, initial non-destructive focus and pending-state protection
  to deletion. Creation and deletion admit one synchronous request at a time;
  deletion rechecks the current role at the action boundary.
- The create-dialog close button now honors pending requests; dialogs can scroll
  inside the phone viewport. Invitation copying handles browser denial and uses
  the shared clipboard helper, retaining the existing origin-bound activation
  link and explicit manual copy fallback.
- Removed a button nested inside the Old Data navigation link. The link itself
  now uses the existing button styles and remains one focusable navigation target.
- Removed a one-value analytics presentation prop and consolidated repeated
  status-color selection, preserving all color choices and label formatting.
- Removed duplicate product suffixes from18route titles. Installed Next16.4.3
  metadata documentation confirms that the root title template already supplies
  the product suffix to child routes. Added an exact login browser-title assertion.
- Replaced garbled decorative CSS comment separators with clear section comments;
  no style declarations changed in that cleanup.

Retained framework-required route/loading wrappers and documented compatibility
routes that are deliberately guarded for rollback; byte-identical wrappers are
not automatically dead code. Installed version documentation also confirms the
current asynchronous params and error `retry` prop contracts.

Manager dialog and duplicate-submission behavior checks:4passed. TypeScript and
the email feature's scoped checks passed at their recorded checkpoints. Final
route/metadata browser and integrated checks follow parallel source freeze.

The400-line audit-ledger route was also decomposed into a3-line route facade,
filter/display model, focused query/export hook, filter controls, responsive rows
and screen composition. Original normalization, authenticated-session/unmount
download cancellation, incomplete-page warnings, bounded export messaging and
text rendering remain. Two hook regressions verify cross-agency filter admission
and cancellation of a request from a revoked session; all13 existing dashboard
transformation contracts still pass against the current source owners.
