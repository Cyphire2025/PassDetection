import { OfflineAuthorizationError } from '@/core/auth/offline-authorization';

import { attendanceScanErrorFeedback } from '../attendance-scan-error';
import { AttendanceTokenAuthorizationError } from '../attendance-token-authorization';

test.each([
  ['QR_NOT_IN_ACTIVE_ROSTER', 'current group roster'],
  ['ROSTER_EVIDENCE_UNAVAILABLE', 'Sync now'],
  ['QR_EVIDENCE_EXPIRED', 'expired'],
  ['QR_EVIDENCE_INVALID', 'invalid'],
] as const)('maps %s to actionable, fixed roster guidance', (code, expected) => {
  expect(attendanceScanErrorFeedback(new AttendanceTokenAuthorizationError(code)).message)
    .toContain(expected);
});

test('maps rollback to a persistent verified-time repair notice', () => {
  const result = attendanceScanErrorFeedback(new OfflineAuthorizationError('clock_rollback'));
  expect(result.message).toContain('Scanning is paused');
  expect(result.clockNotice).toBe(result.message);
});

test('maps an account switch race to an actionable rescan without exposing internals', () => {
  const result = attendanceScanErrorFeedback(
    Object.assign(new Error('/private/account/database'), { code: 'AUTH_CONTEXT_CHANGED' }),
  );

  expect(result.message).toContain('Confirm the active account');
  expect(result.message).not.toContain('/private/account/database');
});

test('classifies storage and network failures without reflecting sensitive payloads', () => {
  const sensitiveQr = `pdatt:${'S'.repeat(43)}`;
  const storage = attendanceScanErrorFeedback(
    Object.assign(new Error(`SQLite disk full near ${sensitiveQr}`), { name: 'SQLiteError' }),
  );
  const network = attendanceScanErrorFeedback(new TypeError(`Network failed for ${sensitiveQr}`));

  expect(storage.message).toContain('protected storage');
  expect(network.message).toContain('network is unavailable');
  expect(`${storage.message}${network.message}`).not.toContain(sensitiveQr);
});
