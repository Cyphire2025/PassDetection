import apiClient from "@/lib/api/client";

export type ProviderName = "gemini" | "openai";
export type GrantRole = "agency_admin" | "agency_manager" | "agency_staff";
export type AssistantConfiguration = {
  enabled: boolean; allowed_roles: GrantRole[]; allowed_user_ids: string[]; provider: ProviderName;
  gemini_model: "gemini-3.8-flash" | "gemini-3.1-pro-preview" | "gemini-3.1-flash-lite";
  gemini_live_model: "gemini-3.8-live" | "gemini-3.8-live-extended-thinking" | "gemini-3.1-flash-live-preview";
  gemini_image_model: "gemini-3.1-flash-image" | "gemini-3.1-flash-lite-image";
  gemini_voice: "Zephyr" | "Kore" | "Puck" | "Charon" | "Aoede";
  reasoning_effort: "low" | "medium" | "high";
  openai_speech_model: "" | "gpt-realtime-2.1-mini" | "gpt-realtime-2.1";
  openai_voice: "marin" | "cedar" | "alloy" | "coral" | "sage";
};
export type GrantPerson = { id: string; name: string; email: string; role: string };
export type SettingsSnapshot = { revision: number; configuration: AssistantConfiguration; credentials: Record<ProviderName, boolean>; granted_users: GrantPerson[] };
export type SettingsWrite = { expected_revision: number; configuration: AssistantConfiguration; gemini_api_key?: string; openai_api_key?: string; clear_gemini_key?: boolean; clear_openai_key?: boolean };
const BASE = "/api/v1/ai-assistant/settings";
export const aiSettingsApi = {
  get: async (signal?: AbortSignal) => (await apiClient.get<SettingsSnapshot>(BASE, { signal })).data,
  save: async (body: SettingsWrite) => (await apiClient.put<SettingsSnapshot>(BASE, body)).data,
  people: async (q: string, signal?: AbortSignal) => (await apiClient.get<{ items: GrantPerson[]; has_more: boolean }>(`${BASE}/people`, { params: { q }, signal })).data,
  check: async (provider: ProviderName) => (await apiClient.post<{ ok: boolean; message: string }>(`${BASE}/check`, { provider }, { timeout: 25000 })).data,
};
