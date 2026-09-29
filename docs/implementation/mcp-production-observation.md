# Read-only production baseline procedure

Owner: repository maintainers. Reviewed 2026-09-29. The collector is implemented
and has six local fixture/negative tests; it has not been run against production.
The current live production state remains unobserved in this workstream.

`scripts/mcp_production_baseline.py` is ready to run through the existing
authorized VPS access path from a trusted checkout containing its release-helper
dependencies. It requires Linux, the default local Unix Docker socket, and an
explicit existing Compose working directory. It refuses a remote Docker
context, an ambiguous backend/database, or a backend whose database endpoint
and network identity do not match the inspected project database.

For example, with an existing private output directory chosen by the operator:

```sh
python3 scripts/mcp_production_baseline.py \
  --root /opt/GlobalConnectsDashboard \
  --output /private/qualification/mcp-baseline-20260929.json
```

The output path must be new; existing evidence is never overwritten. No remote
copy or invocation has been performed by this workstream.

The collector reads physical/available memory and swap; all-host container
count; the bound project's container/image identities, running/OOM state,
resource limits and one usage sample; strictly allowlisted runtime revision,
schema, MCP and pool configuration; and the actual database version, connection
counts/ceiling and MCP emergency state where the table exists. Unrelated
containers contribute only to the count. It never stops, prunes, deletes or
recreates them. The deferred Hostinger64 cleanup remains outside this task.

The collector never emits full Docker inspection objects, environment variables,
logs, user/business rows, database credentials, provider tokens or private
object paths. Failed probes return a static diagnostic rather than command
stderr. Database commands are fixed read-only SELECTs executed through the
already-running database process. The only newly written file is the explicitly
named local JSON evidence file.

This snapshot is a prerequisite for release planning. It does not establish MCP
overhead, load capacity, restricted runtime grants, working private storage or
antivirus, backup validity, maintenance safety or successful rollout. Those
require the separately documented combined workload, populated migration,
recovery and end-to-end qualification gates. Retain the snapshot alongside
`mcp-production-baseline.json`; update claims only after reviewing actual
authenticated observations.
