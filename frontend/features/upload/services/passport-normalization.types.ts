export interface PassportNormalizationResult {
  file: File;
  corrected: boolean;
}

export type PassportCanvasNormalizationResult = PassportNormalizationResult;

export interface Point {
  x: number;
  y: number;
}

export interface DocumentQuad {
  topLeft: Point;
  topRight: Point;
  bottomRight: Point;
  bottomLeft: Point;
}

export interface FittedLine {
  slope: number;
  intercept: number;
  support: number;
}
