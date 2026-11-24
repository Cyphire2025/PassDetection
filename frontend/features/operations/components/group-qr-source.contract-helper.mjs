import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readGroupQrSource() {
  const read = file => readFileSync(new URL(file, import.meta.url), "utf8");
  const sources = new Map([
    ["./tour-group-qr-codes-page.tsx", read("./tour-group-qr-codes-page.tsx")],
    ["../hooks/use-group-qr-codes-controller.ts", read("../hooks/use-group-qr-codes-controller.ts")],
    ["../hooks/use-group-qr-images.ts", read("../hooks/use-group-qr-images.ts")],
    ["../hooks/use-passenger-qr-actions.ts", read("../hooks/use-passenger-qr-actions.ts")],
    ["./group-qr-codes-view.tsx", read("./group-qr-codes-view.tsx")],
    ["./group-qr-page-header.tsx", read("./group-qr-page-header.tsx")],
    ["./group-qr-model.ts", read("./group-qr-model.ts")],
    ["./qr-delivery-preview-dialog.tsx", read("./qr-delivery-preview-dialog.tsx")],
    ["./qr-delivery-status.tsx", read("./qr-delivery-status.tsx")],
    ["./passenger-qr-card.tsx", read("./passenger-qr-card.tsx")],
    ["./qr-status.ts", read("./qr-status.ts")],
  ]);
  const entry = sources.get("./tour-group-qr-codes-page.tsx");
  assert.match(entry, /import \{ useGroupQrCodesController \} from "\.\.\/hooks\/use-group-qr-codes-controller"/);
  assert.match(entry, /const model = useGroupQrCodesController\(groupId\)/);
  assert.match(entry, /import \{ GroupQrCodesView \} from "\.\/group-qr-codes-view"/);
  assert.match(entry, /<GroupQrCodesView model=\{model\}/);
  assert.match(entry, /export \{ QrDeliveryPreviewDialog \} from "\.\/qr-delivery-preview-dialog"/);
  const controller = sources.get("../hooks/use-group-qr-codes-controller.ts");
  assert.match(controller, /import \{ useGroupQrImages \} from "\.\/use-group-qr-images"/);
  assert.match(controller, /useGroupQrImages\(\{/);
  assert.match(controller, /import \{ usePassengerQrActions \} from "\.\/use-passenger-qr-actions"/);
  assert.match(controller, /usePassengerQrActions\(groupId\)/);
  const view = sources.get("./group-qr-codes-view.tsx");
  for (const [name, file] of [
    ["GroupQrPageHeader", "group-qr-page-header"],
    ["PassengerQrCard", "passenger-qr-card"],
    ["QrDeliveryPreviewDialog", "qr-delivery-preview-dialog"],
  ]) {
    assert.ok(view.includes(`import { ${name} } from "./${file}"`));
    assert.match(view, new RegExp(`<${name}\\b`));
    assert.ok(sources.get(`./${file}.tsx`).includes(`export function ${name}(`));
  }
  const dialog = sources.get("./qr-delivery-preview-dialog.tsx");
  assert.match(dialog, /import \{ QrDeliverySummary, QrDeliveryPreviewStatus \} from "\.\/qr-delivery-status"/);
  assert.match(dialog, /<QrDeliverySummary\b/);
  assert.match(dialog, /<QrDeliveryPreviewStatus\b/);
  for (const file of ["./group-qr-codes-view.tsx", "../hooks/use-group-qr-codes-controller.ts", "../hooks/use-group-qr-images.ts"]) {
    assert.match(sources.get(file), /from "(?:\.\/|\.\.\/components\/)group-qr-model"/);
  }
  assert.match(sources.get("./passenger-qr-card.tsx"), /from "\.\/qr-status"/);
  assert.match(sources.get("./qr-delivery-status.tsx"), /from "\.\/qr-status"/);
  return [...sources.values()].join("\n");
}
