import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("./passport-extraction.js", import.meta.url), "utf8");

function loadHarness(vu = 1) {
  const requests = [];
  const metrics = new Map();
  const randomSizes = [];
  const manifest = Array.from({ length: 100 }, (_, index) => ({
    front: "synthetic-front-" + index,
    back: "synthetic-back-" + index,
  }));
  class Metric {
    constructor(name) {
      this.values = [];
      metrics.set(name, this.values);
    }
    add(value) {
      this.values.push(value);
    }
  }
  const response = (status, payload) => ({
    status,
    json: (key) => key ? payload[key] : payload,
  });
  const http = {
    file: (bytes, name, contentType) => ({ bytes, name, contentType }),
    get(url, params) {
      requests.push({ method: "GET", url, params });
      return response(200, url.endsWith("/status")
        ? { id: "00000000-0000-4000-8000-000000000001", extraction_status: "extraction_complete" }
        : {});
    },
    post(url, body, params) {
      requests.push({ method: "POST", url, body, params });
      return response(201, {
        id: "00000000-0000-4000-8000-000000000001",
        extraction_status: "queued",
      });
    },
  };
  const sandbox = {
    __ENV: { BASE_URL: "https://staging.example.test", UPLOAD_TOKEN: "synthetic-link" },
    __VU: vu,
    __ITER: 0,
    Date: { now: () => 1_800_000_000_000 },
    open: (path, mode) => mode === "b" ? new Uint8Array([1, 2, 3]).buffer : JSON.stringify(manifest),
    check: (value, checks) => Object.values(checks).every((check) => check(value)),
    fail: (message) => { throw new Error(message); },
    sleep: () => {},
    Counter: Metric,
    Rate: Metric,
    Trend: Metric,
    http,
    crypto: {
      randomBytes(size) {
        randomSizes.push(size);
        return Uint8Array.from(randomBytes(size)).buffer;
      },
    },
    encoding: {
      b64encode: (bytes, encoding) => {
        assert.equal(encoding, "rawurl");
        return Buffer.from(bytes).toString("base64url");
      },
    },
    module: { exports: {} },
  };
  // Execute the actual complete k6 script with only module declarations
  // adapted to vm.Script. k6 imports/transport/metrics are explicit test ports;
  // no workload statements, requests, keys, polling or outcomes are replaced.
  const executable = source
    .replace(/^import .* from "k6(?:\/[^"]+)?";\r?$/gm, "")
    .replace(/^export const /gm, "const ")
    .replace("export default function ()", "function passportUser()");
  assert.ok(executable.includes("function passportUser()"));
  vm.runInNewContext(executable + "\nmodule.exports = { run: passportUser, options };", sandbox);
  return { ...sandbox.module.exports, requests, metrics, randomSizes };
}

test("upload attempt uses a valid cryptographically random capability", () => {
  const harness = loadHarness();
  harness.run();
  const upload = harness.requests.find((request) => request.method === "POST");
  assert.match(upload.body.upload_idempotency_key, /^[A-Za-z0-9._:-]{32,128}$/);
  assert.equal(upload.params.headers["X-Upload-Session-ID"], upload.body.upload_idempotency_key);
  assert.deepEqual(harness.randomSizes, [32]);
});

test("status polling retains the private upload credential", () => {
  const harness = loadHarness();
  harness.run();
  const upload = harness.requests.find((request) => request.method === "POST");
  const poll = harness.requests.find((request) => request.url.endsWith("/status"));
  assert.equal(poll.params.headers["X-Upload-Session-ID"], upload.body.upload_idempotency_key);
  assert.notEqual(poll.params.headers["X-Upload-Session-ID"], "00000000-0000-4000-8000-000000000001");
});

test("the tenth virtual user replays its exact upload and records one completion", () => {
  const harness = loadHarness(10);
  harness.run();
  const uploads = harness.requests.filter((request) => request.method === "POST");
  assert.equal(uploads.length, 2);
  assert.deepEqual(uploads[1].body, uploads[0].body);
  assert.deepEqual(uploads[1].params.headers, uploads[0].params.headers);
  assert.equal(harness.metrics.get("successful_extractions").length, 1);
  assert.equal(harness.metrics.get("duplicate_submissions").length, 0);
  assert.equal(harness.metrics.get("failed_extractions").length, 0);
});

test("attempt identities remain distinct with the same virtual user and clock", () => {
  const harness = loadHarness();
  harness.run();
  harness.run();
  const uploads = harness.requests.filter((request) => request.method === "POST");
  assert.notEqual(uploads[0].body.upload_idempotency_key, uploads[1].body.upload_idempotency_key);
});

test("metric tags omit bearer URLs and use fixed request names", () => {
  const harness = loadHarness(10);
  harness.run();
  assert.ok(Array.isArray(harness.options.systemTags));
  assert.ok(!harness.options.systemTags.includes("url"));
  assert.ok(!harness.options.systemTags.includes("error"));
  for (const request of harness.requests) {
    assert.ok(request.params.tags.name);
    assert.ok(!request.params.tags.name.includes("synthetic-link"));
    assert.ok(!request.params.tags.name.includes("00000000-0000-4000-8000-000000000001"));
  }
});
