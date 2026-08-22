import assert from "node:assert/strict";
import test from "node:test";
import {
  parseRetryAfterMs,
  retryAfterHeaderValue,
} from "./retry-after.ts";

test("Retry-After supports delta seconds without allowing an aggressive retry", () => {
  assert.equal(parseRetryAfterMs("12"), 12_000);
  assert.equal(parseRetryAfterMs("0.5"), 500);
});

test("Retry-After supports HTTP dates and bounds untrusted delays", () => {
  const now = Date.parse("2026-08-22T10:00:00.000Z");
  assert.equal(
    parseRetryAfterMs("Sat, 22 Aug 2026 10:00:30 GMT", now),
    30_000,
  );
  assert.equal(parseRetryAfterMs("999999", now), 15 * 60 * 1_000);
  assert.equal(parseRetryAfterMs("not-a-date", now), undefined);
});

test("Retry-After is read from AxiosHeaders and plain header records", () => {
  assert.equal(retryAfterHeaderValue({ get: () => "17" }), "17");
  assert.equal(retryAfterHeaderValue({ "retry-after": "23" }), "23");
});
