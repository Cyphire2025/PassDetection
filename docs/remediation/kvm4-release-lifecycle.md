# KVM4 resource qualification and release lifecycle

The measured single-host profile is a deployment candidate until all actual-image
pressure and lifecycle checks pass. `RELEASE_RESOURCE_PROFILE=kvm4` selects
`docker-compose.kvm4.yml`; the current release helper refuses activation while
`tooling/deployment-profiles/kvm4.json` still has candidate status. An available
idle-memory reading does not establish that the full configured limits fit.

The fixed host reserve is 2,048 MiB. Phase planning counts all normal services;
each live helper admission independently inspects every running Docker container,
including unrelated projects. A zero Docker memory limit is unbounded, not zero.
Administrative and migration helpers run serially. Storage staging may overlap
only its copy helper. A Compose profile label does not prove that a process has
stopped. Application starts also require a fresh live-capacity admission.

The complete steady container ceiling is 13,888 MiB; together with the fixed
2,048 MiB host reserve it requires 15,936 MiB. The inspected host has 15,992 MiB.
This is a narrow measured profile, not a general claim that arbitrary workloads
fit. All changed services prohibit swap. Existing nginx and metrics-exporter
retain their 128 MiB RAM caps and their existing Docker swap settings; activation
requires a local Linux Docker socket and verifies `/proc/meminfo` reports zero
host swap, then rechecks that condition and every actual service cap at completion.
Their existing swap allowance does not create physical swap on that host.

## Release ordering and recovery

1. Verify the signed promoted application artifacts, current policy expiry,
   checkout, exact prepared configuration, original Compose project, and profile.
   Pull all digest-pinned persistent-service candidates during preparation.
2. Save a protected durable resource checkpoint with the original container,
   image, mount, network and configuration identities. Stop API ingress, beat and
   frontend; probe the remaining consumers for active/reserved/scheduled work.
   Only cleanly stopped, drained consumers authorize maintenance.
3. Read the schema through the existing PostgreSQL process. Save and fully decode
   a fresh custom archive before provisioning identities or replacing any data
   service. A post-migration retry requires the retained valid pre-migration
   archive; it cannot substitute a new post-migration backup.
4. Apply the separately qualified persistent-service resource transition. Redis
   volatile keys require the same process to be preserved; PostgreSQL minor
   replacement requires the identical named volume and database identity. The
   implementation and its independent evidence are in
   `scripts/release_persistent_resources.py` and its dedicated tests.
5. Provision restricted database identities, perform the version-preserving
   storage cutover, and apply the additive migration. The storage recovery path
   still verifies which provider is authoritative, but leaves application writers
   under the outer resource fence stopped.
6. Admit and activate the exact prepared consumers, API and frontend. Confirm
   actual running state, revision/schema/image identity and public readiness.
   Only then mark the checkpoint complete.

An interrupted activation is retried with the same revision, profile and prepared
artifact. A partial new application deployment is re-fenced and drained before
maintenance resumes. Only original recorded processes or that same prepared new
image may be adopted. Configuration drift, a foreign replacement, an unclean
exit, invalid archive, ambiguous storage handoff, or exceeded live memory budget
keeps the operation stopped. There is no automatic database downgrade, old-image
rollback, queue purge or storage-volume deletion. `prepare` cannot overwrite an
active maintenance checkpoint.

## Evidence and current limits

The final complete operator regression passed 286 tests in 7.371 seconds; its
command and source hashes are retained in `kvm4-tooling-final-evidence.json`.
This includes the actual `CurrentRelease`/outer-fence call sequence against a simulated Docker
boundary. This covers failed archives, interrupted stops, busy accepted work,
partial activation, changed mount/image/project identities, unrelated live host
overcommit, storage recovery deferral, and strict profile drift. These are
failure-injection tests, not proof that the VPS has already been upgraded.

`kvm4-worker-memory-evidence.json` records bounded network-isolated probes against
the actual candidate image. Ten successive accepted Gemini operations in
the same imported-worker child remain below its 384 MiB cap. Repeated email jobs
exposed an actual OOM from an unclosed PDF reader/input stream; both the failure
and the passing explicit-lifetime correction are retained. Ten corrected email
jobs on the final combined image peak at 288.89 MiB. Ten successive Visa jobs
peak at 366.48 MiB beneath 512 MiB; ten successive admitted 40-megapixel ECR
decodes peak at 489.67 MiB beneath 640 MiB. The final imported-worker Gemini
extraction and verification modes peak at 235.21 and 196.20 MiB. Every final
worker run used immutable image
`sha256:0066ad357a08c4b207fa93bfa12e6111a90ebcac3514b4edbbdeb31a66db0f67`,
without application source overlays, and recorded zero cgroup limit/OOM events.
No external AI provider
throughput is claimed. The existing production extraction path is Gemini-first;
the optional local-OCR implementation measured above 384 MiB is not activated by
that worker configuration.

The first persistent four-process API crop test exceeded its 2.5 GiB cap despite
single-operation admission. That failure is retained. The allocator-lifetime
correction subsequently passed with four persistent worker PIDs. The final
combined image completed 20 logical maximum-size crops with 14 explicit bounded
busy retries, peaking at 2,300.18 MiB beneath 2,560 MiB with zero cgroup OOM/limit
events; see `api-native-memory-evidence.json`. An earlier overlapping final-image
attempt failed and remains recorded; the isolated successful repeat does not
erase that failure or establish unconstrained host capacity. CI now executes the
five reused-worker modes and four-process API pressure gate sequentially before
starting the joined stack, preventing other test services from consuming that
qualification window. Physical-host high
availability, external alert delivery and off-host disaster recovery remain
separate obligations.
