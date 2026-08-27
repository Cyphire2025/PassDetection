/* global __dirname */
'use strict';

const { Buffer } = require('node:buffer');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { isAbsolute, join, resolve } = require('node:path');

const BUILD_CONFIG_INPUT_NAMES = Object.freeze([
  'api_origin',
  'app_attest_environment',
  'app_environment',
  'app_integrity_mode',
  'attendance_fixture_enabled',
  'demo_mode',
  'eas_build_profile',
  'eas_project_id',
  'expo_owner',
  'face_liveness_enabled',
  'face_liveness_identity_pool',
  'face_liveness_region',
  'generated_google_services',
  'google_services_input',
  'node_environment',
  'offline_lease_audience',
  'offline_lease_issuer',
  'offline_lease_public_keys',
  'play_integrity_cloud_project',
  'realtime_enabled',
  'sentry_auth_token_presence',
  'sentry_dsn',
  'sentry_organization',
  'sentry_project',
  'sentry_upload_disabled',
  'updates_code_signing_certificate',
  'updates_enabled',
  'updates_url',
]);

const BUILD_CONFIG_ENTRY_STATES = new Set([
  'absent',
  'disabled',
  'enabled',
  'invalid',
  'present',
  'readable',
  'unreadable',
  'valid',
]);

function assertProductionAndroidReleaseEvidenceEnvironment(environment = process.env) {
  if (environment?.NODE_ENV !== 'production') {
    throw new Error(
      'Local Android release staging and packaging require NODE_ENV=production for the complete command chain.',
    );
  }
}

function sha256Bytes(value) {
  return createHash('sha256').update(value).digest('hex').toUpperCase();
}

function boundedInput(value) {
  if (value == null || value === '') return undefined;
  const normalized = String(value).normalize('NFC');
  if (normalized.length > 16_384 || /[\0\r\n]/.test(normalized)) {
    throw new Error('An allowlisted Android build configuration input is invalid.');
  }
  return normalized;
}

function hashedEntry(name, state, value) {
  return Object.freeze({
    name,
    state,
    sha256: value == null
      ? null
      : sha256Bytes(Buffer.from(`${name}\0${value}`, 'utf8')),
  });
}

function scalarEntry(name, value) {
  const normalized = boundedInput(value);
  return normalized == null
    ? hashedEntry(name, 'absent')
    : hashedEntry(name, 'present', normalized);
}

function urlEntry(name, value, identity = 'url') {
  const normalized = boundedInput(value);
  if (normalized == null) return hashedEntry(name, 'absent');
  try {
    const parsed = new URL(normalized);
    const canonical = identity === 'origin' ? parsed.origin : parsed.toString();
    return hashedEntry(name, 'valid', canonical);
  } catch {
    return hashedEntry(name, 'invalid', normalized);
  }
}

function booleanEntry(name, value) {
  const normalized = boundedInput(value);
  if (normalized == null) return hashedEntry(name, 'absent');
  if (normalized === 'true') return hashedEntry(name, 'enabled', 'true');
  if (normalized === 'false') return hashedEntry(name, 'disabled', 'false');
  return hashedEntry(name, 'invalid', normalized);
}

function secretPresenceEntry(name, value) {
  const normalized = boundedInput(value);
  return normalized == null
    ? hashedEntry(name, 'absent')
    : hashedEntry(name, 'present', 'configured');
}

function fileEntry(name, filePath, mobileRoot, dependencies = {}) {
  const normalized = boundedInput(filePath);
  if (normalized == null) return hashedEntry(name, 'absent');
  const absolutePath = isAbsolute(normalized)
    ? normalized
    : resolve(mobileRoot, normalized);
  try {
    const bytes = (dependencies.readFile || readFileSync)(absolutePath);
    return Object.freeze({ name, state: 'readable', sha256: sha256Bytes(bytes) });
  } catch {
    return hashedEntry(name, 'unreadable');
  }
}

function generatedGoogleServicesEntry(mobileRoot, dependencies = {}) {
  const path = join(mobileRoot, 'android', 'app', 'google-services.json');
  try {
    const bytes = (dependencies.readFile || readFileSync)(path);
    return Object.freeze({
      name: 'generated_google_services',
      state: 'readable',
      sha256: sha256Bytes(bytes),
    });
  } catch {
    return hashedEntry('generated_google_services', 'unreadable');
  }
}

