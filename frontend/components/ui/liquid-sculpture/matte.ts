/** A static Canvas2D fallback for dark mode, using the GPU's same colour key.
 * Kept in memory only; the original reference asset is never rewritten. */
export function paintSculptureMatte(canvas: HTMLCanvasElement, image: HTMLImageElement) {
  try {
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return false;
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const data = pixels.data;
    const corners = [0, (canvas.width - 1) * 4, (canvas.height - 1) * canvas.width * 4, (canvas.width * canvas.height - 1) * 4];
    const background = [0, 1, 2].map((channel) => corners.reduce((sum, offset) => sum + data[offset + channel], 0) / 4);
    for (let offset = 0; offset < data.length; offset += 4) {
      const distance = Math.hypot(data[offset] - background[0], data[offset + 1] - background[1], data[offset + 2] - background[2]) / 255;
      const edge = Math.min(1, Math.max(0, (distance - .018) / .112));
      const alpha = edge * edge * (3 - 2 * edge);
      for (let channel = 0; channel < 3; channel++) data[offset + channel] = Math.max(0, Math.min(255, (data[offset + channel] - background[channel] * (1 - alpha)) / Math.max(alpha, .06)));
      data[offset + 3] *= alpha;
    }
    context.putImageData(pixels, 0, 0);
    return true;
  } catch { return false; }
}
