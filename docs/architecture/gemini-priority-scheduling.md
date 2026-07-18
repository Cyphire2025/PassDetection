# Global Gemini priority scheduling

## Contract

Interactive passport extraction always has admission priority over
post-submission AI verification.

- Extraction queue: `interactive-passport-extraction`
- Verification queue: `post-submission-ai-verification`
- Redis is the only admission source of truth across API processes and workers.
- Verification starts only when extraction has no waiting, dispatching, or
  active lease and the extraction quiet period has elapsed.
- Verification that was already admitted is not cancelled when extraction
  arrives. It can finish, while new verification remains blocked.
- Extraction and verification have independent global concurrency ceilings.
- Celery delivery deferrals do not consume provider retry attempts.

The database job rows remain the durable business-workflow ledger. Redis owns
only short-lived scheduling state, and Celery owns durable queue delivery.

## Atomic state machine

One Lua script performs lease cleanup, state inspection, capacity checks, and
each transition atomically:

```text
extraction: waiting -> dispatching -> active -> released
verification: waiting -------------> active -> released
```

Every state is a Redis sorted-set member scored by lease expiry. A shared state
hash stores the state and monotonically increasing generation. Release and
heartbeat compare the generation, so a delayed worker cannot release a newer
lease for the same logical job. Duplicate registration is idempotent, and a
second active delivery is suppressed.

Expired waiting, dispatching, and active leases are pruned by the next
operation. This recovers broker gaps and worker crashes without a process-local
counter or manual lock cleanup. Active runtimes heartbeat at one third of their
lease duration.

All coordinator keys share the Redis Cluster hash tag `{ai-priority}`, so a
transition remains one atomic script in clustered Redis.

## Data minimization

The Redis member is a SHA-256 fingerprint of the workload and durable job id.
Upload-link bearer tokens, qualifier-selection tokens, phone numbers, document
fields, and other PII are never Redis members or scheduler log fields. Scheduler
warnings include only workload class and exception type.

## Failure behavior

| Condition | Extraction | Verification |
| --- | --- | --- |
| Redis healthy, capacity available | Admit | Admit only after priority and quiet-period gates |
| Redis healthy, capacity full | Keep waiting and defer | Keep waiting and defer |
| Extraction waiting/dispatching/active | Continue/admit within its limit | Defer |
| Verification already active when extraction arrives | Extraction can proceed | Active verification may finish |
| Worker crash | Lease expires and capacity recovers | Lease expires and capacity recovers |
| Redis unavailable before admission | Conservative fail-open | Fail closed and defer |
| Redis unavailable after admission | Current work may finish; lease expires if release fails | Current work may finish; lease expires if release fails |

Extraction fail-open is intentional availability behavior. It can temporarily
exceed the global extraction ceiling during a Redis outage, but does not create
a process-local counter that could be mistaken for globally correct state.

## Configuration

```dotenv
GEMINI_EXTRACTION_MAX_CONCURRENCY=32
GEMINI_VERIFICATION_MAX_CONCURRENCY=1
GEMINI_EXTRACTION_TIMEOUT_MS=30000
GEMINI_EXTRACTION_QUIET_PERIOD_MS=2000
GEMINI_RETRY_MAX_ATTEMPTS=3
GEMINI_PRIORITY_CAPACITY_CALIBRATED=false
GEMINI_PROJECT_ALIAS=unconfigured
GEMINI_CONFIG_VERSION=v1
PROCESSING_WORKER_PING_TIMEOUT_SECONDS=1
PROCESSING_WORKER_READINESS_CACHE_SECONDS=15
```

`GEMINI_EXTRACTION_TIMEOUT_MS` and the existing
`GEMINI_TIMEOUT_SECONDS` determine bounded extraction and verification active
leases, respectively, with a recovery grace period. They are not response-time
promises. Provider and end-to-end latency still depends on image processing,
network conditions, provider capacity, and durable queue depth.

`GEMINI_RETRY_MAX_ATTEMPTS` is the hard provider-attempt ceiling for one
logical Gemini operation. The legacy `GEMINI_MAX_RETRIES` remains the requested
provider retry count, so the effective provider attempts are the lower of
`GEMINI_RETRY_MAX_ATTEMPTS` and `GEMINI_MAX_RETRIES + 1`. Scheduler-capacity
deferrals are not provider failures: the task publishes a fresh delayed
delivery and acknowledges the current delivery without consuming that budget.
The same fresh-redelivery rule applies when a recovered delivery finds a
still-fresh database `running` claim. That contention is distinct from a
processing failure, so it does not consume the Celery/provider attempt budget;
if publishing the replacement fails, the current delivery is rejected and
requeued instead of being acknowledged and stranded.
After those in-call provider attempts are exhausted, verification persists a
conservative `NEEDS_REVIEW` result instead of replaying another full provider
retry chain. `PROCESSING_JOB_MAX_ATTEMPTS` separately bounds crash/worker
delivery recovery; it is not multiplied into the Gemini provider retry budget.

