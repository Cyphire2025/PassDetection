'use strict';

const PRODUCTION_HOSTS = new Set(['tech.gctravels.com']);
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '10.0.2.2']);
const REQUIRED_FIXTURE_KEYS = Object.freeze([
  'MAESTRO_PASSENGER_PHONE',
  'MAESTRO_PASSENGER_OTP',
  'MAESTRO_STAFF_EMAIL',
  'MAESTRO_STAFF_PASSWORD',
  'MAESTRO_EXPECTED_API_ORIGIN',
]);

/**
 * Fail closed before a release-Hermes journey can mutate an unintended API.
 * Values are deliberately never returned or logged.
 *
 * @param {Readonly<Record<string, string | undefined>>} source
 * @returns {readonly string[]}
 */
function validateMaestroEnvironment(source) {
  /** @type {string[]} */
  const errors = [];
  for (const key of REQUIRED_FIXTURE_KEYS) {
    const value = source[key];
    if (!value || value !== value.trim() || /[\r\n\0]/.test(value)) {
      errors.push(`${key} must be a protected, non-empty, single-line EAS preview variable.`);
    }
  }

  if (source.EXPO_PUBLIC_APP_ENV !== 'preview') {
    errors.push('EXPO_PUBLIC_APP_ENV must equal preview for fixture journeys.');
  }
  if (source.MAESTRO_FIXTURE_SCOPE !== 'synthetic-staging-v1') {
    errors.push('MAESTRO_FIXTURE_SCOPE must explicitly equal synthetic-staging-v1.');
  }
  if (!/^\d{8,15}$/.test(source.MAESTRO_PASSENGER_PHONE || '')) {
    errors.push('MAESTRO_PASSENGER_PHONE must be an 8-15 digit synthetic staging number.');
  }
  if (!/^\d{6}$/.test(source.MAESTRO_PASSENGER_OTP || '')) {
    errors.push('MAESTRO_PASSENGER_OTP must be the six-digit synthetic staging fixture code.');
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(source.MAESTRO_STAFF_EMAIL || '')) {
    errors.push('MAESTRO_STAFF_EMAIL must be a synthetic staging email address.');
  }
  const password = source.MAESTRO_STAFF_PASSWORD || '';
  if (password.length < 12 || password.length > 256) {
    errors.push('MAESTRO_STAFF_PASSWORD must contain 12-256 characters.');
  }

  try {
    const configuredApi = new URL(source.EXPO_PUBLIC_API_URL || '');
    const expectedOrigin = new URL(source.MAESTRO_EXPECTED_API_ORIGIN || '');
    if (configuredApi.protocol !== 'https:' || expectedOrigin.protocol !== 'https:') {
      errors.push('The embedded and expected fixture API origins must use HTTPS.');
    }
    if (configuredApi.origin !== expectedOrigin.origin) {
      errors.push('EXPO_PUBLIC_API_URL must match MAESTRO_EXPECTED_API_ORIGIN exactly by origin.');
    }
    if (
      PRODUCTION_HOSTS.has(configuredApi.hostname.toLowerCase())
      || LOOPBACK_HOSTS.has(configuredApi.hostname.toLowerCase())
    ) {
      errors.push('Release-Hermes fixture journeys refuse production and loopback API hosts.');
    }
    if (configuredApi.username || configuredApi.password || configuredApi.hash) {
      errors.push('The fixture API URL must not contain credentials or a fragment.');
    }
  } catch {
    errors.push('EXPO_PUBLIC_API_URL and MAESTRO_EXPECTED_API_ORIGIN must be valid absolute URLs.');
  }
  return Object.freeze(errors);
}

if (require.main === module) {
  const errors = validateMaestroEnvironment(process.env);
  if (errors.length) {
    throw new Error(`Maestro staging fixture validation failed:\n- ${errors.join('\n- ')}`);
  }
  process.stdout.write('Maestro staging fixture boundary validated without exposing fixture values.\n');
}

module.exports = { validateMaestroEnvironment };
