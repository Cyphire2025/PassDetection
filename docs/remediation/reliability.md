# Reliability, regression and recovery remediation evidence

Date: 2026-09-26. Scope: REL-01, REL-02, REL-03, REL-05 and DATA-05 from the
independent audit. This work used source review and isolated executions; no
Codex Security Scan, customer data, production deployment or real notification
to a person was used. The production host is reported as Hostinger KVM4. Its
external monitoring remains unverified. A subsequent read-only Hostinger account
inspection confirms weekly backups stored outside the VPS (September 23 and
September 16, in Malaysia). Their creation records show Success; a tested
production restore, PITR and human alert receipt remain unproved.

## Status and evidence boundaries

| Finding | Implemented and verified | Remaining limit |
| --- | --- | --- |
| REL-01 | Shared SQLite connections enable/assert foreign keys before schema creation. Invalid test graphs were repaired; a real gallery insert-order defect was fixed. Python 3.11 branch measurement, repository floors and explicit critical-path floors added. | Final aggregate test/coverage result is recorded below. Coverage remains uneven; percentage gates do not establish exhaustive behavior or PostgreSQL equivalence. Frontend coverage is handled by its separate workstream. |
| REL-02 | Disposable production-image Nginx/TLS/API/PostgreSQL/Redis/private S3/ClamAV/Celery lane. Three browser engines exercise real sessions; HTTP journeys exercise scanned upload, public review/finalization, private read, tenant denial and durable work. Image IDs/logs/traces/source hashes retained. | External Gemini and WhatsApp delivery are intentionally excluded. A pending synthetic contact challenge is seeded; actual verification and consumption run. Native apps were not changed or qualified here. |
| REL-03 | Reviewed rules, real collector-compatible metrics, incident runbooks, synthetic rule tests, isolated worker faults, and a fail-closed private operational-receipt validator. | Production collector, independently retained telemetry/audits, actual responders and alert receipt/acknowledgement are unverified. This operational gate remains open. |
| REL-05 | Closed for the engineering finding: ECR consumer/both ledgers in optional health, counts/age gauges, real consumer outage, actual Prometheus firing/resolution, durable terminal result after recovery and duplicate-delivery suppression all passed. | The deliberately expired image ends in a correctly recorded failure; external classifier success and human notification are outside this qualification. |
| DATA-05 | Current schema `0107_passport_ecr_checks` restored to a separate synthetic database with matching row digests. Historical S3 object version restored. Application models and storage adapter read restored rows and reconcile uploaded-object checksums. | Local rehearsal does not prove off-host backup, WAL/PITR, independently protected retention, Redis-domain recovery, production volume, approved RPO/RTO, failover or a full production reconnect. This enterprise gate remains open. |

REL-04 release-manifest, backup-before-migration and rollback safeguards belong
to the central release workstream. A local image test is not a claim of signed
registry publication, completed deployment or exercised production rollback.

## Regression semantics and coverage

The core regression and coverage runtime is CPython 3.11.15 with the hash-locked
runtime dependencies and exact CI test tools. The qualified Linux image reports
3.11.16; `service-integration-evidence.json` identifies the runtime used for each
separate service execution. `backend/tests/conftest.py` applies
`PRAGMA foreign_keys=ON` on each shared SQLite connection before `create_all`
and asserts the setting. Teardown disposes the in-memory database without
issuing constraint-hostile table drops. `backend/tests/persistence.py` persists
explicitly supplied parents before children. It does not invent absent parents.

Fixture repairs preserve application invariants. Tests now create agencies,
users, groups, assignments and attendance sessions that their children require.
Tests deliberately attempting orphan changes assert an integrity error and
rollback. No production constraint or authorization policy was loosened to
make the suite pass.

The gallery ingestion regression was a product defect: `_persist_batch_assets`
queued parent assets and child variants without ORM relationship ordering.
An enforced foreign key exposed child inserts preceding parents. The fix
flushes the bounded parent batch once, then adds variants in the same outer
transaction. Existing atomicity, cancellation and idempotency tests pass with
the constraint enforced; it does not introduce a per-asset flush loop.

The final complete-source branch run used an independent `COVERAGE_FILE` and
executed 4,387 tests: 4,257 passed, 129 were skipped and the collection-time
expiry fixture described below failed. The repaired fixture and final ECR
retry-count contract were measured in a subsequent **27/27 passing** branch
append. A separate complete no-coverage run verifies the final test state;
its outcome is recorded below. Earlier fixture failures and an earlier shared
coverage-file collision are not presented as successful runs.

Complete-source measurement: **77.82% line / 60.33% branch** — **52,787 of
67,828 lines** and **10,487 of 17,384 branches**. The combined coverage figure
shown by pytest is different because it mixes line and branch opportunities.
The measured gates in `backend/backend_quality_budgets.json` now require:

