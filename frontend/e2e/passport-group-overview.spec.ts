import { expect, test, type Page, type Route } from "@playwright/test";

const groupId = "compact-overview-group";
const group = {
  group_id: groupId, group_name: "Dubai October Delegates", group_status: "active",
  total_passports: 0, pending_review_count: 0, confirmed_count: 0, failed_count: 0,
  latest_submission_at: null, destination: "Dubai", travel_date: "2026-10-22",
  return_date: "2026-10-28", timezone: "Asia/Dubai", package_name: null,
  departure_cities: [], notes: null, custom_questions: [], custom_details: [],
};

async function setup(page: Page, options: { importOnly?: boolean; empty?: boolean; unavailable?: boolean } = {}) {
  const errors: string[] = [];
  const mutations: string[] = [];
  const user = {
    id: "overview-admin", email: "overview@example.test", full_name: "Overview Admin",
    role: "agency_admin", agency_id: "overview-agency", is_active: true, capabilities: [],
  };
  page.on("pageerror", error => errors.push(error.message));
  await page.context().addCookies([{
    name: "access_token", value: "isolated-overview-test", domain: "127.0.0.1",
    path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({
    status, contentType: "application/json", body: JSON.stringify(body),
  });
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/refresh") return json(route, {
      status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z",
    });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/passports/groups") return json(route, [{ ...group, import_only: options.importOnly ?? false }]);
    if (path.endsWith("/submissions-view")) return json(route, {
      items: [], ordered_submission_ids: [], ordered_selection_snapshot: [],
      group_total: 0, total: 0, page: 1, page_size: 50, total_pages: 1,
      returned_count: 0, cluster_boundaries_preserved: true,
      expiry_alerts: options.empty ? [] : [{
        submission_id: "expiry-traveller", client_name: "Traveller needing renewal",
        passport_number: "X1234567", date_of_expiry: "2027-01-22",
      }],
    });
    if (path.endsWith("/whatsapp-links")) return options.unavailable
      ? json(route, { detail: "Fixture unavailable" }, 503)
      : json(route, {
        client_group_id: groupId, can_manage: true, recipient_count: options.empty ? 0 : 707,
        broadcast_count: options.empty ? 0 : 1,
        broadcasts: options.empty ? [] : [{
          id: "linked-broadcast", name: "Dubai October Delegates", recipient_count: 707,
          match_fields: ["name", "phone_number"],
        }],
      });
    if (path.endsWith("/whatsapp-deliveries/tracking")) return options.unavailable
      ? json(route, { detail: "Fixture unavailable" }, 503)
      : json(route, {
        group_id: groupId, poll_after_seconds: null,
        counts: options.empty
          ? { total: 0, queued: 0, sent: 0, delivered: 0, read: 0, failed: 0, delivery_unknown: 0 }
          : { total: 10, queued: 0, sent: 2, delivered: 4, read: 1, failed: 2, delivery_unknown: 1 },
        deliveries: options.empty ? [] : [{
          delivery_id: "accepted", passenger_id: null, passenger_name: "Sample Traveller",
          passport_number: null, document_type: "visa", document_filename: "visa.pdf",
          phone_number: "+919900001234", status: "submitted", error_message: null,
          status_updated_at: "2026-09-29T00:00:00Z",
        }],
      });
    if (request.method() === "GET") return json(route, []);
    mutations.push(`${request.method()} ${path}`);
    return json(route, { detail: "Unexpected mutation in overview fixture" }, 400);
  });
  return { errors, mutations };
}

for (const width of [1440, 768, 390]) {
  test(`compact overview and accessible disclosures at ${width}px`, async ({ page }, testInfo) => {
    const state = await setup(page);
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/passports/groups/${groupId}`);
    const overview = page.getByRole("region", { name: "Group overview", exact: true });
    await expect(overview.getByRole("heading", { name: "Trip details", exact: true })).toBeVisible();
    await expect(overview.getByRole("heading", { name: "WhatsApp broadcasts", exact: true })).toBeVisible();
    await expect(overview.getByRole("heading", { name: "Document deliveries", exact: true })).toBeVisible();
    await expect(overview.getByText("5 of 10 delivered")).toBeVisible();
    const trip = await overview.getByRole("heading", { name: "Trip details", exact: true }).boundingBox();
    const whatsapp = await overview.getByRole("heading", { name: "WhatsApp broadcasts", exact: true }).boundingBox();
    const documents = await overview.getByRole("heading", { name: "Document deliveries", exact: true }).boundingBox();
    if (width === 1440) {
      expect(Math.abs(trip!.y - whatsapp!.y)).toBeLessThan(2);
      expect(Math.abs(trip!.y - documents!.y)).toBeLessThan(2);
      expect((await overview.boundingBox())!.height).toBeLessThan(300);
    } else if (width === 390) {
      expect(whatsapp!.y).toBeGreaterThan(trip!.y);
      expect(documents!.y).toBeGreaterThan(whatsapp!.y);
    }
    const expiry = page.getByRole("button", { name: /Passport Expiry Alerts/ });
    await expect(expiry).toHaveAttribute("aria-expanded", "false");
    expect((await expiry.boundingBox())!.height).toBeLessThan(110);
    await expect(page.getByRole("region", { name: "Passports with expiry alerts" })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`overview-${width}.png`), fullPage: true, animations: "disabled" });

    const tripToggle = overview.getByRole("button", { name: "Show details", exact: true });
    await tripToggle.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("region", { name: "Destination and trip details" })).toBeVisible();
    await overview.getByRole("button", { name: "Hide details", exact: true }).click();
    const recent = overview.locator("summary").filter({ hasText: "Recent delivery updates" });
    await recent.focus();
    await page.keyboard.press("Enter");
    await expect(overview.getByText("Accepted by WhatsApp")).toBeVisible();
    await recent.click();
    await expiry.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: /Traveller needing renewal/ })).toBeVisible();
    await expect(expiry).toHaveAttribute("aria-expanded", "true");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(state.errors).toEqual([]);
    expect(state.mutations).toEqual([]);
  });
}

test("import-only empty groups keep relevant cards and omit expiry alerts", async ({ page }) => {
  await setup(page, { importOnly: true, empty: true });
  await page.goto(`/passports/groups/${groupId}`);
  const overview = page.getByRole("region", { name: "Group overview", exact: true });
  await expect(overview.getByRole("heading", { name: "Trip details", exact: true })).toBeVisible();
  await expect(overview.getByText("No document broadcasts sent yet")).toBeVisible();
  await expect(overview.getByRole("heading", { name: "WhatsApp broadcasts", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Passport Expiry Alerts/ })).toHaveCount(0);
});

test("unavailable tracking is shown as an error rather than an empty result", async ({ page }) => {
  await setup(page, { unavailable: true });
  await page.goto(`/passports/groups/${groupId}`);
  const overview = page.getByRole("region", { name: "Group overview", exact: true });
  await expect(overview.getByRole("alert")).toHaveCount(2, { timeout: 20_000 });
  await expect(overview.getByText("No document broadcasts sent yet")).toHaveCount(0);
  await expect(overview.getByText("No WhatsApp broadcasts linked")).toHaveCount(0);
});
