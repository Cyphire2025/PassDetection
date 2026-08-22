import {
  recordMobileMetric,
  type MobileMetricAttributes,
} from './mobile-observability';

const MAX_RECORDED_ATTENDANCE_DISCARD_COUNT = 24_000;
const MAX_RECORDED_ATTENDANCE_BATCH_COUNT = 100;
const MAX_RECORDED_ATTENDANCE_ACKNOWLEDGEMENT_MS = 120_000;
const MAX_RECORDED_ATTENDANCE_QUEUE_AGE_MS = 30 * 24 * 60 * 60 * 1_000;

export type AttendanceLocalScanResult =
  | 'queued'
  | 'already_queued'
  | 'already_confirmed'
  | 'needs_review'
  | 'previously_rejected'
  | 'capacity_reached';

export type AttendanceTerminalReasonCategory = NonNullable<
  MobileMetricAttributes['terminal_reason']
>;

export type AttendanceReconciliationOutcome = NonNullable<
  MobileMetricAttributes['reconciliation']
>;

export type AttendanceDeliveryFailureCategory = NonNullable<
  MobileMetricAttributes['delivery_failure']
>;

const ATTENDANCE_LOCAL_SCAN_RESULTS = new Set<AttendanceLocalScanResult>([
  'queued',
  'already_queued',
  'already_confirmed',
  'needs_review',
  'previously_rejected',
  'capacity_reached',
]);

const ATTENDANCE_DELIVERY_FAILURE_CATEGORIES = new Set<AttendanceDeliveryFailureCategory>([
  'rate_limited',
  'server_error',
  'timeout',
  'network',
  'other',
]);

type AttendanceDeliveryOutcome = Extract<
  MobileMetricAttributes['outcome'],
  'success' | 'partial' | 'failure' | 'timeout' | 'offline'
>;

function boundedPositiveCount(value: number, maximum: number): number | null {
  if (!Number.isSafeInteger(value) || value <= 0) return null;
  return Math.min(value, maximum);
}

function safelyRecord(operation: () => void): void {
  try {
    operation();
  } catch {
    // Optional telemetry must never alter attendance delivery correctness.
  }
}

/**
 * Projects server and local reason codes onto a fixed operational allowlist.
 * The raw value is never used as a metric name or attribute.
 */
export function attendanceTerminalReasonCategory(
  reasonCode: string | null | undefined,
): AttendanceTerminalReasonCategory {
  const reason = typeof reasonCode === 'string'
    ? reasonCode.trim().slice(0, 100).toUpperCase()
    : '';
  if (reason === 'LOCAL_QUEUE_EXPIRED') return 'local_expired';
  if (reason === 'INVALID_LOCAL_PAYLOAD') return 'local_payload';
  if (reason.includes('AUTH') || reason.includes('UNAUTHORIZED') || reason.includes('FORBIDDEN')) {
    return 'authorization';
  }
  if (reason.includes('ASSIGN') || reason.includes('WRONG_GROUP')) return 'assignment';
  if (
    reason.includes('SCANNED_AT')
    || reason.includes('OCCURRED_AT')
    || reason.includes('FUTURE')
    || reason.includes('WINDOW')
  ) return 'timestamp';
  if (reason.includes('IDEMPOTENCY')) return 'idempotency';
  if (reason.startsWith('QR_') || reason.includes('SIGNED_QR')) return 'qr_evidence';
  if (
    reason.includes('SESSION')
    || reason.includes('ACTIVITY')
    || reason.includes('ATTENDANCE_CONFLICT')
    || reason.includes('REFRESH_REQUIRED')
  ) return 'activity_state';
  if (reason === 'CLIENT_REQUEST_REJECTED') return 'client_request';
  return 'other';
}

/**
 * Records count-only evidence for a deliberate local attendance discard. The
 * boundary intentionally accepts no QR, passenger, trip, session, account, or
 * error value, so callers cannot accidentally turn bearer material into a
 * metric name or attribute.
 */
export function recordExplicitAttendanceDiscard(discardedCount: number): void {
  const count = boundedPositiveCount(discardedCount, MAX_RECORDED_ATTENDANCE_DISCARD_COUNT);
  if (count === null) return;
  safelyRecord(() => {
    recordMobileMetric(
      'attendance_discard',
      count,
      { outcome: 'success', trigger: 'manual', queue: 'attendance' },
    );
  });
}

/** Records only the bounded HTTP request-to-contract acknowledgement latency. */
export function recordAttendanceAcknowledgement(
  durationMs: number,
  outcome: AttendanceDeliveryOutcome,
): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  safelyRecord(() => {
    recordMobileMetric(
      'attendance_acknowledgement_latency',
      Math.min(durationMs, MAX_RECORDED_ATTENDANCE_ACKNOWLEDGEMENT_MS),
      { outcome, trigger: 'mutation', queue: 'attendance' },
    );
  });
}

/** Counts rows included in an actual retry POST, never their identifiers or reasons. */
export function recordAttendanceRetryOutcome(
  rowCount: number,
  outcome: AttendanceDeliveryOutcome,
): void {
  const count = boundedPositiveCount(rowCount, MAX_RECORDED_ATTENDANCE_BATCH_COUNT);
  if (count === null) return;
  safelyRecord(() => {
    recordMobileMetric('attendance_retry', count, {
      outcome,
      trigger: 'mutation',
      queue: 'attendance',
    });
  });
}

