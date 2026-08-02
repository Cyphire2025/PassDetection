# Group Companion architecture

Status: implementation contract
Owners: PassDetection platform and Group Companion mobile
Clients: Android, iOS, and the existing staff dashboard

## Product boundary

Group Companion is one React Native application with three fail-closed modes:
passenger, client manager, and coordinator. PassDetection remains the source of
truth. The native application never becomes an alternate document-submission
channel, an administrative dashboard, or an independent store of travel data.

The existing passport collection links, public upload pages, WhatsApp delivery,
document processing, and dashboard coordinator workflows remain unchanged.
The existing Android WebView coordinator shell remains available during native
parity validation.

## Technology decision

The mobile application uses Expo SDK 57 with TypeScript and Expo Router in the
prebuild workflow. The generated Android and iOS projects are committed so that
native security configuration and release builds are reviewable. It is not an
Expo Go application and does not contain a WebView-based product surface.

Native responsibilities are split as follows:

| Concern | Implementation |
| --- | --- |
| Navigation | Expo Router with role-specific route groups and native stacks |
| Metadata | SQLite with SQLCipher, normalized tables, and one account namespace per database |
| Secrets | Android Keystore and iOS Keychain through SecureStore |
| Documents | AES-256-GCM encrypted files in application-private storage |
| Networking | Fixed HTTPS API origin, short-lived bearer access tokens, rotating refresh tokens |
| Synchronization | Cursor journal, entity versions, tombstones, and access generations |
| Background work | Foreground/reconnect sync plus opportunistic OS background tasks and push-triggered refresh |
| Notifications | Provider abstraction supporting Expo, FCM, and APNs registrations |
| Sensitive screens | Local device unlock, screen-capture controls where supported, and redacted app-switcher state |

The access token is held in memory. The refresh token and the key-wrapping
material are stored in platform secure storage. Biometric authentication unlocks
local state; it does not replace server authentication.

## Trust and authorization model

The application has four independent authorization boundaries:

1. The authenticated mobile principal belongs to an agency tenant.
2. The group is explicitly enabled in GC App and its lifecycle and access window permit access.
3. The principal role is enabled for the group and has an explicit group relationship.
4. A passenger-owned resource also matches the authenticated passenger identity or an explicit, active delegation.

Every resource query applies all four boundaries server-side. A group ID,
passenger ID, document ID, or cursor supplied by the device is only a locator;
it is never authorization evidence.

Client managers are separate from internal agency managers. They are linked to a
client organization for administration, but group access comes exclusively from
explicit assignments. Organization membership never grants implicit access to
all of that client's groups. Personal-document access is absent from the initial
manager permissions.

Coordinator access reuses existing coordinator assignments and attendance
business rules underneath a compact mobile response contract. The mobile API
does not expose passport fields, MRZ data, AI confidence, or internal notes in a
coordinator roster.

Passenger access is derived only after successful phone verification and a safe
claim. Shared or duplicated phone numbers require an explicitly configured
secondary verifier or invitation. Surname and phone similarity never create a
delegation.

## Group access lifecycle

A dashboard group is invisible to every mobile role until a GC App control row
is created and enabled. Access checks combine:

- tenant identity;
- group lifecycle;
- overall GC App enablement;
- role-specific enablement;
- start and expiry timestamps;
- immediate revocation timestamp;
- principal assignment or passenger ownership; and
- access generation.

Active and closed groups may be available inside their configured window.
Archived and deleted groups fail closed. There is no implicit read-only retention
policy in the initial release. Revocation increments `access_generation`, writes
a tombstone/change event, invalidates affected sessions or claims, and instructs
devices to purge the group namespace and encrypted files.

Security-changing updates use an optimistic `revision` and database row locking.
The dashboard must refresh after a conflict; it does not optimistically claim
that an access change succeeded.

## Authentication

### Passenger OTP

1. The device submits a normalized phone number and installation metadata.
2. The server returns the same generic response whether or not an eligible identity exists.
3. The server stores only a keyed digest of the OTP, with expiry, attempt limit, resend cooldown, phone limit, and IP limit.
4. Successful verification exposes only eligible trip claims for currently enabled groups.
5. A unique claim can issue a passenger session; an ambiguous claim requires the configured secondary proof.
6. Claim completion rechecks group access and passenger membership under lock before issuing tokens.

