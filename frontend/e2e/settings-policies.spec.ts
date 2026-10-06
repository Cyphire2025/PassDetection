import { expect, test } from "@playwright/test";
import { DEFAULT_PLATFORM_SETTINGS } from "../features/settings/platform-settings-policy";

for (const role of ["agency_admin", "super_admin"] as const) {
  test(`${role} loads platform policies on demand with the correct write permission`, async ({ page }) => {
    await page.setViewportSize({ width: role === "agency_admin" ? 390 : 1440, height: 900 });
    const user = {
      id: `settings-${role}`, email: "settings@example.test", full_name: "Settings Admin",
      role, agency_id: role === "agency_admin" ? "settings-agency" : null,
      is_active: true, last_login_at: null, created_at: "2026-10-06", updated_at: "2026-10-06",
    };
    let settingsReads = 0;
    const settingsWrites: unknown[] = [];
    await page.context().addCookies([{
      name: "access_token", value: "synthetic-settings-session", domain: "127.0.0.1",
      path: "/", httpOnly: true, sameSite: "Lax",
    }]);
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/v1/auth/refresh") return route.fulfill({ json: {
        status: "authenticated", user, token_type: "bearer",
        access_token_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
      } });
      if (path === "/api/v1/auth/me") return route.fulfill({ json: user });
      if (path === "/api/v1/notifications/feed") return route.fulfill({ json: { items: [], unread_count: 0, next_cursor: null } });
      if (path === "/api/v1/admin/settings") {
        if (route.request().method() === "GET") settingsReads += 1;
        else settingsWrites.push(route.request().postDataJSON());
        return route.fulfill({ json: { ...DEFAULT_PLATFORM_SETTINGS, updated_at: "2026-10-06T12:00:00Z" } });
      }
      return route.fulfill({ json: [] });
    });
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Compact", exact: true })).toBeVisible();
    expect(settingsReads).toBe(0);
    await page.getByRole("button", { name: /Platform policies/ }).click();
    const name = page.getByLabel("Platform name");
    await expect(name).toHaveValue(DEFAULT_PLATFORM_SETTINGS.platform_name);
    expect(settingsReads).toBe(1);
    if (role === "agency_admin") {
      await expect(name).toBeDisabled();
      await expect(page.getByRole("button", { name: "Save policies" })).toBeDisabled();
      await expect(page.getByText(/Only a super administrator/)).toBeVisible();
    } else {
      await name.fill("Unsubmitted draft");
    }
    await page.getByRole("button", { name: /Appearance & navigation/ }).click();
    await page.getByRole("button", { name: /Platform policies/ }).click();
    expect(settingsReads).toBe(1);
    if (role === "super_admin") {
      await expect(name).toHaveValue("Unsubmitted draft");
      await page.getByRole("button", { name: "Save policies" }).click();
      await expect(page.getByText("Settings saved.")).toBeVisible();
      expect(settingsWrites).toEqual([expect.objectContaining({ platform_name: "Unsubmitted draft" })]);
    } else expect(settingsWrites).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
