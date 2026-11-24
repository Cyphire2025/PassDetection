# Residual document distribution review

The 13 selected retained route/support files (originally 1,888 lines) were physically read in full. The new compensation owner and three regression files were also fully read. Current hashes, historical original snapshots, supporting partial reads, and attribution for previously reviewed shared owners are in `document-residual-reviewed-files.json`. The independent existing scope/roster follow-up remains open.

Three reproduced behavior problems were corrected:

- Reupload now captures the authorized agency UUID before rollback expires the actual ORM object. The former normal route raised `MissingGreenlet` before bounded input validation.
- Save refreshes identity-map state in its existing ordered `FOR UPDATE` query, so a current processing batch cannot be treated as an older cached draft/saved batch.
- Reupload and manual upload finish precommit rollback and owned-object compensation under ambient AnyIO cancellation and repeated requester cancellation. Original root exception identity and existing cleanup-failure precedence remain. Commit-outcome ambiguity still retains the objects.

The final focused selection passed **33 cases in 30.92 seconds**. Strict type checking passed for the four runtime owners; no-fix Ruff and formatting checks passed for the four runtime and three test files. A one-call test-only formatting change after that run has an exact whole-AST proof; all four runtime sources were unchanged. No broad suite/build/browser or external service was run.

The source-equivalence receipt inverses only these deliberate fixes and then checks whole original function AST, real runtime annotations/defaults, three actual OpenAPI schemas, original imported objects, and the MCP save alias. The manual upload file grew from 182 to 271 physical lines through readable formatter expansion; its maximum function complexity remains 14. Existing reupload/save caps and coverage floors are retained. Additive proposals are separate from shared gate edits.

The tests use synthetic data and real SQLite ORM/current route policy. A no-op SQLite PostgreSQL advisory-lock UDF lets the actual SQL paths run; it does **not** qualify PostgreSQL locking or MVCC. Native input processing and provider/storage I/O are isolated synthetic boundaries. Initial missing-UDF fixture failures remain recorded as fixture failures. Final coverage is isolated in `.tmp/document-residual-audit/` and binds the current four runtime hashes.

Frozen receipt: `document-residual-verification.json`. Source proof: `document-residual-source-equivalence.json`. Next retained read-only cohort: the four remaining Compose overlays, two nginx API error includes, and monitoring alert test definitions.
