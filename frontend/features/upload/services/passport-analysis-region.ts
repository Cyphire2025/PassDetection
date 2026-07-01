export interface PassportAnalysisBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export const PASSPORT_GUIDE_REGION = {
  leftRatio: 0.14,
  rightRatio: 0.86,
  topRatio: 0.18,
  bottomRatio: 0.82,
} as const;

/**
 * Centralizes the capture guide geometry so every analysis phase works on the
 * same region of interest.
 */
export function getPassportAnalysisBounds(width: number, height: number): PassportAnalysisBounds {
  return {
    left: Math.round(width * PASSPORT_GUIDE_REGION.leftRatio),
    right: Math.round(width * PASSPORT_GUIDE_REGION.rightRatio),
    top: Math.round(height * PASSPORT_GUIDE_REGION.topRatio),
    bottom: Math.round(height * PASSPORT_GUIDE_REGION.bottomRatio),
  };
}
