import type { ConfigContext, ExpoConfig } from 'expo/config';

import { validateAppIntegrityBuildEnvironment } from '../../../../scripts/production-public-env';

describe('app-integrity build configuration', () => {
  it('keeps disabled as a zero-credential rollout default', () => {
    expect(validateAppIntegrityBuildEnvironment({})).toEqual({
      mode: 'disabled',
      cloudProjectNumber: undefined,
      appAttestEnvironment: undefined,
    });
  });

  it.each([
    [
      { EXPO_PUBLIC_APP_INTEGRITY_MODE: 'audit' },
      'must be disabled, monitor, or enforce',
    ],
    [
      {
        EXPO_PUBLIC_APP_INTEGRITY_MODE: 'monitor',
        GC_APP_ATTEST_ENVIRONMENT: 'development',
      },
      'requires EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER',
    ],
    [
      {
        EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
        EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
      },
      'requires GC_APP_ATTEST_ENVIRONMENT',
    ],
  ])('rejects an incomplete or unknown provider build contract', (source, message) => {
    expect(() => validateAppIntegrityBuildEnvironment(source)).toThrow(message);
  });

  it('requires the production App Attest entitlement in a production rollout', () => {
    expect(() => validateAppIntegrityBuildEnvironment({
      EXPO_PUBLIC_APP_INTEGRITY_MODE: 'monitor',
      EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
      GC_APP_ATTEST_ENVIRONMENT: 'development',
    }, true)).toThrow('require GC_APP_ATTEST_ENVIRONMENT=production');

    expect(validateAppIntegrityBuildEnvironment({
      EXPO_PUBLIC_APP_INTEGRITY_MODE: 'enforce',
      EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER: '123456789012',
      GC_APP_ATTEST_ENVIRONMENT: 'production',
    }, true)).toEqual({
      mode: 'enforce',
      cloudProjectNumber: '123456789012',
      appAttestEnvironment: 'production',
    });
  });

  it('emits the reviewed App Attest entitlement only when integrity is enabled', () => {
    const original = {
      mode: process.env.EXPO_PUBLIC_APP_INTEGRITY_MODE,
      project: process.env.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER,
      environment: process.env.GC_APP_ATTEST_ENVIRONMENT,
    };
    try {
      process.env.EXPO_PUBLIC_APP_INTEGRITY_MODE = 'monitor';
      process.env.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER = '123456789012';
      process.env.GC_APP_ATTEST_ENVIRONMENT = 'development';
      jest.resetModules();
      let createExpoConfig: (context: ConfigContext) => ExpoConfig;
      jest.isolateModules(() => {
        createExpoConfig = jest.requireActual('../../../../app.config').default;
      });

      const config = createExpoConfig!({ config: {} as ExpoConfig } as ConfigContext);

      expect(config.ios?.entitlements).toEqual({
        'com.apple.developer.devicecheck.appattest-environment': 'development',
      });
    } finally {
      if (original.mode === undefined) delete process.env.EXPO_PUBLIC_APP_INTEGRITY_MODE;
      else process.env.EXPO_PUBLIC_APP_INTEGRITY_MODE = original.mode;
      if (original.project === undefined) {
        delete process.env.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER;
      } else {
        process.env.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER = original.project;
      }
      if (original.environment === undefined) delete process.env.GC_APP_ATTEST_ENVIRONMENT;
      else process.env.GC_APP_ATTEST_ENVIRONMENT = original.environment;
      jest.resetModules();
    }
  });
});
