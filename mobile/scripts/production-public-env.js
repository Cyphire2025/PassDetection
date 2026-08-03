'use strict';

const EAS_PROJECT_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '10.0.2.2']);

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
 * }}
 */
function validateProductionPublicEnvironment(source) {
  /** @type {string[]} */
  const errors = [];
  const appEnv = source.EXPO_PUBLIC_APP_ENV;
  const demoMode = source.EXPO_PUBLIC_DEMO_MODE;
  const easProjectId = source.EXPO_PUBLIC_EAS_PROJECT_ID;
  const expoOwner = source.EXPO_PUBLIC_EXPO_OWNER;

  if (appEnv !== 'production') {
    errors.push('EXPO_PUBLIC_APP_ENV must equal production.');
  }
  if (demoMode !== 'false') {
    errors.push('EXPO_PUBLIC_DEMO_MODE must be explicitly set to false.');
  }
  const hasAnyEasConfiguration = Boolean(
    easProjectId || expoOwner || source.EXPO_PUBLIC_UPDATES_URL,
  );
  if (hasAnyEasConfiguration && (!easProjectId || !EAS_PROJECT_ID_PATTERN.test(easProjectId))) {
    errors.push('EXPO_PUBLIC_EAS_PROJECT_ID must be a valid UUID when OTA updates are configured.');
  }
  if (hasAnyEasConfiguration && (!expoOwner || /\s/.test(expoOwner))) {
    errors.push(
      'EXPO_PUBLIC_EXPO_OWNER must be a non-empty Expo account name without spaces when OTA updates are configured.',
    );
  }

  const apiUrl = parseHttpsUrl(source.EXPO_PUBLIC_API_URL, 'EXPO_PUBLIC_API_URL', errors);
  if (apiUrl && LOOPBACK_HOSTS.has(apiUrl.hostname.toLowerCase())) {
    errors.push('EXPO_PUBLIC_API_URL must not target a loopback or emulator host.');
  }

  const updatesUrl = hasAnyEasConfiguration
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
    (hasAnyEasConfiguration && (!updatesUrl || !easProjectId || !expoOwner))
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
  });
}

module.exports = { validateProductionPublicEnvironment };
