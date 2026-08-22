import { recordMobileMetric } from '../mobile-observability';
import {
  attendanceTerminalReasonCategory,
  recordAttendanceAcknowledgement,
  recordAttendanceCameraToLocalQueue,
  recordAttendanceDeliveryBatchSize,
  recordAttendanceDeliveryFailure,
  recordAttendanceLocalScanResult,
  recordAttendanceQueueToConfirmation,
  recordAttendanceReconciliationAssessment,
  recordAttendanceRefreshRecovery,
  recordAttendanceRetryOutcome,
  recordAttendanceServerConfirmation,
  recordAttendanceTerminalRejection,
  recordExplicitAttendanceDiscard,
} from '../attendance-observability';

jest.mock('../mobile-observability', () => ({ recordMobileMetric: jest.fn() }));

const mockedRecordMetric = jest.mocked(recordMobileMetric);

beforeEach(() => {
  jest.clearAllMocks();
});

test('records only a bounded count and fixed low-cardinality attributes', () => {
  recordExplicitAttendanceDiscard(7);

  expect(mockedRecordMetric).toHaveBeenCalledWith(
    'attendance_discard',
    7,
    { outcome: 'success', trigger: 'manual', queue: 'attendance' },
  );

  recordExplicitAttendanceDiscard(24_001);
  expect(mockedRecordMetric).toHaveBeenLastCalledWith(
    'attendance_discard',
    24_000,
    { outcome: 'success', trigger: 'manual', queue: 'attendance' },
  );
});

