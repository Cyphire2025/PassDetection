export function toGrayscale(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): Uint8Array {
  const gray = new Uint8Array(width * height);
  for (
    let pixel = 0, offset = 0;
    pixel < gray.length;
    pixel += 1, offset += 4
  ) {
    gray[pixel] = Math.round(
      pixels[offset] * 0.299
      + pixels[offset + 1] * 0.587
      + pixels[offset + 2] * 0.114,
    );
  }
  return gray;
}

export function roundMetric(value: number): number {
  return Math.round(value * 1000) / 1000;
}