function validateAndroidBuildConfigFingerprint(fingerprint) {
  const entries = fingerprint?.manifest?.entries;
  if (
    fingerprint?.schema_version !== 2
    || fingerprint?.evidence_level
      !== 'configuration_observed_at_evidence_time_not_binary_attestation'
    || fingerprint?.manifest?.schema_version !== 2
    || fingerprint?.manifest?.scope !== 'secret_safe_android_build_configuration'
    || !Array.isArray(entries)
    || fingerprint?.input_count !== BUILD_CONFIG_INPUT_NAMES.length
    || entries?.length !== BUILD_CONFIG_INPUT_NAMES.length
  ) {
    throw new Error('The Android build configuration fingerprint is invalid.');
  }
  const names = entries.map((entry) => entry?.name);
  if (JSON.stringify(names) !== JSON.stringify(BUILD_CONFIG_INPUT_NAMES)) {
    throw new Error('The Android build configuration fingerprint allowlist is invalid.');
  }
  for (const entry of entries) {
    if (
      !BUILD_CONFIG_ENTRY_STATES.has(entry?.state)
      || !(entry.sha256 === null || /^[0-9A-F]{64}$/.test(entry.sha256 || ''))
      || (['absent', 'unreadable'].includes(entry.state) && entry.sha256 !== null)
      || (!['absent', 'unreadable'].includes(entry.state) && entry.sha256 === null)
    ) {
      throw new Error('The Android build configuration fingerprint entry is invalid.');
    }
  }
  const expectedHash = sha256Bytes(
    Buffer.from(`${JSON.stringify(fingerprint.manifest)}\n`, 'utf8'),
  );
  if (fingerprint.sha256 !== expectedHash) {
    throw new Error('The Android build configuration fingerprint hash is invalid.');
  }
  return fingerprint;
}

function androidBuildConfigFingerprint(
  mobileRoot = resolve(__dirname, '..'),
  environment = process.env,
  dependencies = {},
) {
  const root = resolve(mobileRoot);
  const updatesUrl = boundedInput(environment.EXPO_PUBLIC_UPDATES_URL);
  const entries = Object.freeze([
    urlEntry('api_origin', environment.EXPO_PUBLIC_API_URL, 'origin'),
    scalarEntry('app_attest_environment', environment.GC_APP_ATTEST_ENVIRONMENT),
    scalarEntry('app_environment', environment.EXPO_PUBLIC_APP_ENV),
    scalarEntry('app_integrity_mode', environment.EXPO_PUBLIC_APP_INTEGRITY_MODE),
    booleanEntry(
      'attendance_fixture_enabled',
      environment.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE,
    ),
    booleanEntry('demo_mode', environment.EXPO_PUBLIC_DEMO_MODE),
    scalarEntry('eas_build_profile', environment.EAS_BUILD_PROFILE),
    scalarEntry('eas_project_id', environment.EXPO_PUBLIC_EAS_PROJECT_ID),
    scalarEntry('expo_owner', environment.EXPO_PUBLIC_EXPO_OWNER),
    booleanEntry('face_liveness_enabled', environment.GC_ANDROID_FACE_LIVENESS_ENABLED),
    scalarEntry(
      'face_liveness_identity_pool',
      environment.GC_ANDROID_FACE_LIVENESS_IDENTITY_POOL_ID,
    ),
    scalarEntry('face_liveness_region', environment.GC_ANDROID_FACE_LIVENESS_REGION),
    generatedGoogleServicesEntry(root, dependencies),
    fileEntry('google_services_input', environment.GOOGLE_SERVICES_JSON, root, dependencies),
    scalarEntry('node_environment', environment.NODE_ENV),
    scalarEntry('offline_lease_audience', environment.EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE),
    scalarEntry('offline_lease_issuer', environment.EXPO_PUBLIC_OFFLINE_LEASE_ISSUER),
    scalarEntry(
      'offline_lease_public_keys',
      environment.EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON,
    ),
    scalarEntry(
      'play_integrity_cloud_project',
      environment.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER,
    ),
    booleanEntry('realtime_enabled', environment.EXPO_PUBLIC_REALTIME_ENABLED),
    secretPresenceEntry('sentry_auth_token_presence', environment.SENTRY_AUTH_TOKEN),
    urlEntry('sentry_dsn', environment.EXPO_PUBLIC_SENTRY_DSN),
    scalarEntry('sentry_organization', environment.SENTRY_ORG),
    scalarEntry('sentry_project', environment.SENTRY_PROJECT),
    booleanEntry('sentry_upload_disabled', environment.SENTRY_DISABLE_AUTO_UPLOAD),
    fileEntry(
      'updates_code_signing_certificate',
      environment.EXPO_UPDATES_CODE_SIGNING_CERTIFICATE,
      root,
      dependencies,
    ),
    hashedEntry('updates_enabled', updatesUrl ? 'enabled' : 'disabled', String(Boolean(updatesUrl))),
    urlEntry('updates_url', updatesUrl),
  ]);
  const manifest = Object.freeze({
    schema_version: 2,
    scope: 'secret_safe_android_build_configuration',
    selection: 'all reviewed Android embedded and build-affecting inputs; names, state, and hashes only; secret tokens reduced to presence',
    entries,
  });
  return validateAndroidBuildConfigFingerprint(Object.freeze({
    schema_version: 2,
    evidence_level: 'configuration_observed_at_evidence_time_not_binary_attestation',
    input_count: entries.length,
    sha256: sha256Bytes(Buffer.from(`${JSON.stringify(manifest)}\n`, 'utf8')),
    manifest,
  }));
}

module.exports = {
  BUILD_CONFIG_INPUT_NAMES,
  androidBuildConfigFingerprint,
  assertProductionAndroidReleaseEvidenceEnvironment,
  validateAndroidBuildConfigFingerprint,
};
