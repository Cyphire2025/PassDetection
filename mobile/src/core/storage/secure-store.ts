import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';

import { excludeAppPrivateUriFromBackup } from './ios-backup';
import { createReplicatedNamespaceMarker } from './replicated-namespace-marker';
import {
  type AccountSecureValueKind,
  assertSecureValueAccessAvailable,
  isUnlockedOnlySecureValueAccessAvailable,
  type SecureValueKind,
} from './secure-store-policy';
import {
  deleteSecureValueFromBackend,
  readSecureValueFromBackend,
  writeSecureValueToBackend,
} from './secure-value-backend';
import { compareAndSetSecureValue, withSecureValueOperation } from './secure-value-operation';

const KEY_PREFIX = 'gc.v1';
const NAMESPACE_INDEX_KEY = `${KEY_PREFIX}.namespaces`;
const INSTALLATION_ID_KEY = `${KEY_PREFIX}.installation-id`;
const ACTIVE_NAMESPACE_KEY = `${KEY_PREFIX}.active-namespace`;
const PENDING_CLEANUP_KEY = `${KEY_PREFIX}.pending-cleanup`;
const PENDING_AUTH_LOCK_KEY = `${KEY_PREFIX}.pending-auth-lock`;
const INSTALL_MARKER = new File(Paths.document, '.gc-install-marker-v1');
const PENDING_CLEANUP_FILE = new File(Paths.document, '.gc-pending-cleanup-v1.json');
const PENDING_AUTH_LOCK_FILE = new File(Paths.document, '.gc-pending-auth-lock-v1.json');
const secretCreationInFlight = new Map<string, Promise<string>>();
let namespaceIndexMutationTail: Promise<void> = Promise.resolve();

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type SecretKind = AccountSecureValueKind;

export type OfflineAuthorizationRecord = Readonly<{
  formatVersion: 1;
  compactLease: string;
  highWaterServerTimeMs: number;
  anchoredWallClockMs: number;
}>;

export type DatabaseHealthMarker = {
  formatVersion: 1;
  state: 'clean' | 'dirty';
  schemaVersion: number;
  lastIntegrityCheckAtMs: number;
};

export type PushRegistrationMarker = Readonly<{
  formatVersion: 1;
  sessionId: string;
  provider: 'expo' | 'fcm' | 'apns';
  tokenDigest: string;
  installationId: string;
  registeredAtMs: number;
}>;

export type AppAttestKeyRecord = Readonly<{
  formatVersion: 1;
  keyId: string;
  registered: boolean;
}>;

const DATABASE_HEALTH_MARKER_FORMAT_VERSION = 1;

function isOfflineAuthorizationRecord(value: unknown): value is OfflineAuthorizationRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === 4
    && record.formatVersion === 1
    && typeof record.compactLease === 'string'
    && record.compactLease.length >= 256
    && record.compactLease.length <= 4_096
    && /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(record.compactLease)
    && typeof record.highWaterServerTimeMs === 'number'
    && Number.isSafeInteger(record.highWaterServerTimeMs)
    && record.highWaterServerTimeMs >= 0
    && typeof record.anchoredWallClockMs === 'number'
    && Number.isSafeInteger(record.anchoredWallClockMs)
    && record.anchoredWallClockMs >= 0;
}

function isDatabaseHealthMarker(value: unknown): value is DatabaseHealthMarker {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const marker = value as Record<string, unknown>;
  const keys = Object.keys(marker);
  return keys.length === 4
    && keys.every((key) => [
      'formatVersion',
      'state',
      'schemaVersion',
      'lastIntegrityCheckAtMs',
    ].includes(key))
    && marker.formatVersion === DATABASE_HEALTH_MARKER_FORMAT_VERSION
    && (marker.state === 'clean' || marker.state === 'dirty')
    && typeof marker.schemaVersion === 'number'
    && Number.isSafeInteger(marker.schemaVersion)
    && marker.schemaVersion >= 0
    && typeof marker.lastIntegrityCheckAtMs === 'number'
    && Number.isSafeInteger(marker.lastIntegrityCheckAtMs)
    && marker.lastIntegrityCheckAtMs >= 0;
}

