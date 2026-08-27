import {
  PhotoDownloadReconciliationGate,
  photoDownloadRuntimeBoundaryKey,
  photoDownloadWakeDelayMs,
} from '../photo-download-runtime-policy';

describe('My Photos foreground runtime policy', () => {
  it('schedules due work deterministically and rechecks long delays in bounded intervals', () => {
    const now = Date.parse('2026-08-23T10:00:00.000Z');
    expect(photoDownloadWakeDelayMs(null, now)).toBeNull();
    expect(photoDownloadWakeDelayMs('2026-08-23T09:59:59.000Z', now)).toBe(0);
    expect(photoDownloadWakeDelayMs('2026-08-23T10:00:05.000Z', now)).toBe(5_000);
    expect(photoDownloadWakeDelayMs('2026-08-23T11:00:00.000Z', now)).toBe(60_000);
  });

  it('includes account namespace even when trip and passenger locators collide', () => {
    const first = photoDownloadRuntimeBoundaryKey('tenant-a.account-a', 'trip', 'passenger');
    const second = photoDownloadRuntimeBoundaryKey('tenant-b.account-b', 'trip', 'passenger');
    expect(first).not.toBe(second);
  });

  it('does not rehash a large completed manifest on every drain event', () => {
    const gate = new PhotoDownloadReconciliationGate();
    let fullReconciliations = 0;
    for (let event = 0; event < 5_000; event += 1) {
      if (gate.requiresFullReconciliation()) {
        fullReconciliations += 1;
        gate.complete();
      }
    }
    expect(fullReconciliations).toBe(1);
  });

  it('keeps full reconciliation pending when an activation has not completed it', () => {
    const gate = new PhotoDownloadReconciliationGate();
    expect(gate.requiresFullReconciliation()).toBe(true);
    expect(gate.requiresFullReconciliation()).toBe(true);
  });
});
