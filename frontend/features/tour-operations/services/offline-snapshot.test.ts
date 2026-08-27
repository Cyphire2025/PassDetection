
import { describe, expect, it } from "vitest";

import {
  minimizeOfflineSnapshotForStorage,
  offlineSnapshotKeys,
  resolveOfflineSnapshotExpiry,
} from "./offline-snapshot";

describe("coordinator offline snapshot policy", () => {
  it("removes contact, family, raw QR, and passport detail data", () => {
    const stored = minimizeOfflineSnapshotForStorage(
      offlineSnapshotKeys.myPassengers("8c6eeea0-43f0-4b30-a1f1-44906072f144"),
      [{
        id: "e5378ff5-204f-433a-9199-a88bb7b0d568",
        client_name: "Passenger One",
        client_email: "sensitive@example.test",
        client_phone: "+910000000000",
        departure_city: "Delhi",
        family_head_name: "Family Head",
        passport_fields: { passport_number: "P123" },
        qr_payload: "pdatt:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        status: "confirmed",
      }],
    );

    expect(stored).toEqual([{
      id: "e5378ff5-204f-433a-9199-a88bb7b0d568",
      client_name: "Passenger One",
      departure_city: "Delhi",
      status: "confirmed",
    }]);
    expect(JSON.stringify(stored)).not.toMatch(/email|phone|family|passport|qr_payload|P123/);
  });

  it("uses a bounded default and clamps an excessive requested expiry", () => {
    const now = Date.parse("2030-01-01T00:00:00.000Z");
    expect(resolveOfflineSnapshotExpiry(now) - now).toBe(72 * 60 * 60_000);
    expect(
      resolveOfflineSnapshotExpiry(now, "2031-01-01T00:00:00.000Z") - now,
    ).toBe(14 * 24 * 60 * 60_000);
  });

  it("preserves an already-expired requested boundary for fail-closed deletion", () => {
    const now = Date.parse("2030-01-02T00:00:00.000Z");
    expect(resolveOfflineSnapshotExpiry(now, "2030-01-01T00:00:00.000Z")).toBeLessThan(now);
  });
});
