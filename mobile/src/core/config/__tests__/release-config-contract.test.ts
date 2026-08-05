import type { ConfigContext, ExpoConfig } from 'expo/config';

import eas from '../../../../eas.json';
import createExpoConfig from '../../../../app.config';

describe('mobile release configuration', () => {
  it('isolates OTA updates by native fingerprint and removes unused iOS permissions', () => {
    const config = createExpoConfig({
      config: {} as ExpoConfig,
    } as ConfigContext);

    expect(config.runtimeVersion).toEqual({ policy: 'fingerprint' });
    expect(config.updates?.enabled).toBe(false);
    expect(config.plugins).toContainEqual([
      'expo-secure-store',
      {
        configureAndroidBackup: false,
        faceIDPermission: false,
      },
    ]);
    expect(config.plugins).toContainEqual([
      'expo-camera',
      {
        cameraPermission:
          'Coordinators use the camera to scan passenger attendance QR codes.',
        microphonePermission: false,
        recordAudioAndroid: false,
      },
    ]);
    expect(config.ios?.associatedDomains).toEqual([
      'applinks:app.globalconnecttravels.com',
    ]);
    expect(config.icon).toBe('./assets/images/gc-app-icon.png');
    expect(config.ios?.icon).toBe('./assets/images/gc-app-icon.png');
    expect(config.android?.adaptiveIcon).toEqual({
      backgroundColor: '#056BB1',
      foregroundImage: './assets/images/gc-app-icon.png',
      monochromeImage: './assets/images/gc-app-monochrome.png',
    });
  });

  it('keeps the store bundle and installable APK on the production EAS environment', () => {
    expect(eas.build.production).toMatchObject({
      environment: 'production',
      autoIncrement: true,
      channel: 'production',
      android: { buildType: 'app-bundle' },
    });
    expect(eas.build['production-apk']).toMatchObject({
      extends: 'production',
      distribution: 'internal',
      android: { buildType: 'apk' },
    });
  });
});
