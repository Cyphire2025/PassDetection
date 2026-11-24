import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const trackerSource = readFileSync(
  new URL("./activity-tracker/use-tracked-activities.ts", import.meta.url),
  "utf8",
);
const providerSource = readFileSync(
  new URL("./whatsapp-activity-tracker.tsx", import.meta.url),
  "utf8",
);

test("batch summary 404 stops retries and interval polling", () => {
  assert.match(providerSource, /from "\.\/activity-tracker\/use-tracked-activities"/);
  assert.match(providerSource, /useTrackedActivities\(\)/);
  assert.match(trackerSource, /retry:\s*\(failureCount: number, error: unknown\)/);
  assert.match(trackerSource, /shouldRetryWhatsAppBatchStatus/);
  assert.match(trackerSource, /whatsappBatchHttpStatus\(error\)/);
  assert.match(
    trackerSource,
    /isTerminalWhatsAppBatchStatus\(\s*whatsappBatchHttpStatus\(query\.state\.error\),\s*\)[\s\S]*return false/,
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
