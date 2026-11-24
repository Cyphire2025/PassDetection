/** Current production FreshFlow upload methods, CSP and private document forwarding.
 * Run against a loopback Next production server with --url. Every API is synthetic.
 * Camera quality is independently exercised by verify-visa-photo-browser.mjs.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { verifiedPortrait } from "./browser-verification-portrait.mjs";
import { localOrigin, isolatedPage, json, assertClean, assertNoOverflow, viewports } from "./browser-verification-local-fixture.mjs";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const origin = localOrigin("http://127.0.0.1:3185");
const output = join(frontend, "test-results/upload-options-browser");
await mkdir(output, { recursive: true });
const portrait = await verifiedPortrait(frontend);
const fixtureHash = createHash("sha256").update(portrait).digest("hex");
assert.equal(fixtureHash, "a6f11efaa834706db23f275b6115058fa87fc7f14362681e6abe14e82749de3e");
const configurations = [
  { name: "live-only", camera: true, upload: false },
  { name: "upload-only", camera: false, upload: true },
  { name: "both", camera: true, upload: true },
];
const report = { origin: origin.origin, fixtureHash, layouts: [], validation: [], assetCache: [] };
let browser;
function groupFor(token, config) {
  return { id: "synthetic-upload-options", name: "Synthetic Singapore Journey", token, status: "active",
    travel_date: "2027-12-01", return_date: "2027-12-08", require_selfie: true,
    allow_files_from_device: config.upload, departure_cities: [], custom_questions: [], custom_details: [],
    relation_with_qualifier_enabled: false, qualifier_relation_options: [],
    upload_configuration: { passport_enabled: true, passport_required: false, passport_live_scan: config.camera,
      passport_ecr_enabled: false, passport_upload_pages: ["front", "back"], visa_photo_required: true,
      visa_photo_live_capture: config.camera, visa_photo_upload: config.upload, required_fields: {},
      qualifier_relation_list_enabled: false, qualifier_relation_other_enabled: false,
      instruction_languages_enabled: false, instruction_languages: [],
      agent_employee_code_label: "Agent/Employee Code", agency_dealership_name_label: "Agency/Dealership Name" } };
}
async function openFlow(viewport, config) {
  const token = `synthetic-options-${viewport.name}-${config.name}`;
  const state = { draft: null, prepares: [], uploads: [], malformedPreview: false, jpeg: null };
  const flow = await isolatedPage(browser, origin, viewport, async (route, request, url) => {
    const path = url.pathname, method = request.method();
    if (path === `/api/v1/upload-links/token/${token}` && method === "GET") { await json(route, groupFor(token, config)); return true; }
    if (path === "/api/v1/returning/capabilities") { await json(route, { enabled: false, code_label: null }); return true; }
    if (path.endsWith("/telemetry")) { await json(route, {}); return true; }
    const session = request.headers()["x-upload-session-id"], base = `/api/v1/public-drafts/${token}`;
    if (path !== base && !path.startsWith(`${base}/`) && path !== `/api/v1/passports/upload/${token}/prepare-file`) return false;
    assert.match(session ?? "", /^[a-f0-9-]{36}$/i, "Every private draft request retains its opaque upload session");
    if (path.endsWith("/prepare-file")) {
      const form = await new Request(request.url(), { method: "POST", headers: request.headers(), body: request.postDataBuffer() }).formData();
      state.prepares.push({ purpose: form.get("purpose"), name: form.get("file").name, session });
      assert.equal(form.get("purpose"), "visa");
      await route.fulfill({ contentType: state.malformedPreview ? "image/png" : "image/jpeg", body: state.jpeg, headers: { "cache-control": "private, no-store" } }); return true;
    }
    if (!state.draft && method === "POST") state.draft = { id: "synthetic-private-draft", revision: 1, status: "active",
      expires_at: new Date(Date.now() + 86_400_000).toISOString(), passport_fields: {}, current_details: {},
      custom_answers: {}, custom_detail_answers: {}, collection: null, verified_phone: null, documents: [], extraction_status: "none" };
    if (path.endsWith("/activity")) { await json(route, { images_present: Boolean(state.draft?.documents.length), presence_recorded: true, heartbeat_after_seconds: 60 }); return true; }
    if (path.endsWith("/discard-documents")) { await json(route, state.draft); return true; }
    if (path.includes("/documents/") && method === "POST") {
      const form = await new Request(request.url(), { method, headers: request.headers(), body: request.postDataBuffer() }).formData();
      assert.equal(Number(form.get("expected_revision")), state.draft.revision);
      assert.ok(form.get("idempotency_key"));
      const file = form.get("file"), bytes = Buffer.from(await file.arrayBuffer());
      state.uploads.push({ session, type: file.type, size: file.size, key: form.get("idempotency_key"), bytes });
      state.draft.revision++; state.draft.documents = [{ id: "synthetic-photo", side: "photo", state: "ready" }];
    } else if (path.includes("/documents/") && method === "GET") {
      await route.fulfill({ contentType: "image/jpeg", body: state.jpeg, headers: { "cache-control": "private, no-store" } }); return true;
    } else if (path === base && method === "PUT") {
      const body = request.postDataJSON(); assert.equal(body.expected_revision, state.draft.revision);
      Object.assign(state.draft, body, { revision: state.draft.revision + 1 });
    } else if (path !== base || !["POST", "GET"].includes(method)) return false;
    await json(route, state.draft); return true;
  });
  await flow.page.addInitScript(() => {
    window.uploadTestViolations = [];
    document.addEventListener("securitypolicyviolation", event => window.uploadTestViolations.push({ directive: event.effectiveDirective, blocked: event.blockedURI, source: event.sourceFile, line: event.lineNumber, column: event.columnNumber }));
  });
  const response = await flow.page.goto(`${origin.origin}/upload/${token}`);
  assert.equal(response.status(), 200);
  const csp = response.headers()["content-security-policy"];
  assert.ok(csp?.includes("'strict-dynamic'")); assert.ok(!csp.includes("'unsafe-eval'"));
  await flow.page.getByRole("button", { name: /New traveller/ }).click();
  await flow.page.getByRole("button", { name: "Only me", exact: true }).click();
  await flow.page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(flow.page.getByRole("region", { name: "Your documents", exact: true })).toBeVisible();
  const nonce = await flow.page.locator("script[nonce]").first().evaluate(element => element.nonce);
  assert.ok(nonce && csp.includes(`'nonce-${nonce}'`));
  const violations = await flow.page.evaluate(() => window.uploadTestViolations);
  for (const violation of violations) {
    assert.equal(violation.directive, "script-src"); assert.equal(violation.blocked, "eval");
    assert.equal(new URL(violation.source).origin, origin.origin);
    const source = await (await fetch(violation.source)).text();
    const line = source.split("\n")[violation.line - 1];
    const nearby = line.slice(Math.max(0, violation.column - 250), violation.column + 100);
    assert.match(nearby, /jitless/); assert.match(nearby, /Function\(""\)/);
  }
  return { ...flow, state, csp, nonce, violations };
}
async function checkLayout(page, config, side) {
  const card = page.locator(`[data-document-side="${side}"]`);
  await expect(card).toBeVisible();
  await expect(card.getByRole("button", { name: "Use camera", exact: true })).toHaveCount(Number(config.camera));
  await expect(card.locator('input[type="file"]')).toHaveCount(Number(config.upload));
  const cardBox = await card.boundingBox();
  for (const control of await card.locator('button, label:has(input[type="file"])').all()) {
    const box = await control.boundingBox();
    assert.ok(box.x >= cardBox.x && box.x + box.width <= cardBox.x + cardBox.width + 1, "Available method remains inside its card");
    assert.ok(box.width > 0 && box.height > 0, "Enabled methods have measurable interactive bounds");
  }
  return cardBox;
}
try {
  for (const suffix of ["?v=0.4.1646425229-csp1", ""]) {
    const path = `/mediapipe/face_detection/face_detection_solution_wasm_bin.js${suffix}`;
    const response = await fetch(`${origin.origin}${path}`, { signal: AbortSignal.timeout(15_000) }); assert.equal(response.status, 200);
    const cacheControl = response.headers.get("cache-control");
    if (suffix) { assert.match(cacheControl, /public/); assert.match(cacheControl, /max-age=86400/); assert.match(cacheControl, /immutable/); }
    else { assert.match(cacheControl, /max-age=0|no-cache/); assert.ok(!cacheControl.includes("immutable")); }
    report.assetCache.push({ path, cacheControl }); await response.body.cancel();
  }
  browser = await chromium.launch({ headless: true }); report.browser = browser.version();
  for (const viewport of viewports) for (const config of configurations) {
    const flow = await openFlow(viewport, config);
    try {
      const cards = {};
      for (const side of ["front", "back", "photo"]) cards[side] = await checkLayout(flow.page, config, side);
      const dimensions = await assertNoOverflow(flow.page, flow.page.getByRole("region", { name: "Your documents" }));
      assert.deepEqual(await flow.page.evaluate(() => window.uploadTestViolations), flow.violations); assertClean(flow.diagnostics);
      const screenshot = join(output, `${viewport.name}-${config.name}.png`); await flow.page.screenshot({ path: screenshot, fullPage: true });
      report.layouts.push({ viewport: viewport.name, config: config.name, cards, dimensions, screenshot, nonce: flow.nonce, csp: flow.csp });
      console.log(`PASS current Fresh methods ${viewport.name} ${config.name}`);
    } finally { await flow.context.close(); }
  }
  const flow = await openFlow(viewports[0], configurations[1]);
  try {
    const input = flow.page.getByLabel("Upload traveller photo", { exact: true });
    await input.setInputFiles({ name: "unsupported.webp", mimeType: "image/webp", buffer: Buffer.from("invalid") });
    await expect(flow.page.getByRole("region", { name: "Your documents", exact: true }).getByRole("alert")).toContainText("single-page PDF"); assert.equal(flow.state.prepares.length, 0); assert.equal(flow.state.uploads.length, 0);
    await input.setInputFiles({ name: "oversized.png", mimeType: "image/png", buffer: Buffer.alloc(10 * 1024 * 1024 + 1) });
    await expect(flow.page.getByRole("region", { name: "Your documents", exact: true }).getByRole("alert")).toContainText("10 MB"); assert.equal(flow.state.prepares.length, 0);
    const fixtures = await flow.page.evaluate(async base64 => {
      const canvas = document.createElement("canvas"); canvas.width = 800; canvas.height = 1200;
      const context = canvas.getContext("2d"); context.fillStyle = "white"; context.fillRect(0, 0, 800, 1200);
      const image = new Image(); image.src = `data:image/jpeg;base64,${base64}`; await image.decode();
      context.drawImage(image, 258, 20, 310, 440, 155, 170, 490, 700);
      return { png: canvas.toDataURL("image/png").split(",")[1], jpeg: canvas.toDataURL("image/jpeg", .9).split(",")[1] };
    }, portrait.toString("base64"));
    flow.state.jpeg = Buffer.from(fixtures.jpeg, "base64");
    const photo = { name: "synthetic-photo.png", mimeType: "image/png", buffer: Buffer.from(fixtures.png, "base64") };
    flow.state.malformedPreview = true; await input.setInputFiles(photo);
    await expect(flow.page.getByRole("region", { name: "Your documents", exact: true }).getByRole("alert")).toContainText("preview could not be prepared"); assert.equal(flow.state.uploads.length, 0);
    flow.state.malformedPreview = false; await input.setInputFiles(photo);
    await expect.poll(() => flow.state.uploads.length).toBe(1);
    await expect(flow.page.locator('[data-document-side="photo"]').getByRole("img")).toBeVisible();
    const upload = flow.state.uploads[0]; assert.equal(upload.type, "image/jpeg"); assert.ok(upload.size > 0 && upload.size <= 2 * 1024 * 1024);
    assert.equal(upload.session, flow.state.prepares.at(-1).session); assert.deepEqual(upload.bytes, flow.state.jpeg);
    await expect.poll(() => flow.state.draft.collection.visa_photo_source).toBe("file");
    assert.equal(flow.state.prepares.length, 2); assert.equal(new Set(flow.state.uploads.map(item => item.key)).size, 1);
    assert.deepEqual(await flow.page.evaluate(() => window.uploadTestViolations), flow.violations); assertClean(flow.diagnostics);
    report.validation = ["unsupported type rejected before prepare", "oversize rejected before prepare", "noncanonical response rejected before private write", "canonical JPEG forwarded once with member authority"];
    const dimensions = await flow.page.evaluate(async base64 => { const image = new Image(); image.src = `data:image/jpeg;base64,${base64}`; await image.decode(); return [image.naturalWidth, image.naturalHeight]; }, upload.bytes.toString("base64"));
    assert.deepEqual(dimensions, [800, 1200]);
    report.outgoingPhoto = { type: upload.type, size: upload.size, dimensions, sha256: createHash("sha256").update(upload.bytes).digest("hex") };
  } finally { await flow.context.close(); }
  report.passed = true;
} catch (error) { report.passed = false; report.failure = String(error); process.exitCode = 1; }
finally { await browser?.close(); await writeFile(join(output, "verification.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ passed: report.passed, failure: report.failure, layouts: report.layouts.length, validation: report.validation }, null, 2)); }