function isPushRegistrationMarker(value: unknown): value is PushRegistrationMarker {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const marker = value as Record<string, unknown>;
  return Object.keys(marker).length === 6
    && marker.formatVersion === 1
    && typeof marker.sessionId === 'string'
    && UUID_PATTERN.test(marker.sessionId)
    && (marker.provider === 'expo' || marker.provider === 'fcm' || marker.provider === 'apns')
    && typeof marker.tokenDigest === 'string'
    && /^[0-9a-f]{64}$/i.test(marker.tokenDigest)
    && typeof marker.installationId === 'string'
    && UUID_PATTERN.test(marker.installationId)
    && typeof marker.registeredAtMs === 'number'
    && Number.isSafeInteger(marker.registeredAtMs)
    && marker.registeredAtMs >= 0;
}

function assertNamespace(namespace: string): void {
  if (!/^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(namespace)) {
    throw new Error('Invalid account namespace.');
  }
}

function keyFor(namespace: string, kind: SecretKind): string {
  assertNamespace(namespace);
  return `${KEY_PREFIX}.${namespace}.${kind}`;
}

function readSecureValue(key: string, kind: SecureValueKind): Promise<string | null> {
  return withSecureValueOperation(
    key,
    () => readSecureValueFromBackend(key, kind),
  );
}

function writeSecureValue(
  key: string,
  kind: SecureValueKind,
  value: string,
): Promise<void> {
  return withSecureValueOperation(
    key,
    () => writeSecureValueToBackend(key, kind, value),
  );
}

function deleteSecureValue(key: string, kind: SecureValueKind): Promise<void> {
  return withSecureValueOperation(
    key,
    () => deleteSecureValueFromBackend(key, kind),
  );
}

async function readNamespaces(): Promise<string[]> {
  const encoded = await readSecureValue(NAMESPACE_INDEX_KEY, 'namespace-index');
  if (!encoded) return [];

  try {
    const parsed: unknown = JSON.parse(encoded);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (value): value is string =>
        typeof value === 'string' && /^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(value),
    );
  } catch {
    return [];
  }
}

function parseNamespaceList(encoded: string | null, strict = false): string[] {
  if (!encoded) return [];
  try {
    const parsed: unknown = JSON.parse(encoded);
    if (!Array.isArray(parsed)) throw new Error('Invalid namespace list.');
    const valid = parsed.filter(
      (value): value is string => (
        typeof value === 'string' && /^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(value)
      ),
    );
    if (strict && valid.length !== parsed.length) throw new Error('Invalid namespace list.');
    return valid;
  } catch {
    if (strict) throw new Error('Secure cleanup state is unavailable.');
    return [];
  }
}

async function readPendingCleanups(): Promise<string[]> {
  const combined = new Set<string>();
  let secureStoreReadable = false;
  let fileReadable = false;
  let firstError: unknown;
  let secureStoreEncoded: string | null = null;
  try {
    secureStoreEncoded = await readSecureValue(PENDING_CLEANUP_KEY, 'pending-cleanup');
    secureStoreReadable = true;
  } catch (error) {
    firstError = error;
  }
  if (secureStoreReadable) {
    // A malformed replica is not equivalent to an empty cleanup queue. Failing
    // closed prevents a damaged marker from silently restoring an account that
    // was explicitly logged out.
    for (const namespace of parseNamespaceList(secureStoreEncoded, true)) {
      combined.add(namespace);
    }
  }

  let fileEncoded: string | null = null;
  try {
    fileEncoded = PENDING_CLEANUP_FILE.exists ? await PENDING_CLEANUP_FILE.text() : null;
    fileReadable = true;
  } catch (error) {
    firstError ??= error;
  }
  if (fileReadable) {
    for (const namespace of parseNamespaceList(fileEncoded, true)) combined.add(namespace);
  }
  if (!secureStoreReadable && !fileReadable) throw firstError;
  return [...combined];
}

