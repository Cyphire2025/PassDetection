import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const trackerSource = readFileSync(
  new URL("./whatsapp-activity-tracker.tsx", import.meta.url),
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

test("a missing tracked activity clears only its persisted progress", () => {
  assert.match(
    trackerSource,
    /isMissingWhatsAppBatchStatus\(whatsappBatchHttpStatus\(error\)\)/,
  );
  assert.match(
    trackerSource,
    /const missingKey = whatsappActivityKey\(activity\)/,
  );
  assert.match(
    trackerSource,
    /current\.filter\([\s\S]*whatsappActivityKey\(candidate\) !== missingKey/,
  );
  assert.match(trackerSource, /WHATSAPP_ACTIVITY_STORAGE_KEY/);
  assert.match(trackerSource, /JSON\.stringify\(trackedActivities\)/);
});
