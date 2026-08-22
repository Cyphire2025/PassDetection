'use strict';

const { Buffer } = require('node:buffer');
const path = require('node:path');

const EAS_PROJECT_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '10.0.2.2']);
const OFFLINE_LEASE_IDENTITY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]{2,119}$/;
const OFFLINE_LEASE_KID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SENTRY_BUILD_IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$/;
const CLOUD_PROJECT_NUMBER_PATTERN = /^[1-9][0-9]{5,24}$/;

/**
 * @param {Record<string, string>} record
 * @returns {string}
 */
function canonicalStringRecord(record) {
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${JSON.stringify(record[key])}`)
    .join(',')}}`;
}

/**
 * @param {Readonly<Record<string, string | undefined>>} source
 * @param {string[]} errors
 * @returns {{ issuer: string; audience: string; publicKeysJson: string } | undefined}
 */
function validateOfflineLeasePublicConfiguration(source, errors) {
  const issuer = source.EXPO_PUBLIC_OFFLINE_LEASE_ISSUER;
  const audience = source.EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE;
  const publicKeysJson = source.EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON;
  if (!issuer || !OFFLINE_LEASE_IDENTITY_PATTERN.test(issuer)) {
    errors.push(
      'EXPO_PUBLIC_OFFLINE_LEASE_ISSUER must be a 3-120 character bounded ASCII identifier.',
    );
  }
  if (!audience || !OFFLINE_LEASE_IDENTITY_PATTERN.test(audience)) {
    errors.push(
      'EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE must be a 3-120 character bounded ASCII identifier.',
    );
  }
  if (!publicKeysJson || publicKeysJson.length > 8_192) {
    errors.push(
      'EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON is required and must be at most 8192 characters.',
    );
    return undefined;
  }

  /** @type {unknown} */
  let parsed;
  try {
    parsed = JSON.parse(publicKeysJson);
  } catch {
    errors.push('EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON must be valid JSON.');
    return undefined;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    errors.push('EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON must be a JSON object.');
    return undefined;
  }
  const entries = Object.entries(parsed);
  if (entries.length < 1 || entries.length > 5) {
    errors.push('EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON must contain between 1 and 5 keys.');
    return undefined;
  }

  /** @type {Record<string, string>} */
  const normalized = Object.create(null);
  for (const [kid, encodedKey] of entries) {
    if (!OFFLINE_LEASE_KID_PATTERN.test(kid) || typeof encodedKey !== 'string') {
      errors.push('Every offline lease key id and public key must use the required format.');
      continue;
    }
    const rawKey = Buffer.from(encodedKey, 'base64url');
    if (rawKey.length !== 32 || rawKey.toString('base64url') !== encodedKey) {
      errors.push('Every offline lease verification key must be canonical base64url Ed25519 bytes.');
      continue;
    }
    normalized[kid] = encodedKey;
  }
  if (canonicalStringRecord(normalized) !== publicKeysJson) {
    errors.push(
      'EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON must be canonical JSON with sorted key ids and no whitespace.',
    );
  }
  if (!issuer || !audience || Object.keys(normalized).length !== entries.length) {
    return undefined;
  }
  return { issuer, audience, publicKeysJson };
}

/**
 * Expo's native updates plugin joins certificate paths to the project root.
 * Convert EAS file-secret absolute paths into a portable relative path first.
 *
 * @param {string | undefined} value
 * @returns {string | undefined}
 */
function normalizeBuildFilePath(value) {
  if (!value || !path.isAbsolute(value)) {
    return value?.replace(/\\/g, '/');
  }

  const relativePath = path.relative(process.cwd(), value);
  if (path.isAbsolute(relativePath)) {
    throw new Error(
      'The update verification certificate must be on the same filesystem volume as the mobile project.',
    );
  }
  const portablePath = relativePath.replace(/\\/g, '/');
  return portablePath.startsWith('.') ? portablePath : `./${portablePath}`;
}

/**
 * @param {string | undefined} value
 * @param {string} key
 * @param {string[]} errors
 * @returns {URL | undefined}
 */
function parseHttpsUrl(value, key, errors) {
  if (!value) {
    errors.push(`${key} is required.`);
    return undefined;
  }
  if (value !== value.trim()) {
    errors.push(`${key} must not contain leading or trailing whitespace.`);
  }

  try {
    const url = new URL(value);

    if (url.protocol !== 'https:') {
      errors.push(`${key} must use HTTPS.`);
    }
    if (url.username || url.password) {
      errors.push(`${key} must not contain URL credentials.`);
    }
    if (url.hash) {
      errors.push(`${key} must not contain a fragment.`);
    }
    if (key === 'EXPO_PUBLIC_API_URL' && url.search) {
      errors.push(`${key} must not contain query parameters.`);
    }

    return url;
  } catch {
    errors.push(`${key} must be a valid absolute URL.`);
    return undefined;
  }
}

