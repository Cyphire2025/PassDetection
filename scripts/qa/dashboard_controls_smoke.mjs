/** UI-only controls on the isolated synthetic Docker stack. Never send or save policies. */
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { startReview } from "./dashboard_visual_review.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const output = join(root, "outputs/dashboard-qa/controls");
const fixture = JSON.parse(await readFile(join(root, "outputs/dashboard-qa/synthetic-seed.json"), "utf8"));
const review = await startReview({ headed: false });
const { page, context, browser } = review;
const results = [];
const blockedWrites = [];
const previews = [];
const apiErrors = [];
page.on("response", response => {
  const url = new URL(response.url());
  if (url.pathname.startsWith("/api/v1/") && response.status() >= 400) apiErrors.push({ path: url.pathname, status: response.status() });
});
await mkdir(output, { recursive: true });
await page.emulateMedia({ reducedMotion: "no-preference" });
page.setDefaultTimeout(15_000);
await context.route("**/api/v1/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const isRead = ["GET", "HEAD", "OPTIONS"].includes(request.method());
  const isSessionRenewal = url.pathname === "/api/v1/auth/refresh";
  const isMessagePreview = request.method() === "POST" && /\/whatsapp\/.*\/preview$/.test(url.pathname);
  if (isMessagePreview) previews.push(url.pathname);
  if (isRead || isSessionRenewal || isMessagePreview) return route.fallback();
  blockedWrites.push({ method: request.method(), path: url.pathname });
  return route.abort("blockedbyclient");
});

async function check(name, action) {
  try {
    const evidence = await action();
    results.push({ name, status: "passed", evidence });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, status: "failed", error: error.stack });
    await screenshot(`failed-${name.replaceAll(/[^a-z]+/g, "-")}`).catch(() => {});
    process.exitCode = 1;
    console.error(`FAIL ${name}: ${error.message}`);
  }
}
async function expectAttribute(locator, name, value) {
  await locator.evaluate((node, { name, value }) => new Promise((resolve, reject) => {
    const deadline = Date.now() + 10_000;
    const poll = () => {
      if (node.getAttribute(name) === value) resolve();
      else if (Date.now() > deadline) reject(new Error(`${name} did not become ${value}`));
      else setTimeout(poll, 50);
    };
    poll();
  }), { name, value });
}
async function screenshot(name) {
  await page.screenshot({ path: join(output, `${name}.png`) });
}
async function openSettings() {
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await page.getByRole("group", { name: "Table density", exact: true }).waitFor();
}
const shell = page.locator("[data-dashboard-shell]");
const storedPreferences = () => page.evaluate(() => JSON.parse(localStorage.getItem("passdetection-dashboard-preferences") ?? "null"));

