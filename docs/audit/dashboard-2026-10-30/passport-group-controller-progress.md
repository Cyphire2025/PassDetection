# Passport group controller checkpoint

The 722-line controller now composes focused view/navigation, metadata, menu,
import, dialog, selected-image download and selection owners. Its public return
projection retains all 106 properties without additions, omissions or duplicate
keys. AST evidence confirms all 65 physically moved statements, with one declared
group-name parameter alias for the selected-image download owner.

The actual-controller baseline reproduced three defects: duplicate IDs after two
same-turn toggles, a 1,501-record selection after two same-turn additions and
decimal counts accepted through their integer prefix. Selection IDs, revision
snapshots and cached Set membership now update atomically. Another negative case
proved that presets could retain revision entries for records excluded by the
selection cap; only admitted IDs now remain in that map.

The initial selection baseline passed one of four cases; all five final selection
cases pass. The broader affected group checks passed 26 cases in five files,
including role access, image revisions, toolbar selection and follow-up behavior.
Thirty Node contracts, TypeScript and scoped ESLint also pass. No whole app suite
or build was repeated. Exact hashes, candidate budgets and receipts are in
`passport-group-controller-reviewed-files.json` and
`passport-group-controller-budget-candidates.json`.

This closes one more of the original 19 oversized owners. Fifteen remain after
the three earlier hook/API roots and this controller; their architecture and UI
proof queues remain open.
