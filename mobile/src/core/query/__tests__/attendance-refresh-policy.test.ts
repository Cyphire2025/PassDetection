import { ApiError } from '@/core/api/client';

import {
  ACTIVE_ATTENDANCE_MAX_REFRESH_MS,
  ACTIVE_ATTENDANCE_MIN_REFRESH_MS,
  activeAttendanceRefreshInterval,
} from '../attendance-refresh-policy';

describe('activeAttendanceRefreshInterval', () => {
  it('stops polling when the route is not focused', () => {
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: false,
      randomValue: 0,
    })).toBe(false);
  });

  it('stops polling when there is no active attendance session', () => {
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: false,
      routeFocused: true,
      randomValue: 0,
    })).toBe(false);
  });

  it('keeps degraded repair fully jittered between thirty and sixty seconds', () => {
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: true,
      randomValue: 0,
    })).toBe(ACTIVE_ATTENDANCE_MIN_REFRESH_MS);
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: true,
      randomValue: 1,
    })).toBe(ACTIVE_ATTENDANCE_MAX_REFRESH_MS);
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: true,
      randomValue: 0.5,
    })).toBe(45_000);
  });

  it('bounds an invalid random source instead of producing an unsafe interval', () => {
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: true,
      randomValue: -10,
    })).toBe(ACTIVE_ATTENDANCE_MIN_REFRESH_MS);
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: true,
      randomValue: 10,
    })).toBe(ACTIVE_ATTENDANCE_MAX_REFRESH_MS);
  });

  it('honors a longer server Retry-After while an active route is focused', () => {
    expect(activeAttendanceRefreshInterval({
      hasActiveSession: true,
      routeFocused: true,
      error: new ApiError('Slow down', 429, 'RATE_LIMITED', 60),
      randomValue: 0,
    })).toBe(60_000);
  });
});
