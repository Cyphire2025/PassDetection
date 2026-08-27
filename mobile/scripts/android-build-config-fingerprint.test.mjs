import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  BUILD_CONFIG_INPUT_NAMES,
  androidBuildConfigFingerprint,
  assertProductionAndroidReleaseEvidenceEnvironment,
  validateAndroidBuildConfigFingerprint,
} = require('./android-build-config-fingerprint.js');

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'gc-build-config-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, 'android', 'app'), { recursive: true });
  writeFileSync(join(root, 'android', 'app', 'google-services.json'), 'firebase-project-selector');
  writeFileSync(join(root, 'google-services-input.json'), 'firebase-input-selector');
  writeFileSync(join(root, 'updates-certificate.pem'), 'public-update-certificate');
  const environment = {
    EAS_BUILD_PROFILE: 'production',
    EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
    EXPO_PUBLIC_API_URL: 'https://api.example.com/api/v1',
    EXPO_PUBLIC_APP_ENV: 'production',
    EXPO_PUBLIC_DEMO_MODE: 'false',
    EXPO_PUBLIC_EAS_PROJECT_ID: '00000000-0000-4000-8000-000000000001',
    EXPO_PUBLIC_EXPO_OWNER: 'global-connect-travels',
    EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'false',
    EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE: 'group-companion-mobile',
    EXPO_PUBLIC_OFFLINE_LEASE_ISSUER: 'https://api.example.com',
    EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON: '{"2026-08":"PUBLIC-KEY"}',
    EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
    EXPO_PUBLIC_REALTIME_ENABLED: 'true',
    EXPO_PUBLIC_SENTRY_DSN: 'https://public-dsn@example.ingest.sentry.io/123',
    EXPO_PUBLIC_UPDATES_URL: 'https://u.expo.dev/00000000-0000-4000-8000-000000000000',
    EXPO_UPDATES_CODE_SIGNING_CERTIFICATE: './updates-certificate.pem',
    GC_APP_ATTEST_ENVIRONMENT: 'production',
    GC_ANDROID_FACE_LIVENESS_ENABLED: 'true',
    GC_ANDROID_FACE_LIVENESS_IDENTITY_POOL_ID: 'pool-secret-looking-provider-id',
    GC_ANDROID_FACE_LIVENESS_REGION: 'ap-south-1',
    GOOGLE_SERVICES_JSON: './google-services-input.json',
    NODE_ENV: 'production',
    SENTRY_AUTH_TOKEN: 'super-secret-auth-token',
    SENTRY_DISABLE_AUTO_UPLOAD: 'false',
    SENTRY_ORG: 'global-connect-travels',
    SENTRY_PROJECT: 'group-companion-mobile',
  };
  return { environment, root };
}

test('hashes only the allowlisted Android build configuration without recording values', (t) => {
  const { environment, root } = fixture(t);
  const first = androidBuildConfigFingerprint(root, environment);
  const second = androidBuildConfigFingerprint(root, { ...environment });
  assert.equal(first.sha256, second.sha256);
  assert.equal(first.schema_version, 2);
  assert.deepEqual(
    first.manifest.entries.map((entry) => entry.name),
    BUILD_CONFIG_INPUT_NAMES,
  );
  assert.equal(first.manifest.entries.find((entry) => entry.name === 'updates_enabled').state, 'enabled');
  assert.equal(first.manifest.entries.find((entry) => entry.name === 'generated_google_services').state, 'readable');
  assert.equal(first.manifest.entries.find((entry) => entry.name === 'google_services_input').state, 'readable');
  assert.equal(first.manifest.entries.find((entry) => entry.name === 'sentry_auth_token_presence').state, 'present');
  const nodeEnvironment = first.manifest.entries.find((entry) => entry.name === 'node_environment');
  assert.equal(nodeEnvironment.state, 'present');
  assert.equal(
    nodeEnvironment.sha256,
    createHash('sha256')
      .update('node_environment\0production')
      .digest('hex')
      .toUpperCase(),
  );
  assert.ok(first.manifest.entries.every((entry) => entry.sha256 === null || /^[0-9A-F]{64}$/.test(entry.sha256)));

  const serialized = JSON.stringify(first);
  for (const value of Object.values(environment)) assert.doesNotMatch(serialized, new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(serialized, /firebase-project-selector|public-update-certificate/);
  assert.doesNotMatch(serialized, /firebase-input-selector|super-secret-auth-token/);
});

test('local Android release evidence fails closed outside production mode', () => {
  assert.doesNotThrow(
    () => assertProductionAndroidReleaseEvidenceEnvironment({ NODE_ENV: 'production' }),
  );
  assert.throws(
    () => assertProductionAndroidReleaseEvidenceEnvironment({}),
    /complete command chain/,
  );
  assert.throws(
    () => assertProductionAndroidReleaseEvidenceEnvironment({ NODE_ENV: 'development' }),
    /complete command chain/,
  );
});

test('configuration changes alter the fingerprint while unset or deferred inputs remain explicit', (t) => {
  const { environment, root } = fixture(t);
  const before = androidBuildConfigFingerprint(root, environment);
  const after = androidBuildConfigFingerprint(root, {
    ...environment,
    GC_ANDROID_FACE_LIVENESS_REGION: 'eu-west-1',
  });
  assert.notEqual(after.sha256, before.sha256);
  const rotatedSecret = androidBuildConfigFingerprint(root, {
    ...environment,
    SENTRY_AUTH_TOKEN: 'different-secret-auth-token',
  });
  assert.equal(rotatedSecret.sha256, before.sha256);
  const missingSecret = androidBuildConfigFingerprint(root, {
    ...environment,
    SENTRY_AUTH_TOKEN: '',
  });
  assert.notEqual(missingSecret.sha256, before.sha256);

  const deferred = androidBuildConfigFingerprint(root, {
    EXPO_PUBLIC_APP_ENV: 'development',
    EXPO_UPDATES_CODE_SIGNING_CERTIFICATE: './missing.pem',
  });
  assert.equal(deferred.manifest.entries.find((entry) => entry.name === 'api_origin').state, 'absent');
  assert.equal(deferred.manifest.entries.find((entry) => entry.name === 'updates_enabled').state, 'disabled');
  assert.equal(
    deferred.manifest.entries.find((entry) => entry.name === 'updates_code_signing_certificate').state,
    'unreadable',
  );
});

test('rejects a modified or incomplete build-configuration fingerprint', (t) => {
  const { environment, root } = fixture(t);
  const fingerprint = androidBuildConfigFingerprint(root, environment);
  assert.throws(
    () => validateAndroidBuildConfigFingerprint({
      ...fingerprint,
      sha256: 'A1'.repeat(32),
    }),
    /fingerprint hash is invalid/,
  );
});
