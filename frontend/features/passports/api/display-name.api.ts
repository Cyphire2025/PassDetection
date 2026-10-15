import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface DisplayNamePatch {
  display_name: string;
  expected_updated_at: string;
}

export interface DisplayNameResponse {
  id: string;
  client_name: string;
  display_name: string | null;
  updated_at: string;
}

export async function updateDisplayName(groupId: string, id: string, body: DisplayNamePatch): Promise<DisplayNameResponse> {
  const { data } = await apiClient.patch<DisplayNameResponse>(API_ENDPOINTS.passports.displayName(groupId, id), body);
  return data;
}
