/**
 * Real Chromium regression for the existing MediaPipe model and upload validator.
 * Run from frontend: node scripts/verify-visa-photo-browser.mjs [--baseline]
 * Uses local assets and a public MediaPipe test portrait, never production data.
 * Results/fixture cache are written below ignored test-results/visa-photo-browser.
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { build } from "vite";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = join(frontend, "test-results", "visa-photo-browser");
const baseline = process.argv.includes("--baseline");
const selectedScenario = process.argv.find(argument => argument.startsWith("--scenario="))?.slice("--scenario=".length);
const fixtureUrl = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg";
const fixtureSha256 = "a6f11efaa834706db23f275b6115058fa87fc7f14362681e6abe14e82749de3e";
const nonce = randomBytes(24).toString("base64");
await mkdir(outputDirectory, { recursive: true });
const fixturePath = join(outputDirectory, "portrait.jpg");
let fixture;
try {
  fixture = await readFile(fixturePath);
} catch {
  const response = await fetch(fixtureUrl, { signal: AbortSignal.timeout(15_000) });
  assert.equal(response.status, 200, "MediaPipe test portrait must download");
  fixture = Buffer.from(await response.arrayBuffer());
  await writeFile(fixturePath, fixture);
}
assert.equal(createHash("sha256").update(fixture).digest("hex"), fixtureSha256, "Unexpected test portrait revision");

// Extract the real policy function without importing Next's server-only module.
const proxySource = (await readFile(join(frontend, "proxy.ts"), "utf8")).replaceAll("\r\n", "\n");
const policyFunction = proxySource.match(/export function buildContentSecurityPolicy\([\s\S]*?\n}\n/);
assert.ok(policyFunction, "Cannot locate production CSP builder");
const nodePolicy = policyFunction[0]
  .replace("export function", "function")
  .replace("nonce: string, isDevelopment: boolean", "nonce, isDevelopment");
// This evaluation is in Node only. Browser pages never permit unsafe-eval.
const csp = new Function(`${nodePolicy}; return buildContentSecurityPolicy;`)()(nonce, false);
assert.ok(!/(?:^|\s)'unsafe-eval'(?:\s|;|$)/.test(csp));

const runtimePath = join(frontend, "features/upload/services/visa-photo-upload-validation.ts").replaceAll("\\", "/");
const prewarmPath = join(frontend, "features/upload/services/visa-photo-upload-detector.ts").replaceAll("\\", "/");
const loaderPath = join(frontend, "features/upload/services/visa-face-detection-loader.ts").replaceAll("\\", "/");
const entrySource = `
import { verifyUploadedVisaPhoto } from ${JSON.stringify(runtimePath)};
${baseline ? "" : `import { prewarmUploadedVisaPhotoDetector } from ${JSON.stringify(prewarmPath)};`}
${baseline ? "" : `import { loadVisaFaceDetection } from ${JSON.stringify(loaderPath)};`}
window.testViolations = [];
document.addEventListener("securitypolicyviolation", event => {
  window.testViolations.push({ directive: event.effectiveDirective, blocked: event.blockedURI });
});
window.runDetector = async () => {
  const image = new Image(); image.src = "/portrait.jpg"; await image.decode();
  const start = performance.now();
  const { FaceDetection } = ${baseline ? "window" : "await loadVisaFaceDetection()"};
  const detector = new FaceDetection({ locateFile: file => "/mediapipe/face_detection/" + file });
  detector.setOptions({model: "short", selfieMode: false, minDetectionConfidence: 0.65});
  let detections = [];
  detector.onResults(value => { detections = value.detections; });
  try {
    await detector.initialize();
    await detector.send({ image });
    const coldMs = performance.now() - start;
    const faceCount = detections.length;
    const blank = document.createElement("canvas"); blank.width = 800; blank.height = 1200;
    blank.getContext("2d").fillStyle = "white"; blank.getContext("2d").fillRect(0, 0, 800, 1200);
    await detector.send({image: blank});
    const blankFaceCount = detections.length;
    const warmMs = [];
    for (let i = 0; i < 5; i += 1) {
      const before = performance.now(); await detector.send({image});
      if (detections.length < 1) throw new Error("Warm face detection lost the face");
      warmMs.push(performance.now() - before);
    }
    await detector.close();
    return {coldMs, faceCount, blankFaceCount, warmMs};
  } catch (error) {
    return {error: String(error), elapsedMs: performance.now() - start};
  }
};
window.prewarmDetector = async () => {
  const before = performance.now();
  ${baseline ? "" : "await prewarmUploadedVisaPhotoDetector();"}
  return performance.now() - before;
};
window.verifyFixture = async kind => {
  const canvas = document.createElement("canvas"); canvas.width = 800; canvas.height = 1200;
  const context = canvas.getContext("2d");
  context.fillStyle = kind === "colored" ? "#406070" : "white";
  context.fillRect(0, 0, 800, 1200);
  if (kind !== "blank") {
    const image = new Image(); image.src = "/portrait.jpg"; await image.decode();
    // Synthetic test composite: face interior with clear outer strips. This is
    // not a product sample and is not evidence of broad biometric accuracy.
    context.drawImage(image, 258, 20, 310, 440, 155, 170, 490, 700);
  }
  const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  const file = new File([blob], kind + ".png", {type: "image/png"});
  const before = performance.now();
  try {
    const result = await verifyUploadedVisaPhoto(file);
    const elapsedMs = performance.now() - before;
    const exactOutput = await createImageBitmap(result.file);
    const dimensions = [exactOutput.width, exactOutput.height]; exactOutput.close();
    return {elapsedMs, validation: result.validation, dimensions,
      bytes: result.file.size, type: result.file.type};
  } catch (error) {
    return {error: String(error), elapsedMs: performance.now() - before};
  }
};
window.testReady = true;
`;
const entryPath = join(outputDirectory, "entry.mjs");
await writeFile(entryPath, entrySource);
const bundles = await build({
  root: frontend, configFile: false, logLevel: "error", publicDir: false,
  resolve: {alias: {"@": frontend}},
  build: {
    write: false, target: "es2022", minify: false,
    lib: {entry: entryPath, formats: ["iife"], name: "VisaPhotoBrowserVerification"},
  },
});
const bundle = (Array.isArray(bundles) ? bundles.flatMap(value => value.output) : bundles.output)
  .find(value => value.type === "chunk");
assert.ok(bundle, "Browser verification bundle was not produced");
const assetRoot = join(frontend, baseline ? "node_modules/@mediapipe/face_detection" : "public/mediapipe/face_detection");
let mode = "simd";
let failedModelRequests = 0;
let failedLoaderRequests = 0;
let delayedLoaderRequests = 0;
const requests = [];
const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url, "http://localhost").pathname;
    response.setHeader("Cache-Control", "no-store");
    if (path === "/") {
      response.setHeader("Content-Type", "text/html");
      response.setHeader("Content-Security-Policy", csp);
      response.end(`<!doctype html><meta charset="utf-8">${baseline ? `<script nonce="${nonce}" src="/face_detection.js"></script>` : ""}<script nonce="${nonce}" src="/entry.js"></script>`);
    } else if (path === "/face_detection.js") {
      response.setHeader("Content-Type", "text/javascript");
      response.end(await readFile(join(assetRoot, "face_detection.js")));
    } else if (path === "/entry.js") {
      response.setHeader("Content-Type", "text/javascript"); response.end(bundle.code);
    } else if (path === "/portrait.jpg") {
      response.setHeader("Content-Type", "image/jpeg"); response.end(fixture);
    } else if (path.startsWith("/mediapipe/face_detection/")) {
      let file = path.slice("/mediapipe/face_detection/".length);
      assert.match(file, /^[a-zA-Z0-9_.-]+$/);
      if (mode === "scalar") file = file.replace("_simd_", "_");
      requests.push({requested: path, served: file});
      if (failedModelRequests > 0 && file.endsWith(".binarypb")) {
        failedModelRequests -= 1; response.statusCode = 503; response.end("Test transient failure"); return;
      }
      if (failedLoaderRequests > 0 && file.endsWith("_wasm_bin.js")) {
        failedLoaderRequests -= 1; response.statusCode = 522; response.end(); return;
      }
      if (delayedLoaderRequests > 0 && file.endsWith("_wasm_bin.js")) {
        delayedLoaderRequests -= 1;
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".wasm") ? "application/wasm" : "application/octet-stream");
      response.end(await readFile(join(assetRoot, file)));
    } else { response.statusCode = 404; response.end(); }
  } catch (error) { response.statusCode = 500; response.end(String(error)); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const report = {baseline, fixture: {url: fixtureUrl, sha256: createHash("sha256").update(fixture).digest("hex")}, csp, results: []};
let browser;
try {
  browser = await chromium.launch({headless: true, args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]});
  report.browser = browser.version();
  for (const selectedMode of selectedScenario ? [] : ["simd", "scalar"]) {
    mode = selectedMode;
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    const requestStart = requests.length;
    await page.goto(origin);
    await page.waitForFunction(() => window.testReady);
    const result = await page.evaluate(() => Promise.race([
      window.runDetector(), new Promise(resolve => setTimeout(() => resolve({error: "test deadline"}), 25_000)),
    ]));
    const violations = await page.evaluate(() => window.testViolations);
    report.results.push({kind: "raw-detector", mode, ...result, violations, errors, assets: requests.slice(requestStart)});
    if (baseline) {
      assert.ok(result.error, `${mode}: unpatched baseline should fail under strict CSP`);
      assert.ok(violations.some(value => value.blocked === "eval"), `${mode}: should reproduce eval CSP failure`);
    } else {
      assert.ok(!result.error, `${mode}: ${result.error}`);
      assert.ok(result.faceCount >= 1, `${mode}: face-positive fixture`);
      assert.equal(result.blankFaceCount, 0, `${mode}: blank fixture`);
      assert.deepEqual(violations, [], `${mode}: no CSP violations`);
    }
    await page.close();
    if (baseline) continue;

    const uploadPage = await browser.newPage();
    await uploadPage.goto(origin);
    await uploadPage.waitForFunction(() => window.testReady);
    const prewarmMs = await uploadPage.evaluate(() => window.prewarmDetector());
    const uploadResults = [];
    for (const kind of ["white", "white", "blank", "colored", "white"]) {
      const result = await uploadPage.evaluate(kind => window.verifyFixture(kind), kind);
      uploadResults.push({kind, ...result});
      assert.ok(!result.error, `${mode} ${kind}: ${result.error}`);
      assert.equal(result.type, "image/jpeg");
      assert.deepEqual(result.dimensions, [800, 1200]);
      assert.ok(result.bytes > 0 && result.bytes <= 2 * 1024 * 1024);
      assert.equal(result.validation.outcome, kind === "white" ? "pass" : "hard_failure");
      assert.equal(result.validation.facePresent, kind !== "blank");
      if (kind === "colored") assert.equal(result.validation.background.isLightNeutral, false);
    }
    const uploadViolations = await uploadPage.evaluate(() => window.testViolations);
    assert.deepEqual(uploadViolations, []);
    report.results.push({kind: "exact-output-validation", mode, prewarmMs, uploadResults, violations: uploadViolations});
    await uploadPage.close();
  }
  for (const scenario of baseline ? [] : selectedScenario ? [selectedScenario] : ["graph-http503", "graph-network-failure-delayed-loader", "loader-http522"]) {
    mode = "simd";
    failedModelRequests = scenario === "graph-http503" ? 1 : 0;
    delayedLoaderRequests = scenario === "graph-network-failure-delayed-loader" ? 1 : 0;
    failedLoaderRequests = scenario === "loader-http522" ? 1 : 0;
    const recoveryPage = await browser.newPage();
    const errors = [];
    const consoleErrors = [];
    recoveryPage.on("pageerror", error => errors.push(String(error)));
    recoveryPage.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
    if (scenario === "graph-network-failure-delayed-loader") {
      await recoveryPage.route("**/*.binarypb*", route => route.abort("failed"));
    }
    await recoveryPage.goto(origin);
    await recoveryPage.waitForFunction(() => window.testReady);
    const failedAttempt = await recoveryPage.evaluate(() => window.verifyFixture("white"));
    await recoveryPage.unroute("**/*.binarypb*");
    const retry = await recoveryPage.evaluate(() => window.verifyFixture("white"));
    await recoveryPage.waitForTimeout(600);
    const violations = await recoveryPage.evaluate(() => window.testViolations);
    report.results.push({kind: "transient-model-failure-recovery", scenario, failedAttempt, retry, violations, errors, consoleErrors});
    assert.ok(failedAttempt.error, "Failed model must reject rather than accept an unchecked image");
    assert.ok(failedAttempt.elapsedMs < 10_000, "Network failure must reject within a bounded timeout");
    assert.ok(!retry.error, `Retry after transient model failure: ${retry.error}`);
    assert.equal(retry.validation.outcome, "pass");
    assert.deepEqual(violations, []);
    assert.deepEqual(errors, [], "Network retry must not cause uncaught runtime errors");
    await recoveryPage.close();
  }
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = String(error); process.exitCode = 1;
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
  const reportPath = join(outputDirectory, baseline ? "baseline.json" : "verification.json");
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({
    passed: report.passed, baseline, browser: report.browser, failure: report.failure,
    results: report.results.map(({kind, mode, scenario, coldMs, warmMs, prewarmMs, uploadResults, failedAttempt, retry, error, violations, errors}) => ({
      kind, mode, scenario, coldMs, warmMs, prewarmMs, error, violations, errors,
      uploadResults: uploadResults?.map(({kind, elapsedMs, validation}) => ({kind, elapsedMs, outcome: validation?.outcome})),
      failedAttempt, retry,
    })),
  }, null, 2));
  console.log(`Report: ${reportPath}`);
}
