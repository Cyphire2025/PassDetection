import { describe, expect, it } from "vitest";
import { parsePassportRetentionControl } from "./passport-retention.api";

describe("passport retention response boundary", () => {
  it("accepts a complete scheduled-retention response", () => {
    expect(parsePassportRetentionControl({
      group_id: "group-1",
      passport_purge_at: "2027-08-22T00:00:00Z",
      passport_retention_days_applied: 365,
      legal_hold: false,
      legal_hold_reason: null,
      legal_hold_set_at: null,
      legal_hold_set_by_user_id: null,
    })).toMatchObject({ legal_hold: false, passport_retention_days_applied: 365 });
  });

  it("rejects malformed shapes and incomplete hold evidence", () => {
    expect(() => parsePassportRetentionControl([])).toThrow();
    expect(() => parsePassportRetentionControl({
      group_id: "group-1",
      passport_purge_at: null,
      passport_retention_days_applied: 365,
      legal_hold: true,
      legal_hold_reason: "Legal review",
      legal_hold_set_at: null,
      legal_hold_set_by_user_id: "admin-1",
    })).toThrow(/missing its audited placement evidence/i);
  });
});
