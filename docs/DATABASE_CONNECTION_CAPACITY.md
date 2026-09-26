# PostgreSQL deployment connection capacity

Owner: repository maintainer (Nipun / Cyphire2025). Reviewed 2026-09-27; next review 2026-12-25.

The authoritative numeric table is [the generated deployment budget](DATABASE_CONNECTION_CAPACITY.generated.md). Current single-instance application pools claim 56 connections against 100 PostgreSQL slots with 10 reserved for operations. The reserve includes three simultaneous maintenance sessions; external application consumers are declared as zero. These declarations must match actual consumers.

`scripts/verify_database_deployment_budget.py` counts every API process, Celery prefork/autoscale maximum, Beat process, pool base/overflow, rendered service replica and permitted rollout overlap. `tooling/database-deployment-budget.json` declares external consumers and per-service surge. Current stop/drain/start uses zero surge; rolling overlap needs a reviewed nonzero declaration. New/unreviewed consumers, missing or unbounded pools, inconsistent ceilings and over-budget deployments fail closed.

CI's rendered Compose verifier and `release_current.py` preflight run the gate. Render the complete intended manifest including all overlays and replica counts. Ad hoc `docker compose --scale`, manually launched containers and external orchestrators bypass the supported release contract. Before supporting them, their peak topology must enter the same gate. Process-local settings validation cannot discover other containers.

Two API replicas with the old `8 + 2` pool claim 96 application connections and fail against 90 usable slots. One API rollout overlap fails identically. Reducing each API process to `4 + 2` permits two replicas plus current workers: 64 application connections; adding eight declared external connections leaves 18 headroom. [Actual PostgreSQL evidence](remediation/database-capacity-evidence.json) holds all 64 sessions and executes concurrent queries. It does not certify throughput, failover or Hostinger workload capacity.

Regenerate the numeric table after reviewing a protected rendered Compose JSON file:

```bash
python3 scripts/verify_database_deployment_budget.py /protected/rendered-compose.json --markdown docs/DATABASE_CONNECTION_CAPACITY.generated.md
```

Rendered Compose can contain credentials: never commit or attach its input. Generated reports contain service names and numbers only. CI rejects stale numeric documentation. Protected runtime pool metrics expose checkouts, overflow, invalidations and timeouts; actual production alert delivery is a separate operator qualification.

Never raise the declared server maximum merely to pass arithmetic. Set the real server ceiling, account for provider-reserved slots and other clients, and measure memory, query/lock latency and workload behavior. PgBouncer or additional capacity needs a compatibility/load/failover rehearsal. A single VPS remains one failure domain regardless of worker count.
