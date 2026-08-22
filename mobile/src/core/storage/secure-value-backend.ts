import * as SecureStore from 'expo-secure-store';
import { NativeModules, Platform } from 'react-native';

import {
  assertSecureValueAccessAvailable,
  secureValuePolicy,
  type SecureValueKind,
} from './secure-store-policy';

type AndroidUnlockedDeviceStore = Readonly<{
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  deleteItem(key: string): Promise<void>;
}>;

export class SecureValueNativeStoreUnavailableError extends Error {
  readonly code = 'SECURE_VALUE_NATIVE_FAILURE';

  constructor() {
    super(
      'Android unlocked-device storage is unavailable. Rebuild the native application.',
    );
    this.name = 'SecureValueNativeStoreUnavailableError';
  }
}

function androidUnlockedDeviceStore(): AndroidUnlockedDeviceStore {
  const candidate = NativeModules.GCUnlockedDeviceStore as Partial<AndroidUnlockedDeviceStore> | undefined;
  if (
    !candidate
    || typeof candidate.getItem !== 'function'
    || typeof candidate.setItem !== 'function'
    || typeof candidate.deleteItem !== 'function'
  ) {
    throw new SecureValueNativeStoreUnavailableError();
  }
  return candidate as AndroidUnlockedDeviceStore;
}

function usesAndroidUnlockedDeviceStore(kind: SecureValueKind): boolean {
  return Platform.OS === 'android' && secureValuePolicy(kind).tier === 'unlocked-only';
}

async function deleteExpoCopies(key: string, kind: SecureValueKind): Promise<void> {
  let firstError: unknown;
  const capture = async (operation: () => Promise<void>): Promise<void> => {
    try {
      await operation();
    } catch (error) {
      firstError ??= error;
    }
  };
  await capture(() => SecureStore.deleteItemAsync(key, secureValuePolicy(kind).options));
  await capture(() => SecureStore.deleteItemAsync(key));
  if (firstError) throw firstError;
}
export async function readSecureValueFromBackend(
  key: string,
  kind: SecureValueKind,
): Promise<string | null> {
  assertSecureValueAccessAvailable(kind);
  const { options } = secureValuePolicy(kind);

  if (usesAndroidUnlockedDeviceStore(kind)) {
    const nativeStore = androidUnlockedDeviceStore();
    // The native read is deliberately first: its lock-state/Keystore check must
    // succeed before JavaScript is allowed to inspect a migratable Expo copy.
    const nativeValue = await nativeStore.getItem(key);
    if (nativeValue !== null) {
      await deleteExpoCopies(key, kind);
      return nativeValue;
    }

    const current = await SecureStore.getItemAsync(key, options);
    const legacy = await SecureStore.getItemAsync(key);
    const value = current ?? legacy;
    if (value === null) return null;

    // Copy into the native Keystore-backed store before retiring either Expo
    // copy. A crash or cleanup error leaves a retryable duplicate and never
    // exposes a value that has not passed a second native unlock check.
    await nativeStore.setItem(key, value);
    await deleteExpoCopies(key, kind);
    return value;
  }

  const current = await SecureStore.getItemAsync(key, options);
  const legacy = await SecureStore.getItemAsync(key);
  if (current !== null) {
    if (legacy !== null) await SecureStore.deleteItemAsync(key);
    return current;
  }
  if (legacy === null) return null;
  await SecureStore.setItemAsync(key, legacy, options);
  await SecureStore.deleteItemAsync(key);
  return legacy;
}

export async function writeSecureValueToBackend(
  key: string,
  kind: SecureValueKind,
  value: string,
): Promise<void> {
  assertSecureValueAccessAvailable(kind);
  if (usesAndroidUnlockedDeviceStore(kind)) {
    await androidUnlockedDeviceStore().setItem(key, value);
    await deleteExpoCopies(key, kind);
    return;
  }

  await SecureStore.setItemAsync(key, value, secureValuePolicy(kind).options);
  await SecureStore.deleteItemAsync(key);
}

export async function deleteSecureValueFromBackend(
  key: string,
  kind: SecureValueKind,
): Promise<void> {
  let firstError: unknown;
  const capture = async (operation: () => Promise<void>): Promise<void> => {
    try {
      await operation();
    } catch (error) {
      firstError ??= error;
    }
  };

  if (usesAndroidUnlockedDeviceStore(kind)) {
    await capture(() => androidUnlockedDeviceStore().deleteItem(key));
  }
  await capture(() => SecureStore.deleteItemAsync(key, secureValuePolicy(kind).options));
  await capture(() => SecureStore.deleteItemAsync(key));
  if (firstError) throw firstError;
}
