export type AssistantPhase = "idle" | "listening" | "thinking" | "speaking";
export type McpAccessStatus = { connected: boolean; available_tools?: number; write_enabled?: boolean; code?: string; message?: string };
export type { SculpturePresentation as VisualState } from "@/components/ui/liquid-sculpture/types";
export type AssistantStatus = { configured: boolean; speech_configured: boolean; model: string; reasoning_effort: string; name: string; account_id?: string; account_scope?: string; access: "read_only" | "mcp_write_enabled"; avatar_appearance?: "male" | "female"; voice_name?: string; voice_model?: string; provider?: "gemini" | "openai"; mode?: "gemini" | "openai" | "hybrid"; voice_provider?: "gemini" | "openai"; native_voice?: boolean; voice_configured?: boolean; settings_revision?: number; can_manage_settings?: boolean };
export type Asset = { id: string; name: string; mime: string; size: number; kind: "uploaded" | "generated"; created_at: string; url: string };
export type Source = { view: string; observed_at: string; completeness: string };
export type Message = { id: string; role: "user" | "assistant"; text: string; attachments?: Asset[]; images?: Asset[]; sources?: Source[]; error?: string; streaming?: boolean };
export type Conversation = { id: string; title: string; created_at: string };
export type Turn = { id: string; user: string; assistant: string; created_at: string; images?: Asset[]; sources?: Source[]; attachment_ids?: string[]; attachments?: Asset[] };
export type PageResult<T> = { items: T[]; next_cursor: string | null };
export type StreamEvent = { type: "status"; message: string; phase: "thinking" } | { type: "text_delta"; text: string } | { type: "source"; source: Source } | { type: "image"; image: Asset } | { type: "done"; request_id: string } | { type: "error"; code: string; message: string } | { type: "replay"; turn: Turn } | { type: "usage"; usage: Record<string, number> };
export type NativeEvent =
  | { type: "ready"; conversation_id: string; max_session_seconds: number }
  | { type: "voice_saved"; conversation_id: string }
  | { type: "heartbeat" }
  | { type: "status"; phase: "thinking" | "listening" }
  | { type: "input_transcript" | "text_delta"; text: string; turn_id: string }
  | { type: "audio"; data: string; sample_rate: number; turn_id: string }
  | { type: "source"; source: Source; turn_id: string }
  | { type: "image"; image: Asset; turn_id: string }
  | { type: "interrupted"; turn_id: string }
  | { type: "answer_reset"; turn_id: string }
  | { type: "turn_complete"; turn: Turn; turn_id: string }
  | { type: "error"; code: string; message: string };
