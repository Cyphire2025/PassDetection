import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const agencyId = "11111111-1111-4111-8111-111111111111";
const companyId = "22222222-2222-4222-8222-222222222222";
const groupId = "44444444-4444-4444-8444-444444444444";
const outputDir = resolve(process.cwd(), "../.tmp/branding-ui");
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8ZkAAAAASUVORK5CYII=", "base64");
const logo = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300"><rect width="300" height="300" fill="white"/><path d="m150 40 22 72 76 1-61 45 22 72-59-44-60 44 23-72-61-45 76-1z" fill="#075985"/><text x="150" y="270" text-anchor="middle" font-family="Arial" font-weight="bold" font-size="24" fill="#075985">NORTHSTAR</text></svg>';
const banner = '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="500"><defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="#9bc3cf"/><stop offset="1" stop-color="#dce7d8"/></linearGradient></defs><rect width="1600" height="500" fill="url(#sky)"/><circle cx="1240" cy="125" r="72" fill="#f6e9c6"/><path d="m0 420 260-300 180 150 210-210 240 260 190-140 320 240z" fill="#7e9e91"/><path d="m0 450 280-140 160 100 270-140 260 125 270-170 360 270z" fill="#527e77"/><path d="m0 450 440-35 300 25 340-45 520 40v65H0z" fill="#315f65"/></svg>';

