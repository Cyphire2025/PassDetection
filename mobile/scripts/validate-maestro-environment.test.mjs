import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { validateMaestroEnvironment } = require('./validate-maestro-environment.js');

const validEnvironment = Object.freeze({
  EXPO_PUBLIC_APP_ENV: 'preview',
  EXPO_PUBLIC_API_URL: 'https://mobile-staging.example.test/api/v1',
  EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'true',
  MAESTRO_EXPECTED_API_ORIGIN: 'https://mobile-staging.example.test',
  MAESTRO_FIXTURE_SCOPE: 'synthetic-staging-v1',
  MAESTRO_PASSENGER_PHONE: '919999999999',
  MAESTRO_PASSENGER_OTP: '123456',
  MAESTRO_STAFF_EMAIL: 'manager-fixture@example.test',
  MAESTRO_STAFF_PASSWORD: 'synthetic-only-password',
  MAESTRO_COORDINATOR_EMAIL: 'coordinator-fixture@example.test',
  MAESTRO_COORDINATOR_PASSWORD: 'synthetic-coordinator-password',
  MAESTRO_ATTENDANCE_GROUP_NAME: 'Synthetic E2E Group',
  MAESTRO_ATTENDANCE_ACTIVITY_NAME: 'Synthetic E2E Checkpoint',
  MAESTRO_ATTENDANCE_QR: `pdatt:${'A'.repeat(43)}`,
  MAESTRO_MANAGER_GROUP_NAME: 'Synthetic Manager Group',
  MAESTRO_MANAGER_ITINERARY_ITEM: 'Synthetic Welcome Briefing',
  MAESTRO_MANAGER_UPDATE_TITLE: 'Synthetic Manager Update',
  MAESTRO_MANAGER_PASSENGER_SEARCH: 'EMP-0001',
  MAESTRO_MANAGER_PASSENGER_NAME: 'Synthetic Passenger One',
  MAESTRO_PASSENGER_PRIMARY_TRIP_NAME: 'Synthetic Primary Trip',
  MAESTRO_PASSENGER_SECONDARY_TRIP_NAME: 'Synthetic Secondary Trip',
  MAESTRO_PASSENGER_ITINERARY_DOCUMENT: 'Synthetic Itinerary',
  MAESTRO_PASSENGER_UPDATE_TITLE: 'Synthetic Passenger Update',
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

test('rejects attendance fixture activation outside the dedicated preview artifact', () => {
  const errors = validateMaestroEnvironment({
    ...validEnvironment,
    EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'false',
  });
  assert.ok(errors.some((error) => error.includes('must equal true')));
});

test('rejects malformed attendance inputs without echoing the QR or coordinator password', () => {
  const qr = 'pdatt:do-not-print-this-fixture-value';
  const password = 'short';
  const errors = validateMaestroEnvironment({
    ...validEnvironment,
    MAESTRO_COORDINATOR_PASSWORD: password,
    MAESTRO_ATTENDANCE_GROUP_NAME: 'x',
    MAESTRO_ATTENDANCE_QR: qr,
  });
  assert.ok(errors.some((error) => error.includes('COORDINATOR_PASSWORD')));
  assert.ok(errors.some((error) => error.includes('GROUP_NAME')));
  assert.ok(errors.some((error) => error.includes('canonical synthetic attendance token')));
  assert.equal(errors.join('\n').includes(qr), false);
  assert.equal(errors.join('\n').includes(password), false);
});

test('requires stable, distinct manager and passenger journey fixtures', () => {
  const errors = validateMaestroEnvironment({
    ...validEnvironment,
    MAESTRO_MANAGER_PASSENGER_SEARCH: 'x',
    MAESTRO_PASSENGER_SECONDARY_TRIP_NAME:
      validEnvironment.MAESTRO_PASSENGER_PRIMARY_TRIP_NAME,
  });
  assert.ok(errors.some((error) => error.includes('MANAGER_PASSENGER_SEARCH')));
  assert.ok(errors.some((error) => error.includes('must be different')));
});
