import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { passportsApi } from "../api/passports.api";
import { updateDisplayName, type DisplayNamePatch } from "../api/display-name.api";

export function useDisplayNameEditor(id: string, groupId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["passport-display-name-editor", groupId, id],
    queryFn: () => passportsApi.getById(id),
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (body: DisplayNamePatch) => updateDisplayName(groupId, id, body),
    retry: false,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all }),
        queryClient.invalidateQueries({ queryKey: ["document-distribution"] }),
        queryClient.invalidateQueries({ queryKey: ["whatsapp"] }),
        queryClient.invalidateQueries({ queryKey: ["upload-links"] }),
      ]);
    },
  });
  return { query, mutation };
}