async function setup(page: Page, options: { banner?: boolean; logo?: boolean; failFirstLogo?: boolean } = {}) {
  const errors: string[] = [];
  const mutations: string[] = [];
  let logoVersion = 1, bannerVersion = 1, companyCreates = 0, groupCreates = 0;
  let logoUrl: string | null = options.logo === false ? null : `/api/v1/branding/company-logo/${companyId}?agency_id=${agencyId}&v=logo-1`;
  let bannerUrl: string | null = options.banner ? `/api/v1/branding/group-banner/${groupId}?agency_id=${agencyId}&v=banner-1` : null;
  let companyName = "Northstar Industries";
  let revision = 3;
  let logoFailed = false;
  const company = () => ({ id: companyId, name: companyName, status: "active", external_reference: null, revision, logo_url: logoUrl, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" });
  const group = () => ({ id: groupId, name: "Bali Leadership Retreat", token: "synthetic-branding-token", agency_id: agencyId, status: "active", created_by_user_id: "branding-admin", created_at: "2026-10-01T00:00:00Z", closed_at: null, import_only: false, destination: "Bali, Indonesia", travel_date: "2026-12-07", return_date: "2026-12-10", timezone: "Asia/Kolkata", package_name: null, departure_cities: [], notes: null, company_id: companyId, company: company(), company_revision: 1, banner_url: bannerUrl });
  const user = { id: "branding-admin", agency_id: agencyId, email: "branding@example.test", full_name: "Workspace Admin", role: "agency_admin", is_active: true, capabilities: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().addCookies([{ name: "access_token", value: "synthetic-branding-test", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/companies/workspace") return json(route, { agency_id: agencyId });
    if (path === "/api/v1/companies/lookup") return json(route, { items: [company()], next_cursor: null, has_more: false });
    if (path.startsWith("/api/v1/branding/")) {
      const isLogo = path.includes("company-logo");
      if (req.method() === "GET") return route.fulfill({ contentType: "image/svg+xml", body: isLogo ? logo : banner });
      mutations.push(`${req.method()} ${path}`);
      if (isLogo && options.failFirstLogo && !logoFailed) { logoFailed = true; return json(route, { error: { message: "Synthetic upload unavailable" } }, 503); }
      const currentUrl = isLogo ? logoUrl : bannerUrl;
      const expected = req.method() === "DELETE" ? url.searchParams.get("expected_version") ?? ""
        : req.postData()?.match(/name="expected_version"\r\n\r\n([^\r\n]*)\r\n/)?.[1] ?? "";
      if (expected !== (currentUrl ? new URL(currentUrl, "https://fixture.test").searchParams.get("v") : "")) {
        return json(route, { error: { message: "This image changed. Reopen the editor and try again." } }, 409);
      }
      if (req.method() === "PUT") expect(req.postDataBuffer()?.includes(Buffer.from('name="file"'))).toBe(true);
      if (isLogo) { logoUrl = req.method() === "DELETE" ? null : `/api/v1/branding/company-logo/${companyId}?agency_id=${agencyId}&v=logo-${++logoVersion}`; revision++; }
      else bannerUrl = req.method() === "DELETE" ? null : `/api/v1/branding/group-banner/${groupId}?agency_id=${agencyId}&v=banner-${++bannerVersion}`;
      return json(route, { url: isLogo ? logoUrl : bannerUrl, revision: isLogo ? revision : null });
    }
    if (path === "/api/v1/companies" && req.method() === "POST") { companyCreates++; companyName = req.postDataJSON().name; logoUrl = null; revision = 1; return json(route, company(), 201); }
    if (path === `/api/v1/companies/${companyId}` && req.method() === "PATCH") { expect(req.postDataJSON().expected_revision).toBe(revision); companyName = req.postDataJSON().name; revision++; return json(route, company()); }
    if (path === "/api/v1/companies") return json(route, { items: [company()], next_cursor: null, has_more: false });
    if (path === "/api/v1/upload-links") {
      if (req.method() === "POST") { groupCreates++; return json(route, { ...group(), ...req.postDataJSON() }, 201); }
      return json(route, [group()]);
    }
    if (path === "/api/v1/passports/groups") return json(route, [{ ...group(), group_id: groupId, group_name: group().name, group_status: "active", company_name: companyName, company_logo_url: logoUrl, total_passports: 12, pending_review_count: 1, confirmed_count: 11, failed_count: 0, latest_submission_at: "2026-10-17T12:00:00Z" }]);
    if (path === "/api/v1/document-distribution/groups") return json(route, [{ group_id: groupId, group_name: group().name, group_status: "active", destination: group().destination, travel_date: group().travel_date, total_passengers: 12, company_name: companyName, company_logo_url: logoUrl }]);
    if (path.endsWith("/submissions-view")) return json(route, { items: [], ordered_submission_ids: [], ordered_selection_snapshot: [], group_total: 12, total: 0, page: 1, page_size: 50, total_pages: 1, returned_count: 0, cluster_boundaries_preserved: true, expiry_alerts: [] });
    if (path.endsWith("/whatsapp-links")) return json(route, { client_group_id: groupId, broadcasts: [], broadcast_count: 0, recipient_count: 0, can_manage: true });
    if (path.endsWith("/whatsapp-deliveries/tracking")) return json(route, { group_id: groupId, poll_after_seconds: null, counts: { total: 0, queued: 0, sent: 0, delivered: 0, read: 0, failed: 0, delivery_unknown: 0 }, deliveries: [] });
    if (path.endsWith("/passport-retention")) return json(route, { group_id: groupId, passport_purge_at: null, legal_hold: false });
    return json(route, []);
  });
  return { errors, mutations, companyCreates: () => companyCreates, groupCreates: () => groupCreates,
    replaceBanner: () => { bannerUrl = `/api/v1/branding/group-banner/${groupId}?agency_id=${agencyId}&v=banner-${++bannerVersion}`; } };
}

async function screenshot(page: Page, name: string) {
  await mkdir(outputDir, { recursive: true });
  await page.screenshot({ path: resolve(outputDir, name), fullPage: true, animations: "disabled" });
}

test("company logos zoom without changing group selection and return keyboard focus", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const api = await setup(page);
  await page.goto("/passports");
  const selected = page.getByRole("checkbox", { name: "Select Bali Leadership Retreat" });
  const trigger = page.getByRole("button", { name: "View Northstar Industries logo" });
  await trigger.click();
  const preview = page.getByRole("dialog", { name: "Northstar Industries logo" });
  await expect(preview).toBeVisible();
  await screenshot(page, "company-logo-preview.png");
  await preview.getByRole("img").click();
  await expect(preview).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await trigger.evaluate((element) => parseFloat(getComputedStyle(element).borderRadius) >= element.clientWidth / 2)).toBe(true);
  await expect(selected).not.toBeChecked();
  await screenshot(page, "all-groups-desktop.png");
  await trigger.click();
  await preview.click({ position: { x: 8, y: 8 } });
  await expect(preview).toHaveCount(0);
  await expect(selected).not.toBeChecked();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "View Northstar Industries logo" }).click();
  await expect(preview).toBeVisible();
  await page.keyboard.press("Escape");
  expect(api.errors).toEqual([]);
});

