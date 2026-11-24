# Release defaults reconciliation and complete operator verification

The combined operator suite exposed 37 errors. Each original traceback had exactly the same cause: `.env.example` still defaulted `EXPECTED_DATABASE_SCHEMA_REVISION` to `0141_workspace_branding`, while the reviewed release manifest now targets `0142_group_background`. The shared Compose database environment anchor also retained that old default. No other distinct error was present in the original log.

Updated only those schema declarations to `0142_group_background`. Historical source/migration constants and exact 0140/0141 admission baselines remain unchanged. No actual local/VPS `.env` file, Compose project/service/container/volume identity, worker identity, application API contract, or published migration was modified. The existing schema release process remains responsible for updating the deployed schema expectation during the authorized forward upgrade.

The strict branding release policy now binds the exact current `docker-compose.yml` hash and additionally binds `.env.example` to its exact BEFORE/AFTER hashes for each of the two reviewed baseline commits. The `.env.example` candidate includes the earlier manually reviewed dormant local OCR-setting removal. No source admission, migration proof, authorization, resume, or rollback requirement was weakened. Independently verified all **20 candidate AFTER hashes** and both exact baseline hash sets; evidence is in `release-defaults-bindings.json`.

`scripts/release_manifest.py` passes the real source-default consistency check. Reran the complete operator suite with the fresh hash-locked environment:

```text
python -m unittest discover -s scripts -p 'test_*.py'
Ran 870 tests in 62.136s
OK (skipped=5)
```

That is 865 passing tests and five skipped tests, with no failures or errors. The full output is retained in `operator-contract-tests-after-defaults.txt`; the earlier failing `operator-contract-tests.txt` is retained as diagnosis evidence. The original 37 errors have no remaining secondary failure after the source-default correction. Ruff check also passes for the edited release policy.

`release-defaults-reviewed-files.json` contains current file hashes and focused review scope. `release-defaults-verification.json` records the original cause count, test result and preserved deployment contracts. These source/operator checks do not claim real Docker/PostgreSQL/VPS release qualification; unavailable real-service release evidence remains a separate gate.
