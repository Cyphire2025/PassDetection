import type { ConfigContext, ExpoConfig } from 'expo/config';

import createExpoConfig from '../../../../app.config';

describe('localization and tablet build configuration', () => {
  it('advertises only reviewed English while retaining an RTL-ready native boundary', () => {
    const config = createExpoConfig({ config: {} as ExpoConfig } as ConfigContext);

    expect(config.plugins).toContainEqual([
      'expo-localization',
      {
        supportedLocales: { ios: ['en'], android: ['en'] },
        supportsRTL: true,
        allowDynamicLocaleChangesAndroid: true,
      },
    ]);
  });

  it('keeps the accepted portrait workflow while supporting responsive tablet windows', () => {
    const config = createExpoConfig({ config: {} as ExpoConfig } as ConfigContext);

    expect(config.orientation).toBe('portrait');
    expect(config.ios).toMatchObject({ supportsTablet: true, requireFullScreen: false });
  });
});
