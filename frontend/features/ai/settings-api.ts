import apiClient from "@/lib/api/client";

export type ProviderName = "gemini" | "openai";
export type ProviderMode = ProviderName | "hybrid";
export type GrantRole = "agency_admin" | "agency_manager" | "agency_staff";
export type UsageLimits = { daily_voice_chats: number; voice_connection_minutes: number; daily_requests: number; daily_images: number; daily_uploads: number; daily_speech_requests: number };
export const DEFAULT_USAGE_LIMITS: UsageLimits = { daily_voice_chats: 30, voice_connection_minutes: 10, daily_requests: 200, daily_images: 12, daily_uploads: 80, daily_speech_requests: 300 };
export type UsageSnapshot = { observed_at: string; resets_at: string; limits: UsageLimits; used: Record<string, number> };
export type AssistantConfiguration = {
  chat_model?: string; voice_model?: string; chat_reasoning?: string; voice_reasoning?: string; voice_name?: string;
  voice_presentation?: "male" | "female" | null;
  mcp_write_enabled?: boolean; mcp_connection_id?: string | null;
  enabled: boolean; allowed_roles: GrantRole[]; allowed_user_ids: string[]; provider: ProviderMode;
  gemini_model: "gemini-3.8-flash" | "gemini-3.1-pro-preview" | "gemini-3.1-flash-lite";
  gemini_live_model: "gemini-3.8-live" | "gemini-3.8-live-extended-thinking" | "gemini-3.1-flash-live-preview";
  gemini_image_model: "gemini-3.1-flash-image" | "gemini-3.1-flash-lite-image";
  gemini_voice: "Zephyr" | "Kore" | "Puck" | "Charon" | "Aoede";
  reasoning_effort: "low" | "medium" | "high";
  openai_reasoning_effort: "none" | "low" | "medium" | "high" | "xhigh" | "max";
  openai_speech_model: "" | "gpt-realtime-2.1-mini" | "gpt-realtime-2.1";
  openai_voice: "marin" | "cedar" | "alloy" | "coral" | "sage";
  usage_limits: UsageLimits;
};
export type GrantPerson = { id: string; name: string; email: string; role: string };
export type SettingsSnapshot = { revision: number; configuration: AssistantConfiguration; credentials: Record<ProviderName, boolean>; granted_users: GrantPerson[] };
export type SettingsWrite = { expected_revision: number; configuration: AssistantConfiguration; gemini_api_key?: string; openai_api_key?: string; clear_gemini_key?: boolean; clear_openai_key?: boolean };
const BASE = "/api/v1/ai-assistant/settings";
export type ModelOption = { id: string; model: string; label: string; provider: ProviderName; kind: "chat" | "voice"; available: boolean; reasoning: string[]; voices: { id: string; label: string; appearance: "male" | "female" }[] };
export type ModelCatalog = { models: ModelOption[]; revision: number; observed_at: string; providers: { provider: ProviderName; status: "ready" | "unavailable" | "not_connected"; message: string }[] };
export type McpConnections = { items: { id: string; name: string; read_enabled: boolean; write_enabled: boolean }[] };
export const aiSettingsApi = {
  models: async (signal?: AbortSignal) => (await apiClient.get<ModelCatalog>(`${BASE}/models`, { signal, timeout: 25000 })).data,
  mcpConnections: async (signal?: AbortSignal) => (await apiClient.get<McpConnections>(`${BASE}/mcp-connections`, { signal })).data,
  get: async (signal?: AbortSignal) => (await apiClient.get<SettingsSnapshot>(BASE, { signal })).data,
  save: async (body: SettingsWrite) => (await apiClient.put<SettingsSnapshot>(BASE, body)).data,
  people: async (q: string, signal?: AbortSignal) => (await apiClient.get<{ items: GrantPerson[]; has_more: boolean }>(`${BASE}/people`, { params: { q }, signal })).data,
  check: async (provider: ProviderName) => (await apiClient.post<{ ok: boolean; message: string }>(`${BASE}/check`, { provider }, { timeout: 25000 })).data,
  usage: async (signal?: AbortSignal) => (await apiClient.get<UsageSnapshot>(`${BASE}/usage`, { signal })).data,
};