For transient Gemini 429/5xx/transport/timeout responses, retries remain inside
the configured request deadline. Numeric and HTTP-date `Retry-After` headers
are parsed and their delay is honored only when it fits inside the remaining
deadline; otherwise the attempt terminates conservatively. Logs and metrics
record only the bounded delay, status class, workload, model, attempt, and
duration, never response bodies, prompts, API keys, or traveller fields.

The extraction value of `32` is a burst-capable staging baseline, not a
production certification and not evidence that 100-user latency has been met.
It avoids an artificial 2/5/10-request bottleneck while remaining below the
visible project RPM allowance. The local OCR, database pool, VPS CPU/memory,
actual model, and upstream concurrent-call behavior still require the specified
production-like 100-user test.

Production readiness returns 503 until all of the following are true:

- `GOOGLE_API_KEY` is non-empty
  (`gemini_api_credentials=configured_or_non_production`);
- the safe project alias is configured
  (`gemini_runtime_identity=configured_or_non_production`);
- operators set `GEMINI_PRIORITY_CAPACITY_CALIBRATED=true` after the controlled
  load test;
- in Celery mode, an active worker consumes each exact AI queue.

This validates configuration presence, not provider authorization or quota.
Readiness deliberately makes no Google API request. A revoked key, wrong
project, unavailable provider, or exhausted quota is detected by bounded
runtime requests and operational metrics, not by the health endpoint.
Disabling the optional post-submission verification stage does not bypass the
credential, identity, or calibrated-capacity gates because interactive
passport extraction still uses Gemini. The verification-worker check alone is
not required when that stage is disabled.
The 2-second quiet period is inside the requested short 1-3 second range.

Compose runs dedicated workers for each priority queue. Their process
concurrency matches the corresponding configured global ceiling. Redis
admission still enforces the global ceiling if multiple hosts or worker
instances are started.

The existing `worker` continues to consume the WhatsApp and legacy default
queues; it does not consume either AI queue.

Every Compose worker has a stable Celery node prefix and a container
healthcheck that targets that exact node and verifies its exact active queues.
This prevents a response from a different healthy worker from masking a
missing or misrouted worker.

Whenever Celery is the processing backend, the API readiness check uses a
bounded Celery `active_queues` inspection rather than a per-request `inspect`.
Each API process serializes and caches the result for
`PROCESSING_WORKER_READINESS_CACHE_SECONDS` (15 seconds by default), and each
broker round trip is capped by `PROCESSING_WORKER_PING_TIMEOUT_SECONDS` (1
second by default). This is a process-local cache, so a multi-process or
multi-host API can issue at most one inspection per process per cache window.
Worker loss can remain cached as healthy for up to that window; Docker's
queue-specific worker healthchecks provide an independent signal. The
production backend container probes `/api/v1/health/ready`, while the
development base file continues to use the liveness probe.

## Runtime project verification

An API key is a credential, not a safe project-identity API. The Gemini API does
not provide this application with a supported, secret-free operation that maps
an API key back to its Google Cloud project. The application therefore cannot
prove the key's project from the key alone.

Operators must compare the key and quota project in Google AI Studio/Cloud
Console, then set a non-secret deployment alias in
`GEMINI_PROJECT_ALIAS` (for example, `gct-prod-tier1`) and increment
`GEMINI_CONFIG_VERSION` whenever the key, model route, endpoint, or quota
project changes.

At startup, the backend emits `gemini_runtime_configuration` with only:

- the safe project alias;
- primary and fallback model names;
- the API base endpoint with credentials, query, and fragment removed;
- config version;
- a boolean indicating whether an API key is configured.

The key and its hash are never logged. Identity values are not added to public
health or client APIs; readiness exposes only non-secret gate statuses.
Production readiness fails with `gemini_api_credentials=api_key_required` for
an absent/blank key and
`gemini_runtime_identity=project_alias_required` while the alias remains
`unconfigured`.

## Observability

The API and every worker write the same low-cardinality aggregates to Redis.
The `/api/v1/health/metrics` and `/api/v1/health/diagnostics` snapshots expose
them under `shared.ai_priority`. Both detailed endpoints require an
authenticated `SUPER_ADMIN`; only `/live` and `/ready` are public. Scheduler
admission never reads these metrics and they never authorize work.

