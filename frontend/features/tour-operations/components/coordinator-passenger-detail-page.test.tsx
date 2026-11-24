import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const boundary = vi.hoisted(() => ({
  passenger: { id: "passenger-a", client_name: "Synthetic Passenger A", departure_city: "Delhi", status: "confirmed", client_email: "excluded@example.test", client_phone: null },
  cached: [] as Record<string, unknown>[],
  write: vi.fn(),
  user: { id: "owner-a", role: "agency_coordinator" },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/stores/auth.store", () => ({
  selectUser: (state: { user: typeof boundary.user }) => state.user,
  selectIsAuthenticated: () => true, selectHasHydrated: () => true,
  useAuthStore: (selector: (state: { user: typeof boundary.user; clearSession: () => void }) => unknown) => selector({ user: boundary.user, clearSession() {} }),
}));
vi.mock("@/features/operations/hooks/use-operations", () => ({
  useMyTourGroupPassenger: () => ({ data: boundary.passenger, isSuccess: true, isLoading: false }),
}));
vi.mock("../hooks/use-network-status", () => ({ useNetworkStatus: () => true }));
vi.mock("../services/offline-snapshot", () => ({
  offlineSnapshotKeys: { myPassengers: (id: string) => `passengers:${id}` },
  useOfflineSnapshot: () => boundary.cached,
  writeOfflineSnapshot: boundary.write,
}));

import { CoordinatorPassengerDetailPage } from "./coordinator-passenger-detail-page";

describe("passenger snapshot persistence", () => {
  beforeEach(() => { boundary.cached = []; boundary.write.mockReset(); });

  it("does not write again when its own snapshot notification rehydrates the same stored passenger fields", () => {
    const view = render(<CoordinatorPassengerDetailPage groupId="group-a" passengerId="passenger-a" />);
    expect(boundary.write).toHaveBeenCalledTimes(1);
    // Snapshot storage excludes contact information and emits a new array on
    // rehydration. This is the next render produced by that notification.
    boundary.cached = [{ id: "passenger-a", client_name: "Synthetic Passenger A", departure_city: "Delhi", status: "confirmed", client_email: null, client_phone: null }];
    view.rerender(<CoordinatorPassengerDetailPage groupId="group-a" passengerId="passenger-a" />);
    expect(boundary.write).toHaveBeenCalledTimes(1);
  });

  it("updates changed persisted fields while retaining the other saved passengers", () => {
    const other = { id: "passenger-b", client_name: "Synthetic Passenger B", departure_city: null, status: "confirmed" };
    boundary.cached = [other, { ...boundary.passenger, status: "needs_review" }];
    render(<CoordinatorPassengerDetailPage groupId="group-a" passengerId="passenger-a" />);
    expect(boundary.write).toHaveBeenCalledExactlyOnceWith("passengers:group-a", [other, boundary.passenger]);
  });
});
