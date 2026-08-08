import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const tracker = read("./whatsapp-activity-tracker.tsx");
const activityApi = read("../api/whatsapp-activity.api.ts");
const trackingUtils = read("../utils/activity-tracking.ts");
const workspace = read("./whatsapp-workspace.tsx");
const recipientDialog = read("./whatsapp-recipient-dialog.tsx");
const dashboardLayout = read("../../../app/(dashboard)/layout.tsx");
const documentWorkspace = read("../../documents/components/document-workspace.tsx");
const qrWorkspace = read("../../operations/components/tour-group-qr-codes-page.tsx");
const endpoints = read("../../../lib/api/endpoints.ts");

test("dashboard owns one durable cross-route WhatsApp activity provider", () => {
  assert.match(dashboardLayout, /<WhatsAppActivityTrackerProvider>/);
  assert.match(tracker, /window\.sessionStorage\.getItem/);
  assert.match(tracker, /parseLegacyWhatsAppBatch/);
  assert.match(tracker, /useQueries\(\{/);
  assert.match(tracker, /whatsappBatchPollInterval/);
  assert.match(tracker, /refetchIntervalInBackground: true/);
  assert.match(trackingUtils, /passdetection:whatsapp:tracked-activities:v1/);
});

test("all send entry points register their durable batch IDs", () => {
  assert.match(workspace, /kind: "broadcast"/);
  assert.match(workspace, /id: result\.batch_id/);
  assert.match(recipientDialog, /kind: "broadcast"/);
  assert.match(recipientDialog, /id: result\.batch_id/);
  assert.match(documentWorkspace, /kind: "document"/);
  assert.match(documentWorkspace, /id: result\.send_batch_id/);
  assert.match(qrWorkspace, /kind: "qr"/);
  assert.match(qrWorkspace, /id: result\.send_batch_id/);
  assert.match(documentWorkspace, /<WhatsAppActivityInline \/>/);
  assert.match(qrWorkspace, /<WhatsAppActivityInline \/>/);
  assert.match(workspace, /<WhatsAppActivityInline \/>/);
});

test("live counts retain the action and passenger label registered by the sender", () => {
  assert.match(tracker, /title: activity\.title/);
  assert.match(tracker, /context_label: activity\.contextLabel/);
  assert.match(recipientDialog, /target\.recipientName/);
  assert.match(recipientDialog, /target\.action/);
});

test("floating progress hides on sender pages and remains draggable elsewhere", () => {
  assert.match(tracker, /!isWhatsAppBroadcastSourcePath\(pathname\)/);
  assert.match(tracker, /createPortal\(/);
  assert.match(tracker, /setPointerCapture/);
  assert.match(tracker, /releasePointerCapture/);
  assert.match(tracker, /clampPosition\(/);
  assert.match(tracker, /WHATSAPP_ACTIVITY_POSITION_KEY/);
  assert.match(tracker, /DRAG_INTENT_THRESHOLD_PX/);
  assert.match(tracker, /target\.closest\(DRAG_EXCLUSION_SELECTOR\)/);
  assert.match(tracker, /onClickCapture=\{suppressClickAfterDrag\}/);
  assert.doesNotMatch(tracker, /GripVertical/);
  assert.doesNotMatch(tracker, /data-whatsapp-activity-drag-handle/);
  assert.match(tracker, /Hide until the next broadcast starts/);
});

test("floating progress uses a green capsule while inline progress remains unchanged", () => {
  assert.match(tracker, /border-emerald-200 bg-emerald-50/);
  assert.match(tracker, /variant === "floating" \? "bg-emerald-100" : "bg-slate-100"/);
  assert.match(tracker, /touch-pan-y select-text/);
  assert.match(tracker, /data-whatsapp-activity-no-drag/);
});

test("failed names load only after the failure arrow is expanded", () => {
  assert.match(tracker, /activity\.failed > 0 \? \(/);
  assert.match(tracker, /enabled: showFailures && activity\.failed > 0/);
  assert.match(tracker, /Failed recipients/);
  assert.match(tracker, /failure\.recipient_name/);
  assert.match(activityApi, /whatsappActivityApi/);
  assert.match(endpoints, /activities\/\$\{kind\}\/\$\{batchId\}\/failures/);
});

test("current recipients expose deferred passenger search with a recoverable empty state", () => {
  assert.match(recipientDialog, /useDeferredValue\(recipientSearchQuery\)/);
  assert.match(recipientDialog, /searchRecipientRosterItems\(/);
  assert.match(recipientDialog, /aria-label="Search current recipients"/);
  assert.match(recipientDialog, /No recipients match/);
});
