# Preserving data while changing the VPS resource profile

The local synthetic deployment rehearsal passed on 27 September 2026.
Its evidence is in persistent-release-evidence.json. This is a release
interruption test, not the production disaster-recovery exercise the owner deferred.

The guarded release stops ingress and the scheduler, proves accepted worker work
has drained, and keeps all application writers stopped in a durable private
checkpoint. It creates and fully decodes a fresh PostgreSQL custom archive before
changing a persistent service. It never restores old data or automatically starts
the previous application images after a failed migration.

The resource transition preserves Redis processes in place. This matters because
the realtime and cache instances intentionally do not persist all keys to disk.
The helper verifies the same image, command, process start, container identity,
mounts and restart count; pauses that exact process; reads its actual Linux
cgroup usage; and requires substantial headroom before changing its cap. It then
unpauses the same process. A failed resize also unpauses that verified process.
It never repairs a missing or restarted Redis process by silently starting an
empty replacement.

PostgreSQL replacement is limited to the reviewed major version 16, identical
bootstrap identity, effective PGDATA, and exact retained named volume. Every
application table and sequence contributes to before/after preservation
fingerprints, alongside the PostgreSQL cluster identifier. The helper verifies
them before advancing. ClamAV retains its existing definitions volume. Unknown
extra mounts, changed volume identities, incomplete archives and unknown
replacement processes stop the release.

The real local rehearsal populated 500 parent records and 500 related records,
two sequences and the schema table, plus retained values, queue items and leases
in all four Redis domains. It injected failures after a real Redis resource update
and after a real PostgreSQL container replacement, then resumed from the saved
checkpoint. The database fingerprint, sequence state and cluster identifier
matched; Redis container/process identities, values, queue order and live leases
matched; all resources reached their expected limits without an OOM. Synthetic
containers, volumes and the decoded archive were retained.

The first rehearsal correctly refused ClamAV's exit status 143. Inspection of the
pinned /init-unprivileged image established that this is its SIGTERM exit.
The corrected helper accepts 0 or 143 for that ClamAV process while still
rejecting OOM, forced SIGKILL and error states; PostgreSQL must exit zero.
The repeated complete rehearsal passed. Thirteen focused failure-boundary tests
also pass, including unknown mounts, changed PGDATA, changed volumes, altered
database contents and external Redis restarts.

The Windows caller used a read-only Linux helper with host PID/cgroup namespaces
only to execute the exact cgroup reader against the Docker host. Actual
pause/update/unpause, Compose replacement, archive decode, PostgreSQL queries
and volume inspection were real. The database fixture used the same pinned
PostgreSQL 16.14 image before and after recreation, so this test does not claim
that a production minor-version upgrade or production recovery has already run.

The original application-fencing and phase-budget checks have separate tests.
Every real persistent replacement or maintenance helper must also account for
all containers actually running on the host, including unrelated projects.
Successful local checks do not establish that these changes are deployed.
