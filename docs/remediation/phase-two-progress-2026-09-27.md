# Current Medium and Low remediation progress — 27 September 2026

**26 of 30 in-scope finding groups are locally closed: 22 Medium and all four Low. Three Medium groups still require completion; one additional Medium group is operationally deferred by the owner. No phase-two changes have been deployed.**

These are bounded original-finding closures, not a claim that the complete candidate is release-qualified or Enterprise-grade. The previous 21-count was correct before the deeper upload decomposition, independent API contract review and actual two-API/dependency recovery evidence completed. The present 26-count additionally includes the final strict mixed-workload qualification; it does not restore the earlier premature UI-01 closure. UI-04 is now independently accepted because an actual browser fault produced the correct server log, deduplicated receipt, release association and privacy checks; external alerts remain deferred separately.

## Exact denominator

The original register has 44 groups: 10 High, 30 Medium and four Low. Linked IDs in a row count once. The preceding phase locally closed eight High and three Medium, leaving **33 total unfinished findings**, comprising two High, 27 Medium and four Low. Native DEP-02 is excluded, so this phase has **30 groups: 26 Medium and four Low**.

| Reconciliation of the earlier 33 | Count |
| --- | ---: |
| Locally closed in this phase | 26 |
| In-scope Medium work still active | 3 |
| In-scope Medium SEC-06 operationally deferred | 1 |
| Previously deferred High REL-03 and DATA-05 | 2 |
| Excluded native Medium DEP-02 | 1 |
| Total | 33 |

Across all original findings, 37 groups have local closure evidence (11 preceding phase + 26 this phase). Across all original Medium/Low groups, 29 of 34 have local closure evidence (three preceding phase + 26 this phase). Deployment is a separate status and remains pending for this phase.

## The 26 locally closed groups

| Original group | Concrete change | Evidence |
| --- | --- | --- |
| ARC-01 | Isolated domain and application HTTP boundaries; explicitly documented, exact, expiring infrastructure allowances enforced by AST checks | docs/architecture/dependency-contract.md; backend/scripts/verify_architecture_boundaries.py; four negative tests |
| ARC-02 / QUAL-02 | Email and tour route responsibilities extracted with stable route identities; upload polling, passport navigation and WhatsApp UI responsibilities separated | email-tour-decomposition.md; frontend-phase2.md; source/module ratchets |
| SEC-02 | Logout revokes the persisted dashboard family, including copied access credentials | phase2-auth.md; real PostgreSQL concurrency checks |
| SEC-03 | Consumed refresh-token replay revokes the successor family; concurrent in-flight rotation has bounded conflict behavior | phase2-auth.md |
| SEC-04 / API-02 / PERF-03 | Legacy pagination validates finite page and offset bounds; deterministic tie ordering | backend/app/presentation/api/v1/pagination.py; pagination/API tests |
| SEC-05 | Shared account, source and global credential admission budgets; consistent verifier work for invalid identities | phase2-auth.md; actual Redis concurrency checks |
| PERF-01 | Bounded off-thread password work preserves concurrency slots through cancellation | phase2-auth.md |
| PERF-04 / SCALE-03 | Encrypted, bounded shared roster index; transactional invalidation and live authorization around page hydration | phase2-roster.md; 51 focused passes, nine PostgreSQL/Redis cases; 320 warm requests without complete-group projections |
| PERF-05 | Literal substring search uses measured PostgreSQL trigram plans, maintaining tenant/lifecycle scope | search-plan-evidence.json; 100,001-row local dataset |
| SCALE-02 | Database budget includes replicas, rollout overlap, workers and reserved capacity | database-capacity-evidence.json; actual 64-session qualification |
| API-01 | Standard error object and correlation across handlers, validation, readiness and proxy-generated failures | docs/API_CONTRACT.md; proxy-error-evidence.json; backend error tests |
| API-03 | New passwords reject more than 72 UTF-8 bytes while preserving existing legacy bcrypt verification | phase2-auth.md; 15 real-bcrypt compatibility/work-budget tests |
| DATA-02 | Composite passport group/agency ownership constraint with non-destructive preflight | phase-two-data-migration.json |
| DATA-03 | Database checks enforce ECR states, outcomes and nonnegative counters | phase-two-data-migration.json |
| DEP-03 | Exact dependency exception requires accountable owner, expiry, locked sources and checked import closure | phase2-tooling.md; negative enforcement tests |
| DOC-02 | Supported, hash-locked developer bootstrap tested on Windows and Linux | tooling-bootstrap-evidence.json |
| DOC-03 | Current database process/replica/overlap calculation replaces stale capacity claims | phase2-tooling.md; docs/DATABASE_CONNECTION_CAPACITY.md |
| DOC-04 | Scope, limitations, owners, evidence fingerprints and expiry accompany engineering claims | docs/ENGINEERING_CLAIMS.md; phase2-tooling.md |
| QUAL-03 (Low) | Typed route builders and validated stored destinations replace unsafe navigation assertions | frontend-phase2.md; route/type tests |
| QUAL-04 (Low) | Removed dormant public manual-crop state/handlers; retained working camera and staff crop workflows | frontend-phase2.md |
| DEP-05 (Low) | Default tooling refuses unsupported Python/Node versions | tooling-bootstrap-evidence.json |
| DOC-05 (Low) | Current contributor and operator reading order, ownership and review policy | phase2-tooling.md; contributor documentation |
| API-04 | Full API form, cookie/Bearer alternatives, refresh, error/header and binary contracts match reviewed runtime semantics | api-contract-review-evidence.json; 15 focused cases; full/mobile snapshot checks |
| SCALE-01 | Actual two-API session/upload continuity, peer logout and origin restart; controlled database outage fails closed and recovers the same state | api-replica-evidence.json; dependency-recovery-evidence.json |
| UI-04 | A real browser render fault reaches the privacy-safe collector; exact support ID, release association, deduplication and one structured server record verified | frontend-render-error-browser-evidence.json; actual final frontend/backend image browser journey |
| SCALE-04 | Declared mixed workload now meets every unchanged cold, large/small-tenant, overload, recovery, durable-queue and memory gate | workload-capacity-evidence.json; phase2-workload-capacity.md; exact final image 0066ad35, four API processes, 2,560 MiB and 24-connection pool budget |

