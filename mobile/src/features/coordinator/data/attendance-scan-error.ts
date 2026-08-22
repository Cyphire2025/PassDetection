import { ApiError } from '@/core/api/client';
import {
  OfflineAuthorizationError,
} from '@/core/auth/offline-authorization';

import {
  AttendanceTokenAuthorizationError,
} from './attendance-token-authorization';

export type AttendanceScanErrorFeedback = Readonly<{
  message: string;
  clockNotice: string | null;
}>;

const CLOCK_REPAIR =
  'Scanning is paused because verified event time is unavailable. Reconnect and sign in again; do not change the device clock.';

function offlineAuthorizationFeedback(
  error: OfflineAuthorizationError,
): AttendanceScanErrorFeedback {
  if (error.code === 'clock_rollback' || error.code === 'clock_unavailable') {
    return { message: CLOCK_REPAIR, clockNotice: CLOCK_REPAIR };
  }
  if (error.code === 'expired' || error.code === 'future') {
    const message =
      'Offline scanning authorization has expired or is not active yet. Connect and sign in again before scanning.';
    return { message, clockNotice: message };
  }
  const message =
    'Secure offline authorization could not be verified. Connect and sign in again before scanning.';
  return { message, clockNotice: message };
}

function rosterFeedback(code: AttendanceTokenAuthorizationError['code']): string {
  if (code === 'QR_NOT_IN_ACTIVE_ROSTER') {
    return 'This QR is not in the current group roster. Synchronize the group, then ask a manager if it is still missing.';
  }
  if (code === 'ROSTER_EVIDENCE_UNAVAILABLE') {
    return 'The verified roster is not ready on this device. Use Sync now before scanning.';
  }
  if (code === 'QR_EVIDENCE_EXPIRED') {
    return 'This device’s verified QR roster has expired. Connect and synchronize before scanning.';
  }
  return 'This QR’s roster evidence is invalid. Synchronize, then ask a manager if the problem continues.';
}

function errorIdentity(error: Error): string {
  return `${error.name} ${error.message}`.toLowerCase();
}

/** Maps internal failures to fixed, payload-free operator guidance. */
export function attendanceScanErrorFeedback(error: unknown): AttendanceScanErrorFeedback {
  if (error instanceof OfflineAuthorizationError) {
    return offlineAuthorizationFeedback(error);
  }
  if (error instanceof AttendanceTokenAuthorizationError) {
    return { message: rosterFeedback(error.code), clockNotice: null };
  }
  if (
    error instanceof Error
    && 'code' in error
    && error.code === 'AUTH_CONTEXT_CHANGED'
  ) {
    return {
      message: 'Your secure session changed before the scan was saved. Confirm the active account and scan again.',
      clockNotice: null,
    };
  }
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) {
      return {
        message: 'Your secure session is no longer authorized. Sign in again before scanning.',
        clockNotice: null,
      };
    }
    if (error.status === 408 || error.status === 425 || error.status >= 500) {
      return {
        message: 'The server is unavailable. Keep the QR available, check the connection, and retry.',
        clockNotice: null,
      };
    }
  }
  if (error instanceof TypeError || (error instanceof Error && error.name === 'AbortError')) {
    return {
      message: 'The network is unavailable. Check the connection, then retry the scan.',
      clockNotice: null,
    };
  }
  if (error instanceof Error) {
    const identity = errorIdentity(error);
    if (/sqlite|database|disk|storage|secure store|keystore|keychain/.test(identity)) {
      return {
        message: 'The scan was not saved to protected storage. Free device space if needed, reopen the app, and retry.',
        clockNotice: null,
      };
    }
  }
  return {
    message: 'The scan was not saved. Keep the QR available and retry; if it repeats, open Scan Issues.',
    clockNotice: null,
  };
}
