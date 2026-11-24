import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { useAuditLedger } from "./use-audit-ledger";

const fixture = vi.hoisted(() => ({ export: vi.fn(), queries: vi.fn() }));
vi.mock("@/features/operations/hooks/use-operations", () => ({
  useAuditLogPages: (filters: unknown) => {
    fixture.queries(filters);
    return { data: { pages: [] }, hasNextPage: false };
  },
  useAuditLogExport: () => ({ mutateAsync: fixture.export, isPending: false }),
}));
const user: User = { id: "ledger-admin", full_name: "Synthetic Admin", email: "ledger@example.test",
  role: "agency_admin", agency_id: "agency-1", is_active: true,
  last_login_at: null, created_at: "2026-10-30", updated_at: "2026-10-30" };
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user, sessionVersion: 1 });
});

it("admits a cross-agency filter only while the current role is super-admin", async () => {
  const { result } = renderHook(useAuditLedger);
  act(() => result.current.updateFilter("agencyId", "agency-2"));
  await waitFor(() => expect(result.current.filters.agencyId).toBe("agency-2"));
  expect(fixture.queries.mock.lastCall?.[0]).not.toHaveProperty("agency_id");
  act(() => useAuthStore.setState({ user: { ...user, role: "super_admin", agency_id: null } }));
  await waitFor(() => expect(fixture.queries.mock.lastCall?.[0]).toHaveProperty("agency_id", "agency-2"));
  act(() => useAuthStore.setState({ user }));
  await waitFor(() => expect(fixture.queries.mock.lastCall?.[0]).not.toHaveProperty("agency_id"));
});

it("aborts an in-flight export when its authenticated session changes", async () => {
  let completeExport: (value: { truncated: boolean }) => void = () => {};
  fixture.export.mockImplementation(() => new Promise<{ truncated: boolean }>((resolve) => { completeExport = resolve; }));
  const { result } = renderHook(useAuditLedger);
  act(() => {
    result.current.updateFilter("startAt", "2026-10-01T09:00");
    result.current.updateFilter("endAt", "2026-10-02T09:00");
  });
  await waitFor(() => expect(result.current.canExport).toBe(true));
  let pending: Promise<void> = Promise.resolve();
  act(() => { pending = result.current.exportLedger(); });
  const signal = fixture.export.mock.calls[0][0].signal as AbortSignal;
  expect(signal.aborted).toBe(false);
  act(() => useAuthStore.setState({ sessionVersion: 2 }));
  expect(signal.aborted).toBe(true);
  await act(async () => { completeExport({ truncated: false }); await pending; });
  expect(result.current.exportNotice).toBeNull();
});
