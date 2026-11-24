import type { PassportImageCropRect } from "../api/passports.api";
import { rotatedImageBounds } from "./passport-image-crop-geometry";
import { clampSharpness } from "./passport-image-editor-state";

export function drawEditedImage(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  rotation: PassportImageCropRect["rotation_degrees"],
  sharpness: number,
  isInteractive: boolean,
  previewDimension: number,
) {
  const sourceWidth = image.naturalWidth;
  const sourceHeight = image.naturalHeight;
  const rotatedBounds = rotatedImageBounds(sourceWidth, sourceHeight, rotation);
  const maxPreviewDimension = isInteractive ? 800 : previewDimension;
  const scale = Math.min(
    1,
    maxPreviewDimension / Math.max(rotatedBounds.width, rotatedBounds.height),
  );
  const rotatedWidth = rotatedBounds.width;
  const rotatedHeight = rotatedBounds.height;
  canvas.width = Math.max(1, Math.round(rotatedWidth * scale));
  canvas.height = Math.max(1, Math.round(rotatedHeight * scale));
  const context = canvas.getContext("2d", { willReadFrequently: sharpness > 1.001 });
  if (!context) return;
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = isInteractive ? "medium" : "high";
  context.save();
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate((rotation * Math.PI) / 180);
  context.drawImage(
    image,
    -(sourceWidth * scale) / 2,
    -(sourceHeight * scale) / 2,
    sourceWidth * scale,
    sourceHeight * scale,
  );
  context.restore();
  if (sharpness > 1.001) applySharpnessPreview(context, canvas, sharpness);
}

function applySharpnessPreview(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  sharpness: number,
) {
  const width = canvas.width;
  const height = canvas.height;
  if (width < 3 || height < 3) return;
  const source = context.getImageData(0, 0, width, height);
  const target = context.createImageData(width, height);
  target.data.set(source.data);
  const effectiveSharpness = 3 + ((clampSharpness(sharpness) - 1) * 2);
  const strength = (effectiveSharpness - 1) * 0.22;
  const centerWeight = 1 + 4 * strength;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const offset = (y * width + x) * 4;
      const left = offset - 4;
      const right = offset + 4;
      const above = offset - width * 4;
      const below = offset + width * 4;
      for (let channel = 0; channel < 3; channel += 1) {
        target.data[offset + channel] = Math.max(0, Math.min(255,
          source.data[offset + channel] * centerWeight
          - strength * (
            source.data[left + channel]
            + source.data[right + channel]
            + source.data[above + channel]
            + source.data[below + channel]
          ),
        ));
      }
    }
  }
  context.putImageData(target, 0, 0);
}

