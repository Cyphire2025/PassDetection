/** Isolated HTTP/browser semantics probe; no application server or real credentials. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const require = createRequire(resolve("frontend/package.json"));
const { chromium } = require("playwright");
const server = createServer((request, response) => {
  const target = new URL(request.url, "http://127.0.0.1");
  if (target.pathname === "/me") {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ owner: /synthetic_owner=([^;]+)/.exec(request.headers.cookie ?? "")?.[1] ?? null }));
  } else if (target.pathname === "/identity") {
    setTimeout(() => {
      response.setHeader("Set-Cookie", `synthetic_owner=${target.searchParams.get("owner")}; HttpOnly; SameSite=Strict; Path=/`);
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ owner: target.searchParams.get("owner") }));
    }, Number(target.searchParams.get("delay") ?? "0"));
  } else { response.end("<!doctype html><title>Synthetic cookie ordering</title>"); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const abortOld of [false, true]) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    const result = await page.evaluate(async (abortOld) => {
      let stateOwner = null;
      const controller = new AbortController();
      const pendingA = fetch("/identity?owner=A&delay=400", { signal: controller.signal })
        .then((response) => response.json())
        .then((session) => { if (stateOwner === null) stateOwner = session.owner; })
        .catch((error) => error.name);
      await new Promise((resolve) => setTimeout(resolve, 50));
      const sessionB = await (await fetch("/identity?owner=B")).json();
      stateOwner = sessionB.owner;
      if (abortOld) controller.abort();
      await pendingA;
      await new Promise((resolve) => setTimeout(resolve, 450));
      return { stateOwner, cookieOwner: (await (await fetch("/me")).json()).owner, scriptCookie: document.cookie };
    }, abortOld);
    assert.equal(result.stateOwner, "B");
    assert.equal(result.cookieOwner, abortOld ? "B" : "A");
    assert.equal(result.scriptCookie, "");
    results.push({ abortOld, ...result });
    await context.close();
  }
  await writeFile(resolve("docs/audit/dashboard-2026-10-30/auth-cookie-browser-evidence.json"), `${JSON.stringify({
    browser: browser.version(), results,
    scope: "Actual loopback HTTP Set-Cookie ordering in Chromium with synthetic values; baseline JS result guard versus abort before delayed headers. This probe establishes browser semantics, not full dashboard integration or cross-tab coordination.",
  }, null, 2)}\n`);
  console.log(JSON.stringify(results));
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
