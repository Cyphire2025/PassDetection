import { describe, expect, it } from "vitest";
import { normalizeStructuredApiErrorDetail } from "./api-error-detail";

describe("structured API error detail", () => {
  it("preserves FastAPI HTTPException metadata for conflict reconciliation", () => {
    expect(normalizeStructuredApiErrorDetail({
      code: "PLATFORM_SETTINGS_REVISION_CONFLICT",
      message: "Reload the latest settings",
      current_updated_at: "2026-08-25T10:00:00+00:00",
    })).toEqual({
      code: "PLATFORM_SETTINGS_REVISION_CONFLICT",
      message: "Reload the latest settings",
      details: { current_updated_at: "2026-08-25T10:00:00+00:00" },
    });
  });

  it("rejects strings and partial object shapes", () => {
    expect(normalizeStructuredApiErrorDetail("conflict")).toBeNull();
    expect(normalizeStructuredApiErrorDetail({ code: "CONFLICT" })).toBeNull();
  });
});
