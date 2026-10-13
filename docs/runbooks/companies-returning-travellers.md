# Local qualification and rollout runbook

This change requires a **Full** release: it adds persistent schema, queue consumers, security-sensitive routes, encrypted retained records and storage ownership. No production migration, deployment, actual provider send or production data import was performed during implementation. Keep disclosure disabled until the remaining qualification gates below pass.

## Configuration and migration

Set independent `TRAVELLER_REUSE_LOOKUP_KEY`, `TRAVELLER_REUSE_ENCRYPTION_KEY` and `TRAVELLER_REUSE_KEY_VERSION` through the deployment secret manager. Never paste or log their values. `TRAVELLER_REUSE_DISCLOSURE_ENABLED` defaults to false. The network/session per-minute limits are configured independently with `TRAVELLER_REUSE_REQUEST_NETWORK_LIMIT_PER_MINUTE` and `TRAVELLER_REUSE_REQUEST_SESSION_LIMIT_PER_MINUTE`.

Run the repository's normal migration checks against a disposable PostgreSQL instance first. The sequence includes company directory 0130, retained evidence 0131, concurrent source seek index 0132 and the subsequent operational impact migration 0133. Verify the exact final head against `backend/app/core/config/release_manifest.json`; do not deploy an intermediate agent checkpoint.

0131 adds independent tables and has a five-second lock-acquisition timeout. It does not backfill identities or inferred permission. Its downgrade refuses if any new record exists. Operational rollback disables disclosure and pauses relevant consumers; it must not drop accepted history. 0132 builds three source cursor indexes concurrently: passport submissions, WhatsApp recipients and rejected-contact rows. It recovers invalid interrupted builds and checks valid definitions before reuse. Record index validity and `EXPLAIN (ANALYZE, BUFFERS)` on representative tenants before enabling traffic.

The required CI migration job also runs `backend/scripts/rehearse_companies_traveller_upgrade.py`. It restores a populated synthetic 0129 backup with 700 roster people and nonempty runtime grants, captures the original preservation fingerprint, interrupts the actual release helper at the committed 0131 checkpoint, creates an invalid concurrent index through a real PostgreSQL uniqueness failure, and resumes through 0133. A deliberately wrong original fingerprint must fail while the schema remains at 0131. The successful resume compares historical row hashes, retained catalog and ACLs against the original fingerprint, checks new tables remain empty, then verifies a no-op rerun. Review `companies-migration-rehearsal-evidence.json` from the exact candidate SHA. Local guard tests establish script behavior only; they are not substitutes for a successful real PostgreSQL receipt.

The retained release captures its source fingerprint with the signed helper's `--capture-baseline` mode after the original 0129 backup and writer fence. Its private receipt binds this value to the original backup, image and release proof; every upgrade or unvalidated resume requires `MCP_RELEASE_BASELINE_SHA256` to match before and after DDL. A target Alembic head alone never authorizes activation. If a helper fails after committing 0133, rerun complete target validation using the original receipt. If validation already succeeded and only activation failed, the bound successful validation receipt permits recovery without incorrectly requiring legitimately populated feature tables to be empty again. Do not regenerate a baseline from an intermediate or target schema, automatically downgrade, or restart 0129 writers after a partial upgrade.

The encryption/lookup keys are not interchangeable with login secrets. Changing a key version invalidates unsupported lookup contexts; it is not an automatic re-encryption mechanism. Do not rotate by simply replacing deployed keys with populated history. A separately reviewed resumable migration and compatibility window are required for online key rotation; that workflow is not implemented by this feature.

## Activation and controlled ingestion

Configure each company's purpose version, notice version and processing basis explicitly. Retention mode is `until_withdrawn`; no fixed age purge is inferred. Group reuse configuration is separately enabled and specifies closed/open roster and individual identifier semantics. Directory recognition and historical matching do not activate disclosure.

Run historical matching previews first. Reconciliation checkpoints are durable, bounded to 100 rows, idempotent and cancelled when the group's company revision changes. Review unmatched, ambiguous and conflicting cases. Do not turn a broad name/phone match into automatic enrollment.

Matching includes linked durable WhatsApp recipient and rejected-contact rows. Check actual import preservation before treating job totals as the entire original workbook. Older truncated rows require a reviewed reimport. Staff resolution rechecks source content and matching configuration, creates a pending membership only, and requires a refreshed preview after a source or identifier-rule change.

