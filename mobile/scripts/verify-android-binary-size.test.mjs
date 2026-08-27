import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ANDROID_RELEASE_BINARY_SIZE_BUDGETS,
  OBSERVED_UNACCEPTABLE_UNIVERSAL_APK_BYTES,
  evaluateAndroidBinarySizes,
  formatMebibytes,
} from './verify-android-binary-size.mjs';

test('accepts positive APK and AAB sizes at their reviewed ceilings', () => {
  assert.deepEqual(evaluateAndroidBinarySizes([
    { type: 'apk', bytes: ANDROID_RELEASE_BINARY_SIZE_BUDGETS.apk },
    { type: 'aab', bytes: ANDROID_RELEASE_BINARY_SIZE_BUDGETS.aab },
  ]), []);
});

test('rejects the observed four-ABI APK instead of adopting it as a baseline', () => {
  const failures = evaluateAndroidBinarySizes([
    { type: 'apk', bytes: OBSERVED_UNACCEPTABLE_UNIVERSAL_APK_BYTES },
  ]);
  assert.equal(failures.length, 1);
  assert.match(failures[0], /APK 172\.38 MiB exceeds 120\.00 MiB/);
});

test('rejects invalid and oversized artifacts with bounded non-path diagnostics', () => {
  const failures = evaluateAndroidBinarySizes([
    { type: 'apk', bytes: 0 },
    { type: 'aab', bytes: ANDROID_RELEASE_BINARY_SIZE_BUDGETS.aab + 1 },
  ]);
  assert.deepEqual(failures, [
    'APK size is invalid.',
    'AAB 150.00 MiB exceeds 150.00 MiB (1 bytes over).',
  ]);
  assert.equal(formatMebibytes(1024 * 1024), '1.00 MiB');
});
