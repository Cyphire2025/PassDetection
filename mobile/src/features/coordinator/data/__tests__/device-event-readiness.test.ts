import NetInfo from '@react-native-community/netinfo';
import * as Battery from 'expo-battery';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';

import { loadDeviceEventReadiness } from '../device-event-readiness';

const AGENCY = '11111111-1111-4111-8111-111111111111';
const ACCOUNT = '22222222-2222-4222-8222-222222222222';
const TRIP = '33333333-3333-4333-8333-333333333333';
const runAsync = jest.fn();

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: { fetch: jest.fn() },
}));
jest.mock('expo-battery', () => ({
  BatteryState: { UNKNOWN: 0, UNPLUGGED: 1, CHARGING: 2, FULL: 3, NOT_CHARGING: 4 },
  getPowerStateAsync: jest.fn(),
}));
jest.mock('expo-file-system', () => ({
  Paths: { availableDiskSpace: 500 * 1024 * 1024 },
}));
jest.mock('@/core/api/client', () => ({ apiRequest: jest.fn() }));
jest.mock('@/core/storage/database', () => ({ openAccountDatabase: jest.fn() }));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedNetworkFetch = jest.mocked(NetInfo.fetch);
const mockedPowerState = jest.mocked(Battery.getPowerStateAsync);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.setState({
    session: {
      accessToken: 'a'.repeat(48),
      accessTokenExpiresAt: '2030-01-02T13:00:00.000Z',
      refreshTokenExpiresAt: '2030-01-03T12:00:00.000Z',
      sessionId: '44444444-4444-4444-8444-444444444444',
      networkMode: 'online',
      principal: {
        id: '55555555-5555-4555-8555-555555555555',
        accountId: ACCOUNT,
        principalType: 'coordinator',
        agencyId: AGENCY,
        passengerId: null,
        displayName: 'Coordinator',
        email: null,
        phoneNumber: null,
        forcePasswordChange: false,
      },
    },
  });
  mockedOpenDatabase.mockResolvedValue({ runAsync } as never);
  runAsync.mockResolvedValue({ changes: 1 });
  mockedPowerState.mockResolvedValue({
    batteryLevel: 0.82,
    batteryState: Battery.BatteryState.CHARGING,
    lowPowerMode: false,
  });
  mockedNetworkFetch.mockResolvedValue({
    isConnected: true,
    isInternetReachable: true,
  } as never);
  mockedApiRequest.mockResolvedValue({ status: 'alive' });
});

test('combines API, battery, storage, network, and a scoped encrypted-database write probe', async () => {
  await expect(loadDeviceEventReadiness(TRIP)).resolves.toEqual({
    apiReachable: true,
    availableStorageBytes: 500 * 1024 * 1024,
    batteryCharging: true,
    batteryLevel: 0.82,
    databaseWritable: true,
    lowPowerMode: false,
    networkReachable: true,
  });
  expect(mockedOpenDatabase).toHaveBeenCalledWith(`${AGENCY}.${ACCOUNT}`);
  expect(runAsync).toHaveBeenCalledWith(
    expect.stringContaining('UPDATE trips SET updated_at = updated_at'),
    `${AGENCY}.${ACCOUNT}`,
    TRIP,
  );
  expect(mockedApiRequest).toHaveBeenCalledWith('/health/live', expect.objectContaining({
    authenticated: false,
    retryAuthentication: false,
    timeoutMs: 5_000,
  }));
});

test('returns explicit unknown/blocked evidence when device probes fail', async () => {
  mockedPowerState.mockRejectedValueOnce(new Error('battery unavailable'));
  mockedNetworkFetch.mockRejectedValueOnce(new Error('network unavailable'));
  mockedApiRequest.mockRejectedValueOnce(new Error('api unavailable'));
  runAsync.mockRejectedValueOnce(new Error('database read only'));

  await expect(loadDeviceEventReadiness(TRIP)).resolves.toMatchObject({
    apiReachable: false,
    batteryCharging: null,
    batteryLevel: null,
    databaseWritable: false,
    lowPowerMode: null,
    networkReachable: null,
  });
});
