import * as Device from 'expo-device';

export type DeviceRiskStatus = 'trusted' | 'compromised' | 'unknown';

let cachedRisk: Promise<DeviceRiskStatus> | null = null;

async function detectDeviceRisk(): Promise<DeviceRiskStatus> {
  try {
    return (await Device.isRootedExperimentalAsync()) ? 'compromised' : 'trusted';
  } catch {
    // Availability and detection failures are deliberately non-fatal. This signal is
    // defense-in-depth and cannot prove that a device is safe.
    return 'unknown';
  }
}

export function getDeviceRiskStatus(): Promise<DeviceRiskStatus> {
  cachedRisk ??= detectDeviceRisk();
  return cachedRisk;
}

export async function assertSensitiveOfflineStorageAllowed(): Promise<void> {
  if ((await getDeviceRiskStatus()) === 'compromised') {
    throw new Error(
      'Offline document access is disabled because this device appears to be rooted or jailbroken.',
    );
  }
}

export function resetDeviceRiskCacheForTesting(): void {
  cachedRisk = null;
}
