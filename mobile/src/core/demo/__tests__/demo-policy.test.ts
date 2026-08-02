import { canUseDemoMode, DEMO_APPLICATION_ID } from '../demo-policy';

describe('demo mode build boundary', () => {
  it('allows the explicitly requested development demo package', () => {
    expect(
      canUseDemoMode({
        requested: true,
        appEnv: 'development',
        applicationId: DEMO_APPLICATION_ID,
        apiHostname: '10.0.2.2',
        isPhysicalDevice: false,
      }),
    ).toBe(true);
  });

  it.each(['preview', 'production'] as const)('fails closed in %s', (appEnv) => {
    expect(
      canUseDemoMode({
        requested: true,
        appEnv,
        applicationId: DEMO_APPLICATION_ID,
        apiHostname: '10.0.2.2',
        isPhysicalDevice: false,
      }),
    ).toBe(false);
  });

  it('does not enable demo access in the normal application package', () => {
    expect(
      canUseDemoMode({
        requested: true,
        appEnv: 'development',
        applicationId: 'com.globalconnects.groupcompanion',
        apiHostname: '10.0.2.2',
        isPhysicalDevice: false,
      }),
    ).toBe(false);
  });

  it('stays disabled unless explicitly requested', () => {
    expect(
      canUseDemoMode({
        requested: false,
        appEnv: 'development',
        applicationId: DEMO_APPLICATION_ID,
        apiHostname: '10.0.2.2',
        isPhysicalDevice: false,
      }),
    ).toBe(false);
  });

  it('does not enable on a physical device or non-loopback API host', () => {
    expect(
      canUseDemoMode({
        requested: true,
        appEnv: 'development',
        applicationId: DEMO_APPLICATION_ID,
        apiHostname: '10.0.2.2',
        isPhysicalDevice: true,
      }),
    ).toBe(false);
    expect(
      canUseDemoMode({
        requested: true,
        appEnv: 'development',
        applicationId: DEMO_APPLICATION_ID,
        apiHostname: 'api.globalconnecttravels.com',
        isPhysicalDevice: false,
      }),
    ).toBe(false);
  });
});