async function writePendingCleanupFile(pending: string[]): Promise<void> {
  PENDING_CLEANUP_FILE.create({ overwrite: true, intermediates: true });
  PENDING_CLEANUP_FILE.write(JSON.stringify(pending));
  try {
    await excludeAppPrivateUriFromBackup(PENDING_CLEANUP_FILE.uri);
  } catch (error) {
    // A cleanup tombstone must not silently become a restorable replica. The
    // SecureStore copy can still satisfy best-effort writes when available.
    try {
      if (PENDING_CLEANUP_FILE.exists) PENDING_CLEANUP_FILE.delete();
    } catch {
      // Preserve the original backup-exclusion failure for deterministic retry.
    }
    throw error;
  }
}

async function writePendingCleanups(
  pending: string[],
  requireEveryReplica: boolean,
): Promise<void> {
  let secureStoreWritten = false;
  let fileWritten = false;
  let firstError: unknown;
  try {
    await writeSecureValue(PENDING_CLEANUP_KEY, 'pending-cleanup', JSON.stringify(pending));
    secureStoreWritten = true;
  } catch (error) {
    firstError = error;
  }
  try {
    await writePendingCleanupFile(pending);
    fileWritten = true;
  } catch (error) {
    firstError ??= error;
  }
  if (
    (!secureStoreWritten && !fileWritten)
    || (requireEveryReplica && (!secureStoreWritten || !fileWritten))
  ) {
    throw firstError ?? new Error('Secure cleanup state could not be persisted.');
  }
}

async function mutateNamespaceIndex<T>(operation: () => Promise<T>): Promise<T> {
  const previous = namespaceIndexMutationTail;
  let release!: () => void;
  namespaceIndexMutationTail = new Promise<void>((resolve) => {
    release = resolve;
  });
  await previous;
  try {
    return await operation();
  } finally {
    release();
  }
}

async function trackNamespace(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await mutateNamespaceIndex(async () => {
    const namespaces = new Set(await readNamespaces());
    namespaces.add(namespace);
    await writeSecureValue(NAMESPACE_INDEX_KEY, 'namespace-index', JSON.stringify([...namespaces]));
  });
}

export type InstallationBinding = {
  markerInstallationId: string | null;
  secureInstallationId: string | null;
};

export function isTrustedInstallationBinding(binding: InstallationBinding): boolean {
  return binding.secureInstallationId !== null
    && UUID_PATTERN.test(binding.secureInstallationId)
    && binding.markerInstallationId === binding.secureInstallationId;
}

export async function readInstallationBinding(): Promise<InstallationBinding> {
  const secureInstallationId = await readSecureValue(INSTALLATION_ID_KEY, 'installation-id');
  const markerInstallationId = INSTALL_MARKER.exists ? await INSTALL_MARKER.text() : null;
  return { markerInstallationId, secureInstallationId };
}

export async function protectInstallationMarkersFromBackup(): Promise<void> {
  if (INSTALL_MARKER.exists) await excludeAppPrivateUriFromBackup(INSTALL_MARKER.uri);
  if (PENDING_CLEANUP_FILE.exists) {
    await excludeAppPrivateUriFromBackup(PENDING_CLEANUP_FILE.uri);
  }
  if (PENDING_AUTH_LOCK_FILE.exists) {
    await excludeAppPrivateUriFromBackup(PENDING_AUTH_LOCK_FILE.uri);
  }
}

const authenticationLockMarker = createReplicatedNamespaceMarker({
  assertNamespace,
  errorMessage: 'Secure authentication-lock state could not be persisted.',
  excludeFromBackup: excludeAppPrivateUriFromBackup,
  file: PENDING_AUTH_LOCK_FILE,
  mutate: mutateNamespaceIndex,
  readSecureReplica: () => readSecureValue(PENDING_AUTH_LOCK_KEY, 'pending-cleanup'),
  writeSecureReplica: (encoded) => (
    writeSecureValue(PENDING_AUTH_LOCK_KEY, 'pending-cleanup', encoded)
  ),
});

