const CLOCK_ROLLBACK_TOLERANCE_MS = 5 * 60 * 1000;

type AccessLease = {
  accessExpiresAt: string;
  lastServerTime: string | null;
};

export function isAccessLeaseExpired(lease: AccessLease, observedNowMs: number): boolean {
  const expiresAt = Date.parse(lease.accessExpiresAt);
  if (!Number.isFinite(expiresAt) || !Number.isFinite(observedNowMs)) return true;

  if (!lease.lastServerTime) return expiresAt <= observedNowMs;
  const serverFloor = Date.parse(lease.lastServerTime);
  if (!Number.isFinite(serverFloor)) return true;

  // A device clock substantially behind the last authenticated server clock
  // cannot be trusted to extend offline access. Fail closed while tolerating
  // ordinary clock skew.
  if (observedNowMs + CLOCK_ROLLBACK_TOLERANCE_MS < serverFloor) return true;
  return expiresAt <= Math.max(observedNowMs, serverFloor);
}