The OTP sender is a provider protocol. Production supports an approved Meta
WhatsApp authentication template through the existing Cloud API transport and
remains fail-closed until its credentials, template name, and exact language are
configured. The development provider is forbidden in production and must not log
codes outside an explicit local-development setting. See
`docs/architecture/whatsapp-passenger-otp.md` for the template contract.

### Client manager and coordinator

Credential login reuses the platform password hasher and account status rules,
then enforces the distinct mobile-role policy. A forced-password-change account
receives a restricted session whose access token carries
`pwd_change_required=true`. Only `me`, password change, refresh, and logout are
available. Trip, sync, push, document, and operational endpoints reject that
session. Password change revokes the restricted session and returns a normal
rotated session.

### Sessions

Access tokens are short lived, signed with a dedicated mobile secret, and require
an algorithm allowlist, issuer, audience, expiry, token type, session ID, tenant,
principal type, and device installation ID. Refresh tokens are opaque random
values whose hashes are stored server-side. Refresh rotation is single-use;
reuse revokes the token family. Logout, account suspension, group revocation,
password reset, and dashboard "revoke all sessions" operations are audited.

## Data model

The additive server model contains these domains:

- client organizations, client-manager profiles, and explicit group assignments;
- GC App group controls with role flags, windows, revision, access generation, and published-version counters;
- versioned itinerary drafts/publications, common documents, and announcements;
- passenger mobile identities and explicit family/dependent delegations;
- OTP challenges and rate-limit state;
- device-bound mobile sessions and refresh-token families;
- push registrations and role-scoped mobile notification deliveries;
- an incremental change journal with monotonic sequence numbers and tombstones;
- idempotent pending-action receipts and coordinator incident records.

Family delegation is modeled but disabled by default. It requires an explicit
dashboard authorization, selected dependents, an expiry/revocation state, and an
audit record for each sensitive access.

## Mobile API shape

The dedicated namespace is `/api/v1/mobile`. It is a response-shaping and
authorization boundary over shared application services, not a duplicate domain.

Core resources are:

- `auth/request-otp`, `auth/verify-otp`, `auth/claim`, `auth/login`, `auth/refresh`, `auth/password`, and `auth/logout`;
- `me`, `sessions`, and `push-registrations`;
- bounded `trips` and a trip `manifest`;
- itinerary, announcements, common-document metadata, and passenger-scoped personal-document metadata;
- personal room, meals, QR representation, and profile;
- manager readiness summaries;
- coordinator roster pages, attendance sessions/actions, rooming, meals, tasks, missing passengers, and incidents;
- `sync/changes` with bounded pages and tombstones.

All response schemas are explicit and compact. Sensitive responses use
`Cache-Control: no-store`. Raw ORM objects and raw object-storage URLs are not
serialized.

## Publishing model

Itinerary, common documents, and announcements have separate draft and published
states. Editing a draft cannot modify the currently published mobile view.
Publishing runs in a transaction that:

1. validates the GC group and staff permission;
2. locks the group control row;
3. advances the relevant published version;
4. records the published snapshot;
5. appends change-journal entries;
6. records an audit event; and
7. schedules a non-sensitive notification event after commit.

Common-document uploads are bounded and allowlisted by MIME/content signature.
The object key is server-generated, the original name is metadata only, and a
SHA-256 checksum and byte length are recorded before publication.

## Synchronization protocol

The trip manifest is metadata-first and contains:

- `server_time` and `next_cursor`;
- `access_generation` and the three published content versions;
- entity versions and checksums;
- document metadata without storage locations;
- tombstones and purge instructions; and
- a bounded indication of further pages.

The device applies each page in one SQL transaction. The cursor advances only
after the page commits. Changes are idempotent by `(entity_type, entity_id,
version)`. A lower version never overwrites a higher local version. An access-
generation mismatch purges the trip namespace before applying current data.

Foreground launch, reconnect, manual retry, and push events trigger authoritative
sync. Background execution is opportunistic because Android and iOS may defer it.
Requests are deduplicated per trip, cancellable, bounded, and retried with jitter.
No client repeatedly polls or downloads an entire group.

Offline mutations use a durable `PendingAction` row with a UUID idempotency key,
principal/tenant/trip namespace, base version, payload, attempts, and explicit
state. Coordinator attendance preserves the existing serialized drain and
server-side idempotency behavior. Conflicts return a machine-readable policy:
accepted, already-applied, retryable, rejected, or refresh-required.

## Encrypted document vault

Document metadata syncs independently from file bytes. A file is downloaded only
when requested or allowed by the user's prefetch policy and only when its version
or checksum changes.

