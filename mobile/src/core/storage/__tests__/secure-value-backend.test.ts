import * as SecureStore from 'expo-secure-store';
import { AppState, NativeModules, Platform } from 'react-native';

import {
  deleteSecureValueFromBackend,
  readSecureValueFromBackend,
  writeSecureValueToBackend,
} from '../secure-value-backend';
import { compareAndSetSecureValue } from '../secure-value-operation';

const key = 'gc.v1.11111111-1111-4111-8111-111111111111.vault-key';

function createNativeStore() {
  return {
    getItem: jest.fn<Promise<string | null>, [string]>(async () => null),
    setItem: jest.fn<Promise<void>, [string, string]>(async () => undefined),
    deleteItem: jest.fn<Promise<void>, [string]>(async () => undefined),
  };
}

let originalPlatform: string;
let originalNativeStore: unknown;

beforeAll(() => {
  originalPlatform = Platform.OS;
  originalNativeStore = NativeModules.GCUnlockedDeviceStore;
});

beforeEach(() => {
  (Platform as unknown as { OS: string }).OS = 'android';
  (AppState as unknown as { currentState: string }).currentState = 'active';
  NativeModules.GCUnlockedDeviceStore = createNativeStore();
  jest.mocked(SecureStore.getItemAsync).mockReset().mockResolvedValue(null);
  jest.mocked(SecureStore.setItemAsync).mockReset().mockResolvedValue(undefined);
  jest.mocked(SecureStore.deleteItemAsync).mockReset().mockResolvedValue(undefined);
});

afterAll(() => {
  (Platform as unknown as { OS: string }).OS = originalPlatform;
  NativeModules.GCUnlockedDeviceStore = originalNativeStore;
});

function nativeStore() {
  return NativeModules.GCUnlockedDeviceStore as ReturnType<typeof createNativeStore>;
}

test('requires the native lock check before inspecting any migratable Expo value', async () => {
  nativeStore().getItem.mockRejectedValue(Object.assign(new Error('locked'), {
    code: 'SECURE_VALUE_REQUIRES_UNLOCK',
  }));

  await expect(readSecureValueFromBackend(key, 'vault-key')).rejects.toMatchObject({
    code: 'SECURE_VALUE_REQUIRES_UNLOCK',
  });
  expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
  expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
});

test('migrates an Expo value into native storage before deleting both Expo copies', async () => {
  jest.mocked(SecureStore.getItemAsync)
    .mockResolvedValueOnce('policy-copy')
    .mockResolvedValueOnce('legacy-copy');

  await expect(readSecureValueFromBackend(key, 'vault-key')).resolves.toBe('policy-copy');

  expect(nativeStore().setItem).toHaveBeenCalledWith(key, 'policy-copy');
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2);
  expect(SecureStore.deleteItemAsync).toHaveBeenNthCalledWith(
    1,
    key,
    expect.objectContaining({ keychainService: 'gc.v2.unlocked-only' }),
  );
  expect(SecureStore.deleteItemAsync).toHaveBeenNthCalledWith(2, key);
  expect(nativeStore().setItem.mock.invocationCallOrder[0]!).toBeLessThan(
    jest.mocked(SecureStore.deleteItemAsync).mock.invocationCallOrder[0]!,
  );
});

test('does not expose a native value until stale Expo duplicates are removed', async () => {
  nativeStore().getItem.mockResolvedValue('native-copy');
  jest.mocked(SecureStore.deleteItemAsync)
    .mockRejectedValueOnce(new Error('policy cleanup failed'))
    .mockResolvedValueOnce(undefined);

  await expect(readSecureValueFromBackend(key, 'vault-key')).rejects.toThrow(
    'policy cleanup failed',
  );
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2);
});

test('writes native unlocked-only data first and retires all Expo copies', async () => {
  await writeSecureValueToBackend(key, 'vault-key', 'protected-value');

  expect(nativeStore().setItem).toHaveBeenCalledWith(key, 'protected-value');
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2);
  expect(nativeStore().setItem.mock.invocationCallOrder[0]!).toBeLessThan(
    jest.mocked(SecureStore.deleteItemAsync).mock.invocationCallOrder[0]!,
  );
});

test('background-safe values retain the Expo SecureStore path on Android', async () => {
  jest.mocked(SecureStore.getItemAsync)
    .mockResolvedValueOnce('refresh-current')
    .mockResolvedValueOnce(null);

  await expect(readSecureValueFromBackend(key, 'refresh')).resolves.toBe('refresh-current');
  await writeSecureValueToBackend(key, 'refresh', 'refresh-next');

  expect(nativeStore().getItem).not.toHaveBeenCalled();
  expect(nativeStore().setItem).not.toHaveBeenCalled();
  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
    key,
    'refresh-next',
    expect.objectContaining({ keychainService: 'gc.v2.background-after-first-unlock' }),
  );
});

test('iOS retains the Keychain migration and accessibility path', async () => {
  (Platform as unknown as { OS: string }).OS = 'ios';
  jest.mocked(SecureStore.getItemAsync)
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce('legacy-value');

  await expect(readSecureValueFromBackend(key, 'vault-key')).resolves.toBe('legacy-value');

  expect(nativeStore().getItem).not.toHaveBeenCalled();
  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
    key,
    'legacy-value',
    expect.objectContaining({ keychainService: 'gc.v2.unlocked-only' }),
  );
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(key);
});

test('deletion remains lock-safe and attempts native, policy, and legacy copies', async () => {
  (AppState as unknown as { currentState: string }).currentState = 'background';
  nativeStore().deleteItem.mockRejectedValue(new Error('native cleanup failed'));
  jest.mocked(SecureStore.deleteItemAsync)
    .mockRejectedValueOnce(new Error('policy cleanup failed'))
    .mockResolvedValueOnce(undefined);

  await expect(deleteSecureValueFromBackend(key, 'vault-key')).rejects.toThrow(
    'native cleanup failed',
  );
  expect(nativeStore().deleteItem).toHaveBeenCalledWith(key);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2);
});

test('compare-and-set uses the same native backend and never recreates an Expo copy', async () => {
  nativeStore().getItem.mockResolvedValue('before');

  await expect(compareAndSetSecureValue(
    key,
    'vault-key',
    (value) => value === 'before',
    'after',
  )).resolves.toBe(true);

  expect(nativeStore().setItem).toHaveBeenCalledWith(key, 'after');
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(4);
});

test('fails closed when an Android build is missing the registered native module', async () => {
  delete NativeModules.GCUnlockedDeviceStore;

  await expect(readSecureValueFromBackend(key, 'vault-key')).rejects.toMatchObject({
    code: 'SECURE_VALUE_NATIVE_FAILURE',
  });
  expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
});
