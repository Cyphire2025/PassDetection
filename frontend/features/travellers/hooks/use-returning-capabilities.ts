"use client";

import { useQuery } from "@tanstack/react-query";
import { returningApi } from "../api/returning.api";

/** Share one cached availability check between the welcome screen and menu. */
export function useReturningCapabilities(token: string, enabled = true) {
  return useQuery({ queryKey: ["returning-capabilities", token], queryFn: ({ signal }) => returningApi.capabilities(token, signal), enabled, staleTime: 60_000, gcTime: 300_000, retry: false, refetchOnWindowFocus: false });
}
