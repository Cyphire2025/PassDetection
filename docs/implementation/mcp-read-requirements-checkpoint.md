# Read-only frontend coverage requirements

Five frontend surfaces had been correctly moved to Phase 3 while retaining the
inventory's generic mutation requirements: document rename `listBatches` and
`getBatch`, email integration `status` and `summary`, and operations
`adminOverview`. Their implemented adapters use authorized bounded reads and do
not create durable business operations.

This metadata-only correction preserves `no_removal_effect_audit` and replaces
`business_transaction_idempotency` and `durable_operation_progress` with
`current_superadmin_read_authorization`, `canonical_website_read_scope`, and
`bounded_observation_and_completeness`. Root and the coordinator independently
reviewed the five source adapters. Ordinary invocation audits and the explicitly
requested rename identifier audit remain permitted read effects.

Every other ledger field is unchanged, including source fingerprints, phase,
disposition, effect review, implementation evidence, and
`implemented_unverified` status. The older diagnostic tool classification is
outside this correction. No runtime behavior, capability, permission, or phase
acceptance changes. The earlier slice checkpoints describe their original
implementation commits; this note records the subsequent finite correction.
