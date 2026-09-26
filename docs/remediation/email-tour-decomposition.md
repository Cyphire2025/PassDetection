# Email and tour route decomposition

The email integration and tour operations modules previously combined unrelated route families, ownership checks, database locking, provider calls and response construction. They now expose stable facade modules while cohesive owners implement those responsibilities. Existing routes, schemas, endpoint identities, HTTP methods and registration order are preserved: 18 email routes and 30 tour routes. Complete backend and generated mobile OpenAPI snapshots match without accepting a new schema diff.

## Email boundaries

`email_integration_access.py` owns mailbox/tenant scope and locked connection lookup. Shared consent startup owns PKCE, encrypted verifier state, browser/account-generation binding and audit creation. Gmail and Outlook callbacks remain separate because their revocation and rotating-token contracts differ. Connection lifecycle routes share a credential protocol that commits the sync-generation fence before contacting a provider, then reloads the owned row under lock. A revocation failure retains encrypted credentials in a durable blocked state; already-invalid provider tokens retain the original treatment.

Review query/projection and decision routes are separate. Marking a message unrelated delegates its scoped derived-work changes to `infrastructure/email/review_decisions.py` inside the caller's transaction; it does not independently commit. The facade drops from over 2,500 lines to 155. Twenty-two of 27 original function ASTs are unchanged; the five changed functions delegate consent, revocation or review effects. No original function disappeared.

## Tour boundaries

Accounts, coordinator assignments, QR lifecycle, activity sessions, scan admission, closeout and office dashboard queries have separate route owners. Shared access checks retain tenant scope, retained-data policy and row-lock behavior. Canonical activity admission/creation retains the original group-row fence and database conflict handling. Response assemblers use one explicit passenger projection and one session projection so office/coordinator and single/batched responses do not drift. Query counts, ordering, serialized fields and visibility policy remain unchanged.

The facade drops from 2,534 lines to 305; the largest new owner is the 415-line attendance projection module. Forty-nine of 54 original function ASTs are unchanged. The five modified functions remove duplicate projection construction. Imports used by the existing mobile backend and browser attendance-runtime endpoints preserve the same defining helper identities; native application source was not edited.

## Verification and limits

The sanitized receipt is [email-tour-decomposition-evidence.json](email-tour-decomposition-evidence.json). Coverage data is stored under dedicated local output paths and does not replace the repository-wide coverage run.

- Email: 243 existing email tests passed, followed by 38 additional protocol cases. New cases cover both providers' encrypted consent/grant persistence, ownership mismatch rejection, callback state validation, revocation failures and successful/invalid token outcomes, and ordering of the durable fence before provider I/O. Existing account-generation race assertions remain intact.
- Tour: the broader selected suite had 254 passes and two stale facade monkeypatch failures. Those dependency targets were corrected without changing assertions; the corrected two plus twelve new QR/projection cases passed. The final overlapping focused run passed all 93 tests. This is 268 unique tour-related cases evidenced across runs, not a claim of one clean 268-test invocation.
- All 48 original route registrations remain ordered and identity-compatible. The complete backend and mobile OpenAPI snapshots match. Strict typing and source budget checks pass.
- Every extracted module is measured. No extracted email module has a floor below the original 36%; no tour module has a floor below the original 56%. The facades require 95%. Measured higher ratchets include 100% credential protocol and passenger projection coverage, 85% provider callback coverage, 90% consent startup, 90% QR lifecycle and 90% attendance dashboard coverage. Unrelated module and global coverage floors remain unchanged.

The route boundaries still orchestrate ORM/application dependencies; this is not a claim of a repository-wide clean architecture conversion. The review decision function remains complex. Provider behavior is tested with controlled provider substitutes and real token encryption; these tests do not authorize or send real Gmail/Outlook messages. PostgreSQL concurrency, full backend regression and current-image browser qualification belong to the integrated release gate and must be reported separately.
