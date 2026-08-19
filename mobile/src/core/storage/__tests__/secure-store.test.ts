import * as Crypto from 'expo-crypto';
import { File, Paths } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';
import { AppState } from 'react-native';

import {
  clearLocalCleanupPending,
  clearNamespaceAuthentication,
  isTrustedInstallationBinding,
  clearNamespaceSecrets,
  getPendingLocalCleanups,
  getInstallationId,
  getOrCreateSecret,
  getOfflineAuthorizationRecord,
  getPushRegistrationMarker,
  getRefreshToken,
  markLocalCleanupPending,
  readInstallationBinding,
  setRefreshToken,
  setOfflineAuthorizationRecord,
  setPushRegistrationMarker,
  writeInstallationBinding,
} from '../secure-store';

jest.mock('expo-crypto', () => ({
  getRandomBytesAsync: jest.fn(),
  randomUUID: jest.fn(),
}));

jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const failures = { read: false, write: false, delete: false };
  const normalize = (parts: unknown[]) => parts.map(String).join('/');

  class MockFile {
    readonly uri: string;

    constructor(...parts: unknown[]) {
      this.uri = normalize(parts);
    }

    get exists() {
      return files.has(this.uri);
    }

    create() {
      if (failures.write) throw new Error('private file write unavailable');
      files.set(this.uri, '');
    }

    write(value: string) {
      if (failures.write) throw new Error('private file write unavailable');
      files.set(this.uri, value);
    }

    async text() {
      if (failures.read) throw new Error('private file read unavailable');
      return files.get(this.uri) ?? '';
    }

    delete() {
      if (failures.delete) throw new Error('private file delete unavailable');
      files.delete(this.uri);
    }
  }

  class MockDirectory {
    readonly exists = true;
    create() {}
  }

  return {
    Directory: MockDirectory,
    File: MockFile,
    Paths: { document: 'file:///document' },
    __mockPrivateFiles: files,
    __mockPrivateFileFailures: failures,
  };
});

type MockFileSystemControls = {
  __mockPrivateFiles: Map<string, string>;
  __mockPrivateFileFailures: { read: boolean; write: boolean; delete: boolean };
};

function fileSystemControls(): MockFileSystemControls {
  // Test-only controls are intentionally omitted from Expo's public types.
  return jest.requireMock('expo-file-system') as MockFileSystemControls;
}

function backupExclusionMock(): jest.Mock<Promise<void>, [string]> {
  return (jest.requireMock('react-native-blob-util') as {
    default: { ios: { excludeFromBackupKey: jest.Mock<Promise<void>, [string]> } };
  }).default.ios.excludeFromBackupKey;
}

const namespace = '11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222';

beforeEach(() => {
  (AppState as unknown as { currentState: string }).currentState = 'active';
  fileSystemControls().__mockPrivateFiles.clear();
  Object.assign(fileSystemControls().__mockPrivateFileFailures, {
    read: false,
    write: false,
    delete: false,
  });
  jest.mocked(SecureStore.getItemAsync).mockReset();
  jest.mocked(SecureStore.setItemAsync).mockReset();
  jest.mocked(SecureStore.deleteItemAsync).mockReset();
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => {
    if (key === 'gc.v1.active-namespace') return namespace;
    if (key === 'gc.v1.namespaces') return JSON.stringify([namespace]);
    return null;
  });
  jest.mocked(SecureStore.setItemAsync).mockResolvedValue(undefined);
  jest.mocked(SecureStore.deleteItemAsync).mockResolvedValue(undefined);
  jest.mocked(Crypto.getRandomBytesAsync).mockReset();
  jest.mocked(Crypto.getRandomBytesAsync).mockResolvedValue(new Uint8Array(32).fill(0xab));
  jest.mocked(Crypto.randomUUID).mockReset();
  jest.mocked(Crypto.randomUUID).mockReturnValue('33333333-3333-4333-8333-333333333333');
  backupExclusionMock().mockReset();
  backupExclusionMock().mockResolvedValue(undefined);
});

test('trusts only an exact valid keychain and app-private marker UUID pair', () => {
  expect(isTrustedInstallationBinding({
    markerInstallationId: '33333333-3333-4333-8333-333333333333',
    secureInstallationId: '33333333-3333-4333-8333-333333333333',
  })).toBe(true);
  expect(isTrustedInstallationBinding({
    markerInstallationId: 'group-companion-v1',
    secureInstallationId: 'group-companion-v1',
  })).toBe(false);
  expect(isTrustedInstallationBinding({
    markerInstallationId: null,
    secureInstallationId: '33333333-3333-4333-8333-333333333333',
  })).toBe(false);
});

