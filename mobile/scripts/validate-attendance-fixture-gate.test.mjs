import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  validateAttendanceFixtureBuildProfiles,
} = require('./validate-maestro-workspace.js');
const {
  validateProductionPublicEnvironment,
} = require('./production-public-env.js');
const baseline = JSON.parse(readFileSync(new URL('../eas.json', import.meta.url), 'utf8'));

function changed(mutator) {
  const configuration = structuredClone(baseline);
  mutator(configuration);
  return validateAttendanceFixtureBuildProfiles(configuration);
}

test('accepts only the isolated unsigned preview fixture build profile', () => {
  assert.deepEqual(validateAttendanceFixtureBuildProfiles(structuredClone(baseline)), []);
});

test('rejects profile leakage, inline secrets, and production inheritance bypasses', () => {
  assert.ok(changed((configuration) => {
    configuration.build.preview.env = {
      EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'true',
    };
  }).some((message) => message.includes('preview must not enable')));

  assert.ok(changed((configuration) => {
    configuration.build['e2e-test'].env.MAESTRO_ATTENDANCE_QR = 'inline-secret';
  }).some((message) => message.includes('protected MAESTRO_')));

  assert.ok(changed((configuration) => {
    configuration.build.production.env.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE = 'true';
  }).some((message) => message.includes('explicitly disable')));

  assert.ok(changed((configuration) => {
    configuration.build['production-apk'].extends = 'base';
  }).some((message) => message.includes('inherit')));
});

test('production public configuration rejects an enabled fixture before build generation', () => {
  assert.throws(
    () => validateProductionPublicEnvironment({
      EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
      EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'true',
      EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
      GC_APP_ATTEST_ENVIRONMENT: 'production',
    }),
    /EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE must be explicitly set to false in production/,
  );
});
