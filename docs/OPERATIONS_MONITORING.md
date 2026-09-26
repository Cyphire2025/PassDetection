# Operational monitoring and incident ownership

The repository now supplies reviewed Prometheus rules in `monitoring/alerts.yml`
and executable firing/resolution tests in `monitoring/alerts.test.yml`. These are
installation inputs, not evidence that anyone is receiving production alerts.
Actual external monitoring and alert routing remain unverified. Read-only
Hostinger account inspection confirms weekly off-server backups; it does not
establish tested recovery, PITR or human alert receipt.

## Required installation record

Before claiming the operational gate is closed, record the production collector
URL, alert destination, a named primary and backup responder, retention policy,
external uptime probe URL, and a dated synthetic alert with its received and
acknowledged timestamps. `platform-oncall` and `recovery-owner` labels are routing
roles; the operator must map them to actual people in the private operations
register. Keep credentials and contact details out of this repository.

Run collection and alert delivery outside the application VPS failure domain.
Scrape the private StatsD exporter through a protected network; never expose its
port publicly. Install a blackbox HTTPS probe as job `passdetection-https` and
StatsD collection as job `passdetection`. Collect host disk metrics with node
exporter. Evaluate these rules every minute. Suggested initial retention is
30 days of metrics and 90 days of security/error events, subject to the approved
privacy and retention policy. Approve actual availability and latency SLOs before
representing these starting thresholds as contractual commitments.

## HTTP and dependencies

Check `/api/v1/health/ready`, recent sanitized request IDs and dependency health.
Compare errors and latency with the last release manifest. Check PostgreSQL
pool use/locks, storage and Redis before restarting healthy API processes.
Preserve current/previous image digests. Use the release runbook's schema-aware
rollback decision. Never downgrade the database automatically.

Probe `/ready` every minute to refresh optional capability gauges; API process
liveness alone cannot report queue health. Configure independent alerts for
backup/WAL age, storage failures and malware definition freshness from the actual
backup/storage/scanner providers. Their metric names are provider dependent;
inventing exporter metrics here would create silently inactive rules.

## ECR queue

`capabilities.ecr_checks` reports worker availability, pending/failed/retry counts
and oldest pending work from both durable ECR ledgers. It deliberately does not
take unrelated dashboard traffic offline. Inspect the `ecr_checks` consumer,
provider limits and DB leases. Restart the missing consumer after its dependency
is restored; do not delete broker queues or manually reset committed results.
Confirm pending age falls and rows finish through the existing idempotent worker.

## Collector and retention

An absent exporter is an incident, not an empty healthy dashboard. Check scrape
targets, network policy and collector storage. Install an external dead-man
check for the monitoring pipeline itself; a failed collector cannot alert about
its own host loss. Export logs/audit evidence into a separately administered sink.
Retain the actual notification and acknowledgement receipt for each drill.

## Disk pressure

Check the host filesystem, PostgreSQL/WAL growth, object-store usage and bounded
log retention. Do not delete database/WAL files or passport objects to recover
space. Expand storage or follow the reviewed application retention workflow.

## Recovery evidence

Publish `passdetection_last_successful_restore_timestamp_seconds` only after a
successful isolated restore, DB/object checksum reconciliation and application
validation. The metric is not a backup-success timestamp. Record the evidence
package and measured RPO/RTO described in `PRODUCTION_RESILIENCE_AND_DR.md`.
Missing restore evidence or a missing HTTPS probe series alerts as unavailable;
an unconfigured collector must not appear healthy merely because it has no data.

## Isolated rule validation

Use the pinned Prometheus image recorded in the CI job to run:

```sh
promtool check rules monitoring/alerts.yml
promtool test rules monitoring/alerts.test.yml
```

Tests prove the stated expressions fire and resolve for synthetic samples. They
do not prove a production collector, Alertmanager receiver, human response,
off-host retention, PITR or restore capability. The release gate remains open
until those operational receipts exist.

## Callable evidence gate

Copy `monitoring/operational-evidence.example.json` to a private evidence directory
outside the repository. Complete it from actual provider records and drill
receipts, including SHA-256 hashes of the referenced files. Keep receipt paths
relative to that directory. The committed example intentionally fails validation:
unknown details and synthetic CI artifacts must not count as operational proof.

```sh
python scripts/verify_operational_evidence.py /private/operations/evidence.json
```

The command performs no network calls or writes. It rejects missing receipts,
changed bytes, evidence older than 35 days, future/reversed timestamps, a backup
or monitor sharing the application's failure domain, unmeasured RPO/RTO and
missing application/object/Redis/PITR drill results. It checks the documented
initial retention minima, which must be reviewed alongside the approved policy.
Passing checks means the supplied package is complete and internally consistent;
a named independent reviewer must still verify its contents against the actual
infrastructure. It cannot authenticate operator assertions or create missing
off-host backups, monitoring, immutable retention or human acknowledgements.
