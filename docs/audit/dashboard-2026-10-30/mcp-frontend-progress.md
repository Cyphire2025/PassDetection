# MCP web review and implementation

All34source files in11frozen batches have been physically read, including the
small shared test fixture. This is a frontend source checkpoint, not a complete
audit of the backing MCP server or a completion of all architectural follow-through.
Current hashes are in mcp-frontend-reviewed-files.json.

The latest focused MCP checkpoint passes180cases across18files, current scoped
TypeScript and ESLint. The ledger now has45full current records, including six
new runtime owners and fully read/written tests. Related backend presentation
and application reviews have their own64-file and84-file ledgers; neither those
reads nor this focused checkpoint establishes real-service release qualification.

Two unreachable consent/example components and their closed client methods,
types and endpoint aliases have been retired after a compiler declaration,
computed-access and facade-escape review. The original14named imports had no
aliases; all six production escapes were actual type queries. Backend/native
OAuth endpoints remain. A temporary unused export barrel was caught and removed
before qualification; its source hash is retained in the retirement manifest.

Current native OAuth/policy coverage passed94cases before retirement. Nine
additional malformed/scope cases now run at the actual native request boundary;
all15selected cases pass without creating pending credentials. Current reviewed
approval/waiting controls passed26cases, and live deletion has an explicit
non-POST/non-PATCH transport assertion. Six obsolete consent UI cases and24
parser-only cases were mapped to actual current approval/callback/backend
controls before retirement. The live callback validator and its negative loops
remain; one additional current whitespace-only approval case was added.

DTOs/capability labels, queries, policy mutations and connection mutations now
have focused owners, retaining the public API and hook import paths. Exact AST
checks preserve35moved declarations, all18live transport methods, capabilities
and query-key initializers. Imports and member fields are expanded for reading.
Ten measured ratchets were merged with the UI/GC batch: eight new owners and
lower ceilings for both existing public modules. No prior ceiling or coverage
floor was raised. mcp-architecture-verification.json separates current evidence
from the historical209-case checkpoint and initial corrected fixture failures.

The live requester page could redirect after the user had left it while
finalization was pending. The negative regression observed that late callback.
A component-lifetime guard now suppresses it; ordinary status refreshes retain
the same in-progress finalization, including in StrictMode. All15requester tests
pass. No callback destination validation, OAuth state/issuer check, comparison-code
flow or anonymous requester authorization was relaxed.

Five actual hook regressions reproduced old administrative intents dispatching
after account changes during global mutation admission or query cancellation.
Nine live MCP administration write hooks now use the shared private mutation
envelope, captured synchronously at invocation. The original actor precondition
is passed to HTTP separately from JSON. Existing calls without the optional
configuration retain their original argument/body shape. The shared wrapper
preserves public variables and per-call callbacks; its own eight behavior checks
and GC integration have separate receipts.

The download verifier now cancels a body immediately when its attachment metadata
is rejected and releases its reader on success or failure. Three negative resource
checks reproduced the previous behavior. Exact-size, streamed byte limits,
SHA-256, Unicode attachment names and explicit delivery acknowledgement remain.
The transfer utility/API/save check passed24tests across3files.

The later complete current MCP test run passed209tests across18files. Scoped lint
passed. Three component test fixtures previously mounted private administration
without any signed-in actor; they now use a complete synthetic administrator.
No original behavior assertions were removed to accommodate the new guard.
The first combined run's16fixture failures remain in mcp-frontend-current-unit.txt;
the corrected run is mcp-frontend-current-unit-after-fixtures.txt. It must not be
confused with the five expected negative owner regressions in the before receipt.

Two further actual-hook regressions observed five requests instead of two after
access denial. Automatic administrative request/operation polling now stops on
401/403/404; explicit refresh can recover, and the existing handling of transient
errors remains. Six denial/recovery cases pass across both hooks. The combined
209-case result is mcp-frontend-denial-unit.txt. Permission normalization also
builds lookup maps once instead of repeatedly scanning tools and write sections;
all15existing permission behavior cases pass.

Still open:

- Continue readable editor/view follow-through. Low physical line counts are
  not evidence of readable code; completed API/types/hooks extraction does not
  close the remaining compact JSX owners.
- Review manual transfer-operation cancellation/lifetime and recovery races.
- Keep affected checks during coherent implementation, then applicable combined
  frontend checks/build/current-production browser journeys at the next deliberate
  stable checkpoint and final verification. Do not rebuild for source reads,
  tracker updates or unrelated small edits. PostgreSQL/Redis/private object
  storage, native deployment and VPS checks remain separate release gates.
