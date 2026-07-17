import assert from "node:assert/strict";
import test from "node:test";
import {
  EXTRACTION_POLL_FAILURE_MAX_DELAY_MS,
  EXTRACTION_POLL_INITIAL_DELAY_MS,
  EXTRACTION_POLL_WINDOW_MS,
  isTransientExtractionPollError,
  nextExtractionPollDelay,
} from "./extraction-polling.ts";

test("keeps a full reconciliation window for the bounded backend pipeline", () => {
  assert.equal(EXTRACTION_POLL_WINDOW_MS, 65_000);
  assert.equal(EXTRACTION_POLL_INITIAL_DELAY_MS, 700);
});

test("backs off transient status failures instead of abandoning after four polls", () => {
  let delay = EXTRACTION_POLL_INITIAL_DELAY_MS;
  const observed = [];

  for (let failure = 0; failure < 8; failure += 1) {
    delay = nextExtractionPollDelay(delay, "failure");
    observed.push(delay);
  }

  assert.equal(observed[0], 1_200);
  assert.ok(observed[2] < EXTRACTION_POLL_FAILURE_MAX_DELAY_MS);
  assert.equal(observed.at(-1), EXTRACTION_POLL_FAILURE_MAX_DELAY_MS);
});

test("successful reconciliation returns to the normal polling cadence", () => {
  assert.equal(nextExtractionPollDelay(5_000, "success"), 1_600);
  assert.equal(nextExtractionPollDelay(Number.NaN, "success"), 850);
});

test("retries only connection, timeout, throttling, and server failures", () => {
  assert.equal(isTransientExtractionPollError({ code: "NETWORK_ERROR" }), true);
  assert.equal(isTransientExtractionPollError({ code: "REQUEST_TIMEOUT" }), true);
  assert.equal(isTransientExtractionPollError({ code: "HTTP_429" }), true);
  assert.equal(isTransientExtractionPollError({ code: "HTTP_503" }), true);
  assert.equal(isTransientExtractionPollError({ code: "HTTP_404" }), false);
  assert.equal(isTransientExtractionPollError({ code: "AUTH_SESSION_EXPIRED" }), false);
});
