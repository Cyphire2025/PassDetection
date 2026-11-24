import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { mcpApi } from "../api/mcp.api";
import { mcpQueryKeys as keys } from "./mcp-query-keys";

export function useMcpUpdateReadAccess() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (update: Parameters<typeof mcpApi.updateReadAccess>[0], _context, owner) => mcpApi.updateReadAccess(update, owner.requestConfig),
    retry: false,
    onMutate: () => client.cancelQueries({ queryKey: [...keys.root, "read-access"] }),
    onSuccess: (confirmed) => {
      client.setQueryData([...keys.root, "read-access"], confirmed);
      return Promise.all([
        client.invalidateQueries({ queryKey: keys.overview }),
        client.invalidateQueries({ queryKey: [...keys.root, "inventory"] }),
      ]);
    }
  });
}

export function useMcpUpdatePermissions() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (update: Parameters<typeof mcpApi.updatePermissions>[0], _context, owner) => mcpApi.updatePermissions(update, owner.requestConfig),
    retry: false,
    onMutate: () => client.cancelQueries({ queryKey: [...keys.root, "permissions"] }),
    onSuccess: (confirmed) => {
      client.setQueryData([...keys.root, "permissions"], confirmed);
      return Promise.all([
        client.invalidateQueries({ queryKey: keys.overview }),
        client.invalidateQueries({ queryKey: [...keys.root, "read-access"] }),
        client.invalidateQueries({ queryKey: [...keys.root, "inventory"] }),
        client.invalidateQueries({ queryKey: [...keys.root, "connections"] }),
      ]);
    }
  });
}

export function useMcpUpdateConnectionPermissions() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (update: Parameters<typeof mcpApi.updateConnectionPermissions>[0], _context, owner) => mcpApi.updateConnectionPermissions(update, owner.requestConfig),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root })
  });
}

export function useMcpControl() {
  const client = useQueryClient();
  return usePrivateMutation({
    mutationFn: (enabled: boolean, _context, owner) => mcpApi.control(enabled, owner.requestConfig),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.root })
  });
}