- Repository-wide **75% line / 58% branch**, with branch measurement mandatory.
- Eleven behavior-heavy security/reliability modules have independent line
  and branch gates: authorization, upload capability, initial/final submission,
  JWT, authenticated dependencies, public OTP, durable cleanup, readiness, ECR
  readiness and gallery ingestion.
- Sixty-four of 65 legacy per-module line ratchets increased; the already high
  declarative-model floor was retained. Floors include a small measured margin
  and are checked into source, not recalculated downward during CI.

For example, measured authorization coverage was 92.18/85.87%, upload capability
100/100%, public contact verification 99.39/97.06%, and client finalization
88.40/79.03% (line/branch). Email synchronization at 24.80%, document assignments
at 26.21%, and some export/import routes below 30% remain weak. They are not
described as enterprise-grade merely because the overall gate passes.

`verify_backend_quality_budgets.py` now rejects statement-only coverage, missing
critical modules, global regressions, branch regressions even when lines pass,
duplicate coverage entries, and non-finite thresholds. Seven focused gate tests
pass. A separate collection-time clock defect in a My Photos test was repaired:
a supposedly overlong +600-second expiry could age into the allowed +300-second
window before execution. The case now constructs its expiry at test execution;
all 24 contract tests pass without weakening the expiration check.

Final aggregate regression: **4,262 passed / 129 skipped / zero failures in
559.71 seconds**, exit code zero. Marker collection confirms all 129 skips
belong to the explicitly enabled `service_integration` lane. Three new SQLite
ownership-constraint cases were added after that full collection and passed
separately in 1.15 seconds; their three migrated-PostgreSQL counterparts run in
the separate 132-test real-service lane. That lane's complete result is recorded
in `reliability-regression-evidence.json`: its initial sweep had **127 passed,
four failed and one skipped** in 533.37 seconds. The four failures were stale
fixtures for mandatory contact details and optional welcome/template behavior;
the missed Redis test needed its explicitly guarded isolated target configured.
Targeted real-service reruns then passed six manual-review cases (two repaired,
four previously passing), two document HTTP cases and the Redis startup case.
That evidences **all 132 unique service cases**, with no outstanding failure or
skip; it is deliberately not described as one clean 132-test sweep. Across the
core run, new SQLite cases and service lane, **4,397 unique backend cases** have
passing evidence. No production validation or concurrency timeout was weakened.
The reconciled service receipt is `service-integration-evidence.json`; its final
Linux document HTTP confirmation passed two cases in 6.10 seconds, independently
of the earlier passing host confirmation.

CI requires the full real-service lane's JUnit output to be nonempty and have
zero skips. It also migrates a separate synthetic role-qualification database
and exercises 18 actual PostgreSQL identity/privilege/row-preservation checks,
including runtime passwords with reserved and Unicode characters. That separate
qualification passed locally; see `database-role-final.txt`.
The full branch measurement and all 65 module/global/critical coverage gates
pass. The curated receipt records both the passing final regression and the
earlier coverage run's repaired fixture failure without concealing it.

## Joined production-image evidence

`docker-compose.qualification.yml` is a separate fixed project, uses synthetic
credentials and a generated short-lived localhost certificate, and never
includes production Compose files or `.env`. PostgreSQL is migrated and roles
are provisioned before the restricted API starts. The maintained S3 fixture
uses SeaweedFS 4.47 at an immutable digest, a private data network, a separate
S3 gateway, and the same scoped identity generator as the release workstream.
Administrative bucket bootstrap/versioning uses independent fixture credentials.
Runtime IAM denies bucket administration and permanent historical-version
deletion. The unauthenticated filer/master are not on the application network.

The final production frontend and backend image IDs are retained in
`outputs/qualification/images.log`. `source-evidence.json` records the Git base
and source-file hashes at evidence capture; it is labelled as a working-tree
snapshot, not a signed build attestation.

The current production-image browser suite passed **3/3 in 40.9 seconds**:
Chromium, Firefox and WebKit each used their own seeded account and real password
plus TOTP authentication. It checked Secure/HttpOnly/SameSite cookies, session
lookup, hostile-Origin refresh rejection, allowed refresh, reload, dashboard
deep link and logout. No API response interception or synthetic cookie injection
is used. The harness waits for the dashboard's initial coordinated renewal
before probing refresh itself, avoiding a test-induced stale-cookie race.

The real HTTP journey additionally passed:

1. Create a scoped synthetic upload group through the authenticated API.
2. Upload two synthetic booklet-cover images through Nginx and real ClamAV.
3. Persist the draft, read its capability-protected preview, deny a wrong
   capability and deny an anonymous authenticated-file request.
