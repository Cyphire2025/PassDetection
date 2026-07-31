import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  createQrImageGenerator,
  generateQrImageEntries,
  planQrImageGeneration,
  QR_IMAGE_GENERATION_CONCURRENCY,
} from "./qr-image-generation.ts";

const page = readFileSync(
  new URL("../components/tour-group-qr-codes-page.tsx", import.meta.url),
  "utf8",
);
const generator = readFileSync(
  new URL("./qr-image-generation.ts", import.meta.url),
  "utf8",
);

test("QR rasterization preserves order and never exceeds the worker limit", async () => {
  const entries = Array.from(
    { length: 12 },
    (_, index) => [`passenger-${index}`, `payload-${index}`],
  );
  let active = 0;
  let peak = 0;

  const images = await generateQrImageEntries(entries, {
    renderPayload: async (payload) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active -= 1;
      return `data:image/png;base64,${payload}`;
    },
  });

  assert.equal(peak, QR_IMAGE_GENERATION_CONCURRENCY);
  assert.deepEqual(
    images,
    entries.map(([passengerId, payload]) => [
      passengerId,
      `data:image/png;base64,${payload}`,
    ]),
  );
});

test("the QR library is lazy-loaded and the page no longer fans out every rasterization", () => {
  assert.doesNotMatch(page, /import\s+QRCode\s+from\s+["']qrcode["']/);
  assert.match(generator, /import\("qrcode"\)/);
  assert.match(page, /createQrImageGenerator\(\)/);
  assert.match(page, /planQrImageGeneration\(/);
  assert.doesNotMatch(page, /Promise\.all\(\s*revealed\.map/s);
});

test("one component generator enforces the worker limit across overlapping generations", async () => {
  let active = 0;
  let peak = 0;
  const sharedGenerator = createQrImageGenerator({
    renderPayload: async (payload) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active -= 1;
      return `data:image/png;base64,${payload}`;
    },
  });
  const first = sharedGenerator.generate(
    Array.from({ length: 8 }, (_, index) => [
      `first-${index}`,
      `first-payload-${index}`,
    ]),
  );
  const second = sharedGenerator.generate(
    Array.from({ length: 8 }, (_, index) => [
      `second-${index}`,
      `second-payload-${index}`,
    ]),
  );

  const [firstResult, secondResult] = await Promise.all([first, second]);

  assert.equal(peak, QR_IMAGE_GENERATION_CONCURRENCY);
  assert.equal(firstResult.entries.length, 8);
  assert.equal(secondResult.entries.length, 8);
});

test("cached payloads are reused while changed payloads alone are regenerated", () => {
  const cache = new Map([
    [
      "passenger-1",
      {
        payload: "unchanged-payload",
        imageUrl: "data:image/png;base64,cached",
      },
    ],
    [
      "passenger-2",
      {
        payload: "old-payload",
        imageUrl: "data:image/png;base64,stale",
      },
    ],
  ]);

  const plan = planQrImageGeneration(
    [
      ["passenger-1", "unchanged-payload"],
      ["passenger-2", "new-payload"],
    ],
    cache,
  );

  assert.deepEqual(plan.cachedEntries, [
    ["passenger-1", "data:image/png;base64,cached"],
  ]);
  assert.deepEqual(plan.pendingEntries, [
    ["passenger-2", "new-payload"],
  ]);
});

test("one failed QR does not discard successful progressive results", async () => {
  const progressiveEntries = [];
  const sharedGenerator = createQrImageGenerator({
    renderPayload: async (payload) => {
      if (payload === "bad-payload") throw new Error("invalid QR payload");
      return `data:image/png;base64,${payload}`;
    },
  });

  const result = await sharedGenerator.generate(
    [
      ["passenger-1", "good-payload"],
      ["passenger-2", "bad-payload"],
      ["passenger-3", "other-good-payload"],
    ],
    {
      onEntry: (entry) => progressiveEntries.push(entry),
    },
  );

  assert.deepEqual(result.failedPassengerIds, ["passenger-2"]);
  assert.deepEqual(result.entries, [
    ["passenger-1", "data:image/png;base64,good-payload"],
    ["passenger-3", "data:image/png;base64,other-good-payload"],
  ]);
  assert.deepEqual(progressiveEntries, result.entries);
});