test('propagates installation-binding read failures without treating them as a fresh install', async () => {
  jest.mocked(SecureStore.getItemAsync).mockRejectedValue(new Error('keychain read failed'));
  await expect(readInstallationBinding()).rejects.toThrow('keychain read failed');
});

test('removes a half-written marker and keychain identity when backup exclusion fails', async () => {
  backupExclusionMock().mockRejectedValue(new Error('backup exclusion failed'));

  await expect(writeInstallationBinding(
    '33333333-3333-4333-8333-333333333333',
  )).rejects.toThrow('backup exclusion failed');

  expect(new File(Paths.document, '.gc-install-marker-v1').exists).toBe(false);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith('gc.v1.installation-id');
});

test('one keychain deletion failure cannot skip other secrets or the active namespace marker', async () => {
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async (key) => {
    if (key.endsWith('.refresh')) throw new Error('keychain unavailable');
  });

  await expect(clearNamespaceSecrets(namespace)).rejects.toThrow('keychain unavailable');

  const deletedKeys = jest.mocked(SecureStore.deleteItemAsync).mock.calls.map(([key]) => key);
  expect(deletedKeys).toEqual(expect.arrayContaining([
    `gc.v1.${namespace}.refresh`,
    `gc.v1.${namespace}.database-key`,
    `gc.v1.${namespace}.vault-key`,
    `gc.v1.${namespace}.selected-trip`,
    `gc.v1.${namespace}.notification-response`,
    `gc.v1.${namespace}.push-registration`,
    `gc.v1.${namespace}.database-health`,
    `gc.v1.${namespace}.offline-authorization`,
    'gc.v1.active-namespace',
  ]));
  const unlockedOnlyKinds = new Set([
    'vault-key',
    'offline-authorization',
    'app-attest-key-id',
  ]);
  for (const kind of [
    'refresh',
    'database-key',
    'vault-key',
    'selected-trip',
    'notification-response',
    'push-registration',
    'database-health',
    'offline-authorization',
    'app-attest-key-id',
  ]) {
    const key = `gc.v1.${namespace}.${kind}`;
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(key);
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(
      key,
      expect.objectContaining({
        keychainService: unlockedOnlyKinds.has(kind)
          ? 'gc.v2.unlocked-only'
          : 'gc.v2.background-after-first-unlock',
      }),
    );
  }
});

test('concurrent first-use callers share one generated vault key', async () => {
  const storageKey = `gc.v1.${namespace}.vault-key`;
  let releaseRead!: () => void;
  const readGate = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  let secretReads = 0;
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => {
    if (key === storageKey) {
      secretReads += 1;
      await readGate;
      return null;
    }
    if (key === 'gc.v1.namespaces') return JSON.stringify([namespace]);
    return null;
  });

  const callers = Array.from({ length: 8 }, () => getOrCreateSecret(namespace, 'vault-key'));
  releaseRead();
  const values = await Promise.all(callers);

  expect(new Set(values)).toEqual(new Set(['ab'.repeat(32)]));
  // One policy-service read plus one legacy-service migration check, shared by
  // every concurrent caller through the creation coalescer.
  expect(secretReads).toBe(2);
  expect(Crypto.getRandomBytesAsync).toHaveBeenCalledTimes(1);
  expect(jest.mocked(SecureStore.setItemAsync).mock.calls.filter(([key]) => key === storageKey)).toHaveLength(1);
});

test('a failed secret creation does not poison later retries', async () => {
  jest.mocked(Crypto.getRandomBytesAsync)
    .mockRejectedValueOnce(new Error('secure random unavailable'))
    .mockResolvedValueOnce(new Uint8Array(32).fill(0xcd));

  await expect(getOrCreateSecret(namespace, 'database-key')).rejects.toThrow(
    'secure random unavailable',
  );
  await expect(getOrCreateSecret(namespace, 'database-key')).resolves.toBe('cd'.repeat(32));
  expect(Crypto.getRandomBytesAsync).toHaveBeenCalledTimes(2);
});

test('migrates a legacy vault key before use and removes the weaker duplicate', async () => {
  const storageKey = `gc.v1.${namespace}.vault-key`;
  const legacyValue = 'ef'.repeat(32);
  let hardenedValue: string | null = null;
  let legacyPresent = true;
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key, options) => {
    if (key === storageKey) {
      return options?.keychainService === 'gc.v2.unlocked-only'
        ? hardenedValue
        : (legacyPresent ? legacyValue : null);
    }
    if (key === 'gc.v1.namespaces') return JSON.stringify([namespace]);
    return null;
  });
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value, options) => {
    if (key === storageKey && options?.keychainService === 'gc.v2.unlocked-only') {
      hardenedValue = value;
    }
  });
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async (key, options) => {
    if (key === storageKey && options === undefined) legacyPresent = false;
  });

  await expect(getOrCreateSecret(namespace, 'vault-key')).resolves.toBe(legacyValue);

  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(storageKey, legacyValue, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    keychainService: 'gc.v2.unlocked-only',
    requireAuthentication: false,
  });
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(storageKey);
  expect(legacyPresent).toBe(false);
});

