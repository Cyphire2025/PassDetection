# Candidate reassessment after local remediation

26 September 2026. Verdict: **Startup-grade, 6.8/10**, with several advanced
engineering controls. This assesses the locally qualified candidate
against audit baseline `48395bb7e3f3cae9568dcc31f130651e9aa6f420`. It is not a new
rating of the unchanged production installation or a completed release approval.
The original 6.1/10 audit remains preserved separately.

The work materially improves access control, database privilege separation,
duplicate response cost, test credibility and release safety. It does not yet
meet the requested enterprise bar: actual alert delivery and tested production
disaster recovery remain incomplete, along with substantial architecture,
capacity, API and security debt. A requested score is not an acceptance test.

## Category scores

Scores use the same eleven categories with equal weighting: 74.5 / 11 = 6.7727,
rounded once to **6.8**. These are engineering judgments, not a certification.
The tier describes the category as a whole; isolated advanced controls do not
promote every part of that category.

| Category | Baseline | Candidate | Current tier | What improved and what still prevents the next tier |
| --- | ---: | ---: | --- | --- |
| Architecture & Structure | 6.0 | 6.5 | Common/Solid | Shared lifecycle authorization and focused workflow extraction improve consistency. Cross-layer imports, oversized orchestrators and absent enforced dependency rules still limit structural assurance. |
| Code Quality & Maintainability | 6.0 | 7.5 | Advanced in enforced gates | Lint/types and unchanged size/complexity limits pass; broad regressions now enforce relational fixtures. Passing gates do not remove widespread route assertions or all large functions. |
| Security | 6.0 | 7.0 | Common/Solid | Retained-data authorization, restricted database roles and scoped storage permissions have negative tests. Copied-token logout, refresh-family replay response, account-wide credential budgets and independent audit anchors remain open. |
| Performance | 6.0 | 6.5 | Common/Solid | Duplicate membership amplification and unbounded cluster hydration are fixed with tested continuation behavior. Full-group projection, blocking bcrypt, unbounded legacy parameters and representative query plans remain unresolved. |
| Scalability | 5.5 | 5.5 | Common/Solid | Durable workers already provide useful separation. The deployment still has one VPS failure domain; no current accepted load envelope or replica/surge-aware pool budget was established. |
| Reliability & Resilience | 6.0 | 7.0 | Common/Solid with advanced verification | Real service contracts, three production-image browser engines, branch floors, actual worker failure/recovery and Prometheus rule execution now have evidence. Received alerts, operational ownership and representative disaster recovery remain incomplete. |
| Browser & Frontend Practices | 6.5 | 7.0 | Common/Solid | All frontend tests pass; restricted-storage fallback and PDF URL cleanup are checked. Modal keyboard behavior, central render-error reporting, camera/device coverage and wider cross-browser journeys remain incomplete. |
| API Design | 6.5 | 6.5 | Common/Solid | Duplicate continuation is explicitly represented. Error-envelope inconsistency, password UTF-8 byte limits, legacy pagination limits and OpenAPI/runtime mismatches remain. |
| Data Layer | 6.0 | 7.0 | Common/Solid | Runtime/migration privilege separation, escaped URLs, actual foreign-key negatives and local restore reconciliation improve assurance. Missing tenant tuple constraints, ECR invariants and production PITR/recovery proof remain. |
| Dependency & Tooling Hygiene | 6.5 | 7.0 | Common/Solid | A maintained, digest-pinned object provider and tested data-preserving transition replace the unsupported default in the candidate release path. Whole-image attestation/promotion and advisory-exception lifecycle remain incomplete; native dependency remediation is excluded. |
| Documentation | 6.5 | 7.0 | Common/Solid | Current schema/workers/Compose overlays and release/recovery boundaries now agree. Contributor onboarding, current capacity guidance and accountable operational evidence still need completion. |

## Exact finding accounting

The original register contains **44 formal groups: 10 High, 30 Medium, 4 Low**.
There were no independently confirmed Critical findings. Shared IDs in one
original row count once. Two unnumbered observations are tracked separately;
they do not change the denominator or create a fifth formal Low finding.

| Priority | Fixed in candidate | Partial, not fixed | Open | Original total |
| --- | ---: | ---: | ---: | ---: |
| High | 8 | 2 | 0 | 10 |
| Medium | 3 | 4 | 23 | 30 |
| Low | 0 | 0 | 4 | 4 |
| **Total** | **11** | **6** | **27** | **44** |