export async function clearSecureStateForInstallationReset(): Promise<void> {
  // Do not remove the namespace index until it has been read successfully; it
  // is the only bounded inventory of account-scoped Keychain entries available
  // for a deterministic retry after a transient Keychain outage.
  const namespaces = await readNamespaces();
  let firstError: unknown;
  const capture = async (operation: () => Promise<unknown> | unknown): Promise<void> => {
    try {
      await operation();
    } catch (error) {
      firstError ??= error;
    }
  };
  await Promise.all(namespaces.flatMap((namespace) => ([
    'refresh',
    'database-key',
    'vault-key',
    'selected-trip',
    'notification-response',
    'push-registration',
    'database-health',
    'offline-authorization',
    'app-attest-key-id',
  ] as const).map((kind) => capture(() => deleteSecureValue(keyFor(namespace, kind), kind)))));
  await Promise.all(([
    [NAMESPACE_INDEX_KEY, 'namespace-index'],
    [INSTALLATION_ID_KEY, 'installation-id'],
    [ACTIVE_NAMESPACE_KEY, 'active-namespace'],
    [PENDING_CLEANUP_KEY, 'pending-cleanup'],
    [PENDING_AUTH_LOCK_KEY, 'pending-cleanup'],
  ] as const).map(([key, kind]) => capture(() => deleteSecureValue(key, kind))));
  await capture(() => {
    if (PENDING_CLEANUP_FILE.exists) PENDING_CLEANUP_FILE.delete();
  });
  await capture(() => {
    if (PENDING_AUTH_LOCK_FILE.exists) PENDING_AUTH_LOCK_FILE.delete();
  });
  await capture(() => {
    if (INSTALL_MARKER.exists) INSTALL_MARKER.delete();
  });
  if (firstError) throw firstError;
}

export async function writeInstallationBinding(installationId: string): Promise<void> {
  if (!UUID_PATTERN.test(installationId)) throw new Error('Invalid installation identity.');
  await writeSecureValue(INSTALLATION_ID_KEY, 'installation-id', installationId);
  const parent = new Directory(Paths.document);
  if (!parent.exists) parent.create({ idempotent: true, intermediates: true });
  try {
    INSTALL_MARKER.create({ overwrite: true, intermediates: true });
    INSTALL_MARKER.write(installationId);
    await excludeAppPrivateUriFromBackup(INSTALL_MARKER.uri);
  } catch (error) {
    try {
      if (INSTALL_MARKER.exists) INSTALL_MARKER.delete();
    } catch {
      // A missing or unreadable marker still prevents trusting the half-write.
    }
    await deleteSecureValue(INSTALLATION_ID_KEY, 'installation-id').catch(() => undefined);
    throw error;
  }
}

export async function getInstallationId(): Promise<string> {
  const existing = await readSecureValue(INSTALLATION_ID_KEY, 'installation-id');
  if (!existing || !UUID_PATTERN.test(existing)) {
    throw new Error('The installation identity has not been initialized.');
  }
  return existing;
}

export async function setRefreshToken(namespace: string, token: string): Promise<void> {
  await trackNamespace(namespace);
  await writeSecureValue(keyFor(namespace, 'refresh'), 'refresh', token);
}

export async function setActiveNamespace(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await trackNamespace(namespace);
  await writeSecureValue(ACTIVE_NAMESPACE_KEY, 'active-namespace', namespace);
}

export async function getActiveNamespace(): Promise<string | null> {
  const namespace = await readSecureValue(ACTIVE_NAMESPACE_KEY, 'active-namespace');
  if (!namespace || !/^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(namespace)) return null;
  return namespace;
}

