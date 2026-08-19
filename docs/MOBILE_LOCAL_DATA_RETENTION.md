# Mobile local-data retention policy

Status: implemented source policy; signed-device storage inspection remains a release gate.

## Product policy

The Group Companion keeps encrypted offline data only while the corresponding
mobile account remains authenticated and authorized on that installation.
Explicit sign-out, account replacement, authorization revocation, or a failed
account-boundary reconciliation initiates deletion of that account's encrypted
SQLite database, encrypted document vault, temporary plaintext views, and
namespace-specific key material.

Sign-out is fail-safe:

1. In-memory authentication and the selected trip are cleared synchronously.
2. Push registration and server refresh credentials are revoked on a
   best-effort basis; being offline cannot delay local sign-out.
3. A durable cleanup marker is written before database or vault deletion.
4. Account vault writes are fenced before deletion begins.
5. Database and vault ciphertext are deleted before namespace keys are removed.
6. If deletion is interrupted, credentials stay revoked, the account remains
   fenced, and bootstrap retries the cleanup before that namespace can reopen.

This intentionally trades a fresh synchronization after the next login for a
smaller privacy and lost-device exposure window. There is no hidden
"reactivation retention" mode.

## Data that is not retained after successful sign-out

- refresh tokens and signed offline authorization leases;
- the account database and its roster, notification, itinerary, attendance,
  and queue projections;
- encrypted documents and account-scoped vault metadata;
- temporary decrypted viewer files and rendering cache residue;
- account-scoped database and vault encryption keys;
- the installation/session push registration on the server, subject to the
  server request reaching the service.

## Security boundary and limitations

Key deletion provides cryptographic erasure for ciphertext that may remain in
flash translation layers or operating-system backups. The application cannot
prove physical block erasure from JavaScript. Production acceptance therefore
requires storage inspection on signed Android and iOS builds after logout,
account switch, force-stop during cleanup, reboot, restore, and reinstall.
Platform backup exclusions and store privacy declarations are separate release
gates and must match this policy.

No production identifiers, document content, tokens, file paths, or user data
may be captured in cleanup telemetry. Only fixed outcome codes and aggregate
durations are permitted.
