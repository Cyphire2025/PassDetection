import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';

import { excludeAppPrivateUriFromBackup } from './ios-backup';

const KEY_PREFIX = 'gc.v1';
const NAMESPACE_INDEX_KEY = `${KEY_PREFIX}.namespaces`;
const INSTALLATION_ID_KEY = `${KEY_PREFIX}.installation-id`;
const ACTIVE_NAMESPACE_KEY = `${KEY_PREFIX}.active-namespace`;
const PENDING_CLEANUP_KEY = `${KEY_PREFIX}.pending-cleanup`;
const INSTALL_MARKER = new File(Paths.document, '.gc-install-marker-v1');
const PENDING_CLEANUP_FILE = new File(Paths.document, '.gc-pending-cleanup-v1.json');
const secretCreationInFlight = new Map<string, Promise<string>>();
let namespaceIndexMutationTail: Promise<void> = Promise.resolve();

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type SecretKind =
  | 'refresh'
  | 'database-key'
  | 'vault-key'
  | 'selected-trip'
  | 'notification-response'
  | 'database-health';

export type DatabaseHealthMarker = {
  formatVersion: 1;
  state: 'clean' | 'dirty';
  schemaVersion: number;
  lastIntegrityCheckAtMs: number;
};

const DATABASE_HEALTH_MARKER_FORMAT_VERSION = 1;

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

function assertNamespace(namespace: string): void {
  if (!/^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(namespace)) {
    throw new Error('Invalid account namespace.');
  }
}

function keyFor(namespace: string, kind: SecretKind): string {
  assertNamespace(namespace);
  return `${KEY_PREFIX}.${namespace}.${kind}`;
}

async function readNamespaces(): Promise<string[]> {
  const encoded = await SecureStore.getItemAsync(NAMESPACE_INDEX_KEY);
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
    secureStoreEncoded = await SecureStore.getItemAsync(PENDING_CLEANUP_KEY);
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
    await SecureStore.setItemAsync(PENDING_CLEANUP_KEY, JSON.stringify(pending), {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    });
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
    await SecureStore.setItemAsync(NAMESPACE_INDEX_KEY, JSON.stringify([...namespaces]), {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    });
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
  const secureInstallationId = await SecureStore.getItemAsync(INSTALLATION_ID_KEY);
  const markerInstallationId = INSTALL_MARKER.exists ? await INSTALL_MARKER.text() : null;
  return { markerInstallationId, secureInstallationId };
}

export async function protectInstallationMarkersFromBackup(): Promise<void> {
  if (INSTALL_MARKER.exists) await excludeAppPrivateUriFromBackup(INSTALL_MARKER.uri);
  if (PENDING_CLEANUP_FILE.exists) {
    await excludeAppPrivateUriFromBackup(PENDING_CLEANUP_FILE.uri);
  }
}

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
    'database-health',
  ] as const).map((kind) => capture(() => SecureStore.deleteItemAsync(keyFor(namespace, kind))))));
  await Promise.all([
    NAMESPACE_INDEX_KEY,
    INSTALLATION_ID_KEY,
    ACTIVE_NAMESPACE_KEY,
    PENDING_CLEANUP_KEY,
  ].map((key) => capture(() => SecureStore.deleteItemAsync(key))));
  await capture(() => {
    if (PENDING_CLEANUP_FILE.exists) PENDING_CLEANUP_FILE.delete();
  });
  await capture(() => {
    if (INSTALL_MARKER.exists) INSTALL_MARKER.delete();
  });
  if (firstError) throw firstError;
}

export async function writeInstallationBinding(installationId: string): Promise<void> {
  if (!UUID_PATTERN.test(installationId)) throw new Error('Invalid installation identity.');
  await SecureStore.setItemAsync(INSTALLATION_ID_KEY, installationId, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
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
    await SecureStore.deleteItemAsync(INSTALLATION_ID_KEY).catch(() => undefined);
    throw error;
  }
}

export async function getInstallationId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(INSTALLATION_ID_KEY);
  if (!existing || !UUID_PATTERN.test(existing)) {
    throw new Error('The installation identity has not been initialized.');
  }
  return existing;
}

export async function setRefreshToken(namespace: string, token: string): Promise<void> {
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(keyFor(namespace, 'refresh'), token, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function setActiveNamespace(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(ACTIVE_NAMESPACE_KEY, namespace, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function getActiveNamespace(): Promise<string | null> {
  const namespace = await SecureStore.getItemAsync(ACTIVE_NAMESPACE_KEY);
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

export async function getRefreshToken(namespace: string): Promise<string | null> {
  return SecureStore.getItemAsync(keyFor(namespace, 'refresh'));
}

export async function getRememberedTripId(namespace: string): Promise<string | null> {
  const value = await SecureStore.getItemAsync(keyFor(namespace, 'selected-trip'));
  return value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
    ? value
    : null;
}

export async function setRememberedTripId(namespace: string, tripId: string): Promise<void> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(tripId)) {
    throw new Error('Invalid trip identity.');
  }
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(keyFor(namespace, 'selected-trip'), tripId, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function getHandledNotificationResponse(namespace: string): Promise<string | null> {
  return SecureStore.getItemAsync(keyFor(namespace, 'notification-response'));
}

export async function setHandledNotificationResponse(
  namespace: string,
  responseKey: string,
): Promise<void> {
  if (!responseKey || responseKey.length > 256) {
    throw new Error('Invalid notification response identity.');
  }
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(keyFor(namespace, 'notification-response'), responseKey, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function getDatabaseHealthMarker(
  namespace: string,
): Promise<DatabaseHealthMarker | null> {
  const encoded = await SecureStore.getItemAsync(keyFor(namespace, 'database-health'));
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
  await SecureStore.setItemAsync(
    keyFor(namespace, 'database-health'),
    JSON.stringify(marker),
    { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY },
  );
}

export async function clearDatabaseHealthMarker(namespace: string): Promise<void> {
  await SecureStore.deleteItemAsync(keyFor(namespace, 'database-health'));
}

export function getOrCreateSecret(
  namespace: string,
  kind: Extract<SecretKind, 'database-key' | 'vault-key'>,
): Promise<string> {
  const storageKey = keyFor(namespace, kind);
  const existingOperation = secretCreationInFlight.get(storageKey);
  if (existingOperation) return existingOperation;

  const operation = (async () => {
    const existing = await SecureStore.getItemAsync(storageKey);
    if (existing && /^[0-9a-f]{64}$/i.test(existing)) return existing;

    const bytes = await Crypto.getRandomBytesAsync(32);
    const created = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    await trackNamespace(namespace);
    await SecureStore.setItemAsync(storageKey, created, {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    });
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
      'database-health',
    ] as const)
      .map((kind) => capture(() => SecureStore.deleteItemAsync(keyFor(namespace, kind)))),
  );

  await capture(() => mutateNamespaceIndex(async () => {
    const remaining = (await readNamespaces()).filter((value) => value !== namespace);
    await SecureStore.setItemAsync(NAMESPACE_INDEX_KEY, JSON.stringify(remaining), {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    });
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
    await capture(() => SecureStore.deleteItemAsync(ACTIVE_NAMESPACE_KEY));
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
    (['refresh', 'selected-trip', 'notification-response'] as const).map((kind) => (
      capture(() => SecureStore.deleteItemAsync(keyFor(namespace, kind)))
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
    await capture(() => SecureStore.deleteItemAsync(ACTIVE_NAMESPACE_KEY));
  }
  if (firstError) throw firstError;
}
