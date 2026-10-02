import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { McpConnectionRequest, McpDevicePlatform, McpRequestCallback } from "./mcp.api";

export class McpRequestError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

async function requesterFetch<T>(id: string, method: "GET" | "PATCH" | "POST", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(method === "POST" ? API_ENDPOINTS.mcp.finalizeRequest(id) : API_ENDPOINTS.mcp.publicRequest(id), {
    method, credentials: "include", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer", signal,
    headers: { "X-MCP-Request": id, ...(method !== "GET" ? { "Content-Type": "application/json" } : {}) },
    ...(method !== "GET" ? { body: JSON.stringify(body ?? {}) } : {}),
  });
  if (!response.ok) throw new McpRequestError(response.status, response.status === 404 || response.status === 409
    ? "This access request is no longer available. Start Authenticate again from your app."
    : "The request could not be checked. Keep this tab open and try again.");
  return await response.json() as T;
}

export const mcpRequestApi = {
  status: (id: string, signal?: AbortSignal) => requesterFetch<McpConnectionRequest>(id, "GET", undefined, signal),
  update: (id: string, labels: { name: string; device_platform: McpDevicePlatform }) => requesterFetch<McpConnectionRequest>(id, "PATCH", labels),
  finalize: (id: string) => requesterFetch<McpRequestCallback>(id, "POST"),
};
