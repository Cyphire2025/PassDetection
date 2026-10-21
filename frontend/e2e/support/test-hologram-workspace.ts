import { expect, type Page } from "@playwright/test";
import { assistantAuth } from "./assistant-auth";
import { observeTestHologram, testHologramSignal } from "./test-hologram-probe";

export async function workspace(page: Page, appearance: "female" | "male" = "female") {
  await assistantAuth(page);
  await observeTestHologram(page);
  await page.route("**/api/v1/ai-assistant/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/availability")) return route.fulfill({ json: { enabled: true, allowed: true } });
    if (path.endsWith("/status")) return route.fulfill({ json: {
      configured: true, speech_configured: true, native_voice: true, voice_configured: true,
      provider: "openai", voice_provider: "openai", model: "gpt-realtime-2.1", avatar_appearance: appearance,
      account_id: "test-portrait-admin", account_scope: "super_admin", can_manage_settings: true,
      settings_revision: 1, access: "read_only",
    } });
    if (path.endsWith("/live")) return route.fulfill({ json: {
      observed_at: "2026-10-21T00:00:00Z", mcp: { connected: true, available_tools: 8, write_enabled: false },
    } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
}

export async function chooseAppearance(page: Page, name: "Test" | "Human hologram" | "Sculpture") {
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Sculpture appearance", exact: true });
  await panel.getByRole("button", { name, exact: true }).click();
  await expect(panel.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  if (name === "Test") {
    await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toHaveAttribute("data-appearance", "test");
    const scene = await page.getByTestId("particle-face-test").locator("canvas").evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
        viewportWidth: innerWidth, viewportHeight: innerHeight, pointerEvents: getComputedStyle(element).pointerEvents };
    });
    expect(scene.x).toBeCloseTo(0); expect(scene.y).toBeCloseTo(0);
    expect(scene.width).toBeCloseTo(scene.viewportWidth); expect(scene.height).toBeCloseTo(scene.viewportHeight);
    expect(scene.pointerEvents).toBe("none");
  }
}

export async function headRotation(page: Page) {
  const uniforms = (await testHologramSignal(page)).headUniforms;
  const matrix = uniforms.modelMatrix ?? uniforms.modelViewMatrix;
  expect(matrix).toHaveLength(16);
  return [0, 1, 2, 4, 5, 6, 8, 9, 10].map((index) => matrix[index]);
}

export async function landscapeCamera(page: Page) {
  const matrix = (await testHologramSignal(page)).landscapeUniforms.viewMatrix;
  expect(matrix).toHaveLength(16);
  return matrix;
}

export const rotationDistance = (a: number[], b: number[]) => Math.hypot(...a.map((value, index) => value - b[index]));
