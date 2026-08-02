export const DEMO_APPLICATION_ID = 'com.globalconnects.groupcompanion.demo';

export function canUseDemoMode(input: {
  requested: boolean;
  appEnv: 'development' | 'preview' | 'production';
  applicationId: string | null;
  apiHostname: string;
  isPhysicalDevice: boolean;
}): boolean {
  return (
    input.requested &&
    input.appEnv === 'development' &&
    input.applicationId === DEMO_APPLICATION_ID &&
    ['localhost', '127.0.0.1', '10.0.2.2'].includes(input.apiHostname) &&
    !input.isPhysicalDevice
  );
}
