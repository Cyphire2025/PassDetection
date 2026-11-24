import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { mcpApi, type McpConnection, type McpPage } from "../api/mcp.api";
import { mcpQueryKeys as keys } from "./mcp-query-keys";

export function useMcpDeleteConnection() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (id: string, _context, owner) => mcpApi.deleteConnection(id, owner.requestConfig),
    retry: false,
    onSuccess: (_, id) => {
      client.setQueriesData<McpPage<McpConnection>>({ queryKey: [...keys.root, "connections"] }, (page) => page
        ? { ...page, items: page.items.filter((connection) => connection.id !== id) } : page);
      return client.invalidateQueries({ queryKey: keys.root });
    }
  });
}

export function useMcpUpdateConnection() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (update: Parameters<typeof mcpApi.updateConnection>[0], _context, owner) => mcpApi.updateConnection(update, owner.requestConfig),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root })
  });
}

export function useMcpSetConnectionAccess() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (update: Parameters<typeof mcpApi.setConnectionAccess>[0], _context, owner) => mcpApi.setConnectionAccess(update, owner.requestConfig),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root })
  });
}

export function useMcpApproveRequest() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (approval: Parameters<typeof mcpApi.approveRequest>[0], _context, owner) => mcpApi.approveRequest(approval, owner.requestConfig),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root })
  });
}

export function useMcpRejectRequest() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (id: string, _context, owner) => mcpApi.rejectRequest(id, owner.requestConfig),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root })
  });
}
