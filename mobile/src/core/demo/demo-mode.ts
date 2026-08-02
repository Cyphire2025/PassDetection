import * as Application from 'expo-application';
import * as Device from 'expo-device';

import { env } from '@/core/config/env';

import { canUseDemoMode } from './demo-policy';

export function isDemoMode(): boolean {
  return canUseDemoMode({
    requested: env.demoModeRequested,
    appEnv: env.appEnv,
    applicationId: Application.applicationId,
    apiHostname: new URL(env.apiUrl).hostname,
    isPhysicalDevice: Device.isDevice,
  });
}

export function assertDemoMode(): void {
  if (!isDemoMode()) {
    throw new Error('Local demo access is unavailable in this application build.');
  }
}
