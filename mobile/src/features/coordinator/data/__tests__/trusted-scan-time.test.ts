import { OfflineAuthorizationError } from '@/core/auth/offline-authorization';
import { offlineAuthorizationReadiness } from '@/core/auth/offline-authorization-readiness';

import {
  SCAN_CLOCK_DRIFT_WARNING_MS,
  trustedAttendanceScanTime,
  trustedScanClockDriftNotice,
} from '../trusted-scan-time';

jest.mock('@/core/auth/offline-authorization-readiness', () => ({
  offlineAuthorizationReadiness: jest.fn(),
}));

const mockedAuthorization = jest.mocked(offlineAuthorizationReadiness);

afterEach(() => {
  jest.restoreAllMocks();
});

test('uses signed trusted server time as scan evidence and wall time only for drift diagnostics', async () => {
  mockedAuthorization.mockResolvedValue({
    remainingMs: 60_000,
    trustedServerTimeMs: 1_900_000_000_123.9,
  });
  jest.spyOn(Date, 'now').mockReturnValue(1_900_000_120_123);

  await expect(trustedAttendanceScanTime()).resolves.toEqual({
    timestampMs: 1_900_000_000_123,
    deviceClockDifferenceMs: 120_000,
  });
});

test('does not replace a rollback rejection with raw device wall time', async () => {
  mockedAuthorization.mockRejectedValue(new OfflineAuthorizationError('clock_rollback'));
  jest.spyOn(Date, 'now').mockReturnValue(1_900_000_000_000);

  await expect(trustedAttendanceScanTime()).rejects.toMatchObject({ code: 'clock_rollback' });
});

test('normalizes an unavailable protected lease into a safe clock-unavailable rejection', async () => {
  mockedAuthorization.mockRejectedValue(new Error('private secure-store path'));

  await expect(trustedAttendanceScanTime()).rejects.toMatchObject({
    code: 'clock_unavailable',
  });
});

test('warns only beyond the bounded trusted-time drift threshold', () => {
  expect(trustedScanClockDriftNotice(SCAN_CLOCK_DRIFT_WARNING_MS)).toBeNull();
  expect(trustedScanClockDriftNotice(-SCAN_CLOCK_DRIFT_WARNING_MS - 1))
    .toContain('more than 5 minutes');
  expect(trustedScanClockDriftNotice(Number.NaN)).toContain('Scanning is paused');
});
