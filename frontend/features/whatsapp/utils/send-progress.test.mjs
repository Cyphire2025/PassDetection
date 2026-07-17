import assert from "node:assert/strict";
import test from "node:test";
import { mergeWhatsAppSendProgress } from "./send-progress.ts";

const response = (overrides = {}) => ({
  batch_id: "batch-1",
  queued: 0,
  sent: 0,
  failed: 0,
  delivery_unknown: 0,
  skipped_already_sent: 0,
  skipped_in_progress: 0,
  skipped_delivery_unknown: 0,
  results: [],
  ...overrides,
});

test("preserves initial skip counts when batch polling reports only delivery outcomes", () => {
  const initial = response({
    queued: 2,
    skipped_already_sent: 3,
    skipped_in_progress: 1,
    skipped_delivery_unknown: 2,
  });
  const current = response({ sent: 1, delivery_unknown: 1 });

  assert.deepEqual(mergeWhatsAppSendProgress(current, initial), {
    ...current,
    skipped_already_sent: 3,
    skipped_in_progress: 1,
    skipped_delivery_unknown: 2,
  });
});

test("restores skip counts from session state after a page reload", () => {
  const current = response({ sent: 4 });
  const persisted = {
    skipped_already_sent: 2,
    skipped_in_progress: 1,
    skipped_delivery_unknown: 1,
  };

  const merged = mergeWhatsAppSendProgress(current, null, persisted);
  assert.equal(merged.skipped_already_sent, 2);
  assert.equal(merged.skipped_in_progress, 1);
  assert.equal(merged.skipped_delivery_unknown, 1);
});
