import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(
  new URL("./whatsapp-workspace.tsx", import.meta.url),
  "utf8",
);
const hooksSource = readFileSync(
  new URL("../hooks/use-whatsapp.ts", import.meta.url),
  "utf8",
);

test("batch summary 404 stops retries and interval polling", () => {
  assert.match(hooksSource, /retry:\s*\(failureCount, error\)/);
  assert.match(hooksSource, /shouldRetryWhatsAppBatchStatus/);
  assert.match(hooksSource, /whatsappBatchHttpStatus\(error\)/);
  assert.match(
    hooksSource,
    /isMissingWhatsAppBatchError\(query\.state\.error\)\) return false/,
  );
});

test("a missing active batch clears only matching local progress", () => {
  assert.match(
    hooksSource,
    /if \(batchId && isMissingWhatsAppBatchError\(error\)\)/,
  );
  assert.match(hooksSource, /onMissingBatch\?\.\(batchId\)/);
  assert.match(pageSource, /clearMissingBatchTracking/);
  assert.match(
    pageSource,
    /current\?\.batch_id === missingBatchId \? null : current/,
  );
  assert.match(pageSource, /current\?\.id === missingBatchId \? null : current/);
  assert.match(pageSource, /storedBatch\.id === missingBatchId/);
  assert.match(
    pageSource,
    /sessionStorage\.removeItem\(LAST_BATCH_STORAGE_KEY\)/,
  );
});
