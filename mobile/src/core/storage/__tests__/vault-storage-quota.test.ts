const mockDirectorySizes = new Map<string, number>();

jest.mock('expo-file-system', () => ({
  Directory: class MockDirectory {
    readonly uri: string;
    readonly exists = true;

    constructor(...parts: ({ uri: string } | string)[]) {
      this.uri = parts
        .map((part) => typeof part === 'string' ? part : part.uri)
        .join('/');
    }

    get size(): number {
      return mockDirectorySizes.get(this.uri) ?? 0;
    }
  },
  File: class MockFile {},
  Paths: { availableDiskSpace: 10 * 1024 * 1024 * 1024 },
}));

// The native module mock must be registered before these imports are evaluated by Jest.
// eslint-disable-next-line import/first
import { Directory } from 'expo-file-system';

// eslint-disable-next-line import/first
import {
  inspectVaultStorageQuotaWithRuntime,
  reserveVaultStorageQuotaWithRuntime,
  type VaultQuotaEvictionCandidate,
  type VaultStorageQuotaRuntime,
} from '../vault-storage-quota';

const ACCOUNT = 'agency.account-a';
const APP_ROOT_URI = 'file:///managed-vault';
const ACCOUNT_ROOT_URI = `${APP_ROOT_URI}/account-hash`;
const policy = {
  maximumAccountBytes: 100,
  maximumAppBytes: 200,
  recoveryTargetRatio: 0.9,
} as const;

function runtime(activeEncryptedUris: readonly string[] = []): VaultStorageQuotaRuntime {
  const appRoot = new Directory(APP_ROOT_URI);
  return {
    activeEncryptedUris: () => activeEncryptedUris,
    managedVaultRoot: async () => appRoot,
    namespaceHash: async () => 'account-hash',
  };
}

beforeEach(() => {
  mockDirectorySizes.clear();
});

test('reports measured account and whole-app pressure through the extracted runtime boundary', async () => {
  mockDirectorySizes.set(APP_ROOT_URI, 150);
  mockDirectorySizes.set(ACCOUNT_ROOT_URI, 80);

  await expect(inspectVaultStorageQuotaWithRuntime(runtime(), ACCOUNT, policy)).resolves.toEqual({
    status: 'healthy',
    accountUsageBytes: 80,
    appUsageBytes: 150,
    accountRemainingBytes: 20,
    appRemainingBytes: 50,
    policy,
  });
});

test('never offers an active ciphertext lease to the quota reclaimer', async () => {
  const encryptedUri = `${ACCOUNT_ROOT_URI}/document.gcv`;
  mockDirectorySizes.set(APP_ROOT_URI, 150);
  mockDirectorySizes.set(ACCOUNT_ROOT_URI, 90);
  const candidate: VaultQuotaEvictionCandidate = {
    encryptedUri,
    namespace: ACCOUNT,
    tripId: '11111111-1111-4111-8111-111111111111',
    documentId: '22222222-2222-4222-8222-222222222222',
    version: 1,
    checksumSha256: 'a'.repeat(64),
    encryptedSizeBytes: 20,
    retentionClass: 'evictable',
    downloadedAtMs: 1,
  };
  const evict = jest.fn(async () => undefined);

  await expect(reserveVaultStorageQuotaWithRuntime(
    runtime([encryptedUri]),
    ACCOUNT,
    { exists: false, size: 0 } as never,
    20,
    1,
    { listCandidates: async () => [candidate], evict },
    policy,
  )).rejects.toThrow('The encrypted offline document storage limit has been reached');
  expect(evict).not.toHaveBeenCalled();
});
