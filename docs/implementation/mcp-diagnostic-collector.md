# Bounded retained diagnostic collection

This increment supplies the operator collector and optional runtime reader. It is
locally tested; it has **not** collected live VPS logs or activated a production
mount. Diagnostics remain unavailable by default. This does not complete Phase 3
or establish that an empty query means a healthy service.

`scripts/mcp_log_collector.py` is a Linux operator command, outside the API and MCP
runtime. The operator provides the exact existing Compose deployment directory,
project label and an existing dedicated output directory. The command accepts no
container IDs, service names, commands, shell fragments or log paths from MCP.
The only Docker operations are local context inspection, running-container
listing, narrowly formatted metadata inspection and bounded log reads. Remote
Docker environment overrides and any endpoint except
`unix:///var/run/docker.sock` are rejected. No container exec, stop, restart,
creation, removal, or file cleanup is performed.

Each selected source must be the unique running normal Compose container for its
exact project, deployment directory and code-owned service. Stopped historical
containers and one-off helpers cannot substitute for it. Metadata includes only
the required labels, ID, image, running state and start time; environment variables
are never requested. Before and after each log read, the collector verifies both
uniqueness and identity. A changed binding discards its provisional records.

The five categories are API, worker, frontend report, integration and proxy.
Backend and the nine named worker/scheduler services supply structured stdout.
Frontend evidence requires the exact `frontend_render_failure` event; integration
classification requires a code-owned AI/email/WhatsApp/notification logger family.
The proxy parser accepts the repository's exact Nginx main format, immediately
discarding addresses, users, paths, user agents and forwarded fields. Nginx's
32-hex request IDs normalize to UUIDs for correlation with application evidence.
The common pure projection and the writer independently omit raw messages,
exceptions, tokens, headers, documents and passenger metadata. Only allowlisted
event/error/level values, timestamps, UUID correlation IDs, bounded status and
duration fields reach the derived files. Log evidence remains untrusted data.

| Boundary | Enforced maximum / behavior |
| --- | --- |
| Discovery | 32 returned containers; 512 KiB per metadata probe; static probe failures |
| Source read | Last 15 minutes, last 2,000 lines, 2 MiB input, 16 KiB per line, five-second subprocess deadline |
| Whole attempt | 60-second collection deadline; remaining services explicitly unavailable; local child termination only |
| Normalized source | 512 KiB and 2,000 records; output overflow is partial, never silently complete |
| Working buffers | Bounded input chunks and five bounded normalized buffers plus one bounded provisional stream; no whole raw stream is retained |
| Retained directory | At most 128 exclusive run directories and 64 MiB; reserve a worst-case full run before writing |
| Reader | At most 128 directory entries, five exact source names, manifest at most 32 KiB, source at most 512 KiB |
| Freshness | Completed observation at most 300 seconds old; more than 30 seconds in the future fails closed |

The deadline bounds local subprocess reads; final local child reaping may add up
to two seconds. Buffer limits do not establish a measured process RSS envelope.
Real Linux Docker-CLI behavior, complete mount permissions, source retention,
collection overhead and scheduling cadence remain qualification work.

Every attempt uses a new `run-<UTC timestamp>-<UUID>` directory. The operator CLI
holds an exclusive nonwaiting lock on the output directory descriptor. New files
use exclusive creation; the five source files precede the sealed manifest, which
binds directory ID, names, byte lengths, record counts and SHA-256 digests. New
directories/files use modes 750/640 and inherit the pre-provisioned root's group.
Existing permissions and files are not changed. Unknown entries, symlinks,
hardlinks and special files fail closed. A second attempt in the same second is
refused, avoiding ambiguous timestamp ordering. An interrupted attempt is retained
and prevents an older run from appearing to be the newest observation. Nothing
rotates, truncates, overwrites or deletes logs or derived evidence. At the count or
disk ceiling, an operator must select a separately provisioned retained directory;
the collector cannot make room by cleanup.

`MCP_DIAGNOSTIC_LOG_ROOT` defaults to `None`. When explicitly configured, the
diagnostic tool uses `SealedMCPLogReader`; it cannot read legacy unsealed fixture
files or fall back to host paths, stdout, shell or Docker. The optional
`docker-compose.mcp-diagnostics.yml` binds only the already-existing derived
directory read-only into the backend with `create_host_path: false`. It is not
included by default. Mount activation and cadence require the reviewed release
path; this source change does not activate them.

Results retain observation time, collection window, bounded-tail coverage and
static missing/partial/failure reasons. Stale, incomplete, ambiguous, tampered or
unconfigured evidence is unavailable. A source without matches says only that no
matching record was found in the available retained window. The database audit
and passport-job readers remain independent, with their existing correlation and
authorization limits.

Local verification: 64 backend tests cover projection, sealed reader, existing
diagnostics and actual SDK HTTP mount dispatch; the two existing diagnostic HTTP
authorization/correlation cases also pass. Seven production modules pass mypy and
scoped Ruff. Operator tests currently pass 18 cases on Windows, with one real Linux
pipe-selector subprocess case explicitly skipped. The suite checks source
replacement/replica ambiguity, missing sources, raw-field omission, static error
codes, bounded pipes, retained incomplete runs, no overwrite and disk limits.
The existing Linux CI script-discovery step will execute that subprocess case;
no new live-source collection or production mount evidence is claimed.