Use the staff enrollment-source picker to view accepted sources incrementally. View the actual source and attest missing issuer/type explicitly. Supply permission evidence and current expected revisions. For a public replacement, acknowledge the previously verified traveller association. The API returns accepted revision and pending-copy count; pending, unsupported or unreadable assets are not usable history. Confirm the independent copy is available before relying on it for current-trip reuse.

The existing Celery runtime includes `travellers.reconcile`, `travellers.copy_assets` and `travellers.withdraw_assets` on the existing `passport_ocr` queue. Periodic recovery, PostgreSQL advisory admission, durable attempts and leases provide backpressure across replicas. There is no automatic provider messaging in these consumers. Confirm the selected worker actually consumes that queue and the scheduler is running; an HTTP enrollment success does not mean a copy has completed.

## Failure and retention exercises

1. Stop the copy consumer, enroll synthetic accepted evidence and verify assets remain pending without appearing as usable documents. Restart and verify one stable independent destination per asset.
2. Interrupt a copy after its durable attempt is reserved. Verify lease expiry/retry and the five-attempt terminal boundary. Time out storage calls and verify admission remains occupied for the provider timeout envelope.
3. Withdraw future reuse during a copy. Publication must recheck authority and queue any orphan destination for deletion after in-flight storage work can no longer recreate it.
4. Delete an old operational group/source after successful copies. Retained originals and immutable provenance must remain; pending copies block unsafe source deletion.
5. Withdraw future reuse with a current submitted trip. Historical grant access must stop immediately, while the authorized current-trip snapshot remains available. Purge an asset or hard-delete its profile and verify its staff image/thumbnail route immediately denies access.
6. Change company assignment, organization status, policy, group requirements, selected passport or contact revision after review. A stale grant/review must fail; accepted previous-trip references must remain unchanged.
7. Submit a replacement with a different upload capability, another group's UUID or another person's grant. It must create no association. Editing candidate source fields/images after association must require refreshed authorization before enrollment.
8. Force transaction rollback midway through a reconciliation page. Retrying must preserve one case per source/company, no skipped rows and no new granted permission or participation.

## Qualification budgets

These are acceptance targets, not claims established by the local query benchmark. On a representative PostgreSQL/API environment, target authenticated directory and review p95 <=300 ms and p99 <=750 ms without storage transfer, <0.1% infrastructure error rate, zero tenant leaks or stale-proof authorizations, and no monotonically growing queue age during a 30-minute steady-state workload. Document-image latency must be separated into authorization, object stat/read and client transfer. Set an explicit supported concurrent-client target from measured results before launch.

Verify the actual queries, not just ORM method timing. Capture plans for large and small tenant distributions, search terms with different selectivity, exact passport lookup, source cursor paging, summary aggregates and deletion/reference checks. Use at least the existing 100,000-person synthetic volume before increasing it. Observe p50/p95/p99, completed requests/sec, query count, database lock waits, working set, durable pending/failed jobs, oldest due-job age, broker queue depth and retry/error rates. Existing request telemetry and metric export sinks must be connected to deployed monitoring; local in-process counters alone are not an operational dashboard.

Copy requests must never load complete documents in application memory. Keep two global copy leases and a maximum 20 MiB object until measured storage/provider behavior justifies a reviewed change. Reconciliation pages remain <=100 and enrollment source pages <=50. Do not increase concurrency or page limits merely to hide backlog; measure whether database, object store, worker availability or invalid inputs are the bottleneck.

## Evidence recorded locally

- The synthetic 700-row shared-phone reconciliation fixture produced 400 provisional matches and 300 unmatched people with <=8 SELECT statements per 100-row page, no profile permission grants and no participation creation.
- 100,000 profiles, 100,000 passports, 200,000 participations, 250 companies, four concurrent SQLite readers and 120.03 seconds produced zero query errors; peak working set 113,246,208 bytes. Receipt: `docs/implementation/companies-reuse-evidence/capacity-100000-profiles-200000-participations.json`.
- p95 local query times: company search 1.814 ms; passport lookup 0.280 ms; traveller page 2.198 ms; group summary 2.676 ms. No API, network, encryption, ORM or provider time is implied by these figures.
- Focused persistent schema, enrollment, copy, snapshot, proof, UI and regression tests are recorded in the feature handoff file. Check the final root-agent receipts for the exact latest aggregate; parallel checkpoints overlap and must not be summed.
- Initial Docker inspection found no running daemon. PostgreSQL migrations, advisory-lock admission and real concurrent storage/queue failure tests remain mandatory; no successful PostgreSQL service qualification is claimed here. No million-user capacity claim is supported.
