import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { useLiveHistoryFeed } from "./use-live-history-feed";

type Page = {
  items: { id: string }[];
  next_cursor: string | null;
  unread_count: number;
};

describe("live feed with bounded history", () => {
  it("keeps new arrivals visible after six history pages and repairs only the head", async () => {
    let arrival = "initial";
    const load = vi.fn(
      async (cursor: string | undefined): Promise<Page> => ({
        items: [{ id: cursor ?? arrival }],
        next_cursor: String(Number(cursor ?? 0) + 1),
        unread_count: 7,
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () =>
        useLiveHistoryFeed<Page>({
          queryKey: ["feed", "user-a"],
          loadPage: load,
          itemKey: (item) => item.id,
          enabled: true,
          interval: false,
        }),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.data?.pages[0].items[0].id).toBe("initial"),
    );
    for (let page = 1; page <= 6; page++) {
      await act(async () => {
        await result.current.fetchNextPage();
      });
      await waitFor(() =>
        expect(result.current.data?.pages.at(-1)?.items[0].id).toBe(
          String(page),
        ),
      );
    }
    expect(result.current.data?.pages).toHaveLength(6);
    arrival = "new-urgent-message";
    load.mockClear();
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() =>
      expect(result.current.data?.pages[0].items[0].id).toBe(arrival),
    );
    expect(load).toHaveBeenCalledTimes(1);
    expect(load.mock.calls[0][0]).toBeUndefined();
    expect(result.current.data?.pages[0].unread_count).toBe(7);
    await act(async () => {
      await result.current.returnToLatest();
    });
    await waitFor(() => expect(result.current.isBrowsingHistory).toBe(false));
    expect(result.current.data?.pages).toHaveLength(1);
    unmount();
    client.clear();
  });

  it("never carries a history cursor into a different user or filter", async () => {
    const load = vi.fn(
      async (cursor: string | undefined): Promise<Page> => ({
        items: [{ id: cursor ?? "head" }],
        next_cursor: "older",
        unread_count: 0,
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender, unmount } = renderHook(
      ({ user }) =>
        useLiveHistoryFeed<Page>({
          queryKey: ["feed", user],
          loadPage: load,
          itemKey: (item) => item.id,
          enabled: true,
          interval: false,
        }),
      { wrapper, initialProps: { user: "a" } },
    );
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    rerender({ user: "b" });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(1));
    expect(result.current.isBrowsingHistory).toBe(false);
    unmount();
    client.clear();
  });
  it("reports malformed server data as an error instead of crashing the dashboard", async () => {
    const load = vi.fn(async (): Promise<Page> => [] as unknown as Page);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result, unmount } = renderHook(() => useLiveHistoryFeed<Page>({ queryKey: ["malformed-feed"], loadPage: load, itemKey: (item) => item.id, enabled: true, interval: false }), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    load.mockResolvedValue({ items: [{ id: "recovered" }], next_cursor: null, unread_count: 1 });
    await act(async () => { await result.current.refetch(); });
    await waitFor(() => expect(result.current.data?.pages[0].items[0].id).toBe("recovered"));
    expect(result.current.isError).toBe(false);
    unmount(); client.clear();
  });

});
