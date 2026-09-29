# Combined website and MCP workload qualification

The runner is implemented; the combined Docker workload has **not been run** in
this workstream. Its passing unit tests verify rejection of incomplete evidence,
not VPS capacity. Authenticated read-only production snapshots are now recorded
in `mcp-production-baseline.json`; they show backend cgroup pressure and retained
Nginx OOM events. Qualification must compare counter deltas against this baseline.

The existing `scripts/qa/qualify_workload_capacity.py` lane now adds two dedicated
synthetic superadmin connections: one reads a 5,000-record group and the other a
100-record group. Each performs one MCP call per second, alternating bounded
group discovery and the website-equivalent passport view. The large actor exports exactly 1,500 selected passports from its 5,000-record
cohort; the small actor exports its complete 100-record group. This preserves the
shared export service ceiling. Each prepares, downloads, opens and acknowledges
one Excel during each expected/recovery stage.
Transfers use fixed same-origin routes, bounded bodies, size and SHA-256 checks;
failed integrity verification never acknowledges delivery. Samples retain
timings, counts and bounded status evidence, without tokens, upload/download
handles, file content or response bodies.

The 20 website reads/second, scan retries, four scanned public uploads, existing
durable worker burst, 80-client website overload and recovery stages remain in
the same run. Existing website latency, achieved throughput, database reserve,
API memory, broker backlog and durable recovery gates remain required. Added MCP
gates require both large/small cohorts, at least 0.9 reads/second per actor,
successful readable exports and no increase in cgroup OOM/kill counters.

Declared MCP p95/p99 limits are 1.5/3 seconds for group discovery, 2/4 seconds for
passport views, and 15/30 seconds for the complete Excel operation including
verified download and acknowledgement. These are qualification thresholds to
measure, not an observed production service-level promise. The report cannot
pass if MCP evidence or OOM telemetry is absent. This short test establishes a
combined workload envelope; it does not isolate a causal MCP-only memory delta
or replace a longer soak/production baseline.

Use only the repository's existing fixed `passdetection-qualification` project
and synthetic `passdetection_ci_browser` database. Apply
`docker-compose.capacity.yml` with the qualification Compose file. That overlay
explicitly enables **only reads and exports**, uses the fixed localhost TLS
origin, retains the existing 4 API workers/24 connection/2,560 MiB profile and
enables no communication providers. The fixture verifies these fixed settings
before issuing its synthetic grants. It does not accept external origins,
production databases, arbitrary credentials or a lower safety profile.

Run the workload script after the isolated stack and capacity overlay are ready,
with no competing qualification traffic. It writes a separate
`docs/implementation/mcp-workload-capacity-evidence.json`; the earlier website
capacity receipt stays intact. Retain its request/resource samples under the
ignored `outputs/qualification` directory. A measured report must identify the
exact candidate image/revision, dataset, stage windows, achieved rates, per-cohort
tails, all failures and evidence limitations before it can support a release.

Local harness evidence: `test_workload_capacity.py`, `test_mcp_capacity.py` and
`test_capacity_container_events.py` passed **26 tests**. They include missing MCP traffic, a slow large export hidden
by a faster small export, absent/increasing OOM evidence, wrong group/counts,
tool errors, corrupt transfer digests and untrusted response URLs. Actual canonical
100/1,500-row generator checks also pass. The harness checks the complete
GIVEN NAME / SURNAME / PassportNumber multiset, including a 50-row duplicate
passport cluster, before acknowledgement; matching row counts alone cannot pass. Fixture-issued
sessions do not qualify real Codex sign-in, browser MFA or Windows vault storage.

The current 20 running service limits total 13.5625 GiB (13,888 MiB), leaving
about 56 MiB of declared budget after a 2 GiB host reserve. All 172 unrelated
containers observed were stopped; 44 stopped project containers were retained.
The backend had about 338 MiB of instantaneous cgroup headroom. Nginx already
retains 151 OOM events and three OOM kills, with unknown event timestamps. These
are pre-existing observations, not candidate effects. Raising backend limits
requires a separately qualified whole-host budget; free host RAM alone is
insufficient. No resources were restarted, changed or deleted for observation.

The OOM lane captures before/after counters for every running container in the
fixed isolated project, including Nginx, database, scanner and storage. It binds
Linux process/cgroup identity to Docker container IDs. Missing telemetry, a
restart/replacement, or any new OOM/kill increment fails; unchanged historical
nonzero counters are permitted. This prevents API-only evidence from masking
proxy or supporting-service pressure.

A separate source-hash-bound pure Linux export-admission proof passed four kernel
lease checks at18:59:30UTC on2026-09-29 (Python3.12.3). Parent/child peak RSS was
23MiB/17MiB under96MiB per-process address-space caps. Evidence is retained at
`outputs/mcp-linux-export-gate-2026-09-29T185930.471475_0000.json`. It created one
new retained isolated helper lock and accessed no application data/containers.
This proves cross-process lease behavior only, not export memory or mixed-load
capacity. Shared container-wide admission now covers preparation and generation
for the locally implemented export families; individual oversized ORM records
can still allocate memory before post-materialization snapshot bounds reject
them. Combined native workload/RSS qualification remains required.
