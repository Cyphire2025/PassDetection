# Mobile local-data retention policy

Status: implemented source policy; signed-device storage inspection remains a release gate.

## Product policy

The Group Companion retains each account's encrypted SQLCipher database, encrypted vault,
encryption keys, durable queues, and minimum namespace metadata across an ordinary sign-out on the
same installation. Ordinary sign-out locks that namespace; it does not purge its encrypted offline
data. This preserves recoverable offline work and completed encrypted downloads without making any
of them available to another account.

The account namespace includes agency and principal ownership, and trip/passenger ownership where
applicable. While signed out, no roster, document, My Photos filename, thumbnail, count, manifest,
queue detail, or decrypted content is visible. A different account on the same installation cannot
enumerate or decrypt the locked namespace. The same authenticated account can unlock it after
signing in again, subject to current server authorization, signed offline-authorization policy, and
trip access reconciliation.

Ordinary sign-out is fail-safe:

1. In-memory authentication and the selected trip are cleared synchronously.
2. Push registration and server refresh credentials are revoked on a
   best-effort basis; being offline cannot delay local sign-out.
3. A durable authentication-lock marker is written before changing the in-memory boundary.
4. Refresh credentials, selected-trip state, notification-response state, push-registration state,
   and the signed offline-authorization record are removed from secure storage.
5. The account database is closed and temporary decrypted viewer files are purged.
6. The SQLCipher database, encrypted vault, database key, vault key, durable queues, and namespace
   ownership record remain encrypted at rest for same-account recovery.
7. If locking is interrupted, bootstrap retries the lock and does not silently restore the account.

The durable action queue must be synchronized before ordinary sign-out. If work cannot be
synchronized, the UI may offer a separately confirmed destructive discard. That explicit path is
not ordinary sign-out and invokes the fenced namespace purge described below.

## Data that is not retained after ordinary sign-out

- refresh tokens and signed offline authorization leases;
- temporary decrypted viewer files and rendering cache residue;
- the installation/session push registration on the server, subject to the
  server request reaching the service.

The encrypted account database and vault, account-scoped database/vault keys, durable queues,
encrypted documents, completed My Photos ciphertext, and minimum encrypted manifests are retained
but locked. Retention is not proof of continued server access. On the same account's next login,
normal authorization and trip reconciliation can purge revoked or expired trip data before it is
presented.

## Explicit destructive removal

An explicitly confirmed discard of unsynchronized actions invokes the existing destructive account
purge. The purge records a durable cleanup marker, fences vault writes, deletes the account database
and encrypted vault, then removes namespace keys and metadata. If deletion fails partway, the
namespace remains fenced and bootstrap retries it; authentication is revoked without prematurely
deleting the keys needed to finish deleting recoverable ciphertext.

Completed My Photos copies are also removed by the narrower **Remove downloaded copies** or
**Clear My Photos storage** action. Account deletion, application/device data wipe, uninstall, and
a security-driven destructive revocation remove the applicable retained namespace according to
the reviewed policy. A My Photos-only cleanup removes the selected manifests, encrypted files, and
staging residue behind the vault-write fence. It does not delete the shared account vault key while
documents or other retained vault data may still need it. Destructive account cleanup removes the
entire encrypted namespace and deletes its account-scoped key material only after fenced storage
cleanup has completed.

**Delete Face Scan** and **Remove my face-search data** are server biometric/enrollment actions.
They do not silently delete completed event-photo downloads. If a future legal or administrative
policy requires both actions, the passenger must receive an explicit warning and the destructive
local purge must be independently recorded and retried.

## Security boundary and limitations

Key deletion provides cryptographic erasure for ciphertext that may remain in flash translation
layers or operating-system backups. Ordinary sign-out deliberately retains the account database and
vault keys; access control depends on the authentication lock, account-bound namespace, current
authorization, and platform key protection. The application cannot prove physical block erasure
from JavaScript. Production acceptance therefore requires storage inspection on signed Android and
iOS builds after logout, different- and same-account login, explicit My Photos removal, destructive
discard/revocation, force-stop during lock or purge, reboot, restore, reinstall, and uninstall.
Platform backup exclusions and store privacy declarations are separate release gates and must match
this policy.

No production identifiers, document content, tokens, file paths, or user data
may be captured in cleanup telemetry. Only fixed outcome codes and aggregate
durations are permitted.
