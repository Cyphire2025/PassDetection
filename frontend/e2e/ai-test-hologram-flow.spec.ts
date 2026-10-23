import { writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";


import { testHologramSignal } from "./support/test-hologram-probe";
import { workspace, sampleHologramCadence } from "./support/test-hologram-workspace";


const WIDTH = 1440, HEIGHT = 960;

test("records actual GPU render cadence without forcing hardware quality", async ({ page }, testInfo) => {
  test.setTimeout(60000);
  await workspace(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/ai");
  await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toHaveAttribute("data-appearance", "test");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0]).toBe(1);
  // Measure actual animated frames after startup, without first opening an
  // appearance panel to select the scene that is already the default.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const result = await sampleHologramCadence(page);
  writeFileSync(testInfo.outputPath("actual-gpu-render-profile.json"), JSON.stringify(result, null, 2));
  await testInfo.attach("actual-gpu-render-profile", { contentType: "application/json", body: JSON.stringify(result) });
  expect(result.renderedFrames).toBeGreaterThan(0);
  expect(result.errors).toEqual([]); expect(result.webglError).toBe(0);
  // Cadence is diagnostic, not a claim that a software GPU represents a user's hardware.
});
