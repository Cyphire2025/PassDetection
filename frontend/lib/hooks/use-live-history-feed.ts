"use client";

import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { useState } from "react";

type CursorPage<Item> = { items: Item[]; next_cursor: string | null };

/** Keep the live head independently addressable while history is read on demand. */
export function useLiveHistoryFeed<Page extends CursorPage<unknown>>({
  queryKey,
  loadPage,
  enabled,
  interval,
  itemKey,
}: {
  queryKey: QueryKey;
  itemKey: (item: Page["items"][number]) => string;
  loadPage: (cursor: string | undefined, signal: AbortSignal) => Promise<Page>;
  enabled: boolean;
  interval: number | false | (() => number | false);
}) {
  const queryClient = useQueryClient();
  const [historyStart, setHistoryStart] = useState<{
    scope: string;
    cursor: string;
  } | null>(null);
  const scope = JSON.stringify(queryKey);
  const loadValidatedPage = async (
    cursor: string | undefined,
    signal: AbortSignal,
  ) => {
    const page = await loadPage(cursor, signal);
    if (
      !page ||
      !Array.isArray(page.items) ||
      (page.next_cursor !== null && typeof page.next_cursor !== "string")
    ) {
      throw new Error("The feed returned an invalid page. Please try again.");
    }
    for (const item of page.items) {
      if (
        !item ||
        typeof item !== "object" ||
        typeof itemKey(item) !== "string"
      ) {
        throw new Error(
          "The feed returned an invalid record. Please try again.",
        );
      }
    }
    return page;
  };
  const live = useQuery({
    queryKey: [...queryKey, "live"],
    queryFn: ({ signal }) => loadValidatedPage(undefined, signal),
    enabled,
    refetchInterval: interval,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: "always",
  });
  const startCursor =
    historyStart?.scope === scope ? historyStart.cursor : null;
  const historyKey = [...queryKey, "history", startCursor];
  const history = useInfiniteQuery({
    queryKey: historyKey,
    queryFn: ({ pageParam, signal }) => loadValidatedPage(pageParam, signal),
    initialPageParam: startCursor ?? "",
    getNextPageParam: (page) => page.next_cursor,
    maxPages: 5,
    enabled: enabled && startCursor !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
    meta: { historyOnly: true },
  });
  const seen = new Set<string>();
  const pages: Page[] = [live.data, ...(history.data?.pages ?? [])].flatMap(
    (page) => {
      if (!page) return [];
      return [
        {
          ...page,
          items: (page.items as Page["items"]).filter((item) => {
            if (seen.has(itemKey(item))) return false;
            seen.add(itemKey(item));
            return true;
          }),
        } as Page,
      ];
    },
  );
  return {
    ...live,
    data: live.data
      ? { pages, pageParams: [null, ...(history.data?.pageParams ?? [])] }
      : undefined,
    historyError: history.error,
    isFetchingNextPage: startCursor !== null && history.isFetching,
    hasNextPage:
      startCursor === null
        ? Boolean(live.data?.next_cursor)
        : history.isError || history.hasNextPage,
    fetchNextPage: () => {
      if (startCursor === null && live.data?.next_cursor) {
        setHistoryStart({ scope, cursor: live.data.next_cursor });
        return Promise.resolve();
      }
      return history.fetchNextPage();
    },
    returnToLatest: () => {
      setHistoryStart(null);
      queryClient.removeQueries({ queryKey: [...queryKey, "history"] });
      return live.refetch();
    },
    isBrowsingHistory: startCursor !== null,
  };
}
