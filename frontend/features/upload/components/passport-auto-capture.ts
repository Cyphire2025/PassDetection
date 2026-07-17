export const PASSPORT_AUTO_CAPTURE_STABLE_MS = 5_000;
export const PASSPORT_AUTO_CAPTURE_TICK_MS = 100;

export interface PassportAutoCaptureProgress {
  progress: number;
  elapsedMs: number;
  remainingMs: number;
  secondsRemaining: number;
  isComplete: boolean;
}

export function getPassportAutoCaptureProgress(
  stableSinceMs: number,
  nowMs: number,
  stableDurationMs = PASSPORT_AUTO_CAPTURE_STABLE_MS,
): PassportAutoCaptureProgress {
  const safeDuration = Number.isFinite(stableDurationMs) && stableDurationMs > 0
    ? stableDurationMs
    : PASSPORT_AUTO_CAPTURE_STABLE_MS;
  const elapsedMs = Math.max(0, Math.min(safeDuration, nowMs - stableSinceMs));
  const remainingMs = Math.max(0, safeDuration - elapsedMs);
  const progress = Math.max(0, Math.min(1, elapsedMs / safeDuration));

  return {
    progress,
    elapsedMs,
    remainingMs,
    secondsRemaining: Math.ceil(remainingMs / 1_000),
    isComplete: remainingMs === 0,
  };
}

export function getEmptyPassportAutoCaptureProgress(): PassportAutoCaptureProgress {
  return getPassportAutoCaptureProgress(0, 0);
}
