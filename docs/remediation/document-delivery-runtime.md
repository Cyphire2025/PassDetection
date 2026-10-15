# Document delivery runtime and memory evidence

## Production result, 16 October 2026

Revision `644176c9b52d09634d0f006201c4387294bae526` completed the explicitly
authorized Fast VPS deployment. Public readiness reported that exact revision and
schema `0140_document_update_context`; all 20 services were running, every configured
health check was healthy, and the new application and Redis containers had no OOM
or restart events. Actual limits were read back as worker 1024 MiB, frontend 256 MiB,
broker 896 MiB, and cache 192 MiB. This is Fast evidence, not Full CI qualification.

Two release-tool issues interrupted cutover: a controlled restart reset a historical
Docker restart count, and the broker's roughly 188,000 small keys exceeded the
original 20,000-key preservation bound. Audited forward recovery retained the
original receipts, images, containers and volumes. A separate isolated 250,000-key
proof passed before increasing the broker inventory bound; cache remained at 20,000.
Database and Redis preservation checks passed before application activation.
The permanent tool fixes record a separate controlled-restart baseline and check
actual Redis inventory/headroom before cutover, with a second check before DDL.

The before/after Bluechip delivery state is unchanged apart from schema: 1,315 rows,
1,315 attempts, the same latest creation timestamp and the same 22 uncertain rows.
No documents or update messages were sent by the operator. Live browser checks
confirmed both broadcast choices, shared-PDF filtering, recipient document
management in all five sections, upload/replace menus and display-name editing.
Real Meta delivery remains untested, and template approval could not be independently
verified using the available read permission. Sanitized production evidence is in
`document-delivery-production-20261016.json`.

The sections below preserve the earlier candidate measurements and their limits.
Later release-tool fixes are separate from the application revision deployed above.

## Candidate resource profile

The candidate raises the shared sending/legacy OCR worker from 384 to 1024 MiB.
It retains one worker child and the same four bounded concurrent document uploads.
Frontend drops from 512 to 256 MiB, Redis broker from 1152 to 896 MiB, and the
evictable Redis cache from 320 to 192 MiB. The service ceiling remains 13888 MiB,
with 2048 MiB reserved for the host against 15992 MiB observed physical memory.

The Redis broker's dataset cap also drops from 512 to 384 MiB; it retains
noeviction, AOF persistence and every-second fsync. Its container allowance remains
two maximum datasets plus 128 MiB for fork/copy-on-write and allocator overhead.
Cache data drops from 256 to 128 MiB with allkeys-lru eviction. Reduced queue
capacity and cache retention are real tradeoffs; normal usage and synthetic donor
probes support preparing this candidate but do not establish all future peaks.

An isolated VPS probe used installed images, synthetic keys, no network, no
credentials, no production mounts, 0.5 CPU per sequential container, and a 6 GiB
host-available guard. Broker AOF rewrite, cache eviction, and frontend login renders
passed with no memory-limit or OOM events. Exact measurements and limitations are
in `document-delivery-rebalance-evidence.json`. Only task-owned temporary containers
were removed. No running production settings, data, or documents changed.

The API and storage service were deliberately not donors: read-only cgroup data
showed the API had two OOM kills since its October 14 startup, and MinIO had reached
its cap. The sending worker had five OOM kills and a 384 MiB peak. Those counters
show process/container limits can be exhausted while the whole host has spare RAM;
they do not establish the exact cause of each individual historical send failure.

## Bounded document dispatch

Each document task admits at most 25 queued/processing rows and stops admitting
new provider sends after 180 seconds. It finishes provider calls already in flight
(each has a 35-second attempt deadline), then republishes the same batch for remaining
rows. Queued rows take priority over active processing rows. The original 540/600
second Celery soft/hard limits remain a final safety ceiling, rather than the normal
batch duration. Continuation is published before acknowledgement, so redelivery
can revisit only unclaimed rows. A late duplicate cannot reclaim accepted or
unknown outcomes. Processing attempts become unknown only after 11 minutes;
fresh processing attempts are left alone. Already committed successes propagate
mobile invalidations per released document set, including later slices.

PDF bytes are released after media upload. If the slice deadline expires after
upload but before message submission, the row returns to queued safely. Source,
consent, destination and document checks still run immediately before submission.
Nothing in this change retries existing unknown outcomes or sends historical rows.

## Text-only updates

`whatsapp.process_document_update_broadcast` consumes immutable `document_update`
message logs in slices of 25/180 seconds. It uses the frozen template name/language,
one body variable, and no header/media. Under the established source lock order it
rechecks linked broadcast membership, consent, destination, traveller scope and
whether documents have since been accepted. Fully fulfilled audiences are skipped.
Provider uncertainty becomes `delivery_unknown`; recovery persists a known message
ID without invoking the provider again. Receipt bindings use existing broadcast
logs and cannot mark a PDF delivered. Durable publication routes the update marker
to this worker and removes the marker before calling it.

## Document-checking timing observations

