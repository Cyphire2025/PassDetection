import * as Crypto from 'expo-crypto';
import { File, Paths } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';

import {
  clearLocalCleanupPending,
  isTrustedInstallationBinding,
  clearNamespaceSecrets,
  getPendingLocalCleanups,
  getInstallationId,
  getOrCreateSecret,
  markLocalCleanupPending,
  readInstallationBinding,
  setRefreshToken,
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
    `gc.v1.${namespace}.database-health`,
    'gc.v1.active-namespace',
  ]));
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
  expect(secretReads).toBe(1);
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
