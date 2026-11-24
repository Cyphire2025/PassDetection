export type RectangularPassportFrameStatus =
  | "checking"
  | "no_document"
  | "incomplete_document"
  | "excessive_skew"
  | "not_passport_page"
  | "ready";

export interface RectangularPassportFrameResult {
  isDetected: boolean;
  confidence: number;
  visibleEdges: number;
  strongEdges: number;
  documentAreaRatio: number;
  skewDegrees: number;
  detailTileRatio: number;
  detailRowCoverage: number;
  status: RectangularPassportFrameStatus;
  lightingStatus: "good" | "too_dark" | "too_bright";
  meanLuminance: number;
  darkPixelRatio: number;
  brightPixelRatio: number;
  motionSignature: Uint8Array;
}

export interface VideoCrop {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface BoundaryEvidence {
  slope: number;
  intercept: number;
  support: number;
  segmentCoverage: number;
  averageContrast: number;
  polarityConsistency: number;
  score: number;
  strength: "strong" | "plausible";
}

export interface DocumentQuad {
  topLeft: Point;
  topRight: Point;
  bottomRight: Point;
  bottomLeft: Point;
}
