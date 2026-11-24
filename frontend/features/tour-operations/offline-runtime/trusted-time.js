import { parseRequiredInstant } from './values.js';

export function createAuthorizationRuntimeAnchor(record, payload) {
  const wallNow = Date.now();
  const performanceNow = performance.now();
  const wallElapsed = wallNow - Number(record.observedWallClockMs);
  if (!Number.isFinite(wallElapsed) || wallElapsed < -2 * 60_000) {
    throw new Error("Trusted time rollback detected.");
  }
  if (wallElapsed > Number(payload.max_suspension_seconds) * 1000) {
    throw new Error("Offline suspension exceeded its signed bound.");
  }
  const trustedAtLaunch = Math.max(
    Number(record.trustedHighWaterMs),
    parseRequiredInstant(payload.server_time) + Math.max(0, wallElapsed),
  );
  return {
    observedPerformanceMs: performanceNow,
    observedWallClockMs: wallNow,
    trustedAtLaunchMs: trustedAtLaunch,
    trustedHighWaterMs: trustedAtLaunch,
  };
}

export function resolveAuthorizationTrustedTime(authorization) {
  const { payload, runtime } = authorization;
  const monotonicElapsed = performance.now() - runtime.observedPerformanceMs;
  const wallElapsed = Date.now() - runtime.observedWallClockMs;
  if (
    !Number.isFinite(monotonicElapsed)
    || !Number.isFinite(wallElapsed)
    || monotonicElapsed < 0
    || wallElapsed < -2 * 60_000
    || Math.abs(wallElapsed - monotonicElapsed) > 2 * 60_000
  ) {
    throw new Error("Device clock changed after signed readiness was verified.");
  }
  const trusted = Math.max(
    runtime.trustedHighWaterMs,
    runtime.trustedAtLaunchMs + monotonicElapsed,
  );
  if (
    trusted - parseRequiredInstant(payload.server_time)
      > Number(payload.max_suspension_seconds) * 1000
  ) {
    throw new Error("Offline suspension exceeded its signed bound.");
  }
  if (trusted < parseRequiredInstant(payload.not_before) || trusted > parseRequiredInstant(payload.expires_at)) {
    throw new Error("Signed offline authorization expired.");
  }
  runtime.trustedHighWaterMs = Math.max(runtime.trustedHighWaterMs, Math.trunc(trusted));
  return runtime.trustedHighWaterMs;
}
