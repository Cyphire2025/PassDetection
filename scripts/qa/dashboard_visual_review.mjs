/** Read-only dashboard rendering against the isolated Docker QA project. */
import { createRequire } from "node:module";
import { createHmac } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(join(root, "frontend/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:3200";
const output = join(root, "outputs/dashboard-qa/visual");

function totp(secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret].map((value) => alphabet.indexOf(value).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from((bits.match(/.{8}/g) ?? []).map((byte) => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  return String((digest.readUInt32BE(digest[19] & 15) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function pageRoutes(directory, prefix = "") {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) result.push(...await pageRoutes(join(directory, entry.name), `${prefix}/${entry.name}`));
    else if (entry.name === "page.tsx") result.push(prefix);
  }
  return result;
}

export async function startReview({ headed = true } = {}) {
  const fixture = JSON.parse(await readFile(join(root, "outputs/dashboard-qa/synthetic-seed.json"), "utf8"));
  const browser = await chromium.launch({ headless: !headed });
  const context = await browser.newContext({ baseURL: origin, viewport: { width: 1440, height: 1040 }, reducedMotion: "reduce" });
  // This runner never visits production or provider URLs. Auth uses only seeded QA accounts.
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort("blockedbyclient");
    return route.continue();
  });
  const account = fixture.accounts.admin;
  const login = await context.request.post("/api/v1/auth/login", {
    form: { username: account.email, password: fixture.manager_password }, headers: { Origin: origin },
  });
  if (!login.ok()) throw new Error(`Synthetic QA login failed: ${login.status()} ${await login.text()}`);
  const challenge = await login.json();
  if (challenge.challenge_token) {
    const verification = await context.request.post("/api/v1/auth/mfa/verify", {
      data: { challenge_token: challenge.challenge_token, code: totp(account.mfa_secret) }, headers: { Origin: origin },
    });
    if (!verification.ok()) throw new Error(`Synthetic QA MFA failed: ${verification.status()} ${await verification.text()}`);
  }
  const page = await context.newPage();
  const failures = [];
  page.on("pageerror", (error) => failures.push({ route: page.url(), error: error.message }));
  const routes = (await pageRoutes(join(root, "frontend/app/(dashboard)"))).sort().map((pattern) => ({
    pattern,
    path: pattern.replaceAll("[groupId]", fixture.group_id).replaceAll("[id]", fixture.passenger_ids[0])
      .replaceAll("[messageId]", "00000000-0000-4000-8000-000000000001").replaceAll("[scope]", "international").replaceAll("[leg]", "onward"),
  }));
  await mkdir(output, { recursive: true });
  return { browser, context, page, routes, failures, results: [], output, origin };
}

export async function captureRoutes(review, start = 0, end = review.routes.length, mobile = false) {
  await review.page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 1040 });
  for (let index = start; index < Math.min(end, review.routes.length); index += 1) {
    const route = review.routes[index];
    const response = await review.page.goto(route.path, { waitUntil: "domcontentloaded" });
    await review.page.locator("main").first().waitFor({ state: "visible", timeout: 20_000 });
    await review.page.waitForTimeout(1200);
    const checks = await review.page.evaluate(() => ({
      title: document.title,
      heading: [...document.querySelectorAll("h1")].map((node) => node.textContent),
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
      bodyText: document.querySelector("main")?.innerText.slice(0, 2800) ?? "",
    }));
    const name = `${String(index + 1).padStart(2, "0")}-${route.pattern.replaceAll(/[^a-zA-Z0-9]+/g, "-")}${mobile ? "-mobile" : ""}.png`;
    await review.page.screenshot({ path: join(output, name), fullPage: true });
    const scroll = await review.page.locator("main").first().evaluate((main) => ({ height: main.scrollHeight, viewport: main.clientHeight }));
    const lowerScreens = [];
    const positions = scroll.height > scroll.viewport * 2.1 ? [0.5, 1] : scroll.height > scroll.viewport + 80 ? [1] : [];
    for (const position of positions) {
      await review.page.locator("main").first().evaluate((main, ratio) => main.scrollTo({ top: (main.scrollHeight - main.clientHeight) * ratio, behavior: "instant" }), position);
      await review.page.waitForTimeout(100);
      const lowerName = name.replace(".png", position === 1 ? "-bottom.png" : "-middle.png");
      await review.page.screenshot({ path: join(output, lowerName) });
      lowerScreens.push(lowerName);
    }
    review.results.push({ ...route, mobile, status: response?.status(), finalUrl: review.page.url(), screenshot: name, lowerScreens, ...checks });
    await writeFile(join(output, "render-results.json"), JSON.stringify({ results: review.results, errors: review.failures }, null, 2));
  }
  return review.results.slice(-(Math.min(end, review.routes.length) - start)).map(({ path, status, heading, horizontalOverflow, screenshot }) => ({ path, status, heading, horizontalOverflow, screenshot }));
}
