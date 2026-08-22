import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./query-provider.tsx", import.meta.url), "utf8");

test("rate-limited reads are never amplified by automatic query retries", () => {
  assert.match(source, /code\.includes\("RATE_LIMITED"\)/);
  assert.match(source, /status >= 400 && status < 500/);
  assert.match(source, /retry: \(failureCount, error\) => shouldRetryQuery/);
});
