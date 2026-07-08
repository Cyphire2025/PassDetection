import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface GlobalSearchResult {
  type: "passport" | "group";
  id: string;
  group_id: string | null;
  title: string;
  subtitle: string | null;
  status: string | null;
  passport_number: string | null;
  client_name: string | null;
  client_email: string | null;
  client_phone: string | null;
  group_name: string | null;
  destination: string | null;
  updated_at: string | null;
}

export const searchApi = {
  global: async (query: string): Promise<GlobalSearchResult[]> => {
    const { data } = await apiClient.get<GlobalSearchResult[]>(API_ENDPOINTS.search.global, {
      params: { q: query, limit: 12 },
    });
    return data;
  },
};
