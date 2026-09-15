import type { ConfigContext, ExpoConfig } from 'expo/config';

function configWith(environment: Record<string, string | undefined>) {
  const saved = Object.fromEntries(Object.keys(environment).map((key) => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(environment)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    let createConfig!: (context: ConfigContext) => ExpoConfig;
    jest.isolateModules(() => { createConfig = jest.requireActual('../../../../app.config').default; });
    return createConfig({ config: {} as ExpoConfig } as ConfigContext);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
}

test('native iOS push is enabled by default independently of API environment', () => {
  for (const environment of ['development', 'preview']) {
    const config = configWith({ GC_IOS_PUSH_NOTIFICATIONS_ENABLED: undefined, EXPO_PUBLIC_APP_ENV: environment });
    expect(config.extra?.iosPushNotificationsEnabled).toBe(true);
    expect(config.plugins).toContainEqual(['./plugins/with-ios-push-capability', { enabled: true }]);
  }
});

test('an explicit personal-team preview disables only the iOS push entitlement plugin setting', () => {
  const config = configWith({ GC_IOS_PUSH_NOTIFICATIONS_ENABLED: 'false', EXPO_PUBLIC_APP_ENV: 'preview' });
  expect(config.extra?.iosPushNotificationsEnabled).toBe(false);
  expect(config.plugins).toContainEqual(['./plugins/with-ios-push-capability', { enabled: false }]);
  expect(config.plugins).toContainEqual(['expo-notifications', expect.objectContaining({ defaultChannel: 'trip-updates' })]);
  expect(config.ios?.associatedDomains).toEqual(['applinks:tech.gctravels.com']);
});

test('the personal-team override cannot silently disable push in a production release', () => {
  expect(() => configWith({ GC_IOS_PUSH_NOTIFICATIONS_ENABLED: 'false', EXPO_PUBLIC_APP_ENV: 'production',
    EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce', EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
    GC_APP_ATTEST_ENVIRONMENT: 'production',
  })).toThrow('Production iOS builds require push notifications');
});
