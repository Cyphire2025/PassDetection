import type { Page } from "@playwright/test";

export async function assistantAuth(page: Page, role = "super_admin") {
  const user = { id: "b6c548e0-6e77-4d1b-b107-6799b9d31999", email: "ai@example.test",
    full_name: "Synthetic Administrator", role, agency_id: role === "super_admin" ? null : "b6c548e0-6e77-4d1b-b107-6799b9d31888",
    is_active: true, created_at: "2026-10-18T00:00:00Z", updated_at: "2026-10-18T00:00:00Z" };
  await page.context().addCookies([{ name: "access_token", value: "synthetic-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: user });
    if (path === "/api/v1/ai-assistant/availability") return route.fulfill({ json: { enabled: true, allowed: true } });
    if (path.endsWith("/auth/refresh")) return route.fulfill({ json: { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" } });
    if (path.endsWith("/notifications/feed")) return route.fulfill({ json: { items: [], unread_count: 0, next_cursor: null } });
    return route.fallback();
  });
}