The download flow is:

1. request passenger-bound or role-bound short-lived authorization;
2. stream into an app-private temporary file with a byte ceiling;
3. validate response type, safe display name, expected length, and checksum;
4. encrypt with a fresh AES-256-GCM nonce using an account-scoped key protected by Keystore/Keychain;
5. atomically commit the ciphertext and local metadata; and
6. remove temporary and obsolete versions.

There is no shared personal-document cache. The file path includes an opaque
account namespace and cannot be supplied by the server. Download concurrency is
bounded. Interrupted temporary files have no plaintext retention and are cleaned
on startup. Revocation, expiry, logout, account change, a fresh-install marker
mismatch, and "Remove offline documents" delete the affected encrypted vault.

The app never writes passports, visas, or tickets to public Downloads or Gallery
locations automatically. Analytics, logs, crash reports, and notification text
contain document categories and opaque IDs only, never document contents or
passport fields.

## Local database

The encrypted database uses separate normalized tables for `User`, `Role`,
`Trip`, `ItineraryDay`, `ItineraryItem`, `Announcement`, `DocumentMetadata`,
`OfflineFile`, `PassengerProfile`, `RoomAssignment`, `MealInformation`,
`QRMetadata`, `SyncCursor`, and `PendingAction`.

Every row is namespaced by account and tenant, then by trip and passenger where
applicable. The active account is not accepted as an implicit query filter:
repositories require the namespace as an input and tests cover account switching.
The database and vault are closed before any active-account pointer changes.

## QR and attendance

Passenger QR material is passenger- and group-specific. The local record stores
only the minimum signed representation and its validity metadata. Cross-group
reuse is rejected server-side. The QR screen may temporarily raise brightness and
must restore the previous value on blur/unmount.

Coordinator offline scanning uses a bounded group-specific verification set and
the existing attendance idempotency semantics. Scan events contain unique client
event IDs, capture time, checkpoint/session, and the minimum passenger reference.
Camera duplicate suppression is a UX optimization; database/server idempotency is
the authoritative duplicate control.

## Notifications and privacy

Push registrations bind provider token, device installation, mobile session,
tenant, principal type, and optional trip. Registration and delivery are
idempotent. Events use opaque identifiers and generic lock-screen copy such as
"A trip document was updated." Opening the app performs authorization again and
then deep-links to the destination. Read state is server-backed and mirrored
locally.

## Dashboard boundary

The staff dashboard exposes one top-level `GC App` section with exactly two
primary destinations:

- Client Manager Accounts
- App Controls

Client-manager deletion is a profile/session operation and must never reuse any
internal-manager deletion flow that removes groups or passenger records. App
Controls owns group enablement, role windows, content drafts/publication,
versions, active-device summaries, sync state, and audit history. All mutation
routes use existing dashboard cookie/CSRF protection plus server-side capability
checks.

## Performance budgets and measurement

Production verification records actual values rather than promising "zero lag."
The initial budgets are:

| Signal | Budget |
| --- | --- |
| Manifest page | at most 500 changes and at most 512 KiB uncompressed |
| Manager group list | server-paginated, default 25 and maximum 100 |
| Coordinator roster | server-paginated, default 50 and maximum 200 |
| Parallel document downloads | 2 per device |
| Network request timeout | endpoint-specific, with cancellation and jittered retry |
| Offline queue drain | serialized per trip and action class |
| UI lists | virtualized; no unbounded passenger or announcement render |

Cold start, warm start, screen transitions, manifest bytes, download time, local
database size, memory, API p50/p95/p99, and crash-free sessions are measured in a
release-candidate build. Synthetic large-group tests cover at least 1,500
passengers, but synthetic measurements are labeled as such and are not presented
as physical-device results.

## Failure and rollback behavior

The feature is additive and disabled by default. Backend deployment precedes the
dashboard and native releases. The migration adds tables, enums/constraints, and
indexes without changing existing travel records. Rollback first disables all GC
App controls and the mobile API, revokes mobile sessions, and stops notification
workers. Dashboard and app releases can then roll back independently. New tables
remain in place until a separately reviewed cleanup migration; rollback never
drops passenger, document, attendance, or group data.

Network failure retains only the correctly namespaced last-known authorized
snapshot. Authorization ambiguity, cursor corruption, account mismatch, failed
decryption, malformed payloads, and generation mismatch fail closed and trigger a
scoped refresh or purge. They never fall back to another account's cache.