/**
 * Sentry DSNs intentionally contain a public key in the URL username. They
 * must never contain the build auth token, a password, query data, or a URL
 * fragment.
 *
 * @param {string | undefined} value
 * @param {string[]} errors
 * @returns {string | undefined}
 */
function validateSentryDsn(value, errors) {
  if (!value) {
    errors.push('EXPO_PUBLIC_SENTRY_DSN is required for production crash and ANR reporting.');
    return undefined;
  }
  if (value.length > 2_048 || value !== value.trim()) {
    errors.push('EXPO_PUBLIC_SENTRY_DSN must be trimmed and at most 2048 characters.');
  }

  try {
    const dsn = new URL(value);
    const projectPath = dsn.pathname.split('/').filter(Boolean);
    if (dsn.protocol !== 'https:') {
      errors.push('EXPO_PUBLIC_SENTRY_DSN must use HTTPS.');
    }
    if (!dsn.username || dsn.password) {
      errors.push('EXPO_PUBLIC_SENTRY_DSN must contain only the public DSN key and no password.');
    }
    if (dsn.search || dsn.hash || projectPath.length < 1) {
      errors.push('EXPO_PUBLIC_SENTRY_DSN must contain a project path and no query or fragment.');
    }
    return value.trim();
  } catch {
    errors.push('EXPO_PUBLIC_SENTRY_DSN must be a valid absolute Sentry DSN.');
    return undefined;
  }
}

/**
 * Validates build-only Sentry source-map upload credentials. The token is
 * deliberately never returned so callers cannot accidentally embed it in the
 * public Expo config.
 *
 * @param {Readonly<Record<string, string | undefined>>} source
 * @returns {{ readonly organization: string; readonly project: string }}
 */
function validateObservabilityBuildEnvironment(source) {
  /** @type {string[]} */
  const errors = [];
  const organization = source.SENTRY_ORG;
  const project = source.SENTRY_PROJECT;
  const authToken = source.SENTRY_AUTH_TOKEN;

  if (!organization || !SENTRY_BUILD_IDENTIFIER_PATTERN.test(organization)) {
    errors.push('SENTRY_ORG must be a bounded Sentry organization slug.');
  }
  if (!project || !SENTRY_BUILD_IDENTIFIER_PATTERN.test(project)) {
    errors.push('SENTRY_PROJECT must be a bounded Sentry project slug.');
  }
  if (
    !authToken ||
    authToken.length < 20 ||
    authToken.length > 512 ||
    authToken !== authToken.trim() ||
    /\s/.test(authToken)
  ) {
    errors.push('SENTRY_AUTH_TOKEN must be a protected, non-public build token.');
  }

  if (errors.length > 0 || !organization || !project) {
    throw new Error(`Observability build configuration failed:\n- ${errors.join('\n- ')}`);
  }
  return Object.freeze({ organization, project });
}

/**
 * Validate public Android provider identity and the non-secret iOS entitlement
 * selection. Disabled remains the safe rollout default.
 *
 * @param {Readonly<Record<string, string | undefined>>} source
 * @param {boolean} production
 * @returns {{
 *   readonly mode: 'disabled' | 'monitor' | 'enforce';
 *   readonly cloudProjectNumber: string | undefined;
 *   readonly appAttestEnvironment: 'development' | 'production' | undefined;
 * }}
 */
function validateAppIntegrityBuildEnvironment(source, production = false) {
  /** @type {string[]} */
  const errors = [];
  const mode = source.EXPO_PUBLIC_APP_INTEGRITY_MODE || 'disabled';
  const cloudProjectNumber = source.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER;
  const appAttestEnvironment = source.GC_APP_ATTEST_ENVIRONMENT;
  if (!['disabled', 'monitor', 'enforce'].includes(mode)) {
    errors.push('EXPO_PUBLIC_APP_INTEGRITY_MODE must be disabled, monitor, or enforce.');
  }
  if (
    mode !== 'disabled'
    && (!cloudProjectNumber || !CLOUD_PROJECT_NUMBER_PATTERN.test(cloudProjectNumber))
  ) {
    errors.push(
      'Enabled app integrity requires EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER.',
    );
  }
  if (
    mode !== 'disabled'
    && !['development', 'production'].includes(appAttestEnvironment || '')
  ) {
    errors.push(
      'Enabled app integrity requires GC_APP_ATTEST_ENVIRONMENT=development or production.',
    );
  }
  if (production && mode !== 'disabled' && appAttestEnvironment !== 'production') {
    errors.push('Production app-integrity builds require GC_APP_ATTEST_ENVIRONMENT=production.');
  }
  if (errors.length > 0) {
    throw new Error(`App integrity build configuration failed:\n- ${errors.join('\n- ')}`);
  }
  return Object.freeze({
    mode,
    cloudProjectNumber: cloudProjectNumber || undefined,
    appAttestEnvironment:
      mode === 'disabled' ? undefined : appAttestEnvironment,
  });
}

