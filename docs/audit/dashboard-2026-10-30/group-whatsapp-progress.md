# Group WhatsApp tracking checkpoint

The original 622-line workspace, 421-line dialogs and 417-line table now have
focused owners for query/filter state, statistics, comparison/pagination,
resolution dialogs, broadcast editing, replacement choice and match rows.
Sixteen runtime files changed; the largest current owner is 268 lines. The
unchanged compact summary and import-only route gate were also read completely.

An actual-dialog keyboard baseline passed one of two cases: the role-radio
buttons did not move focus or selection on ArrowDown. Native grouped radio inputs
now provide the expected browser keyboard behavior while retaining the chosen
recipient and stable request ID across a failed save. Real Chromium checks using
the actual recipient-choice component and compiled project CSS then reproduced
long names clipped inside the bounded surface at both 1440px and 390px. Those
names now wrap fully. Mobile before/after and desktop screenshots were inspected.

The export and roster helpers contained identical complete UUID retry-key
implementations. Both original caller names now use the unchanged pure request-ID
owner, preserving browser UUID preference, random-byte version/variant behavior
and the existing compatibility fallback. The affected earlier presentation helper
record/candidate was refreshed with explicit before-request-id history retained.

Final affected checks passed 18 unit cases in five files, 49 Node contracts,
TypeScript, scoped ESLint and two Chromium cases. All 77 currently registered
passport module budgets pass. Fifty compositional syntax checks preserve moved
query/effect statements, public wrappers, props/keys/callback forwarding and JSX;
the deliberate native-input and long-name corrections are declared separately.
The browser fixture uses synthetic state, starts no HTTP service and blocks all
network requests. It qualifies the recipient choice and CSS, rather than claiming
full production tracking/backend-provider coverage.

Exact current hashes, supporting reads, receipts, screenshots and limitations are
in `group-whatsapp-reviewed-files.json`. Sixteen candidates are in
`group-whatsapp-budget-candidates.json`; the shared ratchet remains parent-owned.
The private 26, controller eight and list seven runtime checkpoints remain
unchanged. Nine of the original oversized owners remain open. No whole app build
or unit suite was repeated for this feature batch.

A final rendered query-refresh case reproduced confirmation remaining enabled
after the selected recipient disappeared from the current candidate list. The
button and confirmation handler now both require that current candidate; choosing
another available person restores submission. Its baseline passed two of three
cases and the final case passes. This two-guard correction is explicitly declared
in the compositional proof, with the earlier movement-only proof retained as
`group-whatsapp-before-recipient-refresh-movement-proof.json`.
