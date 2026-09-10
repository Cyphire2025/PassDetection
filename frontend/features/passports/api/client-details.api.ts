import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PassportSubmission } from "@/types/passport.types";

export type ClientDetailKey = "client_email" | "client_phone" | "departure_city"
  | "nearest_domestic_airport" | "base_city" | "staff_code" | "agent_employee_type"
  | "agent_employee_code" | "designation" | "agency_dealership_name" | "meal_preference";

export interface ClientDetailDescriptor {
  key: ClientDetailKey;
  label: string;
  value: string | null;
  required: boolean;
  type: "text" | "email" | "tel" | "select";
  options: string[];
  max_length: number;
}

export interface ClientDetailsEditorResponse {
  updated_at: string;
  fields: ClientDetailDescriptor[];
  custom_answers: Array<{
    question_id: string; label: string; value: string | null;
    required: boolean; options: string[]; max_length: number;
  }>;
  custom_detail_answers: Array<{
    detail_id: string; label: string; value: string | null;
    required: boolean; max_length: number;
  }>;
}

export type ClientDetailsPatch = Partial<Record<ClientDetailKey, string | null>> & {
  expected_updated_at: string;
  custom_answers?: Array<{ question_id: string; value: string }>;
  custom_detail_answers?: Array<{ detail_id: string; value: string }>;
};

export const clientDetailsApi = {
  get: async (id: string): Promise<ClientDetailsEditorResponse> => {
    const { data } = await apiClient.get<ClientDetailsEditorResponse>(API_ENDPOINTS.passports.clientDetails(id));
    return data;
  },
  update: async (id: string, body: ClientDetailsPatch): Promise<PassportSubmission> => {
    const { data } = await apiClient.patch<PassportSubmission>(API_ENDPOINTS.passports.clientDetails(id), body);
    return data;
  },
};
