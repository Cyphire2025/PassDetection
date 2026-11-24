import { expect, it } from "vitest";
import { initialWhatsAppActivitySummary, parseLegacyWhatsAppBatch, parseTrackedWhatsAppActivities, type TrackedWhatsAppActivity } from "./activity-tracking";

const activity: TrackedWhatsAppActivity = {
  id: "synthetic-batch", kind: "broadcast", startedAt: 1_789_000_000_000,
  title: "Synthetic broadcast", contextLabel: "Synthetic group", sourceGroupId: "synthetic-group",
  documentType: null, total: 1, queued: 1, sent: 0, failed: 0, deliveryUnknown: 0,
};

it.each([1e20, -1, Infinity, NaN])("isolates an invalid persisted timestamp %s without breaking valid progress", (startedAt) => {
  const parsed = parseTrackedWhatsAppActivities(JSON.stringify([{ ...activity, id: "invalid", startedAt }, activity]));
  expect(parsed.map((item) => item.id)).toEqual([activity.id]);
  expect(() => parsed.map(initialWhatsAppActivitySummary)).not.toThrow();
});

it("recovers an out-of-range legacy timestamp before creating a summary", () => {
  const parsed = parseLegacyWhatsAppBatch(JSON.stringify({ id: "legacy-batch", startedAt: 1e20 }));
  expect(parsed).not.toBeNull();
  expect(() => initialWhatsAppActivitySummary(parsed!)).not.toThrow();
});

it("preserves timestamps at both supported Date boundaries", () => {
  const parsed = parseTrackedWhatsAppActivities(JSON.stringify([
    { ...activity, startedAt: 0 }, { ...activity, startedAt: 8_640_000_000_000_000 },
  ]));
  expect(parsed.map((item) => item.startedAt)).toEqual([0, 8_640_000_000_000_000]);
  expect(() => parsed.map(initialWhatsAppActivitySummary)).not.toThrow();
});
