const mockDeleteAllManagedAccountDatabases = jest.fn<Promise<void>, []>();
const mockProtectManagedAccountDatabasesFromBackup = jest.fn<Promise<void>, []>();
const mockClearSecureStateForInstallationReset = jest.fn<Promise<void>, []>();
const mockProtectInstallationMarkersFromBackup = jest.fn<Promise<void>, []>();
const mockReadInstallationBinding = jest.fn<Promise<{
  markerInstallationId: string | null;
  secureInstallationId: string | null;
}>, []>();
const mockWriteInstallationBinding = jest.fn<Promise<void>, [string]>();
const mockDeleteAllManagedVaultStorage = jest.fn<Promise<void>, []>();
const mockProtectManagedVaultStorageFromBackup = jest.fn<Promise<void>, []>();
const mockRandomUUID = jest.fn<string, []>();

jest.mock('expo-crypto', () => ({
  randomUUID: () => mockRandomUUID(),
}));

jest.mock('../database', () => ({
  deleteAllManagedAccountDatabases: () => mockDeleteAllManagedAccountDatabases(),
  protectManagedAccountDatabasesFromBackup: () => (
    mockProtectManagedAccountDatabasesFromBackup()
  ),
}));

jest.mock('../secure-store', () => ({
  clearSecureStateForInstallationReset: () => mockClearSecureStateForInstallationReset(),
  isTrustedInstallationBinding: (binding: {
    markerInstallationId: string | null;
    secureInstallationId: string | null;
  }) => (
    binding.secureInstallationId === '33333333-3333-4333-8333-333333333333'
    && binding.markerInstallationId === binding.secureInstallationId
  ),
  protectInstallationMarkersFromBackup: () => mockProtectInstallationMarkersFromBackup(),
  readInstallationBinding: () => mockReadInstallationBinding(),
  writeInstallationBinding: (installationId: string) => (
    mockWriteInstallationBinding(installationId)
  ),
}));

jest.mock('../vault', () => ({
  deleteAllManagedVaultStorage: () => mockDeleteAllManagedVaultStorage(),
  protectManagedVaultStorageFromBackup: () => mockProtectManagedVaultStorageFromBackup(),
}));

// eslint-disable-next-line import/first -- Native/storage mocks must precede the bootstrap singleton.
import { initializeFreshInstallGuard } from '../installation-guard';

const validInstallationId = '33333333-3333-4333-8333-333333333333';

beforeEach(() => {
  jest.clearAllMocks();
  mockReadInstallationBinding.mockResolvedValue({
    markerInstallationId: validInstallationId,
    secureInstallationId: validInstallationId,
  });
  mockRandomUUID.mockReturnValue('44444444-4444-4444-8444-444444444444');
  mockDeleteAllManagedAccountDatabases.mockResolvedValue(undefined);
  mockProtectManagedAccountDatabasesFromBackup.mockResolvedValue(undefined);
  mockClearSecureStateForInstallationReset.mockResolvedValue(undefined);
  mockProtectInstallationMarkersFromBackup.mockResolvedValue(undefined);
  mockWriteInstallationBinding.mockResolvedValue(undefined);
  mockDeleteAllManagedVaultStorage.mockResolvedValue(undefined);
  mockProtectManagedVaultStorageFromBackup.mockResolvedValue(undefined);
});

test('accepts only an equal device-bound UUID and protects existing managed artifacts', async () => {
  await expect(initializeFreshInstallGuard()).resolves.toBeUndefined();

  expect(mockProtectInstallationMarkersFromBackup).toHaveBeenCalledTimes(1);
  expect(mockProtectManagedAccountDatabasesFromBackup).toHaveBeenCalledTimes(1);
  expect(mockProtectManagedVaultStorageFromBackup).toHaveBeenCalledTimes(1);
  expect(mockDeleteAllManagedAccountDatabases).not.toHaveBeenCalled();
  expect(mockClearSecureStateForInstallationReset).not.toHaveBeenCalled();
  expect(mockWriteInstallationBinding).not.toHaveBeenCalled();
});

