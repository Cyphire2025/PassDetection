# Phase two: dashboard Medium and Low remediation

Owner request: 26 September 2026. Starting candidate: `6033b9f3db2598c167600685d8fab4229de4368c` (local, not deployed).

## Scope and acceptance

Implement and verify all remaining dashboard/backend Medium and Low findings in the original 44-group audit register. Enterprise quality is the target; source changes alone do not establish enterprise operational readiness. Preserve existing business workflows, stored records, object versions and tenant boundaries. Never lower a gate or count a documentation-only change as a behavioral fix.

The starting ledger has 27 unfinished Medium groups and four Low groups. DEP-02 belongs to the excluded native applications, leaving **26 dashboard/backend Medium groups and four Low groups in this phase**. REL-03 external alerting and DATA-05 production disaster recovery are explicitly deferred by the owner. Native `mobile/` and `Coordinators app/` remain excluded. Those exclusions remain visible in the overall register.

The owner supplied the saved phase-two objective and subsequently instructed work to continue on 27 September 2026. This plan records that authorized scope; it does not assert the current state of the app's goal tracker. The earlier deferred High findings have not been falsely marked complete.

## Workstreams

| Workstream | Original findings | Acceptance direction |
| --- | --- | --- |
| Authentication | SEC-02, SEC-03, SEC-05, PERF-01, API-03 | Logout invalidates copied access; refresh reuse invalidates its family; distributed credential budget; bounded off-thread password work; consistent UTF-8 byte validation |
| Frontend | UI-01, UI-02, UI-04, QUAL-03, QUAL-04, frontend ARC-02/QUAL-02 | Dialog keyboard lifecycle, representative browser journeys, privacy-safe renderer reporting, checked routes, removal of dormant maintenance surface, focused responsibilities |
| Tooling and release | DEP-03, REL-04/DEP-04, SCALE-02, DOC-02, DOC-03, DOC-04, DOC-05, DEP-05 | Enforced advisory review, immutable provenance/promotion, replica-aware budgets, reproducible setup, current and accountable evidence/documentation |
| Backend and data | ARC-01, backend ARC-02/QUAL-02, SEC-04/API-02/PERF-03, SEC-06, PERF-04/SCALE-03, PERF-05, API-01, API-04, DATA-02, DATA-03 | Enforced dependency boundaries; bounded queries; audit/read coverage; paged projection; measured query plans; compatible error/OpenAPI contracts; safe database invariants |
| Capacity and topology | SCALE-01, SCALE-04 | Remove source topology obstacles and exercise a declared workload. Actual multi-host availability and production capacity claims require separate real evidence. |

Each workstream retains tests and limitations in a focused phase-two evidence report. Update the shared status only after independent review and integrated checks. Shared IDs remain one original finding group.

## Production and storage boundary

The storage investigation remains read-only: no data deletion, Docker prune, backup deletion, volume removal, or file cleanup is authorized. On 27 September 2026 the owner separately authorized deployment after all required fixes and checks: push main, pull on the VPS, rebuild and verify. That later deployment authorization supersedes the earlier no-deployment restriction; it does not authorize storage cleanup or destructive data operations.

Observed storage inventory: root 193 GiB total / 69 GiB used / 125 GiB available; Docker images 17.89 GB (1.614 GB reclaimable), containers 144.8 MB (47.87 MB reclaimable), nine active volumes 6.921 GB (0 reclaimable), build cache 47.44 GB (32.31 GB reclaimable). Docker categories share layers and must not be added as independent physical disk totals. Journals occupy 70.4 MB. `/opt/GlobalConnectsDashboard-backups` occupies 1.3 GiB and must not be treated as disposable. No cleanup was performed.

Hostinger's account shows two weekly backups stored separately in Malaysia, while the VPS is in Mumbai; those backup objects do not consume the VPS filesystem quota. This does not establish a tested application recovery procedure.

## Release boundary

Preserve the prior qualified checkpoint and unrelated working-tree changes. Qualify the final integrated candidate before any push. A push is not a deployment. Any new schema migration must preflight existing rows, fail with actionable diagnostics on inconsistent data, preserve all records, and be tested against a migrated PostgreSQL database. Do not edit already-applied migrations or promise an untested pull-and-restart deployment.

## Updated owner deployment authorization — 27 September 2026

Latest instruction: "after changes are done, push my code to main, and then pull on the VPS, rebuild and test everything" with the strict requirement that no production data be deleted. This instruction takes precedence over the earlier goal attachment's no-deployment bullet.

Required sequence: qualify and review the integrated candidate; commit only intended remediation changes; push main without force; inspect the current VPS revision, schema, volumes, service state and capacity; verify a fresh recoverable database/object backup and retain existing storage; pull the exact pushed revision; run the guarded release procedure with preflight and bounded migrations; rebuild/recreate only the intended services from qualified artifacts; verify runtime roles, actual schema, image revision, readiness, data-preservation evidence and representative non-destructive application journeys. Do not run production synthetic mutating tests.

No database reset, drop, truncation, business-row deletion, volume deletion, Docker prune, backup deletion, unrelated file cleanup, or silent data repair is permitted. No destructive restore is authorized. Stop a deployment if a safety precondition fails; diagnose without weakening the check or recreating stale services. Data preservation is a release gate, not a claim inferred from passing local tests. External alerting and production disaster-recovery exercises remain deferred.

## Updated owner audit-storage deferral — 27 September 2026

After the implemented checkpoint publisher/verifier and local Object Lock tests were explained, the owner confirmed that no external S3 Object Lock account currently exists and said they will create one later. Production independent audit storage, signing custody and scheduled independent verification for SEC-06 are therefore explicitly deferred. Preserve and qualify the code; do not create an account or present the external protection as deployed. SEC-06 remains visibly Partial / operationally deferred and stays in the original 30-group denominator. This later instruction adds a specific operational deferral; it does not defer the other dashboard/backend fixes or their tests.
