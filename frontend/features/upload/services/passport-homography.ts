import type { Point, DocumentQuad } from "./passport-normalization.types.ts";

export function solveDestinationToSourceHomography(quad: DocumentQuad): number[] | null {
  const destinations: Point[] = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ];
  const sources = [quad.topLeft, quad.topRight, quad.bottomRight, quad.bottomLeft];
  const matrix: number[][] = [];

  for (let index = 0; index < destinations.length; index += 1) {
    const { x: u, y: v } = destinations[index];
    const { x, y } = sources[index];
    matrix.push([u, v, 1, 0, 0, 0, -u * x, -v * x, x]);
    matrix.push([0, 0, 0, u, v, 1, -u * y, -v * y, y]);
  }

  return solveAugmentedMatrix(matrix);
}

function solveAugmentedMatrix(matrix: number[][]): number[] | null {
  const size = matrix.length;
  for (let column = 0; column < size; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < size; row += 1) {
      if (Math.abs(matrix[row][column]) > Math.abs(matrix[pivot][column])) pivot = row;
    }
    if (Math.abs(matrix[pivot][column]) < 1e-9) return null;
    [matrix[column], matrix[pivot]] = [matrix[pivot], matrix[column]];

    const divisor = matrix[column][column];
    for (let item = column; item <= size; item += 1) matrix[column][item] /= divisor;
    for (let row = 0; row < size; row += 1) {
      if (row === column) continue;
      const factor = matrix[row][column];
      for (let item = column; item <= size; item += 1) {
        matrix[row][item] -= factor * matrix[column][item];
      }
    }
  }
  return matrix.map((row) => row[size]);
}
