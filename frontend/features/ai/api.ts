import apiClient from "@/lib/api/client";
import type { Asset, AssistantStatus, Conversation, PageResult, StreamEvent, Turn } from "./types";

const BASE = "/api/v1/ai-assistant";

export function assistantMessage(cause: unknown, fallback: string): string {
  return typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string" ? cause.message : fallback;
}

export async function assistantError(response: Response): Promise<Error> {
  try {
    const data = await response.json();
    return new Error(data.detail?.message || data.error?.message || (typeof data.detail === "string" ? data.detail : "The assistant could not complete this request."));
  } catch { return new Error("The connection was interrupted. Please try again."); }
}

export async function* decodeAssistantStream(body: ReadableStream<Uint8Array>, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
      if (buffer.length > 262144) throw new Error("The response exceeded its safe size limit.");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame.split("\n").filter((line) => line.startsWith("data: ")).map((line) => line.slice(6)).join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as StreamEvent;
        if (event.type === "done" || event.type === "error") terminal = true;
        yield event;
      }
      if (done) break;
    }
    if (!signal.aborted && !terminal) throw new Error("The connection ended before the answer was saved. Please try again.");
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

export const assistantApi = {
  availability: async (signal?: AbortSignal) => (await apiClient.get<{ enabled: boolean; allowed: boolean }>(`${BASE}/availability`, { signal })).data,
  status: async (signal?: AbortSignal, refreshSession = true) => {
    // A first anonymous visit is a public preview, not an expired staff session.
    // Keep coordinated cookie refresh once this workspace has confirmed an account.
    const response = await apiClient.get<AssistantStatus>(`${BASE}/status`, { signal,
      ...(!refreshSession ? { validateStatus: (status: number) => status === 401 || status >= 200 && status < 300 } : {}),
    });
    if (response.status === 401) throw { code: "HTTP_401", status: 401, message: "Sign in to connect your workspace." };
    return response.data;
  },
  live: async (signal?: AbortSignal) => (await apiClient.get<{ observed_at: string; agencies: { id: string; name: string }[] }>(`${BASE}/live`, { signal })).data,
  conversations: async (cursor?: string) => (await apiClient.get<PageResult<Conversation>>(`${BASE}/conversations`, { params: { cursor } })).data,
  conversation: async (id: string, cursor?: string) => (await apiClient.get<PageResult<Turn>>(`${BASE}/conversations/${id}`, { params: { cursor } })).data,
  assets: async (cursor?: string) => (await apiClient.get<PageResult<Asset>>(`${BASE}/assets`, { params: { cursor } })).data,
  upload: async (file: File, signal?: AbortSignal) => {
    const form = new FormData(); form.append("file", file);
    return (await apiClient.post<Asset>(`${BASE}/attachments`, form, { signal, timeout: 120000, headers: { "Content-Type": "multipart/form-data" } })).data;
  },
  transcribe: async (audio: Blob, signal?: AbortSignal) => {
    const form = new FormData(); form.append("file", audio, audio.type.includes("mp4") ? "speech.m4a" : "speech.webm");
    return (await apiClient.post<{ text: string }>(`${BASE}/transcribe`, form, { signal, timeout: 150000, headers: { "Content-Type": "multipart/form-data" } })).data.text;
  },
  speak: async (text: string, signal?: AbortSignal) => (await apiClient.post<Blob>(`${BASE}/speech`, { text }, { signal, timeout: 150000, responseType: "blob" })).data,
  stream: async (input: { request_id: string; conversation_id: string; text: string; attachment_ids: string[]; mode: "chat" | "image"; image_count: number }, signal: AbortSignal, onEvent: (event: StreamEvent) => void) => {
    // Refresh through the existing coordinated cookie session before starting a non-retryable stream.
    await assistantApi.status(signal);
    const response = await fetch(`${BASE}/chat`, { method: "POST", credentials: "same-origin", signal,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" }, body: JSON.stringify(input) });
    if (!response.ok) throw await assistantError(response);
    if (!response.body) throw new Error("Streaming is unavailable in this browser.");
    for await (const event of decodeAssistantStream(response.body, signal)) onEvent(event);
  },
};
