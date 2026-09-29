import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export const MCP_CAPABILITIES = {
  "mcp:read": { label: "Live information", description: "Read application records and processing status." },
  "mcp:export": { label: "Exports", description: "Generate and download permitted reports and files." },
  "mcp:upload": { label: "File uploads", description: "Upload files you provide to supported workflows." },
  "mcp:change": { label: "Application changes", description: "Create and update records through permitted workflows." },
  "mcp:communicate": { label: "Communications", description: "Prepare and send messages when instructed." },
  "mcp:diagnose": { label: "Diagnostics", description: "Inspect bounded, redacted application logs." },
} as const;
export type McpCapability = keyof typeof MCP_CAPABILITIES;
export interface McpOverview {
  enabled: boolean;
  deployment_enabled: boolean;
  emergency_disabled: boolean;
  resource: string;
  capabilities: McpCapability[];
  approved_clients: Record<string, string[]>;
  environment: string;
  revision: string | null;
  observed_at: string;
  qualification: string;
}
export interface McpConnection {
  id: string;
  user_id: string;
  client_id: string;
  name: string;
  capabilities: McpCapability[];
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  status: "active" | "expired" | "revoked";
}
export interface McpActivity {
  id: string;
  action: string;
  result: string;
  entity_id: string | null;
  created_at: string;
}
export interface McpPage<T> { items: T[]; next_offset: number | null }
export interface McpOperation {
  id: string; operation: string; workflow_id: string; connection_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "unknown";
  progress: number; stage: string; revision: number;
  created_entities: { entity_type: string; entity_id: string; path: string }[];
  created_at: string; updated_at: string; completed_at: string | null;
}
export interface McpArtifact {
  id: string; connection_id: string | null; group_id: string | null; direction: "upload" | "export";
  kind?: "artifact" | "contact_workbook" | "whatsapp_header";
  agency_id?: string; broadcast_id?: string | null; operation_id?: string | null;
  sha256?: string; attempt_deadline?: string | null;
  purpose: string; filename: string; byte_size: number; created_at: string; expires_at: string;
  status: "available" | "expired" | "delivered" | "staged" | "queued" | "running" | "ingested" | "ingestion_failed" | "imported" | "uploading" | "ready" | "failed" | "unknown"; delivered_at: string | null;
}
export interface McpInventory {
  tool_count: number; environment: string; revision: string | null; qualification: string;
  tools: { name: string; description: string | null; capability: string; deployment_available: boolean; read_only: boolean; qualification: string }[];
  file_transports: { name: string; capability: string; required_capabilities?: string[]; business_ingestion?: boolean }[];
}
export interface McpConsentRequest {
  client_id: string;
  redirect_uri: string;
  resource: string;
  state: string;
  code_challenge: string;
  code_challenge_method: "S256";
  response_type: "code";
  scopes: McpCapability[];
  name: string;
}
export const mcpApi = {
  overview: async (signal?: AbortSignal) => (await apiClient.get<McpOverview>(API_ENDPOINTS.mcp.overview, { signal })).data,
  connections: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpConnection>>(API_ENDPOINTS.mcp.connections, { params: { offset, limit: 25 }, signal })).data,
  activity: async (offset: number, search: string, signal?: AbortSignal) => (await apiClient.get<McpPage<McpActivity>>(API_ENDPOINTS.mcp.activity, { params: { offset, limit: 25, search }, signal })).data,
  inventory: async (signal?: AbortSignal) => (await apiClient.get<McpInventory>(API_ENDPOINTS.mcp.inventory, { signal })).data,
  operations: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpOperation>>(API_ENDPOINTS.mcp.operations, { params: { offset, limit: 25 }, signal })).data,
  artifacts: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpArtifact>>(API_ENDPOINTS.mcp.artifacts, { params: { offset, limit: 25 }, signal })).data,
  control: async (enabled: boolean) => (await apiClient.put<{ enabled: boolean }>(API_ENDPOINTS.mcp.control, { enabled })).data,
  revoke: async (id: string) => (await apiClient.post<{ revoked: boolean }>(API_ENDPOINTS.mcp.revoke(id))).data,
  updateConnection: async ({ id, ...update }: { id: string; name: string; capabilities: McpCapability[] }) => (await apiClient.patch<McpConnection>(API_ENDPOINTS.mcp.connection(id), update)).data,
  authorize: async (request: McpConsentRequest) => (await apiClient.post<{ redirect_url: string }>(API_ENDPOINTS.mcp.authorize, request)).data,
};
