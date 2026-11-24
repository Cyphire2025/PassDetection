import { useQuery, useQueryClient } from "@tanstack/react-query";
import { mcpApi } from "../api/mcp.api";
import { mcpQueryKeys as keys } from "./mcp-query-keys";

function isAccessDenied(error: unknown) {
  const status = typeof error === "object" && error !== null && "status" in error ? error.status : undefined;
  return status === 401 || status === 403 || status === 404;
}

export function useMcpRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: keys.root });
}

export function useMcpOverview() {
  return useQuery({
    queryKey: keys.overview,
    queryFn: ({ signal }) => mcpApi.overview(signal),
    refetchOnWindowFocus: "always"
  });
}

export function useMcpReadAccess(enabled = true) {
  return useQuery({
    queryKey: [...keys.root, "read-access"],
    queryFn: ({ signal }) => mcpApi.readAccess(signal),
    refetchOnWindowFocus: "always",
    retry: false,
    enabled
  });
}

export function useMcpPermissions(enabled = true) {
  return useQuery({
    queryKey: [...keys.root, "permissions"],
    queryFn: ({ signal }) => mcpApi.permissions(signal),
    refetchOnWindowFocus: "always",
    retry: false,
    enabled
  });
}

export function useMcpConnections(offset: number) {
  return useQuery({
    queryKey: [...keys.root, "connections", offset],
    queryFn: ({ signal }) => mcpApi.connections(offset, signal),
    staleTime: 15_000
  });
}

export function useMcpActivity(offset: number, search: string) {
  return useQuery({
    queryKey: [...keys.root, "activity", offset, search],
    queryFn: ({ signal }) => mcpApi.activity(offset, search, signal)
  });
}

export function useMcpInventory() {
  return useQuery({
    queryKey: [...keys.root, "inventory"],
    queryFn: ({ signal }) => mcpApi.inventory(signal)
  });
}

export function useMcpOperations(offset: number) {
  return useQuery({
    queryKey: [...keys.root, "operations", offset],
    queryFn: ({ signal }) => mcpApi.operations(offset, signal),
    refetchInterval: (query) => !isAccessDenied(query.state.error)
      && query.state.data?.items.some((item) => ["queued", "running", "unknown"].includes(item.status)) ? 5000 : false
  });
}

export function useMcpArtifacts(offset: number) {
  return useQuery({
    queryKey: [...keys.root, "artifacts", offset],
    queryFn: ({ signal }) => mcpApi.artifacts(offset, signal)
  });
}

export function useMcpRequests(offset: number) {
  return useQuery({
    queryKey: [...keys.root, "requests", offset],
    queryFn: ({ signal }) => mcpApi.requests(offset, signal),
    retry: false,
    refetchInterval: (query) => isAccessDenied(query.state.error) ? false : 5000,
    refetchOnWindowFocus: "always"
  });
}
