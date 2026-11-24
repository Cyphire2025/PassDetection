import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const outputDir = resolve(process.cwd(), "../.tmp/ui-pwa-batch/screenshots");

async function setup(page: Page) {
  const user = { id: "resilience-admin", agency_id: "11111111-1111-4111-8111-111111111111", email: "resilience@example.test", full_name: "Synthetic Admin", role: "agency_admin", is_active: true, capabilities: [] };
  const errors: string[] = [];
  let statsAvailable = false;
  page.on("pageerror", error => errors.push(error.message));
  await page.context().addCookies([{ name: "access_token", value: "synthetic-resilience", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/dashboard/stats") return statsAvailable
      ? json(route, { total_passports: 47, pending_review: 3, confirmed: 44, active_links: 2, recent_submissions: [] })
      : json(route, { error: { message: "Synthetic statistics outage" } }, 503);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [{ id: "notice-1", title: "Synthetic passenger update", message: "Review the latest passenger record.", priority: "high", category: "passport", type: "passport_review", entity_type: null, entity_id: null, is_read: false, metadata: null, created_at: new Date().toISOString() }], unread_count: 1, next_cursor: null });
    if (path === "/api/v1/search") return json(route, [{ type: "group", id: "resilience-group", group_id: "resilience-group", title: "Synthetic Bali group", subtitle: "Bali", status: "active", passport_number: null, client_name: null, client_email: null, client_phone: null, group_name: "Synthetic Bali group", destination: "Bali", updated_at: null }]);
    return json(route, []);
  });
  return { errors, recoverStats: () => { statsAvailable = true; } };
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`statistics recovery and notification keyboard isolation at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const fixture = await setup(page);
    await page.goto("/dashboard");
    const summary = page.getByRole("region", { name: "Passport operations summary" });
    await expect(summary.getByText("Unavailable", { exact: true })).toHaveCount(4);
    await expect(page.getByText("Recent activity unavailable", { exact: true })).toBeVisible();
    fixture.recoverStats();
    await page.getByRole("button", { name: "Retry statistics" }).click();
    await expect(summary.getByText("47", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry statistics" })).toHaveCount(0);
    const bell = page.getByRole("button", { name: "Notifications, 1 unread" });
    await bell.click();
    const panel = page.getByRole("dialog", { name: "Notifications", exact: true });
    await expect(panel.getByText("Synthetic passenger update", { exact: true })).toBeVisible();
    await page.keyboard.press("Control+k");
    await expect.poll(() => panel.evaluate(node => node.contains(document.activeElement))).toBe(true);
    const panelBounds = await panel.boundingBox();
    expect(panelBounds!.x).toBeGreaterThanOrEqual(0);
    expect(panelBounds!.x + panelBounds!.width).toBeLessThanOrEqual(viewport.width);
    await mkdir(outputDir, { recursive: true });
    await page.screenshot({ path: resolve(outputDir, `notifications-${viewport.width}.png`), fullPage: true });
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(bell).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(fixture.errors).toEqual([]);
  });
}

test("cleared search cannot reopen a stale result from the keyboard", async ({ page }) => {
  const fixture = await setup(page);
  fixture.recoverStats();
  await page.goto("/dashboard");
  const input = page.getByRole("combobox", { name: "Search passports and groups" });
  await input.fill("Bali");
  await expect(page.getByRole("option", { name: /Synthetic Bali group/ })).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(input).toHaveAttribute("aria-expanded", "false");
  await expect(input).not.toHaveAttribute("aria-activedescendant");
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(fixture.errors).toEqual([]);
});
