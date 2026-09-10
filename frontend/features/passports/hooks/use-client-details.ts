import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { clientDetailsApi, type ClientDetailsPatch } from "../api/client-details.api";

const editorKey = (id: string) => ["passport-client-details-editor", id] as const;

export function useClientDetailsEditor(id: string) {
  return useQuery({
    queryKey: editorKey(id),
    queryFn: () => clientDetailsApi.get(id),
    staleTime: 0,
    gcTime: 0,
    // An open editor keeps its original version and draft. Background refetches
    // must not silently overwrite edits or advance the optimistic lock.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useUpdateClientDetails(id: string, groupId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClientDetailsPatch) => clientDetailsApi.update(id, body),
    retry: false,
    onSuccess: async (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(id), updated);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all }),
        queryClient.invalidateQueries({ queryKey: ["upload-links", groupId] }),
        queryClient.invalidateQueries({ queryKey: ["whatsapp"] }),
        queryClient.invalidateQueries({ queryKey: ["passport-export-fields", groupId] }),
        queryClient.invalidateQueries({ queryKey: ["passport-export-history", groupId] }),
      ]);
    },
  });
}