The shared snapshot contains:

- request counts by extraction or verification workload;
- admitted, deferred, duplicate, stale, and extraction fail-open decisions;
- Redis coordination failures;
- extraction waiting, dispatching, active, and configured concurrency gauges;
- verification waiting, active, and configured concurrency gauges;
- provider success, upstream 429, timeout, network error, upstream failure,
  request error, and retry counters;
- admission, provider, queue-wait, and queue-to-release end-to-end timings.

Every timing reports count, average, minimum, maximum, p50, p95, and p99 over
the latest 2,048 samples per metric. Redis counters retain their total across
that bounded sample window and expire after seven inactive days. Queue timing
uses a six-hour, generation-specific lifecycle record keyed only by the
already-hashed scheduler job fingerprint. Lifecycle keys are deleted on normal
release and expire after crashes. Raw job ids, traveller fields, upload
tokens, provider bodies, models, and exception text are never metric labels or
snapshot values.

If Redis metrics writes fail, a 30-second circuit prevents every provider call
from repeatedly waiting on the failed exporter. Collection continues in a
bounded, thread-safe process-local fallback, and the snapshot explicitly
reports `status=degraded`, `source=process_fallback`, and
`scope=current_process_only`. Samples collected during that outage are not
backfilled when Redis recovers. This fallback preserves request availability
but is not a cross-process production aggregate.

The Redis snapshot contains cumulative counters (with a seven-day inactivity
expiry), not alert windows. The production collector must scrape it
periodically and calculate counter deltas. Start with these release thresholds,
then tune them from a measured staging baseline:

| Signal | Warning | Critical |
| --- | --- | --- |
| Extraction end-to-end p99 | over 40 seconds for 5 minutes | at or over 45 seconds for 5 minutes |
| Gemini upstream 429 ratio | over 2% for 5 minutes | over 5% for 5 minutes |
| Gemini timeout ratio | over 2% for 5 minutes | over 5% for 5 minutes |
| Extraction queue p95 wait | over 5 seconds for 5 minutes | over 15 seconds for 5 minutes |
| Redis coordination failures | any new failure | sustained failures for 2 minutes |
| Required AI worker/readiness | one failed probe | unavailable for 2 minutes |

Ratios use the relevant workload request delta as their denominator and must
exclude periods with fewer than 20 requests to avoid noisy low-volume alerts.
These thresholds are an initial operational contract, not evidence that the
production dashboard or paging integration has been provisioned.

## Staging gate and rollout

1. Set `GOOGLE_API_KEY`, a verified `GEMINI_PROJECT_ALIAS`, and increment
   `GEMINI_CONFIG_VERSION`.
2. Keep `GEMINI_PRIORITY_CAPACITY_CALIBRATED=false`.
3. Start the backend plus the dedicated extraction and verification workers.
   Confirm both worker containers are healthy and both exact queue statuses are
   `available` at `/api/v1/health/ready`.
4. Pre-seed background verification work and run
   `load-tests/k6/passport-extraction.js` with 100 approved non-production
   fixture pairs as documented in `load-tests/k6/README.md`.
5. Correlate k6 results with queue, active-call, upstream 429/timeout/retry,
   database, CPU, and memory metrics. Tune concurrency rather than assuming
   the visible RPM limit proves safe parallelism.
6. Set `GEMINI_PRIORITY_CAPACITY_CALIBRATED=true` only after the production-like
   gate passes, then verify `/api/v1/health/ready`.

This implementation has deterministic 100-admission concurrency coverage, but
that is not a live 100-user upload/Gemini result. The real load gate requires
approved fixtures, a reachable Redis/Celery stack, the intended Gemini project,
and production-like infrastructure.

Rollback is operational: stop the two dedicated AI workers, restore the prior
worker image/configuration, and revert the queue-routing release together.
Do not leave jobs stranded on the two new queues; drain or re-publish them under
the previous deployment before removing the workers. Redis scheduler keys are
lease-bounded and contain no business records, so they may expire naturally
after all new workers are stopped.

## Test invariants

Focused tests cover:

- waiting, dispatching, and active extraction blocking verification;
- atomic extraction/verification races;
- 100 concurrent extraction admissions under one global ceiling;
- quiet-period enforcement and verification resumption;
- multiple coordinator instances sharing one store;
- lease expiry after a simulated crash;
- Redis outage asymmetry;
- generation-aware duplicate suppression and idempotent release;
- exact Celery queue routing and Redis Cluster key topology;
- runtime admission before database claims/provider calls.