/**
 * Validates every remote-update configuration, including preview channels.
 *
 * @param {Readonly<Record<string, string | undefined>>} source
 */
function validateOtaUpdateEnvironment(source) {
  /** @type {string[]} */
  const errors = [];
  const updatesUrlValue = source.EXPO_PUBLIC_UPDATES_URL;
  const easProjectId = source.EXPO_PUBLIC_EAS_PROJECT_ID;
  const expoOwner = source.EXPO_PUBLIC_EXPO_OWNER;
  const certificate = source.EXPO_UPDATES_CODE_SIGNING_CERTIFICATE;

  if (!updatesUrlValue) {
    if (certificate) {
      errors.push(
        'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE must not be set when OTA updates are disabled.',
      );
    }
  } else {
    if (!easProjectId || !EAS_PROJECT_ID_PATTERN.test(easProjectId)) {
      errors.push(
        'EXPO_PUBLIC_EAS_PROJECT_ID must be a valid UUID when OTA updates are configured.',
      );
    }
    if (!expoOwner || /\s/.test(expoOwner)) {
      errors.push(
        'EXPO_PUBLIC_EXPO_OWNER must be an Expo account name without spaces when OTA updates are configured.',
      );
    }
    if (!certificate) {
      errors.push(
        'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE is required when OTA updates are configured.',
      );
    }
  }

  if (certificate && certificate !== certificate.trim()) {
    errors.push(
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE must not contain leading or trailing whitespace.',
    );
  }
  if (certificate && /^(?:https?|data):/i.test(certificate)) {
    errors.push(
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE must be a local build-time file path.',
    );
  }

  const updatesUrl = updatesUrlValue
    ? parseHttpsUrl(updatesUrlValue, 'EXPO_PUBLIC_UPDATES_URL', errors)
    : undefined;
  if (updatesUrl) {
    const expectedPath = easProjectId ? `/${easProjectId}` : undefined;
    if (
      updatesUrl.hostname.toLowerCase() !== 'u.expo.dev' ||
      updatesUrl.port ||
      updatesUrl.search ||
      (expectedPath && updatesUrl.pathname.replace(/\/$/, '') !== expectedPath)
    ) {
      errors.push(
        'EXPO_PUBLIC_UPDATES_URL must be the canonical https://u.expo.dev/<EXPO_PUBLIC_EAS_PROJECT_ID> URL.',
      );
    }
  }

  if (errors.length > 0) {
    throw new Error(`OTA update configuration failed:\n- ${errors.join('\n- ')}`);
  }
}

/**
 * Validates public values embedded into a production mobile binary.
 *
 * This deliberately validates only public build configuration. Signing,
 * provider, and server secrets must remain in their protected systems and must
 * never be added to EXPO_PUBLIC_* variables.
 *
 * @param {Readonly<Record<string, string | undefined>>} source
 * @returns {{
 *   readonly apiUrl: string;
 *   readonly appEnv: 'production';
 *   readonly demoMode: false;
 *   readonly easProjectId: string | undefined;
 *   readonly expoOwner: string | undefined;
 *   readonly updatesUrl: string | undefined;
 *   readonly updatesCodeSigningCertificate: string | undefined;
 *   readonly offlineLeaseIssuer: string;
 *   readonly offlineLeaseAudience: string;
 *   readonly offlineLeasePublicKeysJson: string;
 *   readonly realtimeEnabled: true;
 *   readonly sentryDsn: string;
 * }}
 */