Read-only backend logs between 2026-10-15 08:10:01Z and 15:28:54Z contain 241
verification requests and 2315 file observations (including retries). No group ID
or byte total was logged, so these are not unique document counts and cannot all
be assigned to Bluechip.

| Sample | Count | Median total | P95 total | Median read/security scan | Median classification | Median matching |
|---|---:|---:|---:|---:|---:|---:|
| Seven-file visa requests | 104 | 15.695 s | 18.504 s | 8.610 s | 5.445 s | 0.0014 s |
| Sixteen-file flight requests | 83 | 3.250 s | 8.971 s | 0.873 s | 0.825 s | 0.0018 s |

Visa scan/read phase was above one second in 86 of those 104 requests, with an
8.701-second median. The other 18 had a 0.125-second median phase and a 7.878-second
median total. Cache effects are a possible explanation, not proven by these logs.
The frontend batches at 16 PDFs or 8 MiB, whichever is reached first; seven shown
files do not mean seven scanner workers. At inspection, one browser request ran at
a time, safety scans ran sequentially, and two fresh PDF child processes were
created per batch. These observations motivated the separately approved bounded
benchmark.

The proposed parser improvement used Linux's forkserver to preload clean parser
imports once. The forkserver never received PDF bytes; every batch still created,
limited, and joined fresh PDF parser children. A synthetic seven-image-visa
benchmark of the candidate parser source reduced the warm
classification median from 8.012 to 6.711 seconds (16.2%). Every classification
matched the baseline result, and fresh-child state, per-file alarms, memory limits,
parent timeout termination, malformed PDF rejection and cleanup checks passed.
Peak container memory was 314.6 MiB for spawn and 321.8 MiB for forkserver, with
zero OOM or memory-limit events. However, the required four-parent follow-up
measured steady idle usage rising from 260.03 to 385.39 MiB: an additional
125.36 MiB across four independent parser/matcher processes. Active peak also
rose from 509.24 to 606.67 MiB. All 112 classifications matched and the isolated
1 GiB container had no OOM events, but this excluded the full API application.
The live API has four processes, a 2560 MiB cap and prior OOM events; this test
does not establish safe API headroom. The parser optimization was therefore
rejected under the user's safe-memory condition. The original spawn runtime
and its parser limits/checks remain unchanged.

The two-concurrent-security-scan proposal was rejected after measurement: its warm
median was 0.731 seconds versus 0.616 seconds sequentially. Security scans remain
sequential; all malware, PDF structure, audit and classification requirements
remain in place. The frontend still sends one bounded upload request at a time.
The isolated scanner comparison excludes durable database audit time and cannot
predict the complete production read/security phase. All benchmark PDFs were
synthetic, and each test container was capped at 0.5 CPU. The measurements establish
the rejection of both proposals for this sample, not an exact future Bluechip time.
Sanitized timings, source hash and safety evidence are recorded in
`document-verification-speed-evidence.json`.

## Release boundary

The candidate additive schema is `0138_verified_portal_lookup` →
`0139_passenger_display_name` → `0140_document_update_context`, under deployment
kind `document_distribution_updates_v1`. A fresh isolated PostgreSQL qualification
passed the upgrade, lock-timeout atomic rollback/retry, ORM reads/writes and
transaction rollback, downgrade/re-upgrade, and retention of existing business
fields and message history. An intentional display-label edit advances the group's
existing roster revision; passport identity and recipient routing stay unchanged.
This schema has not been applied to production. The scoped image-side helper now
binds the complete reviewed migration source, captures the original 0138
preservation digest, and requires that same digest for a forward resume from 0139
or an idempotent target check. It preserves original rows, table catalogs and
table/column grants; both new columns must remain null until activation. An
isolated PostgreSQL run passed source upgrade, intermediate resume, target replay,
lock failure, and rejection of altered historical rows/catalog or premature new
values. Details and exact helper source hashes are in
`document-distribution-release-evidence.json`. This source-overlay proof does not
qualify the final production image. The dedicated signed Full or explicitly selected
operator VPS Fast path and RAM transition require their own exact final qualification before activation;
the historical companies/traveller contract does not authorize this transition.

The profile is marked `candidate_pending_final_application_and_lifecycle_checks`.
It can be prepared but cannot activate until exact final application/image and
lifecycle checks are complete and the exact attempt receipts are verified. Signed
Full CI or the explicitly selected operator Fast build/rehearsal evidence,
production idle/drain checks, current queue usage, zero host swap, guarded phased
activation, and running-container readback remain required. No deploy, restart,
resend or new provider call is part of this evidence.

The persistent-service helper now has a narrow, checkpointed exception for exactly
broker 512→384 MiB and cache 256→128 MiB dataset reductions. All other Redis command
changes remain rejected. The exception requires identical image, authentication,
persistence and eviction policy; fenced application writers; retained exact /data
volume; a clean SAVE/stop; and logical value plus absolute-expiry readback after
replacement. Strings, lists, sets, hashes and sorted sets are supported. Other
types, more than 16 databases, more than 250,000 broker keys or 20,000 cache keys,
values using more than 4 MiB, or insufficient dataset/container headroom fail
closed. Cache's one-time RDB is preserved under an
archive filename after verification so ordinary later restarts cannot load stale
cache from that snapshot. Checkpoint recovery never creates an empty replacement
volume, and a later retry of a completed transition allows legitimate new writes.

