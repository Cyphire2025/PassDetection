import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceTestDatabase } from "../test-support/attendance-database";

const boundary = vi.hoisted(() => ({
  state: { user: { id: "owner-a", agency_id: "agency-a", role: "agency_coordinator" }, sessionVersion: 1 },
  open: vi.fn(), protect: vi.fn(), unprotect: vi.fn(),
}));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => boundary.state } }));
vi.mock("./browser-offline-database", async (importOriginal) => ({
  ...await importOriginal<typeof import("./browser-offline-database")>(), openBrowserOfflineDatabase: boundary.open,
}));
vi.mock("./browser-offline-crypto", () => ({ protectBrowserJson: boundary.protect, unprotectBrowserJson: boundary.unprotect }));

const snapshotStore = "coordinator-offline-snapshots";
const key = "passdetection-tour-ops-my-passengers:group-a";
const legacyKey = `${key}:user:owner-a`;
const snapshotId = (owner: string, agency = "agency-a") => JSON.stringify([2, agency, owner, key]);
const passengers = [{ id: "passenger-a", client_name: "Synthetic Passenger A", client_email: "excluded@example.test" }];

describe("offline snapshot identity continuity", () => {
  let storage: ReturnType<typeof attendanceTestDatabase>;
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.clearAllMocks();
    storage = attendanceTestDatabase();
    boundary.state.user = { id: "owner-a", agency_id: "agency-a", role: "agency_coordinator" };
    boundary.state.sessionVersion = 1;
    boundary.open.mockResolvedValue(storage.database);
    boundary.protect.mockImplementation(async (value) => ({ envelope: value }));
    boundary.unprotect.mockImplementation(async (value) => value.envelope);
    window.localStorage.clear();
    // Exercise expiry cleanup as part of the actual public read path.
    vi.stubGlobal("indexedDB", {});
  });

  it("never migrates A's legacy passenger roster into B's encrypted owner scope after an awaited read", async () => {
    window.localStorage.setItem(legacyKey, JSON.stringify(passengers));
    storage.onRead((store, id) => {
      if (store === snapshotStore && id === snapshotId("owner-a")) {
        boundary.state.user = { id: "owner-b", agency_id: "agency-b", role: "agency_coordinator" };
        boundary.state.sessionVersion++;
      }
    });
    const snapshots = await import("./offline-snapshot");
    await expect(snapshots.readOfflineSnapshot(key, [])).resolves.toEqual([]);
    expect(storage.rows(snapshotStore).has(snapshotId("owner-b", "agency-b"))).toBe(false);
    expect(window.localStorage.getItem(legacyKey)).toBe(JSON.stringify(passengers));
  });

  it("preserves the successful same-owner copy, verify and legacy removal workflow", async () => {
    window.localStorage.setItem(legacyKey, JSON.stringify(passengers));
    const snapshots = await import("./offline-snapshot");
    const result = await snapshots.readOfflineSnapshot<typeof passengers>(key, []);
    expect(result).toEqual([expect.objectContaining({ id: "passenger-a", client_name: "Synthetic Passenger A", client_email: null, client_phone: null })]);
    expect(storage.rows(snapshotStore).get(snapshotId("owner-a"))).toMatchObject({ ownerUserId: "owner-a", agencyId: "agency-a" });
    expect(window.localStorage.getItem(legacyKey)).toBeNull();
  });

  it("does not return an encrypted roster after the account changes during decryption", async () => {
    const snapshots = await import("./offline-snapshot");
    await snapshots.writeOfflineSnapshot(key, passengers);
    boundary.unprotect.mockImplementation(async (value) => {
      boundary.state.user = { id: "owner-b", agency_id: "agency-b", role: "agency_coordinator" };
      boundary.state.sessionVersion++;
      return value.envelope;
    });
    await expect(snapshots.readOfflineSnapshot(key, [])).resolves.toEqual([]);
    expect(storage.rows(snapshotStore).has(snapshotId("owner-a"))).toBe(true);
    expect(storage.rows(snapshotStore).has(snapshotId("owner-b", "agency-b"))).toBe(false);
  });
});