test('fails closed until an interrupted legacy migration removes the weaker copy', async () => {
  const storageKey = `gc.v1.${namespace}.vault-key`;
  const legacyValue = 'fe'.repeat(32);
  let hardenedValue: string | null = null;
  let legacyPresent = true;
  let rejectLegacyDelete = true;
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key, options) => {
    if (key === storageKey) {
      return options?.keychainService === 'gc.v2.unlocked-only'
        ? hardenedValue
        : (legacyPresent ? legacyValue : null);
    }
    return null;
  });
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value, options) => {
    if (key === storageKey && options?.keychainService === 'gc.v2.unlocked-only') {
      hardenedValue = value;
    }
  });
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async (key, options) => {
    if (key === storageKey && options === undefined) {
      if (rejectLegacyDelete) throw new Error('legacy delete unavailable');
      legacyPresent = false;
    }
  });

  await expect(getOrCreateSecret(namespace, 'vault-key')).rejects.toThrow(
    'legacy delete unavailable',
  );
  rejectLegacyDelete = false;
  await expect(getOrCreateSecret(namespace, 'vault-key')).resolves.toBe(legacyValue);
  expect(legacyPresent).toBe(false);
});

test('unlocked-only material rejects background access while database metadata remains available', async () => {
  (AppState as unknown as { currentState: string }).currentState = 'background';
  const record = {
    formatVersion: 1 as const,
    compactLease: `header.payload.${'s'.repeat(260)}`,
    highWaterServerTimeMs: 1_900_000_000_000,
    anchoredWallClockMs: 1_800_000_000_000,
  };

  await expect(getOrCreateSecret(namespace, 'vault-key')).rejects.toMatchObject({
    code: 'SECURE_VALUE_REQUIRES_UNLOCK',
  });
  await expect(setOfflineAuthorizationRecord(namespace, record)).rejects.toMatchObject({
    code: 'SECURE_VALUE_REQUIRES_UNLOCK',
  });
  await expect(getOrCreateSecret(namespace, 'database-key')).resolves.toBe('ab'.repeat(32));

  expect(SecureStore.getItemAsync).not.toHaveBeenCalledWith(
    `gc.v1.${namespace}.vault-key`,
    expect.anything(),
  );
  expect(SecureStore.setItemAsync).not.toHaveBeenCalledWith(
    `gc.v1.${namespace}.offline-authorization`,
    expect.anything(),
    expect.anything(),
  );
  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
    `gc.v1.${namespace}.database-key`,
    'ab'.repeat(32),
    expect.objectContaining({
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
      keychainService: 'gc.v2.background-after-first-unlock',
      requireAuthentication: false,
    }),
  );
});

test('returns only an installation identity created by the bootstrap guard', async () => {
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => {
    if (key === 'gc.v1.installation-id') {
      return '33333333-3333-4333-8333-333333333333';
    }
    return null;
  });

  await expect(getInstallationId()).resolves.toBe('33333333-3333-4333-8333-333333333333');
  expect(SecureStore.setItemAsync).not.toHaveBeenCalledWith(
    'gc.v1.installation-id',
    expect.anything(),
    expect.anything(),
  );
});

test('fails closed when bootstrap has not created a valid installation identity', async () => {
  jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
  await expect(getInstallationId()).rejects.toThrow(
    'The installation identity has not been initialized.',
  );
});

test('concurrent account writes cannot lose a namespace-index entry', async () => {
  const secondNamespace = '44444444-4444-4444-8444-444444444444.55555555-5555-4555-8555-555555555555';
  const values = new Map<string, string>();
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => values.get(key) ?? null);
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value) => {
    values.set(key, value);
  });

  await Promise.all([
    setRefreshToken(namespace, 'refresh-one'),
    setRefreshToken(secondNamespace, 'refresh-two'),
  ]);

  expect(new Set(JSON.parse(values.get('gc.v1.namespaces') ?? '[]'))).toEqual(
    new Set([namespace, secondNamespace]),
  );
});

