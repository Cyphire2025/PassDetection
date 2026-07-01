/**
 * useDashboardStats Hook
 * =====================
 * Fetches and caches dashboard statistics.
 */

import { useQuery } from "@tanstack/react-query";
import { dashboardApi } from "../api/dashboard.api";
import { QUERY_KEYS } from "@/constants";

export function useDashboardStats() {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.stats,
    queryFn: () => dashboardApi.getStats(),
    refetchInterval: 30_000, // Poll every 30 seconds to keep stats fresh
  });
}