test.each([
  ['missing marker', { markerInstallationId: null, secureInstallationId: validInstallationId }],
  ['missing keychain identity', { markerInstallationId: validInstallationId, secureInstallationId: null }],
  ['both identities missing', { markerInstallationId: null, secureInstallationId: null }],
  ['mismatched identities', {
    markerInstallationId: '55555555-5555-4555-8555-555555555555',
    secureInstallationId: validInstallationId,
  }],
  ['malformed identity', {
    markerInstallationId: 'group-companion-v1',
    secureInstallationId: 'group-companion-v1',
  }],
] as const)('purges untrusted state for %s before writing a new binding', async (_label, binding) => {
  mockReadInstallationBinding.mockResolvedValue(binding);

  await expect(initializeFreshInstallGuard()).resolves.toBeUndefined();

  expect(mockDeleteAllManagedAccountDatabases).toHaveBeenCalledTimes(1);
  expect(mockDeleteAllManagedVaultStorage).toHaveBeenCalledTimes(1);
  expect(mockClearSecureStateForInstallationReset).toHaveBeenCalledTimes(1);
  expect(mockWriteInstallationBinding).toHaveBeenCalledWith(
    '44444444-4444-4444-8444-444444444444',
  );
  expect(mockDeleteAllManagedAccountDatabases.mock.invocationCallOrder[0]!).toBeLessThan(
    mockDeleteAllManagedVaultStorage.mock.invocationCallOrder[0]!,
  );
  expect(mockDeleteAllManagedVaultStorage.mock.invocationCallOrder[0]!).toBeLessThan(
    mockClearSecureStateForInstallationReset.mock.invocationCallOrder[0]!,
  );
  expect(mockClearSecureStateForInstallationReset.mock.invocationCallOrder[0]!).toBeLessThan(
    mockWriteInstallationBinding.mock.invocationCallOrder[0]!,
  );
});

test('a binding read failure performs no destructive action', async () => {
  mockReadInstallationBinding.mockRejectedValue(new Error('keychain unavailable'));

  await expect(initializeFreshInstallGuard()).rejects.toThrow('keychain unavailable');
  expect(mockDeleteAllManagedAccountDatabases).not.toHaveBeenCalled();
  expect(mockDeleteAllManagedVaultStorage).not.toHaveBeenCalled();
  expect(mockClearSecureStateForInstallationReset).not.toHaveBeenCalled();
  expect(mockWriteInstallationBinding).not.toHaveBeenCalled();
});

test('a managed-artifact purge failure retains keys and never writes a trusted marker', async () => {
  mockReadInstallationBinding.mockResolvedValue({
    markerInstallationId: null,
    secureInstallationId: validInstallationId,
  });
  mockDeleteAllManagedVaultStorage.mockRejectedValue(new Error('vault delete failed'));

  await expect(initializeFreshInstallGuard()).rejects.toThrow('vault delete failed');
  expect(mockClearSecureStateForInstallationReset).not.toHaveBeenCalled();
  expect(mockWriteInstallationBinding).not.toHaveBeenCalled();
});

test('a new-binding write failure remains untrusted and can be retried', async () => {
  mockReadInstallationBinding.mockResolvedValue({
    markerInstallationId: null,
    secureInstallationId: null,
  });
  mockWriteInstallationBinding.mockRejectedValueOnce(new Error('marker write failed'));

  await expect(initializeFreshInstallGuard()).rejects.toThrow('marker write failed');
  expect(mockDeleteAllManagedAccountDatabases).toHaveBeenCalledTimes(1);
  expect(mockDeleteAllManagedVaultStorage).toHaveBeenCalledTimes(1);
  expect(mockClearSecureStateForInstallationReset).toHaveBeenCalledTimes(1);
  await expect(initializeFreshInstallGuard()).resolves.toBeUndefined();
  expect(mockWriteInstallationBinding).toHaveBeenCalledTimes(2);
});

test('concurrent bootstrap callers share one installation-boundary operation', async () => {
  let releaseRead!: () => void;
  const readGate = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  mockReadInstallationBinding.mockImplementation(async () => {
    await readGate;
    return {
      markerInstallationId: validInstallationId,
      secureInstallationId: validInstallationId,
    };
  });

  const first = initializeFreshInstallGuard();
  const second = initializeFreshInstallGuard();
  releaseRead();
  await Promise.all([first, second]);

  expect(mockReadInstallationBinding).toHaveBeenCalledTimes(1);
});