Evidence names above are under `docs/remediation` unless another path is given. Original audit reports remain historical records. Residual design debt and documented ORM coupling are not concealed by the bounded closures.

## What remains, in order of release importance

| Original group | Status and completed work | Exact remaining requirement |
| --- | --- | --- |
| REL-04 / DEP-04 | Partial. Strict signing/promotion controls, whole-image inventory, actual local predecessor/successor retrieval, and applied/read-back GitHub protections exist. | The final local image, memory and interrupted lifecycle qualifications have passed. Issue and verify real GitHub attestations and retained release artifacts for the pushed commit. No unsigned activation fallback. |
| UI-01 | Partial. Shared modal lifecycle, the WebKit pointer-focus fix, focused regressions and actual dialog journeys now pass on all three engines. | The original acceptance explicitly includes actual NVDA/VoiceOver use; that human assistive-technology evidence is still absent. No known remaining code defect in the audited modal behavior is being concealed by this status. |
| UI-02 | Partial. All nine unique production-image journeys now pass across recorded split runs: Chromium, Firefox and supported Linux WebKit. | The original acceptance explicitly includes real iPhone Safari and Android camera devices. Physical-device evidence remains unverified; native implementation is excluded. The software/browser-engine work is complete for this finding. |
| SEC-06 | Partial / owner-deferred operationally. Sensitive-read audit events, signed checkpoints and real local Object Lock/tamper tests exist. | Owner currently has no external storage account and said they will create one later. Independent production storage, signing custody and scheduled independent verification are not established or counted as fixed. |

## Current integrated evidence

- **Backend:** 4,447 tests plus 141 subtests passed, zero failures; 163 real-service cases intentionally deselected for their separate lane. Duration 1,212.18 seconds. All 86 module/coverage ratchets pass; whole-backend line coverage 78.58%, branch coverage 60.90%. Strict mypy passes 712 source files. All 1,373 recorded backend files stayed unchanged during the run. See `core-regression-phase2-evidence.json`.
- **Real services:** all 163 unique cases have passing evidence across a complete 162-pass/one-failure run plus the corrected ten-case family rerun; no remaining skip/error. This is explicitly not a single clean 163-case invocation. Current-schema role checks pass 18/18. See `service-integration-phase2-evidence.json`.
- **Frontend:** 137 files / 902 behavior tests and 707 Node contracts pass. The later focus repair passes 16 targeted cases, final types/lint and all 40 source ratchets. All nine unique joined browser journeys pass across recorded split runs on the rebuilt frontend. Selected critical-module coverage is not whole-frontend coverage, and synthetic camera input is not real-device acceptance.
- **Capacity:** final strict run `59a7fa2a20bf425ba6162b892094307b` passed every unchanged gate on the final image. Large-tenant roster/search p99 were 448.223/56.465 ms; all four uploads, 60 scans and 600 recovery reads succeeded. The 100 durable jobs drained in 22.662 seconds with three consecutive empty samples. Overload returned only recognized 200/429 responses, p99 2,518.55 ms. Peak sampled API memory was 1,638.14 MiB; terminal memory event counters were zero. The earlier failed tail-latency run is retained. This proves the declared local envelope, not a production SLO, external AI throughput, long soak or whole-host simultaneous peak.
- **Memory and preservation:** shared crash-released native admission, buffer cleanup, allocator reclamation and PDF reader closure are verified on final image `0066ad35`. Four persistent API workers survived repeated maximum-input bursts at 2,300.18 MiB under 2,560 MiB, with controlled 503 backpressure and identical-pixel retries; no OOM events occurred. All five reused worker paths pass at their KVM4 caps. Redis fill/AOF fork, concurrent ClamAV reload, PostgreSQL pressure and interrupted persistent-service transitions passed. The qualified 13,888 MiB container envelope retains a 2,048 MiB host reserve. This is bounded component and mixed-workload evidence; deployment still requires actual host and service readback. All 286 operator/tooling cases pass.
- **Production:** read-only inspection confirmed the earlier release and schema 0107, with the old privileged runtime database identity. Local fixes must not be described as live. Existing business records, files, object versions, volumes and backups have not been deleted. Storage cleanup remains inspection-only.

## Additional findings

The separate `additional-findings-register.md` now tracks **15 engineering defect groups: six High, four Medium and five Low**. Some were pre-existing; others were caught in new remediation code or verification tooling before deployment. They do not enlarge the original 44-group denominator. Scanner matches are not counted individually as independently confirmed application exploits.

## Authorized next steps

Complete remaining local fixes and qualification; review and commit only intended changes; push main without force; verify remote CI and signed artifacts; then perform the separately authorized guarded VPS rollout. The latest owner instruction permits deployment but strictly forbids production data deletion. A fresh recoverable backup, migration preflight, storage preservation and post-release verification remain mandatory. External alerts, production disaster-recovery exercises and external audit-checkpoint custody stay deferred.
