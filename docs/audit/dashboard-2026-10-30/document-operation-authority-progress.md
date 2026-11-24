# Queued document operations and initiating authority

The earlier queued-operation candidate is now reproduced and corrected for the reviewed normal document workflows. The source baseline and exact current hashes remain separate from the preceding API architecture tranche; all seven API owners stayed byte-identical throughout this work.

The regression mounts the real `AuthenticatedContent` authority-key boundary, `SessionLifecycle`, auth store, document workspace controller/actions and actual discard/manual passenger dialogs. It confirms an operation, holds the framework's asynchronous mutation-start boundary, then calls the real `setSession(B)`. The query client is cleared, the original workspace unmounts and its dialogs disappear. On the original hooks, releasing queued work nevertheless dispatched both old discard requests, or the original synthetic manual PDF, with B's actual `X-Expected-Actor-Id` and authority tuple at the real client adapter's final delegate.

The original normal-path six-case run had two failures and four passing ordinary/profile controls. The expanded eight-case baseline preserved those two failures while also demonstrating that the existing queued-verification controller abort already worked. These are unintended replacement-actor-bound client dispatches; the controls do not establish a server authorization bypass, production data exfiltration or live provider send. Only synthetic sessions/data and a final in-memory HTTP delegate were used. Framework routing/lazy-loading, unrelated activity registration and offline purge side effects are fixture boundaries; authentication remount/reset, request-owner capture/adapter and response/error normalization execute normally.

Ten private mutation hooks now use the existing `usePrivateMutation` boundary, which captures authority at `mutate`/`mutateAsync` invocation before framework awaits. Bulk discard additionally checks that original owner before and after each API await. The API/client/cookie contracts, existing reset/unmount controllers, query keys, receipt order and capability handling remain unchanged. The real client captures its per-request owner synchronously; the caller boundary now reaches singleton API requests with the correct initiating authority, while existing staged flows keep their abort signals.

The final 105-case affected run across twenty files passes with no filtered/pending cases. Its fourteen normal/controller ownership controls include:

- Stale queued discard/manual PDF dispatch denial after real actor replacement and workspace remount.
- Ordinary and same-owner profile-update success with original actor/authority headers and actual per-call success dialog closure.
- Same-user role/agency-change remount and denial of stale queued manual intent.
- Preserved original public variables by identity, undefined context, structured 409 error and an enabled retry dialog for an ordinary manual-upload failure.
- Existing queued-verification abort protection, plus successful same-owner verification and receipt handling.
- In-flight manual type verification cancellation across replacement, with no subsequent receipt finalization or late capability persistence; same-owner profile updates still permit manual proof and receipt-only finalization. These continuation cases use the actual controller methods through a small host rather than rendering the heavyweight PDF type-review preview dialog.
- Acknowledged bulk cleanup stopping before the second API dispatch when authority changes after the first real API result.

The shared private-mutation compatibility tests also run in that affected selection. They cover original custom variables/context, callback/error/settled semantics and overlapping ownership. No test or production behavior was weakened to fit the guard.

An isolated negative ablation removes only the two per-await bulk assertions while keeping invocation capture installed. The selected acknowledged-bulk case then dispatches twice and fails; the other ten cases present in that experiment are explicitly filtered. The experiment's exact fixed bytes are restored in `finally` and verified by SHA. It is separate from the original hook baseline and from the final complete affected run.

The original/current hook proof preserves all fifteen public hook names/order, query keys and fourteen complete hook ASTs after normalizing the intentional wrapper callee change. Bulk deduplication, API arguments, loop/result order and its original `onSettled` callback remain exact around the new checks. TypeScript, four-path scoped lint, 32 existing document source-contract cases and the existing 556 budgets pass. One measured candidate is supplied for the 286-line hook; no existing cap, critical include or numerical floor changed.

The synthetic fixture was divided by responsibility into a 153-line authenticated workspace/controller owner and a 167-line in-memory transport owner. Their closed caller chain is test file → authority fixture → transport fixture. Neither has an app/runtime importer; MCP discovery should classify only its observed test helpers narrowly as internal dependencies, without a new directory ignore or action permission.

Current source hashes and evidence are in `document-operation-authority-reviewed-files.json`, `document-operation-authority-provenance.json` and `document-operation-authority-verification.json`. The old open-candidate API receipt remains historical; this receipt resolves that caller follow-up with actual source/behavior evidence. No whole application suite, production build or broad browser run was performed. The final combined round remains deferred until all remaining source/implementation batches are complete, as requested by the user.
