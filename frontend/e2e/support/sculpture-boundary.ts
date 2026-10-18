import sharp from "sharp";
import { expect, type Page } from "@playwright/test";

/** Check visible material outside each edge, not the image or a CSS border. */
export async function sculptureBoundary(page: Page, dark: boolean) {
  const panel = await page.locator("[data-image-panel]").boundingBox();
  if (!panel) throw new Error("Image panel is missing");
  const screenshot = await page.screenshot({ animations: "disabled" });
  const { data, info } = await sharp(screenshot).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const band = Math.min(32, panel.height * .12);
  const strips = [
    [panel.x + 20, panel.y - band, panel.width - 40, band - 3],
    [panel.x + panel.width + 3, panel.y + 20, band - 3, panel.height - 40],
    [panel.x + 20, panel.y + panel.height + 3, panel.width - 40, band - 3],
    [panel.x - band, panel.y + 20, band - 3, panel.height - 40],
  ];
  const material: number[] = [];
  const edgePixels: number[] = [];
  for (const [left, top, width, height] of strips) {
    let grains = 0, pixels = 0;
    for (let y = Math.max(0, Math.ceil(top)); y < Math.min(info.height, top + height); y++) {
      for (let x = Math.max(0, Math.ceil(left)); x < Math.min(info.width, left + width); x++) {
        const index = (y * info.width + x) * info.channels;
        const [r, g, b] = [data[index], data[index + 1], data[index + 2]];
        edgePixels.push(r, g, b);
        if (dark ? Math.max(r, g, b) > 95 : r < 190 && g < 185 && b < 180) grains++;
        pixels++;
      }
    }
    expect(pixels).toBeGreaterThan(300);
    expect(grains / pixels, "The existing sculpture should occupy every image edge").toBeGreaterThan(.075);
    material.push(grains / pixels);
  }
  return { screenshot, material, edgePixels: Buffer.from(edgePixels) };
}
