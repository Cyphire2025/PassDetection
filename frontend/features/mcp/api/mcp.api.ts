import type {
  McpOverview,
  McpReadAccess,
  McpReadAccessUpdate,
  McpConnection,
  McpConnectionRequest,
  McpRequestApproval,
  McpActivity,
  McpPage,
  McpOperation,
  McpArtifact,
  McpInventory,
  McpCapability,
} from "./mcp.types";
import apiClient from "@/lib/api/client";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { McpConnectionPermissionUpdate, McpPermissionUpdate, McpPermissions } from "./mcp-permissions";

export type {
  McpOverview,
  McpReadSection,
  McpReadAccess,
  McpReadAccessUpdate,
  McpConnection,
  McpDevicePlatform,
  McpRequestStatus,
  McpConnectionRequest,
  McpRequestApproval,
  McpRequestCallback,
  McpActivity,
  McpPage,
  McpOperation,
  McpArtifact,
  McpInventory,
} from "./mcp.types";
export { MCP_CAPABILITIES, type McpCapability } from "./mcp-capabilities";
export type { McpConnectionPermissionUpdate, McpPermissionSection, McpPermissionUpdate, McpPermissions } from "./mcp-permissions";

function optionalRequestConfig(config?: OwnerBoundRequestConfig): [] | [OwnerBoundRequestConfig] {
  return config === undefined ? [] : [config];
}
export const mcpApi = {
  overview: async (signal?: AbortSignal) =>
    (await apiClient.get<McpOverview>(
      API_ENDPOINTS.mcp.overview,
      { signal }
    )).data,
  readAccess: async (signal?: AbortSignal) =>
    (await apiClient.get<McpReadAccess>(
      API_ENDPOINTS.mcp.readAccess,
      { signal }
    )).data,
  updateReadAccess: async (update: McpReadAccessUpdate, config?: OwnerBoundRequestConfig) =>
    (await apiClient.put<McpReadAccess>(
      API_ENDPOINTS.mcp.readAccess,
      update,
      ...optionalRequestConfig(config)
    )).data,
  permissions: async (signal?: AbortSignal) =>
    (await apiClient.get<McpPermissions>(
      API_ENDPOINTS.mcp.permissions,
      { signal }
    )).data,
  updatePermissions: async (update: McpPermissionUpdate, config?: OwnerBoundRequestConfig) =>
    (await apiClient.put<McpPermissions>(
      API_ENDPOINTS.mcp.permissions,
      update,
      ...optionalRequestConfig(config)
    )).data,
  updateConnectionPermissions: async ({ id, ...update }: McpConnectionPermissionUpdate, config?: OwnerBoundRequestConfig) =>
    (await apiClient.put<McpConnection>(
      API_ENDPOINTS.mcp.connectionPermissions(id),
      update,
      ...optionalRequestConfig(config)
    )).data,
  connections: async (offset: number, signal?: AbortSignal) =>
    (await apiClient.get<McpPage<McpConnection>>(
      API_ENDPOINTS.mcp.connections,
      { params: { offset, limit: 25 }, signal }
    )).data,
  activity: async (offset: number, search: string, signal?: AbortSignal) =>
    (await apiClient.get<McpPage<McpActivity>>(
      API_ENDPOINTS.mcp.activity,
      { params: { offset, limit: 25, search }, signal }
    )).data,
  inventory: async (signal?: AbortSignal) =>
    (await apiClient.get<McpInventory>(
      API_ENDPOINTS.mcp.inventory,
      { signal }
    )).data,
  operations: async (offset: number, signal?: AbortSignal) =>
    (await apiClient.get<McpPage<McpOperation>>(
      API_ENDPOINTS.mcp.operations,
      { params: { offset, limit: 25 }, signal }
    )).data,
  artifacts: async (offset: number, signal?: AbortSignal) =>
    (await apiClient.get<McpPage<McpArtifact>>(
      API_ENDPOINTS.mcp.artifacts,
      { params: { offset, limit: 25 }, signal }
    )).data,
  control: async (enabled: boolean, config?: OwnerBoundRequestConfig) =>
    (await apiClient.put<{ enabled: boolean }>(
      API_ENDPOINTS.mcp.control,
      { enabled },
      ...optionalRequestConfig(config)
    )).data,
  deleteConnection: async (id: string, config?: OwnerBoundRequestConfig) => {
    const { data } = await apiClient.delete<{ deleted: true }>(
      API_ENDPOINTS.mcp.connection(id),
      ...optionalRequestConfig(config)
    );
    if (data.deleted !== true) throw new Error("The connection could not be deleted. Refresh status and try again.");
    return data;
  },
  updateConnection: async ({ id, ...update }: { id: string; name: string; capabilities: McpCapability[] }, config?: OwnerBoundRequestConfig) =>
    (await apiClient.patch<McpConnection>(
      API_ENDPOINTS.mcp.connection(id),
      update,
      ...optionalRequestConfig(config)
    )).data,
  setConnectionAccess: async ({ id, enabled }: { id: string; enabled: boolean }, config?: OwnerBoundRequestConfig) =>
    (await apiClient.patch<McpConnection>(
      API_ENDPOINTS.mcp.connectionAccess(id),
      { enabled },
      ...optionalRequestConfig(config)
    )).data,
  requests: async (offset: number, signal?: AbortSignal) =>
    (await apiClient.get<McpPage<McpConnectionRequest>>(
      API_ENDPOINTS.mcp.requests,
      { params: { offset, limit: 25 }, signal }
    )).data,
  approveRequest: async ({ id, ...approval }: McpRequestApproval & { id: string }, config?: OwnerBoundRequestConfig) =>
    (await apiClient.post<McpConnectionRequest>(
      API_ENDPOINTS.mcp.approveRequest(id),
      approval,
      ...optionalRequestConfig(config)
    )).data,
  rejectRequest: async (id: string, config?: OwnerBoundRequestConfig) =>
    (await apiClient.post<McpConnectionRequest>(
      API_ENDPOINTS.mcp.rejectRequest(id),
      {},
      ...optionalRequestConfig(config)
    )).data,
};
