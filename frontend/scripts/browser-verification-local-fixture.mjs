import assert from "node:assert/strict";
import { expect } from "@playwright/test";

export const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
];
export function localOrigin(fallback = "http://127.0.0.1:3186") {
  const index = process.argv.indexOf("--url");
  const origin = new URL(index < 0 ? fallback : process.argv[index + 1]);
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname), "Only loopback test servers are allowed");
  assert.ok(["http:", "https:"].includes(origin.protocol));
  assert.equal(origin.username + origin.password + origin.search + origin.hash, "", "The local origin must not contain credentials or tokens");
  assert.equal(origin.pathname, "/");
  return origin;
}
export const json = (route, body, status = 200) => route.fulfill({ status, json: body, headers: { "cache-control": "private, no-store" } });
export async function isolatedPage(browser, origin, viewport, handler, user) {
  const context = await browser.newContext({ viewport, serviceWorkers: "block" });
  await context.routeWebSocket("**/*", socket => socket.close());
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  const diagnostics = { errors: [], blocked: [], unexpected: [], requests: [] };
  page.on("pageerror", error => diagnostics.errors.push(String(error)));
  if (user) await context.addCookies([{ name: "access_token", value: "synthetic-local-session", domain: origin.hostname, path: "/", httpOnly: true, sameSite: "Lax" }]);
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin.origin || (!url.pathname.startsWith("/api/") && !["GET", "HEAD"].includes(request.method()))) {
      diagnostics.blocked.push(`${request.method()} ${request.url()}`);
      return route.abort("blockedbyclient");
    }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    diagnostics.requests.push(`${request.method()} ${url.pathname}`);
    if (user && url.pathname === "/api/v1/auth/me") return json(route, user);
    if (user && url.pathname === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (url.pathname === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (await handler(route, request, url)) return;
    diagnostics.unexpected.push(`${request.method()} ${url.pathname}`);
    return json(route, { detail: "Unexpected request blocked by the isolated browser fixture" }, 403);
  });
  return { context, page, diagnostics };
}
export function assertClean(diagnostics) {
  assert.deepEqual(diagnostics.errors, [], "No browser runtime errors");
  assert.deepEqual(diagnostics.blocked, [], "No external or non-API mutation requests attempted");
  assert.deepEqual(diagnostics.unexpected, [], "No unhandled API calls or provider requests");
}
export async function assertNoOverflow(page, region = page.locator("main")) {
  const dimensions = await region.evaluate(element => ({
    width: innerWidth, pageWidth: document.documentElement.scrollWidth,
    clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
  }));
  assert.ok(dimensions.pageWidth <= dimensions.width + 1, "Page has no horizontal overflow");
  assert.ok(dimensions.scrollWidth <= dimensions.clientWidth + 1, "Content stays within its horizontal bounds");
  return dimensions;
}
export async function assertMessagePane(page, pane) {
  const result = await pane.evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
    x: element.getBoundingClientRect().x, width: element.getBoundingClientRect().width, viewport: innerWidth,
    whiteSpace: getComputedStyle(element).whiteSpace, overflowWrap: getComputedStyle(element).overflowWrap }));
  assert.ok(result.scrollWidth <= result.clientWidth + 1, "Message contents have no hidden horizontal scroll");
  assert.ok(result.x >= -1 && result.x + result.width <= result.viewport + 1, "Message pane stays within the viewport");
  return result;
}
export async function assertDialogBoundary(page, dialog) {
  const box = await dialog.boundingBox(), viewport = page.viewportSize();
  assert.ok(box && box.x >= -1 && box.x + box.width <= viewport.width + 1);
  assert.ok(box.y >= -1 && box.y + box.height <= viewport.height + 1);
  await assertNoOverflow(page, dialog);
  const close = dialog.getByRole("button", { name: "Close dialog", exact: true });
  const buttons = dialog.getByRole("button").filter({ visible: true });
  const last = buttons.last();
  await last.focus(); await page.keyboard.press("Tab"); await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab"); await expect(last).toBeFocused();
}
export async function syntheticHeader(page) {
  const buffer = await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 720; canvas.height = 450;
    const context = canvas.getContext("2d"); context.fillStyle = "#173b59"; context.fillRect(0, 0, 720, 450);
    context.fillStyle = "white"; context.font = "bold 32px sans-serif";
    context.fillText("Synthetic travel verification", 34, 190);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  return { name: "synthetic-header.png", mimeType: "image/png", buffer: Buffer.from(buffer, "base64") };
}
