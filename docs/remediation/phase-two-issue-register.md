# Complete prioritized issue register — phase-two checkpoint

27 September 2026. This describes the local candidate, **not the running production release**. Original category reports retain their source evidence and acceptance wording. Linked IDs count as one group.

**Original44 groups:37 locally closed, three active partial, three deferred partial and one excluded native group.** The deferred groups are external alerts REL-03, production disaster recovery DATA-05 and independent audit-checkpoint custody SEC-06. This phase contains30 groups:26 locally closed, three active, one deferred. The earlier33 unfinished total also included two deferred High groups and one excluded native Medium.

No independently confirmed Critical original finding exists. High groups remain highest priority for production because local closure does not establish deployment. No phase-two push or deployment is claimed. Physical device/accessibility acceptance, exact final artifact qualification and remote signing evidence remain visible. GitHub history protection, main-only artifact environment with owner approval and release immutability have now been applied and read back; actual signed publication remains pending.

## Original findings, highest to lowest priority

| Priority | Original ID(s) | Original concrete defect | Current candidate status |
| --- | --- | --- | --- |
| High | REL-03 | Retained current alert routing/response/SLO proof not established | Deferred / partial |
| High | DATA-05 | Production off-host/PITR/object/Redis recovery and measured RPO/RTO unproved | Deferred / partial |
| High | SEC-01 / ARC-03 | Search and direct-read lifecycle policy permit retained deleted passport access that ordinary lists forbid | Locally closed |
| High | DATA-01 | Fresh supplied deployment reuses PostgreSQL bootstrap superuser for application runtime | Locally closed |
| High | QUAL-01 | Frontend lint and frontend/backend budget gates fail; local backend Ruff also reports three imports | Locally closed |
| High | PERF-02 | Oversized duplicate cluster returns entire cluster and repeats all member IDs per row | Locally closed |
| High | DOC-01 | Active central release instructions override expected schema with 0093 while current head is 0107 | Locally closed |
| High | DEP-01 | Default pinned community MinIO service has unmaintained upstream | Locally closed |
| High | REL-01 | Critical coverage floors allow roughly 12–23%; shared SQLite fixture does not enforce FKs | Locally closed |
| High | REL-02 | Mocked development-server browser tests do not verify joined production stack | Locally closed |
| Medium | SEC-06 | Audit chain has no implemented independent anchor; sensitive-read audit incomplete in sampled paths | Deferred / partial |
| Medium | SCALE-04 | No current demonstrated workload capacity envelope | Locally closed within declared envelope |
| Medium | REL-04 / DEP-04 | Whole-image provenance and immutable artifact promotion not established by package locks/build-only CI | Partial / active |
| Medium | UI-01 | Some modals lack consistent focus entry/containment/return despite shared correct primitive | Partial / active |
| Medium | UI-02 | Browser CI only Chromium | Partial / active |
| Medium | UI-04 | Shared web render error boundary logs locally without central reporter | Locally closed |
| Medium | DEP-02 | Mobile URI decoder lock matches one current DoS advisory | Excluded native scope |
| Medium | ARC-01 | 83 application imports across 41 modules point into infrastructure/presentation contrary to advertised strict rule | Locally closed |
| Medium | ARC-02 / QUAL-02 | Large multi-responsibility route/components concentrate orchestration and state | Locally closed |
| Medium | SEC-02 | Ordinary logout leaves copied access JWT valid until its expiry | Locally closed |
| Medium | SEC-03 | Refresh replay rejects consumed token but does not revoke successor family | Locally closed |
| Medium | SEC-04 / API-02 / PERF-03 | Plain legacy page-size parameters flow to SQL without maxima | Locally closed |
| Medium | SEC-05 | Pair-based credential throttle lacks account-wide distributed budget; mobile failure timing differs | Locally closed |
| Medium | PERF-01 | Sync bcrypt blocks async authentication worker | Locally closed |
| Medium | PERF-04 / SCALE-03 | Full authorized group processed for ordinary page/polling requests | Locally closed |
| Medium | PERF-05 | Substring/JSON search lacks demonstrated query-specific index plan | Locally closed |
| Medium | SCALE-01 | Fixed container names and single failure-domain deployment limit supplied scaling topology | Locally closed |
| Medium | SCALE-02 | DB pool preflight counts one API/worker group, not replicas/surge | Locally closed |
| Medium | REL-05 | ECR worker health not represented as API capability/backlog readiness | Locally closed |
| Medium | UI-03 / QUAL-05 | Hotel scan helper throws when localStorage denied; duplicate helper catches failure | Locally closed |
| Medium | API-01 | Domain/HTTP errors use incompatible response envelopes | Locally closed |
| Medium | API-03 | Password schema accepts 73 UTF-8 bytes while bcrypt 5 rejects above 72 | Locally closed |
| Medium | API-04 | OpenAPI auth/errors/binary representations disagree with runtime | Locally closed |
| Medium | DATA-02 | Independent passport group/agency FKs do not enforce matching tenant tuple | Locally closed |
| Medium | DATA-03 | Standalone ECR state/result/counter DB invariants weaker than adjacent ledger | Locally closed |
| Medium | DATA-04 | Raw database DSN interpolation mishandles valid secret characters | Locally closed |
| Medium | DEP-03 | Backend advisory exception lacks enforced owner/expiry/reachability lifecycle | Locally closed |
| Medium | DOC-02 | Main local setup permits unsupported interpreter and bypasses hashed lock | Locally closed |
| Medium | DOC-03 | Capacity guide labels old 81-connection/32-extractor table current | Locally closed |
| Medium | DOC-04 | Main enterprise/strict architecture claims exceed current evidence | Locally closed |
| Low | QUAL-03 | Route assertions bypass part of typed-route checking | Locally closed |
| Low | QUAL-04 | Dormant commented crop flow retains state/handlers | Locally closed |
| Low | DEP-05 | Local Python 3.13 differs from supported 3.11 | Locally closed |
| Low | DOC-05 | Current contributor/operations reading path fragmented | Locally closed |

