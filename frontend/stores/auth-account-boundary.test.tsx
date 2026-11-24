import { QueryClient } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import type { User } from "@/types";
import { useAuthStore } from "./auth.store";

vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));
const actor: User = {
  id: "actor-a", email: "a@example.test", full_name: "Synthetic A", role: "agency_admin", agency_id: "agency-a",
  is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01",
};
let client: QueryClient;
beforeEach(() => {
  window.localStorage.clear(); window.sessionStorage.clear();
  useAuthStore.setState({ user: actor, isAuthenticated: true, hasHydrated: true, sessionVersion: 1 });
  window.localStorage.setItem("passdetection:session-owner", actor.id);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  client.setQueryData(["whatsapp", "groups"], { private: "A passenger list" });
  render(<SessionLifecycle queryClient={client} />);
});
afterEach(() => { vi.restoreAllMocks(); client.clear(); window.localStorage.clear(); window.sessionStorage.clear(); });

it("redacts A's real query cache when another tab already wrote B's shared owner marker", () => {
  window.localStorage.setItem("passdetection:session-owner", "actor-b");
  act(() => useAuthStore.getState().setSession({ ...actor, id: "actor-b" }));
  expect(useAuthStore.getState().user?.id).toBe("actor-b");
  expect(client.getQueryData(["whatsapp", "groups"])).toBeUndefined();
});

it.each(["getItem", "removeItem"] as const)("redacts the old query cache even if browser storage %s is denied", (method) => {
  window.sessionStorage.setItem("passdetection:private-draft", "A private draft");
  vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new DOMException("Synthetic denied storage", "SecurityError"); });
  act(() => useAuthStore.getState().setSession({ ...actor, id: "actor-b" }));
  expect(client.getQueryData(["whatsapp", "groups"])).toBeUndefined();
});

it.each([{ role: "agency_staff" as const }, { agency_id: "agency-b" }])("redacts cached private data when the same actor changes effective authority: %j", (changed) => {
  act(() => useAuthStore.getState().setSession({ ...actor, ...changed }));
  expect(client.getQueryData(["whatsapp", "groups"])).toBeUndefined();
});

it("preserves the same-authority query cache and retained drafts during session/profile renewal", () => {
  window.sessionStorage.setItem("passdetection:whatsapp-send:v1:synthetic", "retained opaque pending identity");
  act(() => useAuthStore.getState().setSession({ ...actor, full_name: "Updated profile", last_login_at: "2026-10-31", updated_at: "2026-10-31" }));
  expect(client.getQueryData(["whatsapp", "groups"])).toEqual({ private: "A passenger list" });
  expect(window.sessionStorage.getItem("passdetection:whatsapp-send:v1:synthetic")).toBe("retained opaque pending identity");
});
