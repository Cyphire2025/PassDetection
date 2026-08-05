import { validateProductionPublicEnvironment } from '../../../../scripts/production-public-env';

const projectId = '123e4567-e89b-42d3-a456-426614174000';

const validEnvironment = {
  EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
  EXPO_PUBLIC_APP_ENV: 'production',
  EXPO_PUBLIC_DEMO_MODE: 'false',
  EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
  EXPO_PUBLIC_EXPO_OWNER: 'global-connect-travels',
  EXPO_PUBLIC_UPDATES_URL: `https://u.expo.dev/${projectId}`,
} as const;

describe('validateProductionPublicEnvironment', () => {
  it('accepts a complete production configuration', () => {
    expect(validateProductionPublicEnvironment(validEnvironment)).toEqual({
      apiUrl: 'https://tech.gctravels.com/api/v1',
      appEnv: 'production',
      demoMode: false,
      easProjectId: projectId,
      expoOwner: 'global-connect-travels',
      updatesUrl: `https://u.expo.dev/${projectId}`,
    });
  });

  it('accepts a local production binary with OTA updates explicitly unconfigured', () => {
    expect(validateProductionPublicEnvironment({
      EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
      EXPO_PUBLIC_APP_ENV: 'production',
      EXPO_PUBLIC_DEMO_MODE: 'false',
    })).toEqual({
      apiUrl: 'https://tech.gctravels.com/api/v1',
      appEnv: 'production',
      demoMode: false,
      easProjectId: undefined,
      expoOwner: undefined,
      updatesUrl: undefined,
    });
  });

  it('accepts a project ID for push notifications without enabling OTA updates', () => {
    expect(validateProductionPublicEnvironment({
      EXPO_PUBLIC_API_URL: 'https://tech.gctravels.com/api/v1',
      EXPO_PUBLIC_APP_ENV: 'production',
      EXPO_PUBLIC_DEMO_MODE: 'false',
      EXPO_PUBLIC_EAS_PROJECT_ID: projectId,
    })).toEqual({
      apiUrl: 'https://tech.gctravels.com/api/v1',
      appEnv: 'production',
      demoMode: false,
      easProjectId: projectId,
      expoOwner: undefined,
      updatesUrl: undefined,
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
    ['EXPO_PUBLIC_EAS_PROJECT_ID', 'not-a-uuid', 'must be a valid UUID'],
    ['EXPO_PUBLIC_EXPO_OWNER', 'owner with spaces', 'without spaces'],
    ['EXPO_PUBLIC_UPDATES_URL', 'https://updates.example.com/runtime', 'must be the canonical'],
    [
      'EXPO_PUBLIC_UPDATES_URL',
      'https://u.expo.dev/123e4567-e89b-42d3-a456-426614174999',
      'must be the canonical',
    ],
  ] as const)('rejects unsafe %s=%s', (key, value, message) => {
    expect(() =>
      validateProductionPublicEnvironment({
        ...validEnvironment,
        [key]: value,
      }),
    ).toThrow(message);
  });

  it('reports all missing values in one actionable failure', () => {
    expect(() => validateProductionPublicEnvironment({})).toThrow(
      [
        'EXPO_PUBLIC_APP_ENV must equal production.',
        'EXPO_PUBLIC_DEMO_MODE must be explicitly set to false.',
        'EXPO_PUBLIC_API_URL is required.',
      ].join('\n- '),
    );
  });
});
