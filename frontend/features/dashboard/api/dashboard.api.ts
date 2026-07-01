/**
 * Dashboard API Client
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface RecentSubmission {
  id: string;
  client_name: string;
  client_email: string;
  status: string;
  created_at: string;
  overall_confidence: number | null;
}

export interface DashboardStats {
  total_passports: number;
  pending_review: number;
  confirmed: number;
  active_links: number;
  recent_submissions: RecentSubmission[];
}

export const dashboardApi = {
  getStats: async (): Promise<DashboardStats> => {
    const { data } = await apiClient.get<DashboardStats>(API_ENDPOINTS.dashboard.stats);
    return data;
  },
};
