/**
 * Shared browser-camera timing and decision policy.
 *
 * Flow-specific pixel thresholds stay with their detector so passport and
 * portrait rules do not become coupled. Timing, rolling readiness, validation
 * outcomes, and Vietnam output limits are intentionally centralised here.
 */
export const CAMERA_QUALITY_POLICY = {
  liveAnalysisIntervalMs: 250,
  liveDecisionWindow: 3,
  livePassingSamples: 2,
  liveReleaseFailureSamples: 2,
  finalValidationTargetMs: 500,
  visaOutputWidth: 800,
  visaOutputHeight: 1200,
  maxVisaOutputBytes: 2 * 1024 * 1024,
} as const;

export type CameraValidationOutcome =
  | "pass"
  | "borderline"
  | "hard_failure";

export interface RollingCameraReadiness {
  samples: boolean[];
  ready: boolean;
}

/**
 * Compares compact luminance signatures instead of full frames. The first
 * sample is intentionally not stable; callers need one prior observation
 * before a rolling readiness decision can include camera steadiness.
 */
export function isCameraMotionStable(
  previousSignature: ArrayLike<number> | null,
  currentSignature: ArrayLike<number>,
  maximumMeanAbsoluteDelta = 14,
): boolean {
  if (
    !previousSignature
    || previousSignature.length === 0
    || previousSignature.length !== currentSignature.length
  ) {
    return false;
  }
  let absoluteDelta = 0;
  for (let index = 0; index < currentSignature.length; index += 1) {
    absoluteDelta += Math.abs(
      currentSignature[index] - previousSignature[index],
    );
  }
  return absoluteDelta / currentSignature.length
    <= maximumMeanAbsoluteDelta;
}

/**
 * Enters readiness after two passing samples in a complete latest-three
 * window. Once ready, a single miss is tolerated; two consecutive misses
 * release readiness so the guide does not flicker on transient detector noise.
 */
export function updateRollingCameraReadiness(
  previousSamples: readonly boolean[],
  nextSample: boolean,
  wasReady: boolean,
): RollingCameraReadiness {
  const samples = [
    ...previousSamples,
    nextSample,
  ].slice(-CAMERA_QUALITY_POLICY.liveDecisionWindow);
  const passingSamples = samples.filter(Boolean).length;
  const releaseSamples = samples.slice(
    -CAMERA_QUALITY_POLICY.liveReleaseFailureSamples,
  );
  const hasReleaseFailure = (
    releaseSamples.length === CAMERA_QUALITY_POLICY.liveReleaseFailureSamples
    && releaseSamples.every((sample) => !sample)
  );
  const ready = wasReady
    ? !hasReleaseFailure
    : samples.length === CAMERA_QUALITY_POLICY.liveDecisionWindow
      && passingSamples >= CAMERA_QUALITY_POLICY.livePassingSamples;

  return { samples, ready };
}
