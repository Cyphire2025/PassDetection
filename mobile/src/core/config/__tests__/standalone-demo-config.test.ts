/* eslint-disable @typescript-eslint/no-require-imports -- Load build config after setting the isolated build environment. */
import type { ConfigContext, ExpoConfig } from 'expo/config';

describe('standalone demo native configuration', () => {
  const previous = process.env;
  beforeEach(() => {
    process.env = { ...previous };
    for (const name of Object.keys(process.env)) {
      if (/^(EXPO_PUBLIC_|GC_|SENTRY_|EAS_BUILD_PROFILE|GOOGLE_SERVICES_JSON|EXPO_UPDATES_)/.test(name)) delete process.env[name];
    }
    Object.assign(process.env, { EXPO_PUBLIC_STANDALONE_DEMO: 'true', EXPO_PUBLIC_DEMO_MODE: 'true',
      EXPO_PUBLIC_APP_ENV: 'preview', EXPO_PUBLIC_API_URL: 'https://demo.invalid/api/v1',
      EXPO_PUBLIC_REALTIME_ENABLED: 'false', EXPO_PUBLIC_APP_INTEGRITY_MODE: 'disabled' });
  });
  afterEach(() => { process.env = previous; });
  function config(): ExpoConfig {
    let value!: ExpoConfig;
    jest.isolateModules(() => {
      const create = (require('../../../../app.config') as typeof import('../../../../app.config')).default;
      value = create({ config: {} as ExpoConfig } as ConfigContext);
    });
    return value;
  }
  it('embeds its own assets, removes internet permission and disables OTA/live links', () => {
    const build = config();
    expect(build.android?.package).toBe('com.globalconnects.groupcompanion');
    expect(build.android?.versionCode).toBe(11);
    expect(build.android?.blockedPermissions).toContain('android.permission.INTERNET');
    expect(build.android?.intentFilters).toEqual([]);
    expect(build.android?.googleServicesFile).toBeUndefined();
    expect(build.updates?.enabled).toBe(false);
    expect(build.updates?.useEmbeddedUpdate).toBe(true);
  });
  it.each([
    ['EXPO_PUBLIC_APP_ENV','production'], ['EXPO_PUBLIC_DEMO_MODE','false'],
    ['EXPO_PUBLIC_API_URL','https://tech.gctravels.com/api/v1'], ['EXPO_PUBLIC_REALTIME_ENABLED','true'],
    ['EXPO_PUBLIC_APP_INTEGRITY_MODE','enforce'], ['EXPO_PUBLIC_UPDATES_URL','https://u.expo.dev/project'],
    ['EXPO_PUBLIC_SENTRY_DSN','https://example.com'], ['GOOGLE_SERVICES_JSON','firebase.json'],
    ['GC_ANDROID_FACE_LIVENESS_ENABLED','true'],
  ])('rejects network-enabled/misconfigured builds: %s', (key, value) => {
    process.env[key] = value;
    expect(config).toThrow('Standalone demo builds must use the offline demo configuration');
  });
});
