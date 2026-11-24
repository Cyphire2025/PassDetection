import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { Company } from "../types";
import { useCompanyMutations } from "./use-companies";
import { useCompanyDataExports } from "./use-company-data-exports";
import { useCompanyReusePolicy } from "./use-company-reuse-policy";
import {
  cleanupCompanyAuthority, companyActor, companyWrites, queuedCompanyMutation,
  resetCompanyAuthority,
} from "../test-support/mutation-authority";

vi.mock("@/lib/api/client", () => ({ default: {
  get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
} }));
beforeEach(resetCompanyAuthority);
afterEach(cleanupCompanyAuthority);

it.each(["create", "update", "remove", "export"] as const)(
  "refuses queued company %s after the initiating actor changes",
  async (operation) => {
    const context = queuedCompanyMutation();
    const { result } = renderHook(() => ({
      company: useCompanyMutations("agency"),
      exports: useCompanyDataExports("agency", "company"),
    }), context);
    let pending!: Promise<unknown>;
    act(() => {
      switch (operation) {
        case "create": pending = result.current.company.create.mutateAsync({ name: "Synthetic company" }); break;
        case "update": pending = result.current.company.update.mutateAsync({ id: "company", name: "Synthetic company", expected_revision: 3 }); break;
        case "remove": pending = result.current.company.remove.mutateAsync({ id: "company", revision: 3 } as Company); break;
        case "export": pending = result.current.exports.create.mutateAsync("excel"); break;
      }
    });
    const outcome = pending.then(() => undefined, (error: unknown) => error);
    await waitFor(() => expect(context.entered).toHaveBeenCalledOnce());
    act(() => useAuthStore.setState({ user: { ...companyActor, id: "replacement-owner" } }));
    let error: unknown;
    await act(async () => { context.release(); error = await outcome; });
    for (const write of companyWrites()) expect(write).not.toHaveBeenCalled();
    expect(error).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  },
);

it.each(["role", "agency"] as const)("refuses a queued company write after the same actor changes %s", async (change) => {
  const context = queuedCompanyMutation();
  const { result } = renderHook(() => useCompanyMutations("agency"), context);
  let pending!: Promise<unknown>;
  act(() => { pending = result.current.create.mutateAsync({ name: "Synthetic company" }); });
  const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await waitFor(() => expect(context.entered).toHaveBeenCalledOnce());
  act(() => useAuthStore.setState({ user: change === "role"
    ? { ...companyActor, role: "agency_staff" }
    : { ...companyActor, agency_id: "other-agency" } }));
  await act(async () => { context.release(); await rejected; });
  for (const write of companyWrites()) expect(write).not.toHaveBeenCalled();
});

it("preserves a queued write across renewal and forwards the original authority outside its exact payload", async () => {
  const context = queuedCompanyMutation();
  const { result } = renderHook(() => useCompanyMutations("agency"), context);
  const body = { name: "Synthetic company", external_reference: null };
  let pending!: Promise<unknown>;
  act(() => { pending = result.current.create.mutateAsync(body); });
  await waitFor(() => expect(context.entered).toHaveBeenCalledOnce());
  act(() => useAuthStore.getState().setSession({ ...companyActor, updated_at: "2026-10-31" }));
  await act(async () => { context.release(); await pending; });
  expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/api/v1/companies", body, {
    params: { agency_id: "agency" }, expectedOwnerUserId: companyActor.id,
    expectedAuthorityKey: JSON.stringify([companyActor.id, companyActor.role, companyActor.agency_id]),
  });
  await waitFor(() => expect(result.current.create.isSuccess).toBe(true));
});

it("suppresses a late successful write's invalidations after the account changes", async () => {
  const context = queuedCompanyMutation();
  context.release();
  let finish!: (value: { data: { id: string } }) => void;
  vi.mocked(apiClient.post).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const invalidate = vi.spyOn(context.client, "invalidateQueries");
  const { result } = renderHook(() => useCompanyMutations("agency"), context);
  let pending!: Promise<unknown>;
  act(() => { pending = result.current.create.mutateAsync({ name: "Synthetic company" }); });
  const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await waitFor(() => expect(apiClient.post).toHaveBeenCalledOnce());
  act(() => useAuthStore.setState({ user: { ...companyActor, id: "replacement-owner" } }));
  await act(async () => { finish({ data: { id: "private-result" } }); await rejected; });
  expect(invalidate).not.toHaveBeenCalled();
});

it("does not repopulate policy cache if authority changes during success invalidation", async () => {
  const context = queuedCompanyMutation();
  context.release();
  const { result } = renderHook(() => useCompanyReusePolicy("agency", "company"), context);
  await waitFor(() => expect(result.current.policy.isSuccess).toBe(true));
  let finish!: () => void;
  const entered = vi.fn();
  const invalidation = new Promise<void>((resolve) => { finish = resolve; });
  vi.spyOn(context.client, "invalidateQueries").mockImplementationOnce(async () => { entered(); await invalidation; });
  const setData = vi.spyOn(context.client, "setQueryData");
  let pending!: Promise<unknown>;
  act(() => { pending = result.current.update.mutateAsync(true); });
  const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await waitFor(() => expect(entered).toHaveBeenCalledOnce());
  act(() => useAuthStore.setState({ user: { ...companyActor, id: "replacement-owner" } }));
  await act(async () => { finish(); await rejected; });
  expect(setData).not.toHaveBeenCalled();
});
