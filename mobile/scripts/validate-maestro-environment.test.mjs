import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { validateMaestroEnvironment } = require('./validate-maestro-environment.js');

const validEnvironment = Object.freeze({
  EXPO_PUBLIC_APP_ENV: 'preview',
  EXPO_PUBLIC_API_URL: 'https://mobile-staging.example.test/api/v1',
  MAESTRO_EXPECTED_API_ORIGIN: 'https://mobile-staging.example.test',
  MAESTRO_FIXTURE_SCOPE: 'synthetic-staging-v1',
  MAESTRO_PASSENGER_PHONE: '919999999999',
  MAESTRO_PASSENGER_OTP: '123456',
  MAESTRO_STAFF_EMAIL: 'manager-fixture@example.test',
  MAESTRO_STAFF_PASSWORD: 'synthetic-only-password',
});

test('accepts a fully explicit non-production synthetic fixture boundary', () => {
  assert.deepEqual(validateMaestroEnvironment(validEnvironment), []);
});

test('rejects production even when the app environment is mislabeled preview', () => {
  const errors = validateMaestroEnvironment({
    ...validEnvironment,
    EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
    MAESTRO_EXPECTED_API_ORIGIN: 'https://tech.gctravels.com',
  });
  assert.ok(errors.some((error) => error.includes('refuse production')));
});

test('rejects missing fixture scope and malformed credentials without echoing values', () => {
  const secret = 'do-not-print-this-secret';
  const errors = validateMaestroEnvironment({
    ...validEnvironment,
    MAESTRO_FIXTURE_SCOPE: undefined,
    MAESTRO_PASSENGER_OTP: secret,
  });
  assert.ok(errors.some((error) => error.includes('synthetic-staging-v1')));
  assert.ok(errors.some((error) => error.includes('six-digit')));
  assert.equal(errors.join('\n').includes(secret), false);
});
