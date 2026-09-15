import { describe, expect, it } from "vitest";
import type { GcGroupReference } from "./types";
import { describeAppAvailability } from "./availability";
import { gcPublicationState } from "./utils";

const group: GcGroupReference = { id: "trip", name: "Trip", lifecycle: "closed", destination: null, start_date: null, end_date: null, company: null };

describe("GC App availability presentation", () => {
  it("uses server app availability independently of collection status or browser dates", () => {
    expect(describeAppAvailability({ ...group, app_availability: "active" })).toMatchObject({ label: "Available now", variant: "success" });
    expect(describeAppAvailability({ ...group, lifecycle: "active", app_availability: "paused", app_availability_reason: "no_roles_enabled" }))
      .toMatchObject({ label: "Paused", description: "No roles have access. Enable at least one role in Access & features." });
  });
  it("does not invent availability when the server summary is missing", () => {
    expect(describeAppAvailability(group).label).toBe("Status unavailable");
  });
  it("gives expiry priority over start and keeps unpublished items drafts", () => {
    const item = { is_published: true, available_from: "2026-11-01T00:00:00Z", available_until: "2026-10-01T00:00:00Z" };
    expect(gcPublicationState(item, Date.parse("2026-10-15T00:00:00Z")).label).toBe("Expired");
    expect(gcPublicationState({ ...item, is_published: false }, Date.parse("2026-10-15T00:00:00Z")).label).toBe("Draft");
  });
});
