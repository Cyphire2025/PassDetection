# Mobile attendance QR offline-admission contract

## Security boundary

The coordinator app may queue a new offline attendance scan only when all of the following are true in the encrypted, account-specific database:

- the selected trip is a coordinator trip;
- the complete-roster marker is set;
- the applied roster revision exactly equals the latest advertised revision;
- the SHA-256 digest of the scanned opaque `pdatt:` value matches exactly one passenger in that account and trip;
- the latest token is active and its version, timestamps, expiry, and evidence interval are structurally complete; and
- both the token and its server-observed evidence remain valid under the authenticated server-clock floor, including clock-rollback protection.

Unknown, cross-trip, duplicate, inactive, revoked, expired, incomplete, and stale evidence fails closed before a new queue row is written. Error messages do not contain the token or its digest. Existing confirmed and durable pending items retain their replay/idempotency behavior.

## Data minimization and synchronization

The roster API and local roster projection contain only the token's lowercase SHA-256 digest, version, state, and bounded validity metadata. They never contain the raw bearer QR. The token has 256 bits of random source entropy, so the digest is suitable as a local exact-match index and is not a practical offline password verifier.

The raw QR remains necessary only inside the encrypted pending attendance action until the server validates it. The server remains canonical for tenant/group ownership, current token state, expiry, attendance-session scope, replay, and idempotency; local admission is an additional rejection layer, not an authorization replacement.

QR state participates in the authoritative roster revision. Direct or otherwise unjournaled issue, rotation, revocation, activation, and expiry updates therefore produce a manifest mismatch and force the existing bounded full-roster reconciliation. Targeted passenger journal entries are accepted only when their event-time revision exactly matches the manifest. A UTC evidence epoch also advances every 24 hours so an online coordinator renews the bounded evidence before it ages out. The v21 migration invalidates legacy coordinator projections and requires one complete refresh.

## Operational guarantees and limits

Roster download, snapshot rebase, staging, and promotion are fenced across every page. SQLite writes stay below conservative variable limits, and the lookup index is scoped by account and trip. Queue capacity, durable pending UI, receipt retention, retry, and server reconciliation semantics are unchanged.

This design proves possession of a currently authorized QR; it does not prove physical presence. A passenger can still share a screenshot or forward the opaque QR. Stronger presence assurance requires a product-level control such as supervised visual identity checks, rotating short-lived challenge QR codes, proximity/device attestation, or a combination of those controls. Those options change the accepted attendance workflow and are intentionally not introduced by this compatibility-preserving hardening.
