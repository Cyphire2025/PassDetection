import * as SecureStore from 'expo-secure-store';
import { AppState } from 'react-native';

export type AccountSecureValueKind =
  | 'refresh'
  | 'database-key'
  | 'vault-key'
  | 'selected-trip'
  | 'notification-response'
  | 'push-registration'
  | 'database-health'
  | 'offline-authorization'
  | 'app-attest-key-id';

export type GlobalSecureValueKind =
  | 'namespace-index'
  | 'installation-id'
  | 'active-namespace'
  | 'pending-cleanup'
  | 'scan-feedback-preference';

export type SecureValueKind = AccountSecureValueKind | GlobalSecureValueKind;
export type SecureValueAccessibilityTier = 'unlocked-only' | 'background-after-first-unlock';

export type SecureValuePolicy = Readonly<{
  tier: SecureValueAccessibilityTier;
  options: Readonly<SecureStore.SecureStoreOptions>;
}>;

/**
 * Changing only `keychainAccessible` does not migrate an existing iOS Keychain
 * item because Expo updates duplicate items' values without updating their
 * accessibility attributes. Versioned services let secure-store.ts copy first,
 * remove the legacy item second, and retry safely after an interrupted upgrade.
 * They also isolate the Android Keystore aliases by sensitivity tier.
 */
const UNLOCKED_ONLY_OPTIONS = Object.freeze({
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  keychainService: 'gc.v2.unlocked-only',
  // Biometric-bound values are invalidated on enrollment changes and cannot be
  // read or updated by required headless workflows. Lock-state policy remains
  // separate from an explicit future user-presence product decision.
  requireAuthentication: false,
}) satisfies Readonly<SecureStore.SecureStoreOptions>;

const BACKGROUND_OPTIONS = Object.freeze({
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  keychainService: 'gc.v2.background-after-first-unlock',
  requireAuthentication: false,
}) satisfies Readonly<SecureStore.SecureStoreOptions>;

export const SECURE_VALUE_ACCESSIBILITY = Object.freeze({
  'namespace-index': 'background-after-first-unlock',
  'installation-id': 'background-after-first-unlock',
  'active-namespace': 'background-after-first-unlock',
  'pending-cleanup': 'background-after-first-unlock',
  'scan-feedback-preference': 'background-after-first-unlock',
  refresh: 'background-after-first-unlock',
  'database-key': 'background-after-first-unlock',
  'vault-key': 'unlocked-only',
  'selected-trip': 'background-after-first-unlock',
  'notification-response': 'background-after-first-unlock',
  'push-registration': 'background-after-first-unlock',
  'database-health': 'background-after-first-unlock',
  'offline-authorization': 'unlocked-only',
  'app-attest-key-id': 'unlocked-only',
} satisfies Readonly<Record<SecureValueKind, SecureValueAccessibilityTier>>);

export function secureValuePolicy(kind: SecureValueKind): SecureValuePolicy {
  const tier = SECURE_VALUE_ACCESSIBILITY[kind];
  return {
    tier,
    options: tier === 'unlocked-only' ? UNLOCKED_ONLY_OPTIONS : BACKGROUND_OPTIONS,
  };
}

/**
 * AppState is a fast routing guard, not the authoritative lock boundary. The
 * iOS Keychain enforces accessibility and Android unlocked-only values are
 * wrapped by GCUnlockedDeviceStore, which performs native lock checks and uses
 * an UNLOCKED_DEVICE_REQUIRED Keystore key on API 35+. Callers must still
 * handle a native rejection when the device locks after this preflight.
 */
export function isUnlockedOnlySecureValueAccessAvailable(): boolean {
  return AppState.currentState === 'active';
}

export class SecureValueRequiresUnlockError extends Error {
  readonly code = 'SECURE_VALUE_REQUIRES_UNLOCK';

  constructor() {
    super('Protected local data is unavailable until the device is unlocked.');
    this.name = 'SecureValueRequiresUnlockError';
  }
}

export function assertSecureValueAccessAvailable(kind: SecureValueKind): void {
  if (
    SECURE_VALUE_ACCESSIBILITY[kind] === 'unlocked-only'
    && !isUnlockedOnlySecureValueAccessAvailable()
  ) {
    throw new SecureValueRequiresUnlockError();
  }
}
