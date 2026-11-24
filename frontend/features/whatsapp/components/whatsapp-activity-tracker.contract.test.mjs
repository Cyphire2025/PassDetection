import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { readComposerControllerSource, readRecipientWorkspaceSource } from "./whatsapp-source.contract-helper.mjs";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const tracker = read("./whatsapp-activity-tracker.tsx");
const trackerState = read("./activity-tracker/use-tracked-activities.ts");
const trackerStorage = read("./activity-tracker/storage.ts");
const floating = read("./activity-tracker/floating-overlay.tsx");
const activityRow = read("./activity-tracker/row.tsx");
const failures = read("./activity-tracker/failure-recipients.tsx");
const activityApi = read("../api/whatsapp-activity.api.ts");
const trackingUtils = read("../utils/activity-tracking.ts");
const composer = readComposerControllerSource();
const updateComposer = read("../workspace/use-trip-update-composer.ts");
const documentComposer = read("../workspace/use-document-composer.ts");
const recipients = readRecipientWorkspaceSource();
const resend = read("../workspace/historical-resend-dialog.tsx");
const dashboardLayout = read("../../../app/(dashboard)/layout.tsx");
const documentDelivery = read("../../documents/hooks/use-document-workspace-delivery.ts");
const documentHeader = read("../../documents/components/document-workspace-header.tsx");
const qrWorkspace = read("../../operations/components/tour-group-qr-codes-page.tsx");
const qrController = read("../../operations/hooks/use-group-qr-codes-controller.ts");
const qrView = read("../../operations/components/group-qr-codes-view.tsx");
const qrHeader = read("../../operations/components/group-qr-page-header.tsx");
const endpoints = read("../../../lib/api/endpoints.ts");

test("dashboard owns one durable cross-route WhatsApp activity provider", () => {
  assert.match(dashboardLayout, /<WhatsAppActivityTrackerProvider>/);
  assert.match(tracker, /from "\.\/activity-tracker\/use-tracked-activities"/);
  assert.match(trackerState, /from "\.\/storage"/);
  assert.match(trackerStorage, /window\.sessionStorage\.getItem/);
  assert.match(trackerStorage, /parseLegacyWhatsAppBatch/);
  assert.match(trackerState, /useQueries\(\{/);
  assert.match(trackerState, /whatsappActivityPollInterval/);
  assert.match(trackerState, /refetchIntervalInBackground: false/);
  assert.match(trackerState, /refetchOnWindowFocus: "always"/);
  assert.match(trackingUtils, /passdetection:whatsapp:tracked-activities:v1/);
});

test("the current composer and update sender register their durable broadcast IDs", () => {
  assert.match(read("../workspace/trip-update-composer.tsx"), /useTripUpdateComposer\(groupId\)/);
  assert.match(read("../workspace/update-message-composer.tsx"), /<TripUpdateComposer key=\{groupId\}/);
  assert.match(read("../workspace/document-composer.tsx"), /useDocumentComposer\(props\)/);
  assert.match(composer, /kind: "broadcast"/);
  assert.match(composer, /id: result\.batch_id/);
  assert.match(updateComposer, /kind: "broadcast"/);
  assert.match(updateComposer, /id: batch\.batch_id/);
  assert.match(qrWorkspace, /from "\.\.\/hooks\/use-group-qr-codes-controller"/);
  assert.match(qrWorkspace, /useGroupQrCodesController\(groupId\)/);
  assert.match(qrWorkspace, /from "\.\/group-qr-codes-view"/);
  assert.match(qrWorkspace, /<GroupQrCodesView model=\{model\} \/>/);
  assert.match(qrController, /const \{ registerActivity \} = useWhatsAppActivityTracker\(\)/);
  assert.match(qrView, /from "\.\/group-qr-page-header"/);
  assert.match(qrView, /<GroupQrPageHeader model=\{model\} \/>/);
  for (const source of [documentComposer, documentDelivery, qrView]) {
    assert.match(source, /id: result\.send_batch_id/);
  }
  assert.match(documentComposer, /kind: "document"/);
  assert.match(documentDelivery, /kind: "document"/);
  assert.match(qrView, /kind: "qr"/);
  assert.match(documentHeader, /<WhatsAppActivityInline \/>/);
  assert.match(qrHeader, /<WhatsAppActivityInline \/>/);
});

test("registered activity preserves the message and group labels while historical resend refreshes its history", () => {
  assert.match(trackerState, /title: activity\.title/);
  assert.match(trackerState, /context_label: activity\.contextLabel/);
  assert.match(composer, /title: definition\.label/);
  assert.match(composer, /contextLabel: group\.name/);
  assert.match(resend, /queryKey: \["whatsapp", "history", groupId\]/);
});

test("floating progress hides on sender pages and remains draggable elsewhere", () => {
  assert.match(tracker, /!isWhatsAppBroadcastSourcePath\(pathname\)/);
  assert.match(tracker, /createPortal\(/);
  assert.match(tracker, /from "\.\/activity-tracker\/floating-overlay"/);
  assert.match(floating, /setPointerCapture/);
  assert.match(floating, /releasePointerCapture/);
  assert.match(floating, /clampPosition\(/);
  assert.match(floating, /WHATSAPP_ACTIVITY_POSITION_KEY/);
  assert.match(floating, /DRAG_INTENT_THRESHOLD_PX/);
  assert.match(floating, /target\.closest\(DRAG_EXCLUSION_SELECTOR\)/);
  assert.match(floating, /onClickCapture=\{suppressClickAfterDrag\}/);
  assert.doesNotMatch(floating, /GripVertical/);
  assert.doesNotMatch(floating, /data-whatsapp-activity-drag-handle/);
  assert.match(activityRow, /Hide until the next broadcast starts/);
});

test("floating progress uses a green capsule while inline progress remains unchanged", () => {
  assert.match(activityRow, /border-emerald-200 bg-emerald-50/);
  assert.match(activityRow, /variant === "floating" \? "bg-emerald-100" : "bg-slate-100"/);
  assert.match(failures, /touch-pan-y select-text/);
  assert.match(failures, /data-whatsapp-activity-no-drag/);
});

test("failed names load only after the failure arrow is expanded", () => {
  assert.match(floating, /from "\.\/row"/);
  assert.match(activityRow, /from "\.\/failure-recipients"/);
  assert.match(activityRow, /activity\.failed > 0 \? \(/);
  assert.match(activityRow, /enabled: showFailures && activity\.failed > 0/);
  assert.match(failures, /Failed recipients/);
  assert.match(failures, /failure\.recipient_name/);
  assert.match(activityApi, /whatsappActivityApi/);
  assert.match(endpoints, /activities\/\$\{kind\}\/\$\{batchId\}\/failures/);
});

test("current recipients expose deferred passenger search and a recoverable empty state", () => {
  assert.match(recipients, /useDeferredValue\(search\)/);
  assert.match(recipients, /Object\.values\(person\.fields\)/);
  assert.match(recipients, /label="Search recipients"/);
  assert.match(recipients, /Try another search or change the recipient filter/);
});