export async function getPendingLocalCleanups(): Promise<string[]> {
  return readPendingCleanups();
}

export async function markLocalCleanupPending(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await mutateNamespaceIndex(async () => {
    const pending = new Set(await readPendingCleanups());
    pending.add(namespace);
    await writePendingCleanups([...pending], false);
  });
}

export async function clearLocalCleanupPending(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await mutateNamespaceIndex(async () => {
    const pending = (await readPendingCleanups()).filter((value) => value !== namespace);
    // A stale replica is safe but would repeatedly retry cleanup, so report the
    // incomplete clear until both replicas acknowledge the new list.
    await writePendingCleanups(pending, true);
  });
}

export async function getPendingAuthenticationLocks(): Promise<string[]> {
  return authenticationLockMarker.get();
}

export async function markAuthenticationLockPending(namespace: string): Promise<void> {
  await authenticationLockMarker.mark(namespace);
}

export async function clearAuthenticationLockPending(namespace: string): Promise<void> {
  await authenticationLockMarker.clear(namespace);
}

export async function getRefreshToken(namespace: string): Promise<string | null> {
  return readSecureValue(keyFor(namespace, 'refresh'), 'refresh');
}

export async function setOfflineAuthorizationRecord(
  namespace: string,
  record: OfflineAuthorizationRecord,
): Promise<void> {
  if (!isOfflineAuthorizationRecord(record)) {
    throw new Error('Invalid offline authorization record.');
  }
  assertSecureValueAccessAvailable('offline-authorization');
  await trackNamespace(namespace);
  await writeSecureValue(
    keyFor(namespace, 'offline-authorization'),
    'offline-authorization',
    JSON.stringify(record),
  );
}
export async function compareAndSetOfflineAuthorizationRecord(
  namespace: string,
  expected: OfflineAuthorizationRecord,
  replacement: OfflineAuthorizationRecord,
): Promise<boolean> {
  if (!isOfflineAuthorizationRecord(expected) || !isOfflineAuthorizationRecord(replacement)) {
    throw new Error('Invalid offline authorization record.');
  }
  assertSecureValueAccessAvailable('offline-authorization');
  await trackNamespace(namespace);
  const storageKey = keyFor(namespace, 'offline-authorization');
  return compareAndSetSecureValue(storageKey, 'offline-authorization', (encoded) => {
    if (encoded.length > 8_192) return false;
    try {
      const parsed: unknown = JSON.parse(encoded);
      return isOfflineAuthorizationRecord(parsed)
        && parsed.formatVersion === expected.formatVersion
        && parsed.compactLease === expected.compactLease
        && parsed.highWaterServerTimeMs === expected.highWaterServerTimeMs
        && parsed.anchoredWallClockMs === expected.anchoredWallClockMs;
    } catch {
      return false;
    }
  }, JSON.stringify(replacement));
}

