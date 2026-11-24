# Document matcher responsibility review

Status: source frozen; implementation and focused regression verification complete.

The1959-line matcher combined batch admission, native PDF compatibility seams, document type rules, identity normalization, scoped index construction and ambiguity resolution. It is now a668-line compatibility facade with9focused owning modules, largest354lines. Native PDF wrappers remain in the facade so the existing reader/library/limit override seams keep their behavior.

## Changes and preserved behavior

- Immutable shared classification/matching records live in `document_matcher_models.py`. The facade keeps explicit compatibility exports, including rule constants and exception identities.
- Text normalization, labeled field extraction, type detection, identifier aliases, scoped passenger indexes and match resolution each have a focused static owner. There is no module proxy, global rebinding, dynamic method installation or runtime import cycle.
- Batch deduplication and parser-payload admission live in `document_batch_classification.py`. The facade explicitly supplies its concrete matcher class, preserving the original exact-class/subclass/override sandbox guard.
- The first regression pass exposed that moved code no longer observed four facade identity-bound overrides. A small immutable per-operation identity-limit record now resolves those exact bounds at the facade; direct/linked identifier caps and precedence remain deterministic. The existing override-boundary regression passes unchanged.
- All65 original method algorithm ASTs were checked.63 remain literally identical; the other2 differ only by a single explicit limit snapshot and constant-reference substitution. Normalizing those dependency references restores exact original ASTs. Batch logic changes only to receive the concrete class explicitly. Evidence is retained in `document-matcher-refactor-before.json` and `document-matcher-refactor-verification.json`.
- No matching confidence, identity precedence, classification vocabulary, ambiguity fallback, manual approval, transaction, native allocation, parser isolation or authorization rule changed. This is a maintainability change; no unmeasured speedup or production capacity is claimed.
- Added10 measured line/complexity/coverage ratchets to the existing backend quality budget file. All previous budgets and coverage gates remain unchanged. `document-matcher-ratchets.json` records the selected bounds and focused coverage measurements.

## Verification

- Full focused set with branch coverage:172passed in35.23seconds, using the repository `.venv`. Covers classification, scoped identity matching and cap overrides, batch deduplication, ingestion, PDF allocation/resource closure, parser sandbox/memory, XForms, verification staging, update receipts and real manual-upload route behavior with synthetic data.
- The same tests previously passed in99core and73sandbox/staging batches after the relevant changes.
- Strict mypy:25document modules passed.
- Backend quality budgets passed140modules after adding the10ratchets.
- Architecture boundaries and targeted Ruff passed.
- MCP inventory remains passed for1953surfaces; no workflow classification or tool capability changed in this refactor.
- Focused coverage is retained in `document-matcher-coverage.json`; native rendering/parsing regressions do not establish real Linux Docker cgroup qualification or production document accuracy. No provider calls, production data or developer-environment changes were used.

## Coverage limits

`document-matcher-reviewed-files.json` records current SHA-256 values for15source paths. The matcher, extracted owners, rule vocabulary, PDF support and manual approval cipher received full-source review within this lane. The sandbox received partial review of admission and child-result boundaries, and ingestion received partial review of scope/index/capacity handoffs. Their uninspected remainder is explicitly pending; test execution does not mark it fully reviewed.