/** Counts rows entering the single authoritative refresh-and-retry recovery path. */
export function recordAttendanceRefreshRecovery(
  rowCount: number,
  outcome: AttendanceDeliveryOutcome,
): void {
  const count = boundedPositiveCount(rowCount, MAX_RECORDED_ATTENDANCE_BATCH_COUNT);
  if (count === null) return;
  safelyRecord(() => {
    recordMobileMetric('attendance_refresh_recovery', count, {
      outcome,
      trigger: 'mutation',
      queue: 'attendance',
    });
  });
}

/** Counts one completed local queue decision without any scan or identity value. */
export function recordAttendanceLocalScanResult(result: AttendanceLocalScanResult): void {
  if (!ATTENDANCE_LOCAL_SCAN_RESULTS.has(result)) return;
  safelyRecord(() => {
    recordMobileMetric('attendance_local_scan', 1, {
      attendance_result: result,
      queue: 'attendance',
      trigger: 'mutation',
    });
  });
}

/** Counts server-confirmed rows, separating new accepts from idempotent replays. */
export function recordAttendanceServerConfirmation(
  result: 'accepted' | 'already_applied',
  rowCount: number,
): void {
  if (result !== 'accepted' && result !== 'already_applied') return;
  const count = boundedPositiveCount(rowCount, MAX_RECORDED_ATTENDANCE_BATCH_COUNT);
  if (count === null) return;
  safelyRecord(() => {
    recordMobileMetric('attendance_confirmation', count, {
      attendance_result: result,
      queue: 'attendance',
      trigger: 'mutation',
    });
  });
}

/** Records the number of rows in one real attendance POST. */
export function recordAttendanceDeliveryBatchSize(
  rowCount: number,
  outcome: AttendanceDeliveryOutcome,
): void {
  const count = boundedPositiveCount(rowCount, MAX_RECORDED_ATTENDANCE_BATCH_COUNT);
  if (count === null) return;
  safelyRecord(() => {
    recordMobileMetric('attendance_delivery_batch_size', count, {
      outcome,
      queue: 'attendance',
      trigger: 'mutation',
    });
  });
}

/** Counts one failed attendance request using a fixed transport/status category. */
export function recordAttendanceDeliveryFailure(
  category: AttendanceDeliveryFailureCategory,
): void {
  if (!ATTENDANCE_DELIVERY_FAILURE_CATEGORIES.has(category)) return;
  safelyRecord(() => {
    recordMobileMetric('attendance_delivery_failure', 1, {
      delivery_failure: category,
      queue: 'attendance',
      trigger: 'mutation',
    });
  });
}

/** Counts terminal rows using only a bounded safe-reason category. */
export function recordAttendanceTerminalRejection(
  reasonCode: string | null | undefined,
  rowCount: number,
): void {
  const count = boundedPositiveCount(rowCount, MAX_RECORDED_ATTENDANCE_BATCH_COUNT);
  if (count === null) return;
  const category = attendanceTerminalReasonCategory(reasonCode);
  safelyRecord(() => {
    recordMobileMetric('attendance_terminal_rejection', count, {
      queue: 'attendance',
      terminal_reason: category,
      trigger: 'mutation',
    });
  });
}

/** Measures a valid camera callback through its completed durable queue decision. */
export function recordAttendanceCameraToLocalQueue(
  durationMs: number,
  result: AttendanceLocalScanResult | 'failure',
): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  if (result !== 'failure' && !ATTENDANCE_LOCAL_SCAN_RESULTS.has(result)) return;
  safelyRecord(() => {
    recordMobileMetric(
      'attendance_camera_to_local_queue',
      Math.min(durationMs, MAX_RECORDED_ATTENDANCE_ACKNOWLEDGEMENT_MS),
      {
        ...(result === 'failure' ? {} : { attendance_result: result }),
        outcome: result === 'failure' || result === 'capacity_reached' ? 'failure' : 'success',
        queue: 'attendance',
        trigger: 'mutation',
      },
    );
  });
}

/** Measures durable queue creation through a successful server acknowledgement. */
export function recordAttendanceQueueToConfirmation(durationMs: number): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  safelyRecord(() => {
    recordMobileMetric(
      'attendance_queue_to_confirmation',
      Math.min(durationMs, MAX_RECORDED_ATTENDANCE_QUEUE_AGE_MS),
      { outcome: 'success', queue: 'attendance', trigger: 'mutation' },
    );
  });
}

function reconciliationOutcome(
  confirmed: number,
  expected: number,
  queue: Readonly<{ awaitingConfirmation: number; needsReview: number }> | null,
): AttendanceReconciliationOutcome {
  const countsValid = Number.isSafeInteger(confirmed)
    && Number.isSafeInteger(expected)
    && confirmed >= 0
    && expected >= 0
    && confirmed <= expected;
  const queueValid = queue !== null
    && Number.isSafeInteger(queue.awaitingConfirmation)
    && Number.isSafeInteger(queue.needsReview)
    && queue.awaitingConfirmation >= 0
    && queue.needsReview >= 0;
  if (!countsValid || !queueValid) return 'unverifiable';
  if (queue.needsReview > 0) return 'needs_review';
  if (queue.awaitingConfirmation > 0) return 'pending_queue';
  return confirmed === expected ? 'ready' : 'count_mismatch';
}

/** Records count-only final-reconciliation evidence from one completed assessment. */
export function recordAttendanceReconciliationAssessment(
  confirmed: number,
  expected: number,
  queue: Readonly<{ awaitingConfirmation: number; needsReview: number }> | null,
): void {
  safelyRecord(() => {
    recordMobileMetric('attendance_reconciliation', 1, {
      queue: 'attendance',
      reconciliation: reconciliationOutcome(confirmed, expected, queue),
      trigger: 'manual',
    });
  });
}
