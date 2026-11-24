import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

test("offline runtime installation bypasses old HTTP cache and caches only the public allowlist", async () => {
  const handlers = new Map();
  let requested = [];
  let installed;
  runInNewContext(readFileSync(new URL("../../../public/sw.js", import.meta.url), "utf8"), {
    self: { location: { origin: "https://offline-fixture.example.test" }, addEventListener: (name, handler) => handlers.set(name, handler), skipWaiting() {} },
    caches: { open: async () => ({ addAll: async (requests) => { requested = [...requests]; } }) },
    URL, Request, Set, Promise,
  });
  handlers.get("install")({ waitUntil: (promise) => { installed = promise; } });
  await installed;
  assert.deepEqual(requested.map((request) => new URL(request.url ?? request, "https://offline-fixture.example.test").pathname), [
    "/offline.html", "/offline-scanner.js", "/offline/vendor/zxing-browser.min.js",
  ]);
  assert.ok(requested.every((request) => request.cache === "reload"));
});
