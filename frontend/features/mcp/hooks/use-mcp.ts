import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mcpApi, type McpConnection, type McpPage } from "../api/mcp.api";

const keys = { root: ["mcp-admin"] as const, overview: ["mcp-admin", "overview"] as const };
export function useMcpRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: keys.root });
}
export function useMcpOverview() {
  return useQuery({ queryKey: keys.overview, queryFn: ({ signal }) => mcpApi.overview(signal), refetchOnWindowFocus: "always" });
}
export function useMcpReadAccess(enabled = true) {
  return useQuery({ queryKey: [...keys.root, "read-access"], queryFn: ({ signal }) => mcpApi.readAccess(signal),
    refetchOnWindowFocus: "always", retry: false, enabled });
}
export function useMcpUpdateReadAccess() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.updateReadAccess, retry: false,
    onMutate: () => client.cancelQueries({ queryKey: [...keys.root, "read-access"] }),
    onSuccess: (confirmed) => {
      client.setQueryData([...keys.root, "read-access"], confirmed);
      return Promise.all([
        client.invalidateQueries({ queryKey: keys.overview }),
        client.invalidateQueries({ queryKey: [...keys.root, "inventory"] }),
      ]);
    } });
}
export function useMcpPermissions(enabled = true) {
  return useQuery({ queryKey: [...keys.root, "permissions"], queryFn: ({ signal }) => mcpApi.permissions(signal),
    refetchOnWindowFocus: "always", retry: false, enabled });
}
export function useMcpUpdatePermissions() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.updatePermissions, retry: false,
    onMutate: () => client.cancelQueries({ queryKey: [...keys.root, "permissions"] }),
    onSuccess: (confirmed) => {
      client.setQueryData([...keys.root, "permissions"], confirmed);
      return Promise.all([
        client.invalidateQueries({ queryKey: keys.overview }),
        client.invalidateQueries({ queryKey: [...keys.root, "read-access"] }),
        client.invalidateQueries({ queryKey: [...keys.root, "inventory"] }),
        client.invalidateQueries({ queryKey: [...keys.root, "connections"] }),
      ]);
    } });
}
export function useMcpUpdateConnectionPermissions() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.updateConnectionPermissions, retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
export function useMcpConnections(offset: number) {
  return useQuery({ queryKey: [...keys.root, "connections", offset], queryFn: ({ signal }) => mcpApi.connections(offset, signal), staleTime: 15_000 });
}
export function useMcpActivity(offset: number, search: string) {
  return useQuery({ queryKey: [...keys.root, "activity", offset, search], queryFn: ({ signal }) => mcpApi.activity(offset, search, signal) });
}
export function useMcpInventory() {
  return useQuery({ queryKey: [...keys.root, "inventory"], queryFn: ({ signal }) => mcpApi.inventory(signal) });
}
export function useMcpOperations(offset: number) {
  return useQuery({ queryKey: [...keys.root, "operations", offset], queryFn: ({ signal }) => mcpApi.operations(offset, signal),
    refetchInterval: (query) => query.state.data?.items.some((item) => ["queued", "running", "unknown"].includes(item.status)) ? 5000 : false });
}
export function useMcpArtifacts(offset: number) {
  return useQuery({ queryKey: [...keys.root, "artifacts", offset], queryFn: ({ signal }) => mcpApi.artifacts(offset, signal) });
}
export function useMcpControl() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.control, retry: false, onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
export function useMcpRevoke() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.revoke, retry: false, onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
export function useMcpDeleteConnection() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.deleteConnection, retry: false,
    onSuccess: (_, id) => {
      client.setQueriesData<McpPage<McpConnection>>({ queryKey: [...keys.root, "connections"] }, (page) => page
        ? { ...page, items: page.items.filter((connection) => connection.id !== id) } : page);
      return client.invalidateQueries({ queryKey: keys.root });
    } });
}
export function useMcpUpdateConnection() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.updateConnection, retry: false, onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
export function useMcpSetConnectionAccess() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.setConnectionAccess, retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
export function useMcpAuthorize() {
  return useMutation({ mutationFn: mcpApi.authorize, retry: false });
}
export function useMcpRequests(offset: number) {
  return useQuery({ queryKey: [...keys.root, "requests", offset], queryFn: ({ signal }) => mcpApi.requests(offset, signal),
    retry: false, refetchInterval: 5000, refetchOnWindowFocus: "always" });
}
export function useMcpApproveRequest() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.approveRequest, retry: false, onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
export function useMcpRejectRequest() {
  const client = useQueryClient();
  return useMutation({ mutationFn: mcpApi.rejectRequest, retry: false, onSuccess: () => client.invalidateQueries({ queryKey: keys.root }) });
}