try {
  let initialPadding;
  await check("baseline table rendering", async () => {
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    await page.locator("main tbody td").first().waitFor();
    initialPadding = await page.locator("main tbody td").first().evaluate(node => getComputedStyle(node).paddingTop);
    return { paddingTop: initialPadding };
  });
  await check("appearance controls change rendered preferences", async () => {
    await openSettings();
    await page.getByRole("group", { name: "Table density", exact: true }).getByRole("button", { name: "Compact", exact: true }).click();
    await page.getByRole("group", { name: "Workspace width", exact: true }).getByRole("button", { name: "Focused", exact: true }).click();
    await page.getByRole("group", { name: "Text size", exact: true }).getByRole("button", { name: "Larger", exact: true }).click();
    await page.getByRole("switch", { name: "Compact navigation", exact: true }).click();
    await page.getByRole("switch", { name: "Reduce motion", exact: true }).click();
    await expectAttribute(shell, "data-density", "compact");
    await expectAttribute(shell, "data-text-size", "large");
    await expectAttribute(shell, "data-reduce-motion", "true");
    await page.getByRole("button", { name: "Expand sidebar", exact: true }).waitFor();
    const rendered = await page.evaluate(() => ({
      contentMaxWidth: getComputedStyle(document.querySelector(".dashboard-content")).maxWidth,
      sidebarWidth: document.querySelector("aside").getBoundingClientRect().width,
      transitionDuration: getComputedStyle(document.querySelector("aside")).transitionDuration,
      helperFontSize: getComputedStyle(document.querySelector(".workspace-page-header p.text-sm")).fontSize,
    }));
    assert.equal(rendered.contentMaxWidth, "1152px");
    assert.equal(rendered.sidebarWidth, 76);
    assert.equal(rendered.helperFontSize, "15.2px");
    assert.ok(Number.parseFloat(rendered.transitionDuration) <= 0.001);
    await screenshot("appearance-modified");
    return { ...rendered, preferences: await storedPreferences() };
  });
  await check("all appearance preferences survive reload", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await expectAttribute(shell, "data-density", "compact");
    await expectAttribute(shell, "data-text-size", "large");
    await expectAttribute(shell, "data-reduce-motion", "true");
    await expectAttribute(page.getByRole("switch", { name: "Compact navigation", exact: true }), "aria-checked", "true");
    await expectAttribute(page.getByRole("group", { name: "Workspace width", exact: true }).getByRole("button", { name: "Focused", exact: true }), "aria-pressed", "true");
    const saved = await storedPreferences();
    assert.deepEqual(saved.state, { density: "compact", contentWidth: "focused", textSize: "large", reduceMotion: true, sidebarCollapsed: true });
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    await page.locator("main tbody td").first().waitFor();
    const paddingTop = await page.locator("main tbody td").first().evaluate(node => getComputedStyle(node).paddingTop);
    assert.ok(Number.parseFloat(paddingTop) < Number.parseFloat(initialPadding));
    return { saved, tablePaddingTop: paddingTop, originalTablePaddingTop: initialPadding };
  });
  await check("settings sections render without policy mutations", async () => {
    await openSettings();
    for (const [section, content] of [["Platform policies", "Platform name"], ["Account & security", "Your account"], ["Data administration", "Delete All Data"], ["Appearance & navigation", "Table density"]]) {
      await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: new RegExp(`^${section.replaceAll("&", "&")}`) }).click();
      await page.getByText(content, { exact: true }).first().waitFor();
      await screenshot(`settings-${section.toLowerCase().replaceAll(/[^a-z]+/g, "-")}`);
    }
    await page.getByRole("button", { name: "Reset appearance", exact: true }).click();
    await expectAttribute(shell, "data-density", "comfortable");
    await page.getByRole("button", { name: "Collapse sidebar", exact: true }).waitFor();
    return { reset: await storedPreferences() };
  });
  await check("global search finds the synthetic passenger", async () => {
    const search = page.getByRole("combobox", { name: "Search passports and groups" });
    await search.fill("Browser Passenger 1");
    const result = page.getByRole("option").filter({ hasText: "Browser Passenger 1" }).first();
    await result.waitFor();
    await screenshot("global-search-passenger");
    const label = await result.innerText();
    await result.click();
    await page.waitForURL(`**/passports/${fixture.passenger_ids[0]}`);
    await page.getByRole("heading", { name: "Browser Passenger 1", exact: true }).waitFor();
    return { result: label, pathname: new URL(page.url()).pathname };
  });
  await check("passport selections survive successive searches", async () => {
    await page.goto(`/passports/groups/${fixture.group_id}`, { waitUntil: "domcontentloaded" });
    const search = page.getByRole("textbox", { name: "Search group passengers" });
    await search.waitFor();
    const first = page.getByRole("checkbox", { name: "Select Browser Passenger 1", exact: true });
    await first.check();
    await search.fill("Browser Passenger 2");
    await page.getByRole("checkbox", { name: "Select Browser Passenger 2", exact: true }).check();
    await page.getByText("2 selected", { exact: true }).waitFor();
    await search.fill("no-matching-person");
    await page.getByText("2 selected", { exact: true }).waitFor();
    await search.fill("");
    await first.waitFor();
    assert.equal(await first.isChecked(), true);
    assert.equal(await page.getByRole("checkbox", { name: "Select Browser Passenger 2", exact: true }).isChecked(), true);
    await screenshot("passport-selection-after-search");
    await page.getByRole("button", { name: "Clear selection", exact: true }).click();
    assert.equal(await first.isChecked(), false);
    return { retainedAcrossSearches: 2, explicitlyCleared: true };
  });
  await check("WhatsApp recipient roster finds formatted phone numbers", async () => {
    await page.goto("/whatsapp", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Open actions for QA Travel Updates", exact: true }).click();
    await page.getByRole("button", { name: "Recipient List", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Recipient List - QA Travel Updates", exact: true });
    const search = dialog.getByRole("searchbox", { name: "Search current recipients" });
    await search.fill("(202) 555-0102");
    await dialog.getByText("QA Blake", { exact: true }).waitFor();
    await dialog.getByText("QA Avery", { exact: true }).waitFor({ state: "hidden" });
    await screenshot("whatsapp-formatted-phone-search");
    await search.fill("");
    await dialog.getByText("QA Avery", { exact: true }).waitFor();
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden" });
    return { query: "(202) 555-0102", matchedName: "QA Blake" };
  });
  await check("WhatsApp custom recipient selections survive filtering", async () => {
    await page.getByRole("button", { name: "Open actions for QA Travel Updates", exact: true }).click();
    await page.getByRole("button", { name: "Send Passport Link", exact: true }).click();
    const dialog = page.getByRole("dialog").filter({ has: page.getByRole("radio", { name: "Custom select", exact: true }) });
    await dialog.getByRole("radio", { name: "Custom select", exact: true }).check();
    await dialog.getByRole("button", { name: "Clear", exact: true }).click();
    const search = dialog.getByRole("searchbox", { name: "Search recipients by name or phone" });
    await search.fill("Avery");
    await dialog.getByRole("checkbox", { name: /QA Avery/ }).check();
    await search.fill("0102");
    await dialog.getByRole("button", { name: "Select matching", exact: true }).click();
    await dialog.getByText("2 recipients selected", { exact: true }).waitFor();
    await search.fill("Casey");
    await dialog.getByText("2 recipients selected", { exact: true }).waitFor();
    await search.fill("");
    assert.equal(await dialog.getByRole("checkbox", { name: /QA Avery/ }).isChecked(), true);
    assert.equal(await dialog.getByRole("checkbox", { name: /QA Blake/ }).isChecked(), true);
    assert.equal(await dialog.getByRole("checkbox", { name: /QA Casey/ }).isChecked(), false);
    assert.equal(await dialog.locator('button[type="submit"]').isDisabled(), true);
    await screenshot("whatsapp-selection-after-search");
    await dialog.getByRole("button", { name: "Clear", exact: true }).click();
    await dialog.getByText("0 recipients selected", { exact: true }).waitFor();
    await page.keyboard.press("Escape");
    return { retainedAcrossSearches: 2, explicitClear: true, sendDisabledWithoutConsent: true };
  });
  await check("mobile section navigation keeps every destination visible", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    const evidence = [];
    for (const [path, name] of [["/email-integrations", "Email integrations"], ["/gc-app/app-controls", "GC App"]]) {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const nav = page.getByRole("navigation", { name, exact: true });
      await nav.waitFor();
      const links = await nav.locator("a").evaluateAll(nodes => nodes.map(node => {
        const box = node.getBoundingClientRect();
        return { text: node.innerText, left: box.left, right: box.right, height: box.height, active: node.getAttribute("aria-current") === "page" };
      }));
      assert.equal(links.filter(link => link.active).length, 1);
      assert.ok(links.every(link => link.left >= 0 && link.right <= 390 && link.height >= 44));
      await screenshot(`mobile-navigation-${name.toLowerCase().replaceAll(" ", "-")}`);
      evidence.push({ path, links });
    }
    return evidence;
  });
  await check("mobile document lanes preserve readable columns and reachable menus", async () => {
    const evidence = [];
    const paths = [
      `/documents/distribution/visa/${fixture.group_id}`,
      `/documents/distribution/flight-tickets/${fixture.group_id}/international/onward`,
      `/documents/distribution/flight-tickets/${fixture.group_id}/domestic/return`,
    ];
    for (const [index, path] of paths.entries()) {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const region = page.getByRole("region", { name: "Passenger document review table" });
      await region.waitFor();
      await region.locator("tbody td:nth-child(2)").first().waitFor();
      await region.scrollIntoViewIfNeeded();
      const geometry = await region.evaluate(node => {
        const table = node.querySelector("table");
        const passengerCell = node.querySelector("tbody td:nth-child(2)");
        return { regionWidth: node.getBoundingClientRect().width, tableWidth: table.getBoundingClientRect().width,
          passengerCellWidth: passengerCell.getBoundingClientRect().width, rowHeight: passengerCell.parentElement.getBoundingClientRect().height,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1 };
      });
      assert.ok(geometry.regionWidth <= 390 && geometry.tableWidth >= 1120 && geometry.passengerCellWidth >= 150);
      assert.ok(geometry.rowHeight < 150);
      assert.equal(geometry.horizontalOverflow, false);
      await screenshot(`document-lane-${index + 1}-mobile-readable`);
      const trigger = region.getByRole("button", { name: "Browser Passenger 1 document actions", exact: true });
      // Let the contained table finish scrolling before clicking: a subsequent
      // scroll deliberately dismisses this anchored menu in the application.
      await trigger.scrollIntoViewIfNeeded();
      await page.waitForTimeout(150);
      await trigger.click();
      const menu = page.getByRole("menu", { name: "Browser Passenger 1 document actions", exact: true });
      await menu.waitFor();
      await page.waitForTimeout(150);
      assert.equal(await menu.isVisible(), true);
      const box = await menu.boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= 390 && box.y >= 0 && box.y + box.height <= 844);
      await screenshot(`document-lane-${index + 1}-mobile-menu`);
      await page.keyboard.press("Escape");
      await menu.waitFor({ state: "hidden" });
      evidence.push({ path, geometry, menu: box });
    }
    return evidence;
  });
  await check("mobile audit cards contain long actor identifiers", async () => {
    await page.goto("/audit-logs", { waitUntil: "domcontentloaded" });
    await page.locator("main article").first().waitFor();
    await page.locator("main article").first().scrollIntoViewIfNeeded();
    // These off-screen cards defer their contents using content-visibility.
    // Capture after the browser paints the now-visible card content.
    await page.waitForTimeout(200);
    await page.locator("main article p").first().waitFor({ state: "visible" });
    const cards = await page.locator("main article").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect();
      const parent = node.parentElement.getBoundingClientRect();
      return { left: box.left, right: box.right, width: box.width, parentLeft: parent.left, parentRight: parent.right };
    }));
    assert.ok(cards.length > 0 && cards.every(card => card.left >= card.parentLeft && card.right <= card.parentRight && card.right <= 390));
    await screenshot("mobile-audit-card-bounds");
    return { checkedCards: cards.length, cards };
  });
  assert.deepEqual(blockedWrites, []);
  assert.deepEqual(review.failures, []);
  assert.deepEqual(apiErrors, []);
} catch (error) {
  results.push({ status: "failed", error: error.stack });
  await screenshot("failure").catch(() => {});
  process.exitCode = 1;
  console.error(error.message);
} finally {
  await writeFile(join(output, "results.json"), JSON.stringify({ results, pageErrors: review.failures, apiErrors, blockedWrites, previewRequests: previews.length }, null, 2));
  await browser.close();
}
