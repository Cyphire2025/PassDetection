# Real-service qualification and database privilege evidence

Date: 26 September 2026. This is isolated synthetic qualification of current
candidate source, not a production deployment or an immutable build attestation.
The project `passdetection-service-contract-qualification` has its own PostgreSQL,
Redis, maintained private S3 service and Celery worker. It does not use the live
VPS or the earlier joined-journey database/Redis. Test source was mounted read-only
into a Linux image derived from the qualified backend runtime, with exact CI test
tools installed. The runtime was CPython 3.11.16, pytest 9.0.3, pytest-asyncio 1.4.0
and pytest-cov 5.0.0. Coverage was disabled for this separate contract lane.

The database was migrated from empty to `0107_passport_ecr_checks`; topology and
`alembic check` passed. The application database, FCM transaction-fixture database
and subsequent role-qualification database are separate synthetic databases.
The maintained S3 service uses the reviewed SeaweedFS 4.47 digest, a versioned
fixture bucket and scoped application credentials. An actual prefork Celery
worker consumed the dedicated `enterprise-ci` queue and answered its control ping.

## Results and exact counting

**All 132 distinct service cases now have passing evidence across the full
initial run and focused follow-up runs. This was not one all-green full run.**

| Run | Result | Time | Contribution to final unique passing cases |
| --- | --- | ---: | ---: |
| Initial complete real-service lane | 127 passed, 4 failed, 1 skipped | 533.37 s | 127 |
| Manual-review PostgreSQL family after local fixture repair | 6 passed | 112.85 s | 2; four were already passing |
| Traveller document HTTP family after local fixture/assertion repair, fully wired Linux rerun | 2 passed | 6.10 s | 2 |
| Explicit isolated real Redis startup/capacity test | 1 passed | 0.28 s | 1 |
| **Distinct cases with final passing evidence** | **132; no unresolved failure or skipped case** | — | **132** |

The first two failures supplied no email even though the existing use case
requires one. The test now supplies valid contact data and surfaces an early
task exception instead of hiding it behind an event timeout. Real row-lock,
concurrent duplicate submission and late-extraction assertions remain intact.

The two document HTTP fixtures did not match the configured approved welcome
template and expected welcome to be mandatory before document delivery, contrary
to existing behavior. Only that test file changed: it now exercises document
delivery before welcome, processes signed receipts and verifies exactly the
two actual traveller destinations, no qualifier and no duplicate send when the
durable document batch is processed again. The native apps and application code
were not changed to make these cases pass.

The Redis case originally lacked its explicit opt-in URL. It now runs against a
separate Redis instance with the required safe hostname, port 6379 and database
15. Its four concurrent startup probes and real global-capacity rejection pass;
the safety guard was not relaxed. The CI owner added the corresponding explicit
isolated target so this case cannot silently remain outside the intended lane.

Three new PostgreSQL cases within the 132 prove an existing email ownership
constraint on the Alembic-migrated schema: valid parents succeed, while missing
connections, existing parents in another tenant and existing parents owned by
another user fail with the expected foreign-key violation. The matching three
SQLite cases passed separately with foreign keys enabled. This strengthens
constraint-test assurance and does not close DATA-02's missing passport constraint.

The initial complete log and its failures are retained under
`outputs/service-integration-qualification/service-tests-first.txt`. Follow-up
logs, service identities and image ID are in that same directory. The compact
[machine-readable receipt](service-integration-evidence.json) reconciles these
runs without double-counting. The manual-review result is retained in
[its final log](manual-review-postgresql-final.txt); the additional host document
run also passed two cases in 129.46 seconds before the Linux confirmation.

## Independent role qualification

A fresh `passdetection_ci_roles` database was migrated to the current head and
the actual `qualify_database_roles.py` completed **18 assertions**. These include
idempotent provisioning, preserved data, runtime CRUD and audit append, denied
DDL/audit mutation/role assumption and column-grant bypass checks, migration
authority, and authenticated synchronous/asynchronous DSNs using a synthetic
reserved-character and Unicode password. The [compact role result](database-role-final.txt)
is separate from the 132 service-test count.

These results do not establish production grants, deployment, off-host backup,
PITR, representative RPO/RTO, external provider delivery or human alert receipt.
REL-03 and DATA-05 retain their independent operational acceptance boundaries.
