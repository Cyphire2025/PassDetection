import type { DocumentBoundaryEstimate } from "./passport-final.types.ts";
import { PASSPORT_FINAL_THRESHOLDS } from "./passport-final-policy.ts";

export function estimateDocumentCoverage(
  gray: Uint8Array,
  width: number,
  height: number,
): DocumentBoundaryEstimate {
  const left = strongestVerticalBoundary(gray, width, height, "left");
  const right = strongestVerticalBoundary(gray, width, height, "right");
  const top = strongestHorizontalBoundary(gray, width, height, "top");
  const bottom = strongestHorizontalBoundary(gray, width, height, "bottom");
  const minimumSupport = PASSPORT_FINAL_THRESHOLDS.documentBoundarySupport;
  const boundaries = [
    {
      boundary: left,
      outerInset: left.position / Math.max(1, width - 1),
    },
    {
      boundary: right,
      outerInset: (width - 1 - right.position) / Math.max(1, width - 1),
    },
    {
      boundary: top,
      outerInset: top.position / Math.max(1, height - 1),
    },
    {
      boundary: bottom,
      outerInset: (height - 1 - bottom.position) / Math.max(1, height - 1),
    },
  ];
  const strongBoundaries = boundaries.filter(
    ({ boundary }) => boundary.support >= minimumSupport,
  );
  const strongBoundaryCount = strongBoundaries.length;
  const missingBoundaryLikely = strongBoundaryCount === 3
    && strongBoundaries.every(({ outerInset }) => (
      outerInset <= (
        PASSPORT_FINAL_THRESHOLDS.documentBoundaryOuterInsetRatio
      )
    ));
  // Text columns and portrait edges can look like partial page boundaries.
  // Four agreeing edges provide a coverage estimate. Three are only used when
  // each detected edge sits in its expected outer zone; that evidence is kept
  // borderline unless the visible document area is definitively too small.
  if (strongBoundaryCount < 4 && !missingBoundaryLikely) {
    return {
      coverage: 1,
      strongBoundaryCount,
      missingBoundaryLikely: false,
    };
  }

  const estimatedLeft = left.support >= minimumSupport ? left.position : 0;
  const estimatedRight = right.support >= minimumSupport
    ? right.position
    : width - 1;
  const estimatedTop = top.support >= minimumSupport ? top.position : 0;
  const estimatedBottom = bottom.support >= minimumSupport
    ? bottom.position
    : height - 1;
  return {
    coverage: clamp01(
      ((estimatedRight - estimatedLeft + 1) / width)
        * ((estimatedBottom - estimatedTop + 1) / height),
    ),
    strongBoundaryCount,
    missingBoundaryLikely,
  };
}

function strongestVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "left" | "right",
): { position: number; support: number } {
  const start = side === "left" ? 1 : Math.round(width * 0.72);
  const end = side === "left" ? Math.round(width * 0.28) : width - 2;
  let best = { position: side === "left" ? 0 : width - 1, support: 0 };
  for (let x = start; x <= end; x += 1) {
    let supported = 0;
    let samples = 0;
    for (let y = Math.round(height * 0.06); y < height * 0.94; y += 3) {
      const index = y * width + x;
      if (Math.abs(gray[index + 1] - gray[index - 1]) >= 24) {
        supported += 1;
      }
      samples += 1;
    }
    const support = supported / Math.max(1, samples);
    if (support > best.support) best = { position: x, support };
  }
  return best;
}

function strongestHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "top" | "bottom",
): { position: number; support: number } {
  const start = side === "top" ? 1 : Math.round(height * 0.72);
  const end = side === "top" ? Math.round(height * 0.28) : height - 2;
  let best = { position: side === "top" ? 0 : height - 1, support: 0 };
  for (let y = start; y <= end; y += 1) {
    let supported = 0;
    let samples = 0;
    for (let x = Math.round(width * 0.05); x < width * 0.95; x += 3) {
      const index = y * width + x;
      if (
        Math.abs(gray[index + width] - gray[index - width]) >= 24
      ) {
        supported += 1;
      }
      samples += 1;
    }
    const support = supported / Math.max(1, samples);
    if (support > best.support) best = { position: y, support };
  }
  return best;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}
