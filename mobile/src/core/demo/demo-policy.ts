export const DEMO_APPLICATION_ID = 'com.globalconnects.groupcompanion.demo';
export const STANDALONE_DEMO_APPLICATION_ID = 'com.globalconnects.groupcompanion';

export function canUseDemoMode(input: {
  requested: boolean;
  appEnv: 'development' | 'preview' | 'production';
  applicationId: string | null;
  apiHostname: string;
  isPhysicalDevice: boolean;
  standalone?: boolean;
}): boolean {
  if (input.standalone) {
    return input.requested && input.appEnv === 'preview'
      && input.applicationId === STANDALONE_DEMO_APPLICATION_ID
      && input.apiHostname === 'demo.invalid';
  }
  return (
    input.requested &&
    input.appEnv === 'development' &&
    input.applicationId === DEMO_APPLICATION_ID &&
    ['localhost', '127.0.0.1', '10.0.2.2'].includes(input.apiHostname) &&
    !input.isPhysicalDevice
  );
}
