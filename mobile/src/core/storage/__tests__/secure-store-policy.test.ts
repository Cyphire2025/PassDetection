import * as SecureStore from 'expo-secure-store';
import { AppState } from 'react-native';

import {
  assertSecureValueAccessAvailable,
  SECURE_VALUE_ACCESSIBILITY,
  secureValuePolicy,
  type SecureValueKind,
} from '../secure-store-policy';

const everyKind = Object.keys(SECURE_VALUE_ACCESSIBILITY) as SecureValueKind[];
const unlockedOnlyKinds: SecureValueKind[] = [
  'vault-key',
  'offline-authorization',
  'app-attest-key-id',
];

beforeEach(() => {
  (AppState as unknown as { currentState: string }).currentState = 'active';
});

test('assigns every secure value to exactly one explicit accessibility tier', () => {
  expect(everyKind).toHaveLength(14);
  expect(everyKind.filter(
    (kind) => SECURE_VALUE_ACCESSIBILITY[kind] === 'unlocked-only',
  )).toEqual(unlockedOnlyKinds);
  expect(everyKind.filter(
    (kind) => SECURE_VALUE_ACCESSIBILITY[kind] === 'background-after-first-unlock',
  )).toEqual([
    'namespace-index',
    'installation-id',
    'active-namespace',
    'pending-cleanup',
    'scan-feedback-preference',
    'refresh',
    'database-key',
    'selected-trip',
    'notification-response',
    'push-registration',
    'database-health',
  ]);
});

test.each(everyKind)('%s uses a device-only, non-biometric, versioned service', (kind) => {
  const policy = secureValuePolicy(kind);
  expect(policy.options.requireAuthentication).toBe(false);
  expect(policy.options.keychainService).toMatch(/^gc\.v2\./);
  expect(policy.options.keychainAccessible).toBe(
    policy.tier === 'unlocked-only'
      ? SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY
      : SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  );
});

test('only unlocked-only values fail closed outside an active foreground', () => {
  (AppState as unknown as { currentState: string }).currentState = 'background';

  for (const kind of unlockedOnlyKinds) {
    expect(() => assertSecureValueAccessAvailable(kind)).toThrow(
      expect.objectContaining({ code: 'SECURE_VALUE_REQUIRES_UNLOCK' }),
    );
  }
  for (const kind of everyKind.filter((candidate) => !unlockedOnlyKinds.includes(candidate))) {
    expect(() => assertSecureValueAccessAvailable(kind)).not.toThrow();
  }
});