export async function getOfflineAuthorizationRecord(
  namespace: string,
): Promise<OfflineAuthorizationRecord | null> {
  const encoded = await readSecureValue(
    keyFor(namespace, 'offline-authorization'),
    'offline-authorization',
  );
  if (!encoded || encoded.length > 8_192) return null;
  try {
    const parsed: unknown = JSON.parse(encoded);
    return isOfflineAuthorizationRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function clearOfflineAuthorizationRecord(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await deleteSecureValue(keyFor(namespace, 'offline-authorization'), 'offline-authorization');
}

export async function getAppAttestKeyRecord(
  namespace: string,
): Promise<AppAttestKeyRecord | null> {
  assertNamespace(namespace);
  const encoded = await readSecureValue(
    keyFor(namespace, 'app-attest-key-id'),
    'app-attest-key-id',
  );
  if (!encoded || encoded.length > 1_024) return null;
  try {
    const record: unknown = JSON.parse(encoded);
    if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
    const value = record as Record<string, unknown>;
    if (
      Object.keys(value).length !== 3
      || value.formatVersion !== 1
      || typeof value.keyId !== 'string'
      || !/^[A-Za-z0-9_+/=-]{32,512}$/.test(value.keyId)
      || typeof value.registered !== 'boolean'
    ) {
      return null;
    }
    return {
      formatVersion: 1,
      keyId: value.keyId,
      registered: value.registered,
    };
  } catch {
    return null;
  }
}

export async function setAppAttestKeyRecord(
  namespace: string,
  record: AppAttestKeyRecord,
): Promise<void> {
  assertNamespace(namespace);
  if (
    record.formatVersion !== 1
    || !/^[A-Za-z0-9_+/=-]{32,512}$/.test(record.keyId)
    || typeof record.registered !== 'boolean'
  ) {
    throw new Error('Invalid App Attest key identifier.');
  }
  assertSecureValueAccessAvailable('app-attest-key-id');
  await trackNamespace(namespace);
  await writeSecureValue(
    keyFor(namespace, 'app-attest-key-id'),
    'app-attest-key-id',
    JSON.stringify(record),
  );
}

export async function clearAppAttestKeyRecord(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await deleteSecureValue(keyFor(namespace, 'app-attest-key-id'), 'app-attest-key-id');
}

export async function getRememberedTripId(namespace: string): Promise<string | null> {
  const value = await readSecureValue(keyFor(namespace, 'selected-trip'), 'selected-trip');
  return value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
    ? value
    : null;
}

export async function setRememberedTripId(namespace: string, tripId: string): Promise<void> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(tripId)) {
    throw new Error('Invalid trip identity.');
  }
  await trackNamespace(namespace);
  await writeSecureValue(keyFor(namespace, 'selected-trip'), 'selected-trip', tripId);
}

export async function getHandledNotificationResponse(namespace: string): Promise<string | null> {
  return readSecureValue(keyFor(namespace, 'notification-response'), 'notification-response');
}

export async function setHandledNotificationResponse(
  namespace: string,
  responseKey: string,
): Promise<void> {
  if (!responseKey || responseKey.length > 256) {
    throw new Error('Invalid notification response identity.');
  }
  await trackNamespace(namespace);
  await writeSecureValue(
    keyFor(namespace, 'notification-response'),
    'notification-response',
    responseKey,
  );
}