test("company logo retry preserves the created company and supports removal", async ({ page }) => {
  const api = await setup(page, { failFirstLogo: true });
  await page.goto("/companies");
  await page.getByRole("button", { name: "Add client company", exact: true }).click();
  const form = page.getByRole("dialog", { name: "Add client company", exact: true });
  await form.getByLabel("Client company name").fill("Summit Ventures");
  await form.locator('input[type="file"]').setInputFiles({ name: "summit-logo.png", mimeType: "image/png", buffer: png });
  await form.getByRole("button", { name: "Add client company", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  await form.getByRole("button", { name: "Add client company", exact: true }).click();
  await expect(form).toHaveCount(0);
  expect(api.companyCreates()).toBe(1);
  await page.reload();
  await expect(page.getByRole("button", { name: "View Summit Ventures logo" })).toBeVisible();
  await page.getByRole("button", { name: "Edit Summit Ventures" }).click();
  const editor = page.getByRole("dialog", { name: "Edit company / client" });
  await screenshot(page, "company-logo-editor.png");
  await editor.getByRole("button", { name: "Remove company logo" }).click();
  await editor.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole("button", { name: "View Summit Ventures logo" })).toHaveCount(0);
  expect(api.errors).toEqual([]);
});

test("group banner contains only the header and status boxes, with responsive editing", async ({ page }) => {
  const api = await setup(page, { banner: true });
  await page.clock.install();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/passports/groups/${groupId}`);
  const hero = page.getByRole("region", { name: "Group header", exact: true });
  await expect(hero.getByRole("heading", { name: "Bali Leadership Retreat" })).toBeVisible();
  await expect(hero.getByRole("region", { name: "Group passport readiness" })).toBeVisible();
  const heroBounds = await hero.boundingBox();
  const overviewBounds = await page.getByRole("region", { name: "Group overview" }).boundingBox();
  expect(heroBounds!.y + heroBounds!.height).toBeLessThan(overviewBounds!.y);
  await screenshot(page, "group-banner-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(hero.getByRole("heading")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "group-banner-mobile.png");
  await page.getByRole("button", { name: "Edit banner", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Group banner", exact: true });
  // A background refresh must not silently rebase an open image edit onto a
  // colleague's newer upload. Reopening explicitly accepts the current image.
  api.replaceBanner();
  const refreshed = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/passports/groups");
  await page.clock.fastForward(31_000);
  await refreshed;
  await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => done())));
  await editor.getByRole("button", { name: "Remove group banner" }).click();
  await editor.getByRole("button", { name: "Save banner", exact: true }).click();
  await expect(editor.getByRole("alert")).toContainText("image changed");
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Edit banner", exact: true }).click();
  await editor.getByRole("button", { name: "Remove group banner" }).click();
  await editor.getByRole("button", { name: "Save banner", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(hero).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add banner", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add banner", exact: true }).click();
  await editor.locator('input[type="file"]').setInputFiles({ name: "bali.png", mimeType: "image/png", buffer: png });
  api.replaceBanner();
  const addedElsewhere = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/passports/groups");
  await page.clock.fastForward(31_000);
  await addedElsewhere;
  await expect(editor).toBeVisible();
  await expect(editor.getByText("bali.png", { exact: true })).toBeVisible();
  await editor.getByRole("button", { name: "Save banner", exact: true }).click();
  await expect(editor.getByRole("alert")).toContainText("image changed");
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Edit banner", exact: true }).click();
  await editor.locator('input[type="file"]').setInputFiles({ name: "bali.png", mimeType: "image/png", buffer: png });
  await editor.getByRole("button", { name: "Save banner", exact: true }).click();
  await expect(hero).toBeVisible();
  await page.reload();
  await expect(hero).toBeVisible();
  expect(api.errors).toEqual([]);
});

test("both document distribution categories show the company logo", async ({ page }) => {
  const api = await setup(page);
  for (const category of ["visa", "flight-tickets"]) {
    await page.goto(`/documents/distribution/${category}`);
    await page.getByRole("button", { name: "View Northstar Industries logo" }).click();
    await expect(page.getByRole("dialog", { name: "Northstar Industries logo" })).toBeVisible();
    await page.keyboard.press("Escape");
    if (category === "visa") await screenshot(page, "visa-company-logo.png");
  }
  expect(api.errors).toEqual([]);
});

test("a banner can be uploaded while creating an optional import group", async ({ page }) => {
  const api = await setup(page);
  await page.goto("/upload-links");
  await page.getByRole("button", { name: "Create Group Link", exact: true }).click();
  const form = page.getByRole("dialog", { name: "Create Upload Link", exact: true });
  await form.getByRole("radio", { name: /^Import data/ }).check();
  await form.getByRole("button", { name: /Select a company/ }).click();
  await form.getByRole("option", { name: "Northstar Industries" }).click();
  await form.getByRole("textbox", { name: "Group Name", exact: true }).fill("Summer Retreat");
  await form.getByRole("textbox", { name: "Destination", exact: true }).fill("Bali");
  await form.getByLabel(/Travel\/Departure Date/).fill("2026-12-07");
  await form.getByLabel(/Return Date/).fill("2026-12-10");
  await form.locator('input[type="file"]').setInputFiles({ name: "bali-banner.png", mimeType: "image/png", buffer: png });
  await form.getByRole("button", { name: "Create Group", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Group Created", exact: true })).toBeVisible();
  expect(api.groupCreates()).toBe(1);
  expect(api.mutations).toContain(`PUT /api/v1/branding/group-banner/${groupId}`);
  expect(api.errors).toEqual([]);
});
