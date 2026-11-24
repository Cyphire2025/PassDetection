# Shared dashboard realtime review

The retained shared service was fully read at `mobile_realtime.py` SHA
`0b3e460a3aa34cabd3fe6431c10dd3747b634f91617649cf019224da90df046c`
(1,006 physical lines). Dashboard cookie authorization, socket serving,
post-commit hints, frontend socket/invalidation consumers, and existing hub and
route tests were traced. The ledger distinguishes full source reads from the
partial application startup/shutdown trace. Native route exclusion does not
exclude this shared implementation.

The separately sealed deliberate behavior checkpoint reproduced eight failures
and one valid-message control with synthetic Redis protocol resources. A list
or object in `invalidation` could raise during hash membership and terminate the
only subscriber. Cancellation during startup could skip closing unpublished
client/PubSub resources. A failed background task could interrupt shutdown
before socket, lease and Redis cleanup. The fix validates the wire kind before
membership, completes owned cleanup through repeated cancellation, propagates
cancellation afterwards, and drains failed children before cleanup. Diagnostics
contain the error type without raw exception or message content. All 35 affected
cases and scoped lint/types passed. The immutable receipt is
`shared-realtime-behavior-verification.json` (SHA `a1465e48bd6950cd10acdf452d3f3233d7018c06836237345099c1da5fc081a3`).

The following composition checkpoint preserves those behavior fixes and splits
the service into nine actual responsibility owners: public lifecycle facade,
local connection registry, two-phase capacity manager, Redis lease store,
transport, per-socket queue, immutable contracts, bounded wire protocol/Lua, and
resource cleanup. The facade is 223 lines; the largest owner is the 269-line
transport. There are no runtime proxies, inherited method fragments, or callback
bags. The registry depends on a small read-only availability protocol and the
transport receives the concrete registry for fanout.

Qualification for the composition includes:

- 53 affected test cases, including subscriber/publisher/reconnect recovery,
  malformed renewal responses, six authentication-boundary fields and repeated
  cancellation/close failures.
- Six actual deferred admission/renewal/shutdown controls run against both the
  frozen original hub and the composed hub. These preserve local reservation,
  tenant indexing, cancellation slot release, late-acquire rejection and the
  normal unregister-versus-renew race.
- 125 actual before/current health, readiness and acceptance projections, plus
  twelve public runtime signature/type-hint comparisons. Export aliases,
  default factory, singleton, metrics registration and Lua remain compatible.
- 34 exact complete declaration AST comparisons, nine full method comparisons
  after explicit attribute/call projection, and seven source-expanded control
  flow comparisons. A separate public-wiring supplement verifies six additional
  exact global declarations and the metrics provider call. The original proof
  and receipt remain byte-identical.
- Strict scoped mypy for all nine implementation files and Ruff/format checks
  for all thirteen affected source/test files. Additive normal and critical
  candidates protect the actual relocated owners; no prior realtime cap or
  coverage floor existed and none is reduced.

This is explicitly a composition change to private layout/module metadata,
counter ownership and an immutable drain snapshot. It is not described as
whole-class AST identity. The original test assertions and fixture bodies were
preserved; only parser imports moved to their actual owner.

The frozen current receipt is `shared-realtime-composition-verification.json`
(SHA `9e2d608db998ec3b7ff326b187f15a3b8d1a81e93d7dd032950312e4a8faee52`).
The source records, measurements and original/current controls are linked there.
No live Redis/PostgreSQL service, real file-descriptor leak, authentication
bypass, provider send, production data, VPS release, full application suite or
browser qualification is claimed. One final combined verification remains
parent-owned under the user's current cadence.

The old frontend socket callback lifetime remains an unproven candidate,
separate from the qualified server changes. The exact native-only ingress
refinement is a read-only classification proposal in
`native-ops-scope-refinement-proposal.json`, not a runtime deletion, policy edit,
native feature audit or full semantic read credit. Shared canonical attendance,
staff notifications, push delivery, QR/sync, models and this realtime service
remain retained.