4. Seed only a pending synthetic OTP delivery result; call real OTP verification
   and final submission endpoints. Verify consumption and final private-key
   promotion without falsely asserting AI verification.
5. Read the final private file through the staff route and storage adapter;
   compare SHA-256 and inspect persisted status/contact proof/audit independently.
6. Authenticate a manager belonging to a different synthetic agency and prove
   the same private file returns 403.
7. Stop the general worker, persist an encrypted cleanup tombstone and publish
   its real Celery task, restart, and require the object to disappear with one
   completion audit and no remaining tombstone.

The qualification's overall `/ready` deliberately remains degraded for missing
external Gemini credentials/capacity. Fault assertions permit only that declared
omission; unrelated configured traffic-gating capabilities must remain healthy.
This does not mislabel unconfigured AI as available or certify a production
environment from a local synthetic test.

Evidence: `docs/remediation/qualification-browser-final.txt`,
`outputs/qualification/joined-journey-evidence.json` and the corresponding
`application-journey.log`, `worker-completion.log`, service logs and browser traces.
The curated, publishable receipt is `reliability-joined-evidence.json`; it omits
synthetic session and object identifiers and explicitly records the consumer's
unavailable state after its bounded readiness cache expires.
CI runs the same production-image lane after its existing build/test gates.

## ECR health and alert evidence

The optional `ecr_checks` capability reports consumer health plus pending,
failed and retry counts and oldest pending age from both standalone and passport
ledgers. Queries aggregate in SQL and return no identifiers or document content.
A savepoint prevents a failed optional query from leaving PostgreSQL's enclosing
transaction aborted. Failure reports unavailable, never a fabricated zero backlog.
Consumer probes use the existing bounded/cached readiness machinery.

Fifteen ECR/runtime/deadline tests pass. The pinned Prometheus `promtool` tests
prove consumer-failure firing/resolution, stale queue age and lost collection.
The real isolated consumer fault has also passed available → unavailable →
available, retaining the optional `traffic_gate: false` distinction.

Real collector/queue-drain extension: **passed**. With unchanged production
thresholds, both alerts actually fired in Prometheus after **300.25 seconds**.
The consumer then drained the stale expired-image row to a single durable
`image_expired` terminal failure with **attempts=1**, despite duplicate task
deliveries; no classifier call occurred. Both alerts resolved **10.12 seconds**
after recovery. Evidence is retained in `ecr-alerts-firing.log`,
`ecr-alerts-resolved.log` and `ecr-worker-completion.log` under
`outputs/qualification`, and the joined JSON evidence. This proves the real
metric/collector/rule path but not delivery to an external human recipient.
A terminal failure is not a successful ECR classification.

## Recovery and operational gate

The maintained-provider local restore completed in **20.813 seconds** for its
tiny synthetic dataset. PostgreSQL revision and full-row count/digests matched
for ten tables: agencies, users, groups, submissions, audit logs, refresh tokens,
public upload contact challenges, ECR batches, ECR items and storage cleanup jobs. The
separate restore target refuses overwrite. A versioned synthetic object was
overwritten, its historical content recovered, and the restored current content
checked byte-for-byte.

A separate application read against the restored database verified **14
real uploaded-object references** using the application storage adapter,
content hashes and object checksum metadata. Three explicitly declared rendering
placeholders were excluded and counted. This is bounded synthetic reconciliation,
not a claim that every production reference has been audited.

Evidence: `outputs/qualification/recovery-evidence.json`,
`docs/remediation/qualification-recovery-final.txt`, and
`outputs/qualification/recovery-application-objects.log`. A curated result is
retained in `docs/remediation/reliability-recovery-evidence.json`.

`monitoring/alerts.yml`, `monitoring/statsd_mapping.yml` and
`docs/OPERATIONS_MONITORING.md` define initial alert thresholds and response
procedures. `scripts/verify_operational_evidence.py` validates a private operator
receipt package without network calls or writes. The committed
`monitoring/operational-evidence.example.json` deliberately fails. Four semantic
tests exercise missing/stale/future/changed receipts, same-host failure domains,
missing PITR/Redis proof and breached recovery objectives. A green result proves
only a complete, timely, checksum-consistent supplied package; an independent
reviewer must authenticate its contents against the real infrastructure.

Still required before closing REL-03/DATA-05: actual backup/monitor inventory,
independent encrypted deletion-protected backups and retained telemetry, proven
WAL/PITR, separate Redis/security-domain recovery, representative application and
object reconciliation, approved measured RPO/RTO, and a real responder's dated
alert receipt and acknowledgement. Local scripts and synthetic tests cannot
substitute for those facts.
