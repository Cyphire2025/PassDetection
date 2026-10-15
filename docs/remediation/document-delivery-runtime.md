# Document delivery runtime and memory candidate

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
benchmark; this runtime change itself does not alter document checking.

## Release boundary

The profile is marked `candidate_pending_final_application_and_lifecycle_checks`.
It can be prepared but cannot activate until exact final application/image and
lifecycle checks are complete and the qualification evidence is updated. Full CI,
production idle/drain checks, current queue usage, zero host swap, guarded phased
activation, and running-container readback remain required. No deploy, restart,
resend or new provider call is part of this evidence.

The existing persistent-service lifecycle also rejects a Redis command change:
it pauses/resizes the original process to preserve volatile keys and does not
recreate Redis. The new dataset bounds therefore require a separately qualified
preserving transition before activation. A runtime CONFIG SET alone is not a
permanent fix because the existing container's startup arguments would restore
the old larger dataset after restart. Do not bypass that guard or only change the
qualification flag to deploy this candidate.
