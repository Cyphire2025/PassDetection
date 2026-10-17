import { canUseDemoMode, DEMO_APPLICATION_ID } from '../demo-policy';

describe('demo mode build boundary', () => {
  it.each([true, false])('allows the offline review build on physical device=%s', (isPhysicalDevice) => {
    expect(canUseDemoMode({ requested: true, standalone: true, appEnv: 'preview',
      applicationId: 'com.globalconnects.groupcompanion', apiHostname: 'demo.invalid', isPhysicalDevice })).toBe(true);
  });

  it.each([
    { requested: false }, { appEnv: 'production' as const }, { appEnv: 'development' as const },
    { apiHostname: 'tech.gctravels.com' }, { apiHostname: 'localhost' },
    { applicationId: DEMO_APPLICATION_ID }, { standalone: false },
  ])('rejects an unsafe standalone configuration: %s', (override) => {
    expect(canUseDemoMode({ requested: true, standalone: true, appEnv: 'preview',
      applicationId: 'com.globalconnects.groupcompanion', apiHostname: 'demo.invalid',
      isPhysicalDevice: true, ...override })).toBe(false);
  });

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
