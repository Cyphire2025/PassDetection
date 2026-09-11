/** Local-only browser verification; API responses use synthetic fixtures. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const origin = new URL(process.argv[2] ?? "http://127.0.0.1:3187");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname), "Only a loopback server is allowed");
const output = join(frontend, "test-results", "access-level-browser");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = { evidence: "Production Next build with synthetic API fixtures; no production access", cases: [] };
const owner = {
  id: "00000000-0000-4000-8000-000000000001", email: "owner@example.test", full_name: "SUPERADMIN",
  role: "super_admin", actual_role: "super_admin", can_switch_access_level: true,
  agency_id: null, access_level_agency_name: null, is_active: true,
  last_login_at: null, created_at: "2026-09-11T00:00:00Z", updated_at: "2026-09-11T00:00:00Z",
};

async function fixture(actualRole = "super_admin", viewport = { width: 1440, height: 900 }) {
  let role = actualRole;
  const requests = [];
  const errors = [];
  const context = await browser.newContext({ viewport, serviceWorkers: "block" });
  const user = () => ({ ...owner, role, actual_role: actualRole, can_switch_access_level: actualRole === "super_admin",
    agency_id: role === "super_admin" ? null : "00000000-0000-4000-8000-000000000002",
    access_level_agency_name: role === "super_admin" ? null : "Global Connect",
  });
  await context.addCookies([{ name: "access_token", value: "synthetic-local-session", domain: origin.hostname, path: "/", httpOnly: true }]);
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin.origin) return route.abort("blockedbyclient");
    if (!url.pathname.startsWith("/api/v1/")) return route.continue();
    const json = (value, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
    if (url.pathname === "/api/v1/auth/me") return json(user());
    if (url.pathname === "/api/v1/auth/refresh") return json({ status: "authenticated", user: user(), token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (url.pathname === "/api/v1/auth/access-level" && request.method() === "POST") {
      const body = request.postDataJSON();
      assert.equal(actualRole, "super_admin");
      assert.deepEqual(Object.keys(body), ["role"]);
      role = body.role;
      requests.push(role);
      return json(user());
    }
    if (url.pathname === "/api/v1/dashboard/stats") return json({ total_passports: 0, pending_review: 0, confirmed: 0, active_links: 0, recent_submissions: [] });
    if (url.pathname === "/api/v1/notifications/feed") return json({ items: [], unread_count: 0, next_cursor: null });
    if (request.method() === "GET") return json([]);
    errors.push(`Unexpected mutation ${request.method()} ${url.pathname}`);
    return json({ detail: "Local test blocked this operation" }, 403);
  });
  context.on("page", (page) => page.on("pageerror", (error) => errors.push(String(error))));
  return { context, requests, errors };
}

try {
  const { context, requests, errors } = await fixture();
  const page = await context.newPage();
  const otherTab = await context.newPage();
  await page.goto(`${origin.origin}/dashboard`);
  await otherTab.goto(`${origin.origin}/dashboard`);
  await expect(page.getByLabel("Change access level, currently Superadmin")).toBeVisible();
  await expect(otherTab.getByLabel("Change access level, currently Superadmin")).toBeVisible();
  await page.getByLabel("Change access level, currently Superadmin").click();
  await expect(page.getByRole("group", { name: "Access levels" })).toBeVisible();
  await page.screenshot({ path: join(output, "desktop-menu.png") });
  await page.getByRole("button", { name: "Staff", exact: true }).click();
  await expect(page).toHaveURL(`${origin.origin}/passports`);
  await expect(page.getByLabel("Change access level, currently Staff")).toBeVisible();
  await expect(otherTab).toHaveURL(`${origin.origin}/passports`);
  await expect(otherTab.getByLabel("Change access level, currently Staff")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Change access level, currently Staff")).toBeVisible();
  report.cases.push("Staff selection navigates to passports, persists on reload, synchronizes a second tab");

  for (const [label, expectedPath] of [["Manager", "/dashboard"], ["Coordinator", "/coordinator"], ["Superadmin", "/dashboard"]]) {
    await page.getByLabel(/Change access level, currently/).click();
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(page).toHaveURL(`${origin.origin}${expectedPath}`);
    await expect(page.getByLabel(`Change access level, currently ${label}`)).toBeVisible();
    if (label === "Coordinator") {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByLabel("Change access level, currently Coordinator").click();
      await expect(page.getByRole("button", { name: "Superadmin", exact: true })).toBeInViewport();
      await page.screenshot({ path: join(output, "coordinator-mobile-menu.png") });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.keyboard.press("Escape");
    }
    report.cases.push(`${label} selected directly with no confirmation or MFA`);
  }
  assert.deepEqual(requests, ["agency_staff", "agency_manager", "agency_coordinator", "super_admin"]);
  assert.deepEqual(errors, []);
  await context.close();

  for (const actualRole of ["agency_manager", "agency_staff", "agency_coordinator"]) {
    const ordinary = await fixture(actualRole);
    const ordinaryPage = await ordinary.context.newPage();
    const path = actualRole === "agency_coordinator" ? "/coordinator" : actualRole === "agency_staff" ? "/passports" : "/dashboard";
    await ordinaryPage.goto(`${origin.origin}${path}`);
    await expect(ordinaryPage.getByText("Restoring your secure session…")).toBeHidden();
    await expect(ordinaryPage.getByLabel(/Change access level, currently/)).toHaveCount(0);
    assert.deepEqual(ordinary.requests, []);
    assert.deepEqual(ordinary.errors, []);
    report.cases.push(`Ordinary ${actualRole} has no selector`);
    await ordinary.context.close();
  }
  await writeFile(join(output, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
