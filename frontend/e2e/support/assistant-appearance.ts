import type { Page } from "@playwright/test";

/** Select the scene under test through the user's appearance controls. */
export async function selectAssistantAppearance(page: Page, name: "Sculpture" | "Human hologram" | "Test") {
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  const appearance = page.getByRole("dialog", { name: "Sculpture appearance", exact: true });
  await appearance.getByRole("button", { name, exact: true }).click();
  await appearance.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
}
