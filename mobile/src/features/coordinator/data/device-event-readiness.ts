import NetInfo from '@react-native-community/netinfo';
import * as Battery from 'expo-battery';
import { Paths } from 'expo-file-system';
import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';

export const EVENT_STORAGE_BLOCK_BYTES = 100 * 1024 * 1024;
export const EVENT_STORAGE_WARNING_BYTES = 250 * 1024 * 1024;
export const EVENT_BATTERY_BLOCK_LEVEL = 0.15;
export const EVENT_BATTERY_WARNING_LEVEL = 0.30;
const API_HEALTH_TIMEOUT_MS = 5_000;
const ApiLivenessSchema = z.object({ status: z.literal('alive') }).passthrough();

export type DeviceEventReadiness = Readonly<{
  apiReachable: boolean;
  availableStorageBytes: number | null;
  batteryCharging: boolean | null;
  batteryLevel: number | null;
  databaseWritable: boolean;
  lowPowerMode: boolean | null;
  networkReachable: boolean | null;
}>;

function validStorageBytes(value: number): number | null {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function validBatteryLevel(value: number): number | null {
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

export async function loadDeviceEventReadiness(tripId: string): Promise<DeviceEventReadiness> {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  const namespace = principalAccountNamespace(principal);
  const database = await openAccountDatabase(namespace);
  const [powerResult, networkResult, apiResult, writeResult] = await Promise.allSettled([
    Battery.getPowerStateAsync(),
    NetInfo.fetch(),
    apiRequest('/health/live', {
      authenticated: false,
      retryAuthentication: false,
      schema: ApiLivenessSchema,
      timeoutMs: API_HEALTH_TIMEOUT_MS,
    }),
    database.runAsync(
      `UPDATE trips SET updated_at = updated_at
        WHERE account_namespace = ? AND id = ? AND role = 'coordinator'`,
      namespace,
      tripId,
    ),
  ]);
  const power = powerResult.status === 'fulfilled' ? powerResult.value : null;
  const network = networkResult.status === 'fulfilled' ? networkResult.value : null;
  const databaseWritable = writeResult.status === 'fulfilled' && writeResult.value.changes === 1;
  return {
    apiReachable: apiResult.status === 'fulfilled',
    availableStorageBytes: validStorageBytes(Paths.availableDiskSpace),
    batteryCharging: power
      ? power.batteryState === Battery.BatteryState.CHARGING
        || power.batteryState === Battery.BatteryState.FULL
      : null,
    batteryLevel: power ? validBatteryLevel(power.batteryLevel) : null,
    databaseWritable,
    lowPowerMode: power ? power.lowPowerMode : null,
    networkReachable: network
      ? network.isConnected === true && network.isInternetReachable !== false
      : null,
  };
}