function validateProductionPublicEnvironment(source) {
  /** @type {string[]} */
  const errors = [];
  const appEnv = source.EXPO_PUBLIC_APP_ENV;
  const demoMode = source.EXPO_PUBLIC_DEMO_MODE;
  const easProjectId = source.EXPO_PUBLIC_EAS_PROJECT_ID;
  const expoOwner = source.EXPO_PUBLIC_EXPO_OWNER;
  const updatesCodeSigningCertificate =
    source.EXPO_UPDATES_CODE_SIGNING_CERTIFICATE;
  const offlineLease = validateOfflineLeasePublicConfiguration(source, errors);
  const sentryDsn = validateSentryDsn(source.EXPO_PUBLIC_SENTRY_DSN, errors);
  const appIntegrity = validateAppIntegrityBuildEnvironment(source, true);

  if (appEnv !== 'production') {
    errors.push('EXPO_PUBLIC_APP_ENV must equal production.');
  }
  if (demoMode !== 'false') {
    errors.push('EXPO_PUBLIC_DEMO_MODE must be explicitly set to false.');
  }
  if (source.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE !== 'false') {
    errors.push(
      'EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE must be explicitly set to false in production.',
    );
  }
  if (source.EXPO_PUBLIC_REALTIME_ENABLED !== 'true') {
    errors.push('EXPO_PUBLIC_REALTIME_ENABLED must be explicitly set to true in production.');
  }
  if (appIntegrity.mode !== 'enforce') {
    errors.push('EXPO_PUBLIC_APP_INTEGRITY_MODE must equal enforce in production.');
  }
  const hasUpdatesConfiguration = Boolean(source.EXPO_PUBLIC_UPDATES_URL);
  if (!easProjectId) {
    errors.push('EXPO_PUBLIC_EAS_PROJECT_ID is required for production push notifications.');
  } else if (!EAS_PROJECT_ID_PATTERN.test(easProjectId)) {
    errors.push('EXPO_PUBLIC_EAS_PROJECT_ID must be a valid UUID.');
  }
  if (expoOwner && /\s/.test(expoOwner)) {
    errors.push(
      'EXPO_PUBLIC_EXPO_OWNER must be an Expo account name without spaces when provided.',
    );
  }
  if (hasUpdatesConfiguration && !easProjectId) {
    errors.push('EXPO_PUBLIC_EAS_PROJECT_ID is required when OTA updates are configured.');
  }
  if (hasUpdatesConfiguration && !expoOwner) {
    errors.push('EXPO_PUBLIC_EXPO_OWNER is required when OTA updates are configured.');
  }
  if (hasUpdatesConfiguration && !updatesCodeSigningCertificate) {
    errors.push(
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE is required when OTA updates are configured.',
    );
  }
  if (!hasUpdatesConfiguration && updatesCodeSigningCertificate) {
    errors.push(
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE must not be set when OTA updates are disabled.',
    );
  }
  if (
    updatesCodeSigningCertificate &&
    updatesCodeSigningCertificate !== updatesCodeSigningCertificate.trim()
  ) {
    errors.push(
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE must not contain leading or trailing whitespace.',
    );
  }
  if (
    updatesCodeSigningCertificate &&
    /^(?:https?|data):/i.test(updatesCodeSigningCertificate)
  ) {
    errors.push(
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE must be a local build-time file path.',
    );
  }

  const apiUrl = parseHttpsUrl(source.EXPO_PUBLIC_API_URL, 'EXPO_PUBLIC_API_URL', errors);
  if (apiUrl && LOOPBACK_HOSTS.has(apiUrl.hostname.toLowerCase())) {
    errors.push('EXPO_PUBLIC_API_URL must not target a loopback or emulator host.');
  }

  const updatesUrl = hasUpdatesConfiguration
    ? parseHttpsUrl(source.EXPO_PUBLIC_UPDATES_URL, 'EXPO_PUBLIC_UPDATES_URL', errors)
    : undefined;
  if (updatesUrl) {
    const expectedPath = easProjectId ? `/${easProjectId}` : undefined;
    if (
      updatesUrl.hostname.toLowerCase() !== 'u.expo.dev' ||
      updatesUrl.port ||
      updatesUrl.search ||
      (expectedPath && updatesUrl.pathname.replace(/\/$/, '') !== expectedPath)
    ) {
      errors.push(
        'EXPO_PUBLIC_UPDATES_URL must be the canonical https://u.expo.dev/<EXPO_PUBLIC_EAS_PROJECT_ID> URL.',
      );
    }
  }

  if (
    errors.length > 0 ||
    !apiUrl ||
    !offlineLease ||
    !sentryDsn
  ) {
    throw new Error(`Production public environment validation failed:\n- ${errors.join('\n- ')}`);
  }

  return Object.freeze({
    apiUrl: apiUrl.toString().replace(/\/$/, ''),
    appEnv: 'production',
    demoMode: false,
    easProjectId: easProjectId || undefined,
    expoOwner: expoOwner || undefined,
    updatesUrl: updatesUrl?.toString().replace(/\/$/, ''),
    updatesCodeSigningCertificate: updatesCodeSigningCertificate || undefined,
    offlineLeaseIssuer: offlineLease.issuer,
    offlineLeaseAudience: offlineLease.audience,
    offlineLeasePublicKeysJson: offlineLease.publicKeysJson,
    realtimeEnabled: true,
    sentryDsn,
  });
}

module.exports = {
  normalizeBuildFilePath,
  validateAppIntegrityBuildEnvironment,
  validateObservabilityBuildEnvironment,
  validateOtaUpdateEnvironment,
  validateProductionPublicEnvironment,
};
