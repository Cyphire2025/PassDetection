import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Matrix4, Vector3 } from "three";
import sharp from "sharp";
import { decodeHumanHead } from "../../features/ai/components/human-head-geometry";
import { prepareTestHead } from "../../features/ai/components/test-hologram-adult-head";
import type { RenderedHead } from "./test-hologram-coverage";

type Region = "forehead" | "cheeks" | "scalp";
type Density = { pixels: number; covered: number; coverage: number; largestGapPixels: number; largestGapDiameterCss: number };

/** Anatomical regions projected using the actual submitted draw transforms.
 * The source triangles define where a dense sculpture should exist; they are
 * never rendered, and cannot fill holes in the tested particle output.
 */
export function headRegionMasks(capture: RenderedHead, uniforms: Record<string, number[]>, viewport: { width: number; height: number }, appearance: "female" | "male" = "female") {
  const source = Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;
  const head = prepareTestHead(decodeHumanHead(source, appearance), appearance);
  const matrix = new Matrix4().fromArray(uniforms.projectionMatrix).multiply(new Matrix4().fromArray(uniforms.modelViewMatrix));
  const masks = Object.fromEntries(["forehead", "cheeks", "scalp"].map((name) => [name, new Uint8Array(capture.width * capture.height)])) as Record<Region, Uint8Array>;
  const project = (vertex: number) => {
    const p = new Vector3().fromArray(head.positions, vertex * 3).applyMatrix4(matrix);
    return { x: (p.x + 1) * viewport.width / 2 * capture.scaleX - capture.left,
      y: (1 - p.y) * viewport.height / 2 * capture.scaleY - capture.top };
  };
  for (let triangle = 0; triangle < head.triangles.length; triangle += 3) {
    const ids = Array.from(head.triangles.subarray(triangle, triangle + 3));
    const [x, y, z] = [0, 1, 2].map((axis) => ids.reduce((sum, vertex) => sum + head.positions[vertex * 3 + axis], 0) / 3);
    const name: Region | undefined = Math.abs(x) < .30 && y > .36 && y < .64 && z > .2 ? "forehead"
      : Math.abs(x) > .20 && Math.abs(x) < .40 && y > -.24 && y < .07 && z > .25 ? "cheeks"
        : y > .78 && z > .05 ? "scalp" : undefined;
    if (!name) continue;
    const [a, b, c] = ids.map(project), mask = masks[name];
    const edge = (p: typeof a, q: typeof a, px: number, py: number) => (px - p.x) * (q.y - p.y) - (py - p.y) * (q.x - p.x);
    const left = Math.max(0, Math.floor(Math.min(a.x, b.x, c.x))), right = Math.min(capture.width - 1, Math.ceil(Math.max(a.x, b.x, c.x)));
    const top = Math.max(0, Math.floor(Math.min(a.y, b.y, c.y))), bottom = Math.min(capture.height - 1, Math.ceil(Math.max(a.y, b.y, c.y)));
    for (let py = top; py <= bottom; py++) for (let px = left; px <= right; px++) {
      const signs = [edge(a, b, px + .5, py + .5), edge(b, c, px + .5, py + .5), edge(c, a, px + .5, py + .5)];
      if (signs.every((value) => value >= 0) || signs.every((value) => value <= 0)) mask[py * capture.width + px] = 1;
    }
  }
  // Exclude two capture pixels at anatomical region edges. The comparison is
  // about holes within the sculpture, not antialiasing at a chosen ROI border.
  for (const mask of Object.values(masks)) {
    const original = mask.slice();
    for (let y = 0; y < capture.height; y++) for (let x = 0; x < capture.width; x++) {
      if (!original[y * capture.width + x]) continue;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
        if (x + dx < 0 || x + dx >= capture.width || y + dy < 0 || y + dy >= capture.height || !original[(y + dy) * capture.width + x + dx]) mask[y * capture.width + x] = 0;
      }
    }
  }
  return masks;
}

export function renderedDensity(capture: RenderedHead, masks: ReturnType<typeof headRegionMasks>) {
  const occupancy = Buffer.from(capture.mask, "base64"), result = {} as Record<Region, Density>;
  for (const [name, mask] of Object.entries(masks) as [Region, Uint8Array][]) {
    let pixels = 0, covered = 0, largestGapPixels = 0, largestGapDiameterCss = 0;
    const seen = new Uint8Array(mask.length);
    for (let index = 0; index < mask.length; index++) {
      if (!mask[index]) continue;
      pixels++; if (occupancy[index]) { covered++; continue; }
      if (seen[index]) continue;
      const queue = [index]; seen[index] = 1;
      let left = index % capture.width, right = left, top = Math.floor(index / capture.width), bottom = top;
      for (let cursor = 0; cursor < queue.length; cursor++) {
        const current = queue[cursor], x = current % capture.width, y = Math.floor(current / capture.width);
        left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
        for (const [nx, ny] of [[x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]]) {
          const next = ny * capture.width + nx;
          if (nx < 0 || nx >= capture.width || ny < 0 || ny >= capture.height || seen[next] || !mask[next] || occupancy[next]) continue;
          seen[next] = 1; queue.push(next);
        }
      }
      largestGapPixels = Math.max(largestGapPixels, queue.length);
      largestGapDiameterCss = Math.max(largestGapDiameterCss, Math.hypot((right - left + 1) / capture.scaleX, (bottom - top + 1) / capture.scaleY));
    }
    result[name] = { pixels, covered, coverage: covered / Math.max(1, pixels), largestGapPixels, largestGapDiameterCss };
  }
  return result;
}

/** Local dark-pit contrast in the final, unmodified compositor screenshot.
 * A broad shadow is removed by the local average; dark recesses between grains
 * remain. This is a diagnostic alongside coverage, not a claim about anatomy.
 */
export async function renderedPitContrast(png: Buffer, capture: RenderedHead, masks: ReturnType<typeof headRegionMasks>) {
  const image = sharp(png).removeAlpha().greyscale();
  const original = await image.clone().raw().toBuffer({ resolveWithObject: true });
  const smooth = await image.clone().blur(3).raw().toBuffer();
  return Object.fromEntries(Object.entries(masks).map(([name, mask]) => {
    let pixels = 0, darkPixels = 0, squared = 0;
    for (let index = 0; index < mask.length; index++) {
      if (!mask[index]) continue;
      const x = Math.floor((index % capture.width + capture.left + .5) / capture.scaleX);
      const y = Math.floor((Math.floor(index / capture.width) + capture.top + .5) / capture.scaleY);
      const location = y * original.info.width + x;
      const depth = Math.max(0, smooth[location] - original.data[location]);
      pixels++; squared += depth * depth; if (depth > 14) darkPixels++;
    }
    return [name, { pixels, darkFraction: darkPixels / Math.max(1, pixels), negativeContrastRms: Math.sqrt(squared / Math.max(1, pixels)) }];
  }));
}
