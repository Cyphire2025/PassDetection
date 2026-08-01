import assert from "node:assert/strict";
import test from "node:test";

import {
  WHATSAPP_BATCH_FAST_POLL_MS,
  WHATSAPP_BATCH_MAX_POLL_MS,
  WHATSAPP_BATCH_MEDIUM_POLL_MS,
  WHATSAPP_BATCH_SLOW_POLL_MS,
  WHATSAPP_BATCH_TRANSIENT_RETRY_LIMIT,
  isMissingWhatsAppBatchStatus,
  shouldRetryWhatsAppBatchStatus,
  whatsappBatchHttpStatus,
  whatsappBatchPollInterval,
} from "./batch-polling.ts";

const startedAt = Date.UTC(2026, 7, 1, 0, 0, 0);

test("terminal batch responses stop polling", () => {
  assert.equal(whatsappBatchPollInterval(0, startedAt, startedAt), false);
  assert.equal(whatsappBatchPollInterval(-1, startedAt, startedAt), false);
});

test("queued batches back off within a bounded interval", () => {
  assert.equal(
    whatsappBatchPollInterval(1, startedAt, startedAt),
    WHATSAPP_BATCH_FAST_POLL_MS,
  );
  assert.equal(
    whatsappBatchPollInterval(1, startedAt, startedAt + 2 * 60_000),
    WHATSAPP_BATCH_MEDIUM_POLL_MS,
  );
  assert.equal(
    whatsappBatchPollInterval(1, startedAt, startedAt + 10 * 60_000),
    WHATSAPP_BATCH_SLOW_POLL_MS,
  );
  assert.equal(
    whatsappBatchPollInterval(1, startedAt, startedAt + 31 * 60_000),
    WHATSAPP_BATCH_MAX_POLL_MS,
  );
});

test("old queued batches keep polling instead of expiring locally", () => {
  assert.equal(
    whatsappBatchPollInterval(1, startedAt, startedAt + 24 * 60 * 60_000),
    WHATSAPP_BATCH_MAX_POLL_MS,
  );
  assert.equal(
    whatsappBatchPollInterval(undefined, startedAt, startedAt + 24 * 60 * 60_000),
    WHATSAPP_BATCH_MAX_POLL_MS,
  );
  assert.equal(
    whatsappBatchPollInterval(1, null, startedAt),
    WHATSAPP_BATCH_MAX_POLL_MS,
  );
});

test("missing batch responses are terminal", () => {
  assert.equal(whatsappBatchHttpStatus({ code: "HTTP_404" }), 404);
  assert.equal(whatsappBatchHttpStatus({ response: { status: 404 } }), 404);
  assert.equal(isMissingWhatsAppBatchStatus(404), true);
  assert.equal(shouldRetryWhatsAppBatchStatus(0, 404), false);
  assert.equal(shouldRetryWhatsAppBatchStatus(2, 404), false);
});

test("network and server failures retain bounded retries", () => {
  assert.equal(whatsappBatchHttpStatus({ code: "NETWORK_ERROR" }), undefined);
  assert.equal(whatsappBatchHttpStatus({ code: "HTTP_503" }), 503);
  assert.equal(isMissingWhatsAppBatchStatus(undefined), false);
  assert.equal(shouldRetryWhatsAppBatchStatus(0, undefined), true);
  assert.equal(shouldRetryWhatsAppBatchStatus(1, 500), true);
  assert.equal(
    shouldRetryWhatsAppBatchStatus(
      WHATSAPP_BATCH_TRANSIENT_RETRY_LIMIT,
      503,
    ),
    false,
  );
});
