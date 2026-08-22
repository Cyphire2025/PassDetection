import {
  normalizeBuildFilePath,
  validateObservabilityBuildEnvironment,
  validateOtaUpdateEnvironment,
  validateProductionPublicEnvironment,
} from '../../../../scripts/production-public-env';

const projectId = '123e4567-e89b-42d3-a456-426614174000';
const offlineLeaseEnvironment = {
  EXPO_PUBLIC_OFFLINE_LEASE_ISSUER: 'passdetection-mobile-offline',
  EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE: 'gc-mobile-offline',
  EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON:
    '{"unit-test-2026-01":"ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"}',
} as const;
const sentryDsn = 'https://public-key@o0.ingest.sentry.io/12345';

const validEnvironment = {
  EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
  EXPO_PUBLIC_APP_ENV: 'production',
  EXPO_PUBLIC_DEMO_MODE: 'false',
  EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'false',
  EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
  EXPO_PUBLIC_EXPO_OWNER: 'global-connect-travels',
  EXPO_PUBLIC_UPDATES_URL: `https://u.expo.dev/${projectId}`,
  EXPO_UPDATES_CODE_SIGNING_CERTIFICATE: './private-build-input/certificate.pem',
  EXPO_PUBLIC_REALTIME_ENABLED: 'true',
  EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
  EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
  GC_APP_ATTEST_ENVIRONMENT: 'production',
  EXPO_PUBLIC_SENTRY_DSN: sentryDsn,
  ...offlineLeaseEnvironment,
} as const;