export async function getPushRegistrationMarker(
  namespace: string,
): Promise<PushRegistrationMarker | null> {
  assertNamespace(namespace);
  const encoded = await readSecureValue(keyFor(namespace, 'push-registration'), 'push-registration');
  if (!encoded) return null;
  try {
    const parsed: unknown = JSON.parse(encoded);
    return isPushRegistrationMarker(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function setPushRegistrationMarker(
  namespace: string,
  marker: PushRegistrationMarker,
): Promise<void> {
  assertNamespace(namespace);
  if (!isPushRegistrationMarker(marker)) {
    throw new Error('Invalid push registration marker.');
  }
  await trackNamespace(namespace);
  await writeSecureValue(
    keyFor(namespace, 'push-registration'),
    'push-registration',
    JSON.stringify(marker),
  );
}

export async function clearPushRegistrationMarker(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await deleteSecureValue(keyFor(namespace, 'push-registration'), 'push-registration');
}

export async function getDatabaseHealthMarker(
  namespace: string,
): Promise<DatabaseHealthMarker | null> {
  const encoded = await readSecureValue(keyFor(namespace, 'database-health'), 'database-health');
  if (!encoded) return null;
  try {
    const parsed: unknown = JSON.parse(encoded);
    return isDatabaseHealthMarker(parsed) ? parsed : null;
  } catch {
    // A malformed marker is never evidence that a database is healthy.
    return null;
  }
}

export async function setDatabaseHealthMarker(
  namespace: string,
  marker: DatabaseHealthMarker,
): Promise<void> {
  if (!isDatabaseHealthMarker(marker)) {
    throw new Error('Invalid database health marker.');
  }
  await trackNamespace(namespace);
  await writeSecureValue(
    keyFor(namespace, 'database-health'),
    'database-health',
    JSON.stringify(marker),
  );
}

export async function clearDatabaseHealthMarker(namespace: string): Promise<void> {
  await deleteSecureValue(keyFor(namespace, 'database-health'), 'database-health');
}

export function getOrCreateSecret(
  namespace: string,
  kind: Extract<SecretKind, 'database-key' | 'vault-key'>,
): Promise<string> {
  const storageKey = keyFor(namespace, kind);
  const existingOperation = secretCreationInFlight.get(storageKey);
  if (existingOperation) return existingOperation;

  const operation = (async () => {
    const existing = await readSecureValue(storageKey, kind);
    if (existing && /^[0-9a-f]{64}$/i.test(existing)) return existing;

    const bytes = await Crypto.getRandomBytesAsync(32);
    const created = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    await trackNamespace(namespace);
    await writeSecureValue(storageKey, kind, created);
    return created;
  })();
  secretCreationInFlight.set(storageKey, operation);
  return operation.finally(() => {
    if (secretCreationInFlight.get(storageKey) === operation) {
      secretCreationInFlight.delete(storageKey);
    }
  });
}

export async function clearNamespaceSecrets(namespace: string): Promise<void> {
  assertNamespace(namespace);
  let firstError: unknown;
  const capture = async (operation: () => Promise<unknown>): Promise<void> => {
    try {
      await operation();
    } catch (error) {
      firstError ??= error;
    }
  };

  // Each deletion is independent: one keychain failure must not leave the
  // refresh token, encryption keys, or active-account marker untouched.
  await Promise.all(
    ([
      'refresh',
      'database-key',
      'vault-key',
      'selected-trip',
      'notification-response',
      'push-registration',
      'database-health',
      'offline-authorization',
      'app-attest-key-id',
    ] as const)
      .map((kind) => capture(() => deleteSecureValue(keyFor(namespace, kind), kind))),
  );

  await capture(() => mutateNamespaceIndex(async () => {
    const remaining = (await readNamespaces()).filter((value) => value !== namespace);
    await writeSecureValue(NAMESPACE_INDEX_KEY, 'namespace-index', JSON.stringify(remaining));
  }));

  let activeNamespace: string | null = null;
  let activeNamespaceReadFailed = false;
  try {
    activeNamespace = await getActiveNamespace();
  } catch (error) {
    firstError ??= error;
    activeNamespaceReadFailed = true;
  }
  if (activeNamespaceReadFailed || activeNamespace === namespace) {
    await capture(() => deleteSecureValue(ACTIVE_NAMESPACE_KEY, 'active-namespace'));
  }

  if (firstError) throw firstError;
}

/**
 * Revokes local authentication while retaining encryption keys and namespace
 * ownership needed to retry a failed database/vault deletion after restart.
 */
export async function clearNamespaceAuthentication(namespace: string): Promise<void> {
  assertNamespace(namespace);
  let firstError: unknown;
  const capture = async (operation: () => Promise<unknown>): Promise<void> => {
    try {
      await operation();
    } catch (error) {
      firstError ??= error;
    }
  };

  await Promise.all(
    ([
      'refresh',
      'selected-trip',
      'notification-response',
      'push-registration',
      'offline-authorization',
    ] as const).map((kind) => (
       capture(() => deleteSecureValue(keyFor(namespace, kind), kind))
    )),
  );

  let activeNamespace: string | null = null;
  let activeNamespaceReadFailed = false;
  try {
    activeNamespace = await getActiveNamespace();
  } catch (error) {
    firstError ??= error;
    activeNamespaceReadFailed = true;
  }
  if (activeNamespaceReadFailed || activeNamespace === namespace) {
    await capture(() => deleteSecureValue(ACTIVE_NAMESPACE_KEY, 'active-namespace'));
  }
  if (firstError) throw firstError;
}

export { isUnlockedOnlySecureValueAccessAvailable };
