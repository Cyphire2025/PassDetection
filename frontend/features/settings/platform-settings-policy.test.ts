import { describe, expect, it } from "vitest";
import {
  buildPlatformSettingsUpdate,
  conflictCurrentUpdatedAt,
  DEFAULT_PLATFORM_SETTINGS,
  isPlatformSettingsRevisionConflict,
} from "./platform-settings-policy";

describe("platform settings concurrency policy", () => {
  it("sends the authoritative revision without leaking the response-only field", () => {
    const payload = buildPlatformSettingsUpdate(
      { ...DEFAULT_PLATFORM_SETTINGS, platform_name: "Operations" },
      "2026-08-25T09:15:00+00:00",
    );

    expect(payload).toEqual(expect.objectContaining({
      platform_name: "Operations",
      expected_updated_at: "2026-08-25T09:15:00+00:00",
    }));
    expect(payload).not.toHaveProperty("updated_at");
  });

  it("allows a null revision only to represent the server-authorized first write", () => {
    expect(buildPlatformSettingsUpdate(DEFAULT_PLATFORM_SETTINGS, null).expected_updated_at).toBeNull();
  });

  it("recognizes only the explicit settings revision conflict contract", () => {
    const conflict = {
      status: 409,
      code: "PLATFORM_SETTINGS_REVISION_CONFLICT",
      message: "Reload required",
      details: { current_updated_at: "2026-08-25T10:00:00+00:00" },
    };

    expect(isPlatformSettingsRevisionConflict(conflict)).toBe(true);
    expect(conflictCurrentUpdatedAt(conflict)).toBe("2026-08-25T10:00:00+00:00");
    expect(isPlatformSettingsRevisionConflict({ ...conflict, status: 400 })).toBe(false);
    expect(isPlatformSettingsRevisionConflict({ ...conflict, code: "OTHER_CONFLICT" })).toBe(false);
  });
});
