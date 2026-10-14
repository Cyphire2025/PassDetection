import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyPeoplePage, CompanyPerson } from "../types/company-people";
import { useCompanyPeople } from "./use-company-people";

vi.mock("./use-company-session", () => ({ useCompanySession: () => ({ key: "people-session", ready: true }) }));
vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { list: vi.fn() } }));
const person: CompanyPerson = { id: "person-1", display_name: "Saved person", status: "active", revision: 1,
  trip_count: 1, document_version_count: 1, duplicate_status: "none", current_passport_last4: null };
const page = (pending: boolean, items: CompanyPerson[] = []): CompanyPeoplePage => ({
  items, indexing_pending: pending, has_more: false, next_cursor: null,
});
const tick = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
function mount(initial = { search: "", cursor: undefined as string | undefined, pause: false }) {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(({ search, cursor, pause }) => useCompanyPeople("agency", "company", search, cursor, true, pause),
    { wrapper, initialProps: initial });
  return { ...hook, client, invalidate };
}
beforeEach(() => { vi.resetAllMocks(); vi.useFakeTimers(); focusManager.setFocused(true); });
afterEach(() => { cleanup(); vi.useRealTimers(); focusManager.setFocused(undefined); });

it("loads newly indexed people automatically and refreshes totals as records arrive and indexing finishes", async () => {
  vi.mocked(companyPeopleApi.list).mockResolvedValueOnce(page(true))
    .mockResolvedValueOnce(page(true, [person])).mockResolvedValue(page(false, [person]));
  const { result, invalidate } = mount();
  await tick(1);
  expect(result.current.people.data?.items).toEqual([]);
  invalidate.mockClear();
  await tick(5_000);
  expect(result.current.people.data?.items).toEqual([person]);
  expect(result.current.people.isLoading).toBe(false);
  expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ["companies", "agency", "session", "people-session", "ready", "company", "summary"], exact: true });
  await tick(5_000);
  expect(result.current.people.data?.indexing_pending).toBe(false);
  expect(invalidate).toHaveBeenCalledTimes(2);
  await tick(60_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(3);
});

it("stops after twelve automatic checks and keeps manual refresh available for a longer backfill", async () => {
  vi.mocked(companyPeopleApi.list).mockResolvedValue(page(true));
  const { result } = mount();
  await tick(1);
  await tick(120_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(13);
  await tick(120_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(13);
  await act(async () => { await result.current.people.refetch(); });
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(14);
});

it("does not poll a hidden browser tab, an open person dialog, a search, or a cursor page", async () => {
  vi.mocked(companyPeopleApi.list).mockResolvedValue(page(true));
  const { rerender } = mount();
  await tick(1);
  focusManager.setFocused(false);
  await tick(15_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(1);
  focusManager.setFocused(true);
  rerender({ search: "", cursor: undefined, pause: true });
  await tick(15_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(1);
  rerender({ search: "Saved person", cursor: undefined, pause: false });
  await tick(15_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(2);
  rerender({ search: "", cursor: "next-page", pause: false });
  await tick(15_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(3);
});

it("stops automatic requests after an access or network error", async () => {
  vi.mocked(companyPeopleApi.list).mockResolvedValueOnce(page(true, [person])).mockRejectedValue({ status: 403 });
  const { result } = mount();
  await tick(1);
  await tick(5_000);
  expect(result.current.people.isError).toBe(true);
  await tick(60_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(2);
});

it("does not invalidate totals repeatedly when identical pending results are returned", async () => {
  vi.mocked(companyPeopleApi.list).mockResolvedValue(page(true, [person]));
  const { invalidate } = mount();
  await tick(1);
  invalidate.mockClear();
  await tick(15_000);
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(4);
  expect(invalidate).not.toHaveBeenCalled();
});