Within severity, unresolved requirements precede locally closed groups. SCALE-01 would be High before a multi-host HA promise, and SCALE-04 High before an unsupported capacity promise; neither promise is made here.

## Additional findings and total accounting

The separate [additional findings register](additional-findings-register.md) contains 15 engineering defect groups: six High, four Medium and five Low. Some were pre-existing; others were introduced and caught during remediation or concern verification tooling. They do not inflate original closure credits. Individual scanner matches are not counted as independent confirmed application exploits.

**44 original groups + 15 separately tracked additional groups = 59 tracked engineering issue groups.** This excludes the two unnumbered observations below and is not a count of 59 exploitable vulnerabilities. The original closure total remains37. Additional findings retain their own evidence/status and are not all declared release-qualified.

## Unnumbered observations and nice-to-have work

- Repeated family-size constants: addressed by one named2–20 bound; supporting cleanup, not another formal Low issue.
- Conditional older-native response-buffer bound: remains excluded with native implementation; no affected physical device was originally demonstrated.
- Further decomposition where change patterns justify it, more device coverage, independent release reviewers and multiple physical failure domains are improvement work. They do not create invented original finding groups.

## Evidence and release order

Use [current Medium/Low progress](phase-two-progress-2026-09-27.md) for closure receipts and remaining gates, and the original Desktop category reports for source references and standards. Refresh the 59-group count if another independent additional defect is accepted.

Local software/browser-engine/capacity and exact image gates passed; retain outstanding physical-device and screen-reader acceptance; commit intended changes; push main; verify CI/signing/protected promotion and retained artifacts; then perform the authorized guarded VPS rollout. Preserve records, uploads, object versions, volumes, backups and unrelated files. No production cleanup or destructive restore is authorized.
