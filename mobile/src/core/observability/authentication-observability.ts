import { recordMobileMetric } from './mobile-observability';

const MAX_AUTHENTICATION_QUARANTINE_DEPTH = 100;

function safelyRecord(operation: () => void): void {
  try {
    operation();
  } catch {
    // Authentication correctness must never depend on optional telemetry.
  }
}

/** Counts a completed local authentication-lock attempt without an account identifier. */
export function recordAuthenticationLockOutcome(outcome: 'success' | 'failure'): void {
  if (outcome !== 'success' && outcome !== 'failure') return;
  safelyRecord(() => {
    recordMobileMetric('authentication_lock', 1, { outcome, trigger: 'mutation' });
  });
}

/** Records only the aggregate number of namespaces still fenced at bootstrap. */
export function recordAuthenticationQuarantineDepth(count: number): void {
  if (!Number.isSafeInteger(count) || count < 0) return;
  safelyRecord(() => {
    recordMobileMetric(
      'authentication_quarantine_depth',
      Math.min(count, MAX_AUTHENTICATION_QUARANTINE_DEPTH),
      { trigger: 'startup' },
    );
  });
}
