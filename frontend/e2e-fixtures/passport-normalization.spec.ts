import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

let runtime = "";
test.beforeAll(async () => {
  const { build } = await import("vite");
  const bundled = await build({
    configFile: false, logLevel: "error",
    build: { write: false, minify: false, lib: { entry: resolve(__dirname, "../features/upload/services/passport-perspective-correction.ts"), formats: ["iife"], name: "PassportNormalization" } },
  });
  const outputs = Array.isArray(bundled) ? bundled : [bundled];
  const output = outputs.flatMap(result => "output" in result ? result.output : []).find(result => result.type === "chunk");
  if (!output || output.type !== "chunk") throw new Error("Passport normalization browser bundle was not produced");
  runtime = output.code;
});

for (const shape of ["aligned", "skewed"] as const) {
test(`rectifies a detailed ${shape} synthetic page and preserves an undecidable source`, async ({ page }) => {
  await page.goto("about:blank");
  await page.addScriptTag({ content: runtime });
  const result = await page.evaluate(async (shape) => {
    const normalizer = (window as unknown as { PassportNormalization: { normalizePassportCanvasCapture: (canvas: HTMLCanvasElement, name: string, side: "front" | "back") => Promise<{ file: File; corrected: boolean }>; normalizePassportFile: (file: File) => Promise<{ file: File; corrected: boolean }> } }).PassportNormalization;
    const canvas = document.createElement("canvas");
    canvas.width = 1400;
    canvas.height = 1000;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#111111";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ddd6c6";
    ctx.beginPath();
    if (shape === "aligned") ctx.rect(90, 70, 1220, 860);
    else { ctx.moveTo(90, 70); ctx.lineTo(1310, 90); ctx.lineTo(1290, 930); ctx.lineTo(100, 910); ctx.closePath(); }
    ctx.fill();
    ctx.fillStyle = "#77716a";
    ctx.fillRect(140, 130, 310, 460);
    ctx.fillStyle = "#242629";
    for (let y = 150; y < 690; y += 38) for (let x = 530; x < 1200; x += 36) ctx.fillRect(x, y, 20, 9);
    for (let y = 750; y < 860; y += 28) for (let x = 150; x < 1220; x += 29) ctx.fillRect(x, y, 16, 8);
    const corrected = await normalizer.normalizePassportCanvasCapture(canvas, "synthetic-page.png", "front");
    const image = await createImageBitmap(corrected.file);
    const dimensions = [image.width, image.height];
    image.close();
    const undecidable = document.createElement("canvas");
    undecidable.width = 400; undecidable.height = 240;
    undecidable.getContext("2d")!.fillRect(0, 0, 400, 240);
    const preserved = await normalizer.normalizePassportCanvasCapture(undecidable, "undecidable.png", "back");
    const original = new File(["synthetic non-image"], "document.pdf", { type: "application/pdf" });
    const rejected = await normalizer.normalizePassportFile(original);
    return { corrected: corrected.corrected, dimensions, name: corrected.file.name, mime: corrected.file.type, bytes: corrected.file.size, undecidableCorrected: preserved.corrected, originalFilePreserved: rejected.file === original && !rejected.corrected };
  }, shape);
  expect(result.corrected, JSON.stringify(result)).toBe(true);
  expect(result.dimensions[0]).toBeGreaterThan(1100);
  expect(result.dimensions[0]).toBeLessThan(1400);
  expect(result.dimensions[1]).toBeGreaterThan(700);
  expect(result.dimensions[1]).toBeLessThan(1000);
  expect(result.name).toBe("synthetic-page.jpg");
  expect(result.mime).toBe("image/jpeg");
  expect(result.bytes).toBeGreaterThan(10_000);
  expect(result.undecidableCorrected).toBe(false);
  expect(result.originalFilePreserved).toBe(true);
});
}