test('serializes a policy migration read with a later write to the same key', async () => {
  const storageKey = `gc.v1.${namespace}.refresh`;
  let currentValue: string | null = 'refresh-before';
  let releaseRead!: () => void;
  let markReadStarted!: () => void;
  const readGate = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  const readStarted = new Promise<void>((resolve) => {
    markReadStarted = resolve;
  });
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key, options) => {
    if (key === storageKey && options?.keychainService) {
      markReadStarted();
      await readGate;
      return currentValue;
    }
    if (key === storageKey) return null;
    if (key === 'gc.v1.namespaces') return JSON.stringify([namespace]);
    return null;
  });
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value, options) => {
    if (key === storageKey && options?.keychainService) currentValue = value;
  });

  const read = getRefreshToken(namespace);
  await readStarted;
  const write = setRefreshToken(namespace, 'refresh-after');
  await Promise.resolve();
  await Promise.resolve();
  expect(SecureStore.setItemAsync).not.toHaveBeenCalledWith(
    storageKey,
    'refresh-after',
    expect.anything(),
  );

  releaseRead();
  await expect(read).resolves.toBe('refresh-before');
  await expect(write).resolves.toBeUndefined();
  expect(currentValue).toBe('refresh-after');
});

test('push registration markers are strict, account-scoped, and never contain the token', async () => {
  const marker = {
    formatVersion: 1 as const,
    sessionId: '33333333-3333-4333-8333-333333333333',
    provider: 'expo' as const,
    tokenDigest: 'a'.repeat(64),
    installationId: '44444444-4444-4444-8444-444444444444',
    registeredAtMs: 1_700_000_000_000,
  };
  await setPushRegistrationMarker(namespace, marker);
  const stored = jest.mocked(SecureStore.setItemAsync).mock.calls.find(
    ([key]) => key === `gc.v1.${namespace}.push-registration`,
  );
  expect(stored?.[1]).toBe(JSON.stringify(marker));
  expect(stored?.[1]).not.toContain('ExponentPushToken');

  jest.mocked(SecureStore.getItemAsync).mockResolvedValueOnce(JSON.stringify(marker));
  await expect(getPushRegistrationMarker(namespace)).resolves.toEqual(marker);
  jest.mocked(SecureStore.getItemAsync).mockResolvedValueOnce(JSON.stringify({
    ...marker,
    tokenDigest: 'raw-device-token',
  }));
  await expect(getPushRegistrationMarker(namespace)).resolves.toBeNull();
});

test('offline authorization records are strict, account-scoped, and cleared with authentication', async () => {
  const record = {
    formatVersion: 1 as const,
    compactLease: `header.payload.${'s'.repeat(260)}`,
    highWaterServerTimeMs: 1_900_000_000_000,
    anchoredWallClockMs: 1_800_000_000_000,
  };
  await setOfflineAuthorizationRecord(namespace, record);
  const stored = jest.mocked(SecureStore.setItemAsync).mock.calls.find(
    ([key]) => key === `gc.v1.${namespace}.offline-authorization`,
  );
  expect(stored?.[1]).toBe(JSON.stringify(record));

  jest.mocked(SecureStore.getItemAsync).mockResolvedValueOnce(JSON.stringify(record));
  await expect(getOfflineAuthorizationRecord(namespace)).resolves.toEqual(record);
  jest.mocked(SecureStore.getItemAsync).mockResolvedValueOnce(JSON.stringify({
    ...record,
    unreviewedField: true,
  }));
  await expect(getOfflineAuthorizationRecord(namespace)).resolves.toBeNull();

  await clearNamespaceAuthentication(namespace);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(
    `gc.v1.${namespace}.offline-authorization`,
  );
});

test('a cleanup tombstone survives a correlated SecureStore outage via app-private storage', async () => {
  jest.mocked(SecureStore.setItemAsync).mockRejectedValue(new Error('keychain write unavailable'));

  await expect(markLocalCleanupPending(namespace)).resolves.toBeUndefined();
  expect(await new File(Paths.document, '.gc-pending-cleanup-v1.json').text()).toBe(
    JSON.stringify([namespace]),
  );

  jest.mocked(SecureStore.getItemAsync).mockRejectedValue(new Error('keychain read unavailable'));
  await expect(getPendingLocalCleanups()).resolves.toEqual([namespace]);
});

test('a malformed cleanup replica fails closed instead of being treated as empty', async () => {
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => {
    if (key === 'gc.v1.pending-cleanup') return '{not-json';
    return null;
  });

  await expect(getPendingLocalCleanups()).rejects.toThrow('Secure cleanup state is unavailable.');
});

test('cleanup acknowledgement requires both durable replicas to clear', async () => {
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => {
    if (key === 'gc.v1.pending-cleanup') return JSON.stringify([namespace]);
    return null;
  });
  const marker = new File(Paths.document, '.gc-pending-cleanup-v1.json');
  marker.create({ overwrite: true, intermediates: true });
  marker.write(JSON.stringify([namespace]));
  fileSystemControls().__mockPrivateFileFailures.write = true;

  await expect(clearLocalCleanupPending(namespace)).rejects.toThrow(
    'private file write unavailable',
  );
});
