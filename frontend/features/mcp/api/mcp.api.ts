import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export const MCP_CAPABILITIES = {
  "mcp:read": { label: "Look up information", description: "Find groups, check passenger details and see recorded activity." },
  "mcp:export": { label: "Download reports", description: "Create and download the reports you ask for." },
  "mcp:upload": { label: "Use selected files", description: "Use files you choose for an available task." },
  "mcp:change": { label: "Make changes", description: "Create or update records for tasks you request." },
  "mcp:communicate": { label: "Send messages", description: "Send the messages you explicitly ask it to send." },
  "mcp:diagnose": { label: "Investigate problems", description: "Read limited, filtered technical information to help investigate a problem." },
} as const;
export type McpCapability = keyof typeof MCP_CAPABILITIES;
export interface McpOverview {
  enabled: boolean;
  deployment_enabled: boolean;
  emergency_disabled: boolean;
  resource: string;
  capabilities: McpCapability[];
  approved_clients: Record<string, string[]>;
  direct_clients?: Record<string, string[]>;
  client_names?: Record<string, string>;
  environment: string;
  revision: string | null;
  observed_at: string;
  qualification: string;
  read_only_mode?: boolean;
  effective_capabilities?: McpCapability[];
}
export interface McpReadSection {
  id: string; label: string; supported: boolean; tool_names: string[];
  coverage_description?: string;
  metadata_only?: boolean;
  tool_requirements?: { name: string; required_sections: string[] }[];
}
export interface McpReadAccess {
  read_only_mode: boolean; effective_capabilities: McpCapability[];
  allowed_read_sections: string[]; revision: number; sections: McpReadSection[];
  connection_metadata_tools: string[]; environment: string;
  backend_revision: string | null; observed_at: string;
}
export interface McpReadAccessUpdate {
  allowed_read_sections: string[]; expected_revision: number;
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
  status: "active" | "disabled" | "expired" | "revoked";
  enabled?: boolean;
  device_platform?: McpDevicePlatform | null;
}
export type McpDevicePlatform = "Windows" | "macOS" | "Other";
export type McpRequestStatus = "pending" | "approved" | "rejected" | "expired" | "finalized";
export interface McpConnectionRequest {
  id: string; name: string; device_platform: McpDevicePlatform; client_name: string;
  comparison_code: string; status: McpRequestStatus; requested_capabilities: McpCapability[];
  approved_capabilities?: McpCapability[] | null; created_at: string; expires_at: string;
  decided_at?: string | null; connection_id?: string | null;
}
export interface McpRequestApproval {
  name: string; device_platform: McpDevicePlatform; capabilities: McpCapability[];
}
export interface McpRequestCallback {
  redirect_url: string; client_id: string; redirect_uri: string; resource: string; state: string;
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
  tools: { name: string; description: string | null; capability: string; deployment_available: boolean; read_only: boolean; qualification: string;
    required_read_sections?: string[]; section_access_allowed?: boolean }[];
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
  device_platform?: McpDevicePlatform;
}
export const mcpApi = {
  overview: async (signal?: AbortSignal) => (await apiClient.get<McpOverview>(API_ENDPOINTS.mcp.overview, { signal })).data,
  readAccess: async (signal?: AbortSignal) => (await apiClient.get<McpReadAccess>(API_ENDPOINTS.mcp.readAccess, { signal })).data,
  updateReadAccess: async (update: McpReadAccessUpdate) => (await apiClient.put<McpReadAccess>(API_ENDPOINTS.mcp.readAccess, update)).data,
  connections: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpConnection>>(API_ENDPOINTS.mcp.connections, { params: { offset, limit: 25 }, signal })).data,
  activity: async (offset: number, search: string, signal?: AbortSignal) => (await apiClient.get<McpPage<McpActivity>>(API_ENDPOINTS.mcp.activity, { params: { offset, limit: 25, search }, signal })).data,
  inventory: async (signal?: AbortSignal) => (await apiClient.get<McpInventory>(API_ENDPOINTS.mcp.inventory, { signal })).data,
  operations: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpOperation>>(API_ENDPOINTS.mcp.operations, { params: { offset, limit: 25 }, signal })).data,
  artifacts: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpArtifact>>(API_ENDPOINTS.mcp.artifacts, { params: { offset, limit: 25 }, signal })).data,
  control: async (enabled: boolean) => (await apiClient.put<{ enabled: boolean }>(API_ENDPOINTS.mcp.control, { enabled })).data,
  revoke: async (id: string) => (await apiClient.post<{ revoked: boolean }>(API_ENDPOINTS.mcp.revoke(id))).data,
  updateConnection: async ({ id, ...update }: { id: string; name: string; capabilities: McpCapability[] }) => (await apiClient.patch<McpConnection>(API_ENDPOINTS.mcp.connection(id), update)).data,
  setConnectionAccess: async ({ id, enabled }: { id: string; enabled: boolean }) => (await apiClient.patch<McpConnection>(API_ENDPOINTS.mcp.connectionAccess(id), { enabled })).data,
  requests: async (offset: number, signal?: AbortSignal) => (await apiClient.get<McpPage<McpConnectionRequest>>(API_ENDPOINTS.mcp.requests, { params: { offset, limit: 25 }, signal })).data,
  approveRequest: async ({ id, ...approval }: McpRequestApproval & { id: string }) => (await apiClient.post<McpConnectionRequest>(API_ENDPOINTS.mcp.approveRequest(id), approval)).data,
  rejectRequest: async (id: string) => (await apiClient.post<McpConnectionRequest>(API_ENDPOINTS.mcp.rejectRequest(id), {})).data,
  authorize: async (request: McpConsentRequest) => (await apiClient.post<{ redirect_url: string }>(API_ENDPOINTS.mcp.authorize, request)).data,
};
