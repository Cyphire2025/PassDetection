import { recordMobileMetric } from './mobile-observability';

const MAX_MAINTENANCE_DURATION_MS = 120_000;
const MAX_MAINTENANCE_CHANGED_ROWS = 100_000;

/**
 * Records only aggregate retention evidence. The API intentionally accepts no
 * namespace, path, entity identifier, SQL, error, or storage content.
 */
export function recordStorageMaintenance(
  durationMs: number,
  changedRows: number,
  outcome: 'success' | 'failure',
): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  const boundedChanges = Number.isSafeInteger(changedRows) && changedRows >= 0
    ? Math.min(changedRows, MAX_MAINTENANCE_CHANGED_ROWS)
    : null;
  if (boundedChanges === null) return;
  try {
    recordMobileMetric(
      'storage_maintenance_duration',
      Math.min(durationMs, MAX_MAINTENANCE_DURATION_MS),
      { outcome, trigger: 'background' },
    );
    recordMobileMetric('storage_maintenance_run', 1, {
      outcome,
      trigger: 'background',
    });
    if (outcome === 'success' && boundedChanges > 0) {
      recordMobileMetric('storage_maintenance_changes', boundedChanges, {
        outcome,
        trigger: 'background',
      });
    }
  } catch {
    // Storage correctness and the original database error always win.
  }
}