describe('validateProductionPublicEnvironment', () => {
  it('normalizes relative build-file paths for Expo native generation', () => {
    expect(normalizeBuildFilePath('private\\certificate.pem')).toBe(
      'private/certificate.pem',
    );
  });

  it('applies the signed canonical OTA contract outside production too', () => {
    expect(() => validateOtaUpdateEnvironment({
      EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
      EXPO_PUBLIC_EXPO_OWNER: 'global-connect-travels',
      EXPO_PUBLIC_UPDATES_URL: `https://u.expo.dev/${projectId}`,
      EXPO_UPDATES_CODE_SIGNING_CERTIFICATE: './certificate.pem',
    })).not.toThrow();

    expect(() => validateOtaUpdateEnvironment({
      EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
      EXPO_PUBLIC_EXPO_OWNER: 'global-connect-travels',
      EXPO_PUBLIC_UPDATES_URL: `https://u.expo.dev/${projectId}`,
    })).toThrow('EXPO_UPDATES_CODE_SIGNING_CERTIFICATE is required');
  });

  it('accepts a complete production configuration', () => {
    expect(validateProductionPublicEnvironment(validEnvironment)).toEqual({
      apiUrl: 'https://tech.gctravels.com/api/v1',
      appEnv: 'production',
      demoMode: false,
      easProjectId: projectId,
      expoOwner: 'global-connect-travels',
      updatesUrl: `https://u.expo.dev/${projectId}`,
      updatesCodeSigningCertificate: './private-build-input/certificate.pem',
      offlineLeaseIssuer: 'passdetection-mobile-offline',
      offlineLeaseAudience: 'gc-mobile-offline',
      offlineLeasePublicKeysJson:
        '{"unit-test-2026-01":"ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"}',
      realtimeEnabled: true,
      sentryDsn,
    });
  });

  it('accepts a production binary with push configured and OTA updates unconfigured', () => {
    expect(validateProductionPublicEnvironment({
      EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
      EXPO_PUBLIC_APP_ENV: 'production',
      EXPO_PUBLIC_DEMO_MODE: 'false',
      EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'false',
      EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
      EXPO_PUBLIC_REALTIME_ENABLED: 'true',
      EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
      EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
      GC_APP_ATTEST_ENVIRONMENT: 'production',
      EXPO_PUBLIC_SENTRY_DSN: sentryDsn,
      ...offlineLeaseEnvironment,
    })).toEqual({
      apiUrl: 'https://tech.gctravels.com/api/v1',
      appEnv: 'production',
      demoMode: false,
      easProjectId: projectId,
      expoOwner: undefined,
      updatesUrl: undefined,
      updatesCodeSigningCertificate: undefined,
      offlineLeaseIssuer: 'passdetection-mobile-offline',
      offlineLeaseAudience: 'gc-mobile-offline',
      offlineLeasePublicKeysJson:
        '{"unit-test-2026-01":"ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"}',
      realtimeEnabled: true,
      sentryDsn,
    });
  });

  it('accepts a project ID for push notifications without enabling OTA updates', () => {
    expect(validateProductionPublicEnvironment({
      EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
      EXPO_PUBLIC_APP_ENV: 'production',
      EXPO_PUBLIC_DEMO_MODE: 'false',
      EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE: 'false',
      EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
      EXPO_PUBLIC_REALTIME_ENABLED: 'true',
      EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
      EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
      GC_APP_ATTEST_ENVIRONMENT: 'production',
      EXPO_PUBLIC_SENTRY_DSN: sentryDsn,
      ...offlineLeaseEnvironment,
    })).toEqual({
      apiUrl: 'https://tech.gctravels.com/api/v1',
      appEnv: 'production',
      demoMode: false,
      easProjectId: projectId,
      expoOwner: undefined,
      updatesUrl: undefined,
      updatesCodeSigningCertificate: undefined,
      offlineLeaseIssuer: 'passdetection-mobile-offline',
      offlineLeaseAudience: 'gc-mobile-offline',
      offlineLeasePublicKeysJson:
        '{"unit-test-2026-01":"ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"}',
      realtimeEnabled: true,
      sentryDsn,
    });
  });

  it.each([
    ['EXPO_PUBLIC_API_URL', undefined, 'EXPO_PUBLIC_API_URL is required'],
    ['EXPO_PUBLIC_API_URL', 'http://tech.gctravels.com/api/v1', 'must use HTTPS'],
    ['EXPO_PUBLIC_API_URL', 'https://127.0.0.1:8000/api/v1', 'must not target a loopback'],
    ['EXPO_PUBLIC_API_URL', ' https://tech.gctravels.com/api/v1', 'must not contain leading'],
    ['EXPO_PUBLIC_API_URL', 'https://tech.gctravels.com/api/v1?tenant=1', 'query parameters'],
    ['EXPO_PUBLIC_APP_ENV', 'preview', 'must equal production'],
    ['EXPO_PUBLIC_DEMO_MODE', undefined, 'must be explicitly set to false'],
    ['EXPO_PUBLIC_DEMO_MODE', 'true', 'must be explicitly set to false'],
    [
      'EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE',
      'true',
      'must be explicitly set to false in production',
    ],
    ['EXPO_PUBLIC_REALTIME_ENABLED', 'false', 'must be explicitly set to true'],
    ['EXPO_PUBLIC_APP_INTEGRITY_MODE', 'monitor', 'must equal enforce'],
    ['EXPO_PUBLIC_EAS_PROJECT_ID', 'not-a-uuid', 'must be a valid UUID'],
    ['EXPO_PUBLIC_EAS_PROJECT_ID', undefined, 'is required for production push notifications'],
    ['EXPO_PUBLIC_SENTRY_DSN', undefined, 'is required for production crash and ANR reporting'],
    ['EXPO_PUBLIC_SENTRY_DSN', 'http://public@example.test/1', 'must use HTTPS'],
    ['EXPO_PUBLIC_SENTRY_DSN', 'https://public:password@example.test/1', 'no password'],
    ['EXPO_PUBLIC_OFFLINE_LEASE_ISSUER', undefined, 'OFFLINE_LEASE_ISSUER must be'],
    ['EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE', 'contains spaces', 'OFFLINE_LEASE_AUDIENCE must be'],
    ['EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON', '{}', 'must contain between 1 and 5 keys'],
    [
      'EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON',
      '{ "unit-test-2026-01": "ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ" }',
      'must be canonical JSON',
    ],
    ['EXPO_PUBLIC_EXPO_OWNER', 'owner with spaces', 'without spaces'],
    ['EXPO_PUBLIC_UPDATES_URL', 'https://updates.example.com/runtime', 'must be the canonical'],
    [
      'EXPO_PUBLIC_UPDATES_URL',
      'https://u.expo.dev/123e4567-e89b-42d3-a456-426614174999',
      'must be the canonical',
    ],
    [
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE',
      undefined,
      'is required when OTA updates are configured',
    ],
    [
      'EXPO_UPDATES_CODE_SIGNING_CERTIFICATE',
      'https://example.com/certificate.pem',
      'must be a local build-time file path',
    ],
  ] as const)('rejects unsafe %s=%s', (key, value, message) => {
    expect(() =>
      validateProductionPublicEnvironment({
        ...validEnvironment,
        [key]: value,
      }),
    ).toThrow(message);
  });

  it('rejects a certificate path when OTA updates are disabled', () => {
    expect(() => validateProductionPublicEnvironment({
      EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
      EXPO_PUBLIC_APP_ENV: 'production',
      EXPO_PUBLIC_DEMO_MODE: 'false',
      EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
      EXPO_PUBLIC_SENTRY_DSN: sentryDsn,
      EXPO_UPDATES_CODE_SIGNING_CERTIFICATE: './certificate.pem',
      ...offlineLeaseEnvironment,
    })).toThrow('must not be set when OTA updates are disabled');
  });

  it('requires protected build-only source-map credentials', () => {
    expect(validateObservabilityBuildEnvironment({
      SENTRY_ORG: 'global-connect-travels',
      SENTRY_PROJECT: 'group-companion',
      SENTRY_AUTH_TOKEN: 'sntrys_unit_test_token_1234567890',
    })).toEqual({
      organization: 'global-connect-travels',
      project: 'group-companion',
    });

    expect(() => validateObservabilityBuildEnvironment({
      SENTRY_ORG: 'global-connect-travels',
      SENTRY_PROJECT: 'group-companion',
      SENTRY_AUTH_TOKEN: 'short',
    })).toThrow('protected, non-public build token');
  });

  it('reports all missing values in one actionable failure', () => {
    expect(() => validateProductionPublicEnvironment({})).toThrow(
      [
        'EXPO_PUBLIC_APP_ENV must equal production.',
        'EXPO_PUBLIC_DEMO_MODE must be explicitly set to false.',
        'EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE must be explicitly set to false in production.',
        'EXPO_PUBLIC_REALTIME_ENABLED must be explicitly set to true in production.',
        'EXPO_PUBLIC_APP_INTEGRITY_MODE must equal enforce in production.',
        'EXPO_PUBLIC_EAS_PROJECT_ID is required for production push notifications.',
        'EXPO_PUBLIC_API_URL is required.',
      ].join('\n- '),
    );
  });
});
