import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { SendTravellerWelcomeRequest } from "@/types/document-distribution.types";
import { travellerWelcomeApi } from "../api/traveller-welcome.api";

export function useTravellerWelcomePreview(groupId: string, sourceBroadcastId?: string, headerImageId?: string) {
  return useQuery({
    queryKey: ["document-distribution", "traveller-welcome", groupId, sourceBroadcastId ?? "default", headerImageId ?? "original"],
    queryFn: ({ signal }) => travellerWelcomeApi.preview(groupId, sourceBroadcastId, headerImageId, signal),
    enabled: Boolean(groupId),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const seconds = query.state.data?.poll_after_seconds;
      return seconds && seconds > 0 ? seconds * 1_000 : false;
    },
    refetchIntervalInBackground: false,
    gcTime: 0,
  });
}

export function useSendTravellerWelcome(groupId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: SendTravellerWelcomeRequest) => travellerWelcomeApi.send(groupId, request),
    onSettled: () => {
      // A timeout can occur after the server queues messages; refresh before offering a retry.
      queryClient.invalidateQueries({ queryKey: ["document-distribution", "traveller-welcome", groupId] });
      queryClient.invalidateQueries({ queryKey: ["document-distribution", "delivery-preview", groupId] });
    },
  });
}