The actual isolated VPS transition passed, including interruption immediately after
container replacement, same-volume recovery, preserved values/absolute TTL across
16 Redis databases, and idempotent replay. The cache fixture contained 2184 keys
including a 3 MiB value: 89.83 MiB used before fingerprinting, 106.06 MiB after
fingerprinting, and a 107.86 MiB replacement cgroup peak under the 192 MiB cap. No
OOM occurred. Earlier higher-fill cache fixtures were refused by the unchanged
10% admission headroom requirement; those workloads are not qualified. Broker
lifecycle preservation was exercised with a small mixed-type dataset; the larger
359 MiB AOF rewrite pressure test remains separate. Sanitized results and candidate
source hashes are in `redis-dataset-transition-evidence.json`.

A later isolated broker probe qualified the entire 250,000-key bound, using
249,993 synthetic 256-byte strings plus seven mixed-type/cross-database keys. It
completed fingerprinting, SAVE, replacement on the same volume, interrupted
replacement recovery and absolute-TTL/value comparison in 77.294 seconds. The
replacement peaked at 368.16 MiB under its 896 MiB cap with zero reported OOMs;
the operator Python process peaked at 299.37 MiB. All synthetic resources were
removed and no provider calls occurred. Exact inputs and measurements are in
`redis-large-inventory-evidence.json`. This tests the existing fingerprint and
retention algorithm with an in-process broker key-bound override, not a different
production dataset or an exact-image qualification of later release code. The
192 MiB cache retains its earlier 20,000-key bound.

Fresh document release preparation now checks the actual Redis inventory and
headroom before staging or cutover. It reads every supported logical value using
the existing bounded fingerprint routine, checks per-value size and database/key
limits, and measures dataset/cgroup headroom both before and after that read.
Only a small summary is recorded; this observation does not replace the fenced
preservation baseline. Both Redis services are checked again after all writers
stop and before database migration. Target-schema recovery skips this original-
configuration preflight and follows its recorded Redis transition stages instead.
Neither preflight saves snapshots, changes limits nor stops Redis.

The candidate now wires `document_distribution_updates_v1` into a dedicated
`DocumentRetainedUpdate` path. The existing signed-CI dispatcher selects its Full
mode. The separately selected operator `--mode fast` path implements the user's
explicit VPS-build request for this exact schema/resource change; it does not
relax ordinary Fast source policy or claim Full CI qualification. Fast requires
unchanged backend dependencies, immutable live base images, successful stopped
builders, exact API/source/schema image binding and an image-side rehearsal of
0138→0139→0140, including intermediate recovery and preservation failure cases.
Backend native runtime and Dockerfile changes are inherited from the existing
image, not rebuilt or separately security-qualified. Frontend application assets
are rebuilt from the candidate lockfile on the retained bounded build path.

Both modes run the isolated exact-image resource qualifier before any live writer
fence or migration. The resulting private attempt-local
`document-resource-qualification.json` binds the revision, backend/frontend/Redis
images, profile, overlay and exact qualifier/executor source hashes. Missing,
changed or unsuccessful evidence blocks the release; recovery cannot generate a
replacement receipt. The profile's candidate status is not silently promoted.
Fast's private `fast-document-migration-rehearsal.json` and build binding are also
immutable on recovery: no recompile, replacement image or new rehearsal can be
substituted into an existing release attempt. Its records state
`full_ci_qualified: false` explicitly.

The fenced transition captures and verifies a database archive plus original
row/catalog/grant digest, applies only 0138→0139→0140, and then runs the narrow Redis
transition through a retained-container adapter. Original Redis containers remain
stopped and intact; replacements reuse the exact named or anonymous /data volume,
image, credentials, persistence policy and service DNS aliases. Worker/frontend
clones receive only their two reviewed RAM changes. No original application writer
is automatically restarted after an additive migration; interrupted activation
uses the same bound receipts and forward recovery. Readiness, public served-byte
proof, complete inventory retention and actual memory-limit readback remain gates.

The actual retained adapter also passed a separate isolated VPS test with both
Redis services: an interruption after Docker create but before its checkpoint
recovered the exact stopped candidate, kept one active writer, retained the original
container and data volume, and preserved logical values and absolute expiry.
No OOM occurred, and all synthetic containers/volumes/internal networks were removed.
This small mechanical proof is in `retained-redis-transition-evidence.json`;
pressure qualification and exact final-image proof remain separate requirements.
Nothing in this evidence applies the schema or RAM limits to production. A runtime
CONFIG SET alone remains insufficient because unchanged startup arguments restore
the old dataset allowance after restart. Do not bypass evidence gates or only
change the qualification flag to activate this candidate.
