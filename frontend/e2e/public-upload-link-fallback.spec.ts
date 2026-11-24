import { expect, test, type Page } from "@playwright/test";

const token = "synthetic-unavailable-link";
const recoveryKey = `gct:upload-recovery:${token}`;
const recovery = { version: 1, idempotencyKey: "synthetic-private-upload-key", submissionId: "saved-draft" };
const group = {
  id: "fallback-group", name: "Reopened trip", token, status: "active",
  departure_cities: [], qualifier_relation_options: [], custom_questions: [], custom_details: [],
  require_selfie: false, allow_files_from_device: true,
};

async function interceptLink(page: Page, response: () => { status: number; body: unknown }) {
  const writes: string[] = [];
  let lookups = 0;
  await page.addInitScript(({ key, value }) => sessionStorage.setItem(key, JSON.stringify(value)), { key: recoveryKey, value: recovery });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === `/api/v1/upload-links/token/${token}`) {
      lookups += 1;
      const { status, body } = response();
      return route.fulfill({ status, json: body });
    }
    if (path === "/api/v1/returning/capabilities") return route.fulfill({ json: { enabled: false, code_label: null } });
    if (path.endsWith("/telemetry")) return route.fulfill({ json: {} });
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 400, json: { detail: "Unexpected request in unavailable-link fixture" } });
  });
  return { writes, lookups: () => lookups };
}

for (const unavailable of [
  { name: "missing", status: 404, body: { detail: "Group link was not found" }, title: "Link Unavailable" },
  { name: "closed", status: 410, body: { detail: { code: "CLIENT_GROUP_CLOSED", message: "This link is closed." } }, title: "This link is closed." },
]) {
  test(`${unavailable.name} link preserves private recovery and retries into the current entry chooser`, async ({ page }) => {
    let opened = false;
    const state = await interceptLink(page, () => opened ? { status: 200, body: group } : unavailable);
    await page.setViewportSize({ width: 320, height: 844 });
    await page.goto(`/upload/${token}`);
    const failure = page.getByRole("alert", { name: unavailable.title });
    await expect(failure).toBeVisible();
    expect(state.lookups()).toBe(1);
    await expect(page.getByRole("button", { name: /New traveller/ })).toHaveCount(0);
    expect(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)!), recoveryKey)).toEqual(recovery);
    if (unavailable.name === "closed") await expect(failure).not.toContainText("expired");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    opened = true;
    await page.getByRole("button", { name: "Check again", exact: true }).click();
    await expect(page.getByRole("button", { name: /New traveller/ })).toBeVisible();
    expect(state.lookups()).toBe(2);
    expect(state.writes).toEqual([]);
  });
}

test("temporary link failure retains recovery and explicit retry opens the current portal", async ({ page }) => {
  let connected = false;
  const state = await interceptLink(page, () => connected ? { status: 200, body: group } : { status: 503, body: { detail: "Temporary outage" } });
  await page.goto(`/upload/${token}`);
  await expect(page.getByRole("heading", { name: "Unable to open this link" })).toBeVisible();
  expect(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)!), recoveryKey)).toEqual(recovery);
  connected = true;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: /New traveller/ })).toBeVisible();
  expect(state.writes).toEqual([]);
});

test("missing metadata renders a recoverable error instead of an endless loading screen", async ({ page }) => {
  const state = await interceptLink(page, () => ({ status: 200, body: null }));
  await page.goto(`/upload/${token}`);
  await expect(page.getByRole("heading", { name: "Unable to open this link" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeEnabled();
  expect(state.writes).toEqual([]);
});
