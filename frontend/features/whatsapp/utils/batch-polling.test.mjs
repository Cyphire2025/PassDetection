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
  whatsappActivityPollInterval,
  whatsappAwaitingReceiptCount,
  whatsappRecipientPollInterval,
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

test("dispatch completion keeps checking provider acceptance and late failure receipts", () => {
  assert.equal(whatsappActivityPollInterval(0, { submitted: 10 }, startedAt, 10, 0, startedAt), 2_000);
  assert.equal(whatsappActivityPollInterval(0, { sent: 9, failed: 1 }, startedAt, 9, 0, startedAt + 90_000), 5_000);
  assert.equal(whatsappActivityPollInterval(0, { delivered: 7, failed: 3 }, startedAt, 7, 0, startedAt + 120_000), false);
  assert.equal(whatsappAwaitingReceiptCount({ submitted: 2, sent: 3, delivered: 4, read: 1 }, 10), 5);
  assert.equal(whatsappAwaitingReceiptCount(undefined, 10), 10);
});

test("receipt checks are bounded, including uncertain outcomes and missing timing metadata", () => {
  assert.equal(whatsappActivityPollInterval(0, { delivery_unknown: 1 }, startedAt, 0, 1, startedAt + 60_000), 5_000);
  assert.equal(whatsappActivityPollInterval(0, { sent: 10 }, startedAt, 10, 0, startedAt + 30 * 60_000), false);
  assert.equal(whatsappActivityPollInterval(0, { sent: 10 }, NaN, 10, 0, startedAt), false);
  assert.equal(whatsappBatchPollInterval(1, NaN, startedAt), 30_000);
});

test("open rosters reconcile ordinary sends and resends without rapid perpetual polling", () => {
  const roster = (status, latest_resend_status = null, age = 0) => [{ message_statuses: [{
    status, latest_resend_status, status_updated_at: new Date(startedAt - age).toISOString(),
  }] }];
  assert.equal(whatsappRecipientPollInterval(roster("submitted"), startedAt), 2_000);
  assert.equal(whatsappRecipientPollInterval(roster("sent", null, 90_000), startedAt), 5_000);
  assert.equal(whatsappRecipientPollInterval(roster("delivered", "submitted"), startedAt), 2_000);
  assert.equal(whatsappRecipientPollInterval(roster("delivered", "queued", 31 * 60_000), startedAt), 30_000);
  assert.equal(whatsappRecipientPollInterval(roster("sent", null, 31 * 60_000), startedAt), false);
  assert.equal(whatsappRecipientPollInterval(roster("failed"), startedAt), false);
});
