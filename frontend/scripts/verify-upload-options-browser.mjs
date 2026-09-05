/**
 * Verify the real Next production bundle, nonce/CSP and configurable upload UI.
 * Start a production Next server, then run from frontend:
 * node scripts/verify-upload-options-browser.mjs --url http://127.0.0.1:3185
 * API calls are stubbed; only loopback servers are allowed. No detector shims.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const urlIndex = process.argv.indexOf("--url");
const origin = new URL(urlIndex < 0 ? "http://127.0.0.1:3185" : process.argv[urlIndex + 1]);
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname), "Only a local test server is allowed");
assert.ok(["http:", "https:"].includes(origin.protocol));
const output = join(frontend, "test-results", "upload-options-browser");
await mkdir(output, { recursive: true });
const fixture = await readFile(join(frontend, "test-results", "visa-photo-browser", "portrait.jpg"));
const fixtureHash = createHash("sha256").update(fixture).digest("hex");
assert.equal(fixtureHash, "a6f11efaa834706db23f275b6115058fa87fc7f14362681e6abe14e82749de3e");

const configurations = [
  { name: "live-only", camera: true, upload: false },
  { name: "upload-only", camera: false, upload: true },
  { name: "both", camera: true, upload: true },
];
const viewports = [
  { name: "desktop", width: 1440, height: 1080 },
  { name: "mobile", width: 390, height: 844 },
];
const report = { origin: origin.origin, fixtureHash, layouts: [], validation: [], requests: [] };
let browser;

function groupFor(token, config) {
  return {
    id: "test-upload-options", name: "Sample Travel Group", token, agency_id: "test-agency",
    status: "active", created_at: "2026-09-05T00:00:00Z", destination: "Singapore",
    travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Singapore",
    require_selfie: true, allow_files_from_device: config.upload,
    base_city_enabled: false, nearest_international_airport_enabled: false,
    staff_code_enabled: false, agent_employee_code_enabled: false,
    meal_preference_enabled: false, ask_nearest_domestic_airport: false,
    relation_with_qualifier_enabled: false, designation_enabled: false,
    agency_dealership_name_enabled: false, departure_cities: [],
    custom_questions: [], custom_details: [], qualifier_relation_options: [],
    upload_configuration: {
      passport_enabled: true, passport_required: false, passport_live_scan: config.camera,
      passport_upload_pages: ["front", "back"], visa_photo_required: true,
      visa_photo_live_capture: config.camera, visa_photo_upload: config.upload,
      required_fields: {}, agent_employee_code_label: "Agent/Employee Code",
      agency_dealership_name_label: "Agency/Dealership Name",
    },
  };
}

async function openFlow(viewport, config) {
  const token = `test-options-${viewport.name}-${config.name}`;
  const context = await browser.newContext({ viewport, serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  const errors = [];
  const consoleErrors = [];
  const unexpectedRequests = [];
  const uploads = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("response", (response) => {
    if (response.url().includes("/mediapipe/") || response.status() >= 400) {
      report.requests.push({ url: response.url(), status: response.status() });
    }
  });
  await page.addInitScript(() => {
    window.uploadTestViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.uploadTestViolations.push({ directive: event.effectiveDirective, blocked: event.blockedURI, source: event.sourceFile, line: event.lineNumber, column: event.columnNumber, sample: event.sample });
    });
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    if (requestUrl.origin !== origin.origin) {
      unexpectedRequests.push(request.url());
      return route.abort("blockedbyclient");
    }
    if (!requestUrl.pathname.startsWith("/api/v1/")) return route.continue();
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (requestUrl.pathname === `/api/v1/upload-links/token/${token}`) return json(groupFor(token, config));
    if (requestUrl.pathname === `/api/v1/passports/upload/${token}` && request.method() === "POST") {
      const form = await new Request(request.url(), {
        method: "POST", headers: request.headers(), body: request.postDataBuffer(),
      }).formData();
      const photo = form.get("passport_photo_file");
      assert.ok(photo && typeof photo !== "string", "Verified photo must reach the upload request");
      const bytes = Buffer.from(await photo.arrayBuffer());
      uploads.push({ type: photo.type, size: photo.size, source: form.get("visa_photo_source"), bytes });
      return json({
        id: "test-saved-photo", client_name: form.get("client_name"), image_s3_key: "",
        status: "ready_for_client_review", extraction_status: "ready_for_review", extracted_fields: null,
      });
    }
    if (requestUrl.pathname.endsWith("/telemetry")) return json({});
    unexpectedRequests.push(`${request.method()} ${requestUrl.pathname}`);
    return json({ error: { code: "TEST_UNEXPECTED_API", message: "Unexpected request in local UI test" } }, 400);
  });
  const response = await page.goto(`${origin.origin}/upload/${token}`);
  assert.equal(response.status(), 200);
  const csp = response.headers()["content-security-policy"];
  assert.ok(csp?.includes("'strict-dynamic'"), "Test must exercise the production CSP");
  assert.ok(!/(?:^|\s)'unsafe-eval'(?:\s|;|$)/.test(csp), "Production CSP must not permit unsafe-eval");
  await page.getByRole("button", { name: /Single/ }).click();
  await expect(page.getByTestId("visa-photo-choice")).toBeVisible();
  const nonce = await page.locator("script[nonce]").first().evaluate((element) => element.nonce);
  assert.ok(nonce && csp.includes(`'nonce-${nonce}'`), "Next script must carry the response nonce");
  const startupViolations = await page.evaluate(() => window.uploadTestViolations);
  // Zod safely probes JIT availability once while parsing the group response.
  // Record that existing caught probe; validate its actual bundle source so no
  // unrelated eval failure can be silently treated as harmless startup noise.
  for (const violation of startupViolations) {
    assert.equal(violation.directive, "script-src");
    assert.equal(violation.blocked, "eval");
    assert.equal(new URL(violation.source).origin, origin.origin);
    const source = await (await fetch(violation.source)).text();
    const line = source.split("\n")[violation.line - 1];
    const nearbySource = line.slice(Math.max(0, violation.column - 250), violation.column + 100);
    assert.match(nearbySource, /jitless/);
    assert.match(nearbySource, /Function\(""\)/);
  }
  return { context, page, errors, consoleErrors, unexpectedRequests, uploads, csp, nonce, startupViolations };
}

async function checkLayout(page, viewport, config, testId, cameraName, uploadName) {
  const card = page.getByTestId(testId);
  const cardBox = await card.boundingBox();
  assert.ok(cardBox);
  const boxes = [];
  for (const [enabled, name] of [[config.camera, cameraName], [config.upload, uploadName]]) {
    const button = card.getByRole("button", { name, exact: true });
    await expect(button).toHaveCount(Number(enabled));
    if (!enabled) continue;
    const box = await button.boundingBox();
    assert.ok(box);
    assert.ok(box.x >= cardBox.x && box.x + box.width <= cardBox.x + cardBox.width + 1, `${testId}: action stays inside card`);
    boxes.push(box);
  }
  if (boxes.length === 1) {
    assert.ok(Math.abs(boxes[0].x + boxes[0].width / 2 - cardBox.x - cardBox.width / 2) < 2, `${testId}: single method is centered`);
  } else {
    assert.ok(Math.abs(boxes[0].width - boxes[1].width) < 2, `${testId}: both actions have equal width`);
    if (viewport.name === "desktop") assert.ok(Math.abs(boxes[0].y - boxes[1].y) < 2, `${testId}: desktop actions share a row`);
    else assert.ok(boxes[1].y >= boxes[0].y + boxes[0].height, `${testId}: mobile actions stack`);
  }
  return { card: cardBox, actions: boxes };
}

async function fixturePayload(page, kind, index) {
  const base64 = await page.evaluate(async ({ portrait, kind }) => {
    const canvas = document.createElement("canvas");
    canvas.width = 800; canvas.height = 1200;
    const context = canvas.getContext("2d");
    context.fillStyle = kind === "colored" ? "#406070" : "white";
    context.fillRect(0, 0, 800, 1200);
    if (kind !== "blank") {
      const image = new Image(); image.src = portrait; await image.decode();
      // Composite from the public MediaPipe test portrait, never a product sample.
      context.drawImage(image, 258, 20, 310, 440, 155, 170, 490, 700);
    }
    return canvas.toDataURL("image/png").split(",")[1];
  }, { portrait: `data:image/jpeg;base64,${fixture.toString("base64")}`, kind });
  return { name: `test-${kind}-${index}.png`, mimeType: "image/png", buffer: Buffer.from(base64, "base64") };
}

try {
  report.assetCache = [];
  for (const suffix of ["?v=0.4.1646425229-csp1", ""]) {
    const path = `/mediapipe/face_detection/face_detection_solution_wasm_bin.js${suffix}`;
    const response = await fetch(`${origin.origin}${path}`, { signal: AbortSignal.timeout(15_000) });
    assert.equal(response.status, 200);
    const cacheControl = response.headers.get("cache-control");
    if (suffix) {
      assert.match(cacheControl, /public/);
      assert.match(cacheControl, /max-age=86400/);
      assert.match(cacheControl, /immutable/);
    } else {
      assert.match(cacheControl, /max-age=0|no-cache/);
      assert.ok(!cacheControl.includes("immutable"), "Unversioned model assets must revalidate");
    }
    report.assetCache.push({ path, cacheControl });
    await response.body.cancel();
  }
  browser = await chromium.launch({ headless: true, args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  report.browser = browser.version();
  for (const viewport of viewports) {
    for (const config of configurations) {
      const flow = await openFlow(viewport, config);
      try {
        const visa = await checkLayout(flow.page, viewport, config, "visa-photo-choice", "Use live camera", "Upload studio photo");
        const passport = await checkLayout(flow.page, viewport, config, "passport-document-choice", "Live scan", "Upload passport images");
        const dimensions = await flow.page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
        assert.ok(dimensions.width <= dimensions.viewport, "No horizontal page overflow");
        assert.deepEqual(flow.errors, []);
        assert.deepEqual(flow.unexpectedRequests, []);
        const violations = await flow.page.evaluate(() => window.uploadTestViolations);
        report.activeDiagnostics = { viewport: viewport.name, config: config.name, violations, consoleErrors: flow.consoleErrors, errors: flow.errors };
        assert.deepEqual(violations, flow.startupViolations);
        const screenshot = join(output, `${viewport.name}-${config.name}.png`);
        await flow.page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
        report.layouts.push({ viewport: viewport.name, config: config.name, visa, passport, dimensions, screenshot, csp: flow.csp, startupViolations: flow.startupViolations });
        console.log(`PASS layout ${viewport.name} ${config.name}`);
      } finally { await flow.context.close(); }
    }
  }

  const flow = await openFlow(viewports[0], configurations[1]);
  try {
    report.productionCsp = flow.csp;
    await flow.page.getByRole("button", { name: "Upload studio photo", exact: true }).click();
    const dialog = flow.page.getByRole("dialog", { name: "Upload Studio Visa Photo" });
    await expect(dialog).toBeVisible();
    const kinds = ["white", "blank", "colored", "white"];
    for (const [index, kind] of kinds.entries()) {
      const payload = await fixturePayload(flow.page, kind, index);
      const start = performance.now();
      await flow.page.getByLabel("Choose a studio Visa Photo", { exact: true }).setInputFiles(payload);
      await expect(flow.page.getByText(`Selected: ${payload.name}`, { exact: true })).toBeVisible();
      if (kind === "white") {
        await expect(flow.page.getByRole("button", { name: "Use Visa Photo", exact: true })).toBeVisible({ timeout: 20_000 });
        await expect(dialog.getByRole("alert")).toHaveCount(0);
      } else {
        await expect(dialog.getByRole("alert")).toContainText(kind === "blank" ? "No face was found" : "The background is not white or off-white", { timeout: 20_000 });
        await expect(flow.page.getByRole("button", { name: "Use Visa Photo", exact: true })).toHaveCount(0);
      }
      const elapsedMs = performance.now() - start;
      const screenshot = join(output, `validation-${index}-${kind}.png`);
      await flow.page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
      report.validation.push({ kind, elapsedMs, outcome: kind === "white" ? "pass" : "rejected", screenshot });
      console.log(`PASS validation ${kind} ${Math.round(elapsedMs)}ms`);
    }
    await flow.page.getByRole("button", { name: "Use Visa Photo", exact: true }).click();
    await expect(flow.page.getByTestId("visa-photo-choice")).toContainText("Completed");
    await flow.page.getByLabel(/Full name/).fill("Asha Example");
    await flow.page.getByRole("button", { name: "Continue without passport", exact: true }).click();
    await expect(flow.page.getByRole("heading", { name: "Review Traveller Details", exact: true })).toBeVisible();
    assert.equal(flow.uploads.length, 1);
    const upload = flow.uploads[0];
    assert.equal(upload.type, "image/jpeg");
    assert.equal(upload.source, "file");
    assert.ok(upload.size > 0 && upload.size <= 2 * 1024 * 1024);
    const outputDimensions = await flow.page.evaluate(async (base64) => {
      const image = new Image(); image.src = `data:image/jpeg;base64,${base64}`; await image.decode();
      return [image.naturalWidth, image.naturalHeight];
    }, upload.bytes.toString("base64"));
    assert.deepEqual(outputDimensions, [800, 1200]);
    report.outgoingPhoto = { type: upload.type, size: upload.size, source: upload.source, dimensions: outputDimensions, sha256: createHash("sha256").update(upload.bytes).digest("hex") };
    report.startupViolations = flow.startupViolations;
    report.validationViolations = (await flow.page.evaluate(() => window.uploadTestViolations)).slice(flow.startupViolations.length);
    report.pageErrors = flow.errors;
    assert.deepEqual(report.validationViolations, []);
    assert.deepEqual(flow.errors, []);
    assert.deepEqual(flow.unexpectedRequests, []);
    assert.ok(report.requests.some(({ url }) => url.includes("/mediapipe/face_detection/") && url.includes(".wasm")), "Real Next upload must load the actual WASM");
  } finally { await flow.context.close(); }
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failure = String(error);
  process.exitCode = 1;
} finally {
  await browser?.close();
  const reportPath = join(output, "verification.json");
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, failure: report.failure, layouts: report.layouts.length, validation: report.validation, outgoingPhoto: report.outgoingPhoto, reportPath }, null, 2));
}