High closures are SEC-01 / ARC-03, DATA-01, QUAL-01, PERF-02, DOC-01, DEP-01,
REL-01 and REL-02. The two partial High groups are **REL-03** (operational alert
and response assurance) and **DATA-05** (production disaster recovery).
Medium closures are **REL-05**, **UI-03 / QUAL-05**, and **DATA-04**.
The [full status ledger](status.md) maps every original group to the code,
evidence and remaining acceptance criteria. Partial groups are not counted fixed.

## Evidence supporting the improvement

- Backend: **4,262 passing core cases**, plus **3 newly added SQLite cases** and
  **132 unique real-service cases** = **4,397 distinct cases with passing evidence**.
  The core run intentionally skipped the opt-in service cases. The separate
  service lane first passed 127, failed four stale test fixtures and skipped one
  missing explicit Redis setup; targeted corrected runs cover all five. This is
  explicitly split-run evidence, not one all-green 132-case sweep.
- Backend coverage: **77.82% lines / 60.33% branches**, with global floors,
  65 original module ratchets and 11 critical line/branch gates passing. Coverage
  includes a full measurement plus a targeted append after a clock-fixture
  correction; the final independent core regression passed. Some email/export
  areas remain below 30% line coverage.
- Frontend: **789 tests in 118 files**, lint/types and all 24 module ratchets pass.
  The **95.15% line / 90.26% branch** result measures nine selected files, not the
  entire frontend. No native app release or device smoothness claim is made.
- Database roles: **18 real PostgreSQL assertions** cover denied privilege
  escalation, protected audit/schema writes, preserved rows, idempotence and
  reserved-character/Unicode credential connections.
- Production-image qualification: real TLS/session flows pass in Chromium,
  Firefox and WebKit. Actual private upload, scanner, API, database, storage,
  tenant denial and durable worker recovery are joined. External AI and WhatsApp
  delivery are outside this proof.
- Storage: real legacy-provider migration preserves and independently verifies
  **1,001 historical versions**, with source retention, bounded streaming,
  metadata/tag checks, concurrent-copy rejection and interruption safeguards.
  Provider IDs/timestamps change; uncertain writes stop for reconciliation or a
  fresh destination. This is a maintenance-window migration, not zero downtime.
- Recovery/monitoring: local synthetic restoration matches ten table digests and
  14 real object references; actual Prometheus thresholds fire and resolve during
  a consumer fault. These do not prove production recovery time or human alerts.

Detailed receipts: [regression](reliability-regression-evidence.json),
[service contracts](service-integration.md), [web](frontend-performance.md),
[storage](storage-verification.md), [joined journeys](reliability-joined-evidence.json)
and [synthetic recovery](reliability-recovery-evidence.json).

## Actual production evidence and remaining priorities

Read-only SSH inspection confirms the original deployed revision and legacy
MinIO, existing PostgreSQL and object volumes, and local database dump artifacts.
After owner sign-in, the actual Hostinger account also confirms **weekly backups
stored outside the VPS**: September 23 (64.22 GB) and September 16 (31.73 GB),
both listed in Malaysia while the VPS is in Mumbai. Matching backup creation
events show Success. This is verified backup presence, not a tested restore.
The provider's displayed 1h 54m restore estimate is not measured application RTO.

1. **High — DATA-05:** qualify recovery into a separate destination, reconcile
   database/object/Redis state, establish selected-time PostgreSQL recovery and
   protected retention, and agree and measure RPO/RTO. Never restore over the
   live VPS just to test the backup. Weekly backup presence alone leaves a
   potentially multi-day loss window.
2. **High — REL-03 (setup deferred by owner):** establish collection outside the VPS, a real receiver,
   primary/backup responders, retention and approved service objectives; retain
   an actual delivered and acknowledged fault alert.
3. **Medium:** prioritize the remaining token/session controls, password byte
   validation, pagination/request cost, audit assurance and tenant DB invariants;
   then address capacity, query plans, accessibility, API consistency and release
   artifact provenance. Exact IDs and acceptance criteria remain in the ledger.
4. **Low:** remove unsafe typed-route assertions and dormant rollout debt;
   enforce the supported developer interpreter and improve the onboarding path.

The candidate has not been pushed or deployed. Production has not been
restarted, migrated, restored, rescheduled or otherwise modified by this
inspection. A Git pull alone is not the storage/role transition; the
[reviewed release procedure](../CURRENT_RELEASE_AND_STORAGE.md) retains source
data and verified backups and stops on failed checks. Absolute freedom from
regressions or data loss cannot be established by local tests. The all-ten-High
goal remains unfinished until the two operational requirements are satisfied.