test.each([0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
  'does not emit invalid discard counts (%p)',
  (value) => {
    recordExplicitAttendanceDiscard(value);
    expect(mockedRecordMetric).not.toHaveBeenCalled();
  },
);

test('does not reinterpret a completed discard as failed when telemetry is unavailable', () => {
  mockedRecordMetric.mockImplementationOnce(() => {
    throw new Error('metrics transport unavailable');
  });

  expect(() => recordExplicitAttendanceDiscard(3)).not.toThrow();
});

test('records bounded acknowledgement, retry, and refresh-recovery evidence', () => {
  recordAttendanceAcknowledgement(1_750, 'success');
  recordAttendanceRetryOutcome(12, 'partial');
  recordAttendanceRefreshRecovery(3, 'offline');

  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'attendance_acknowledgement_latency',
    1_750,
    { outcome: 'success', trigger: 'mutation', queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'attendance_retry',
    12,
    { outcome: 'partial', trigger: 'mutation', queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    3,
    'attendance_refresh_recovery',
    3,
    { outcome: 'offline', trigger: 'mutation', queue: 'attendance' },
  );
});

test('clamps operational evidence and drops invalid numeric values', () => {
  recordAttendanceAcknowledgement(120_001, 'timeout');
  recordAttendanceRetryOutcome(101, 'failure');
  recordAttendanceRefreshRecovery(101, 'success');
  recordAttendanceAcknowledgement(Number.NaN, 'failure');
  recordAttendanceRetryOutcome(0, 'success');
  recordAttendanceRefreshRecovery(1.5, 'success');

  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'attendance_acknowledgement_latency',
    120_000,
    { outcome: 'timeout', trigger: 'mutation', queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'attendance_retry',
    100,
    { outcome: 'failure', trigger: 'mutation', queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    3,
    'attendance_refresh_recovery',
    100,
    { outcome: 'success', trigger: 'mutation', queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenCalledTimes(3);
});

test('records fixed local, confirmation, batch, and end-to-end attendance outcomes', () => {
  recordAttendanceLocalScanResult('already_confirmed');
  recordAttendanceServerConfirmation('accepted', 3);
  recordAttendanceServerConfirmation('already_applied', 2);
  recordAttendanceDeliveryBatchSize(5, 'success');
  recordAttendanceCameraToLocalQueue(125, 'queued');
  recordAttendanceQueueToConfirmation(4_500);

  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'attendance_local_scan',
    1,
    { attendance_result: 'already_confirmed', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'attendance_confirmation',
    3,
    { attendance_result: 'accepted', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    3,
    'attendance_confirmation',
    2,
    { attendance_result: 'already_applied', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    4,
    'attendance_delivery_batch_size',
    5,
    { outcome: 'success', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    5,
    'attendance_camera_to_local_queue',
    125,
    {
      attendance_result: 'queued',
      outcome: 'success',
      queue: 'attendance',
      trigger: 'mutation',
    },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    6,
    'attendance_queue_to_confirmation',
    4_500,
    { outcome: 'success', queue: 'attendance', trigger: 'mutation' },
  );
});

test('projects arbitrary rejection codes onto fixed safe categories', () => {
  const secret = 'passenger-991-signed-qr-secret';

  expect(attendanceTerminalReasonCategory('QR_REVOKED')).toBe('qr_evidence');
  expect(attendanceTerminalReasonCategory('QR_WRONG_GROUP')).toBe('assignment');
  expect(attendanceTerminalReasonCategory('ATTENDANCE_CONFLICT')).toBe('activity_state');
  expect(attendanceTerminalReasonCategory('SCANNED_AT_IN_FUTURE')).toBe('timestamp');
  expect(attendanceTerminalReasonCategory(secret)).toBe('other');

  recordAttendanceTerminalRejection(secret, 4);
  expect(mockedRecordMetric).toHaveBeenCalledWith(
    'attendance_terminal_rejection',
    4,
    { queue: 'attendance', terminal_reason: 'other', trigger: 'mutation' },
  );
  expect(JSON.stringify(mockedRecordMetric.mock.calls)).not.toContain(secret);
});

test('records only the fixed request-level delivery failure category', () => {
  recordAttendanceDeliveryFailure('server_error');
  recordAttendanceDeliveryFailure('raw-503-url' as never);

  expect(mockedRecordMetric).toHaveBeenCalledTimes(1);
  expect(mockedRecordMetric).toHaveBeenCalledWith(
    'attendance_delivery_failure',
    1,
    {
      delivery_failure: 'server_error',
      queue: 'attendance',
      trigger: 'mutation',
    },
  );
});

test.each([
  [7, 7, { awaitingConfirmation: 0, needsReview: 0 }, 'ready'],
  [6, 7, { awaitingConfirmation: 0, needsReview: 0 }, 'count_mismatch'],
  [6, 7, { awaitingConfirmation: 1, needsReview: 0 }, 'pending_queue'],
  [6, 7, { awaitingConfirmation: 0, needsReview: 1 }, 'needs_review'],
  [8, 7, { awaitingConfirmation: 0, needsReview: 0 }, 'unverifiable'],
  [7, 7, null, 'unverifiable'],
] as const)(
  'records reconciliation outcome %s/%s as %s',
  (confirmed, expected, queue, outcome) => {
    recordAttendanceReconciliationAssessment(confirmed, expected, queue);
    expect(mockedRecordMetric).toHaveBeenLastCalledWith(
      'attendance_reconciliation',
      1,
      { queue: 'attendance', reconciliation: outcome, trigger: 'manual' },
    );
  },
);

test('drops invalid operational values and clamps bounded durations and counts', () => {
  recordAttendanceLocalScanResult('secret' as never);
  recordAttendanceCameraToLocalQueue(Number.NaN, 'queued');
  recordAttendanceCameraToLocalQueue(120_001, 'failure');
  recordAttendanceQueueToConfirmation(2_592_000_001);
  recordAttendanceDeliveryBatchSize(101, 'partial');
  recordAttendanceServerConfirmation('accepted', 0);
  recordAttendanceServerConfirmation('secret' as never, 1);
  recordAttendanceTerminalRejection('QR_REVOKED', 1.5);

  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'attendance_camera_to_local_queue',
    120_000,
    { outcome: 'failure', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'attendance_queue_to_confirmation',
    2_592_000_000,
    { outcome: 'success', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    3,
    'attendance_delivery_batch_size',
    100,
    { outcome: 'partial', queue: 'attendance', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenCalledTimes(3);
});
