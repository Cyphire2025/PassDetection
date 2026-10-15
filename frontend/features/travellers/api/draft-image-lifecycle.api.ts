import apiClient from "@/lib/api/client";

export interface DraftImageActivity { images_present: boolean; presence_recorded: boolean; heartbeat_after_seconds: number }
export function draftImageLifecycleApi<T>(path: string, headers: Record<string, string>) {
  return {
    activity: async (signal?: AbortSignal) => (await apiClient.post<DraftImageActivity>(`${path}/activity`, undefined, { signal, headers })).data,
    discard: async (expected_revision: number, signal?: AbortSignal, keepalive = false): Promise<T | undefined> => {
      const body = { expected_revision };
      if (!keepalive) return (await apiClient.post<T>(`${path}/discard-documents`, body, { signal, headers })).data;
      await fetch(`${path}/discard-documents`, { method: "POST", credentials: "include", keepalive: true, headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
    },
  };
}
