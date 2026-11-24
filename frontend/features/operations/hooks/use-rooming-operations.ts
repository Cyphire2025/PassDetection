import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import {
  operationsApi,
  type RoomingAllocationMutationResponse,
  type RoomingWorkspace,
} from "../api/operations.api";
import {
  expectedRoomingRevisionsForHotel,
  expectedRoomingRevisionsForSelection,
  isRoomingRevisionConflict,
  mergeRoomingAllocationMutation,
  type RoomingMutationMergeStatus,
} from "../services/rooming-allocation-mutations";
import { roomingWorkspaceKey } from "./operations-query-scope";

export function useRoomingWorkspace(groupId: string) {
  return useQuery({
    queryKey: roomingWorkspaceKey(groupId),
    queryFn: () => operationsApi.roomingWorkspace(groupId),
    retry: false,
  });
}

export function useRoomingPriorityFields(groupId: string) {
  return useQuery({
    queryKey: [...roomingWorkspaceKey(groupId), "priority-fields"],
    queryFn: () => operationsApi.roomingPriorityFields(groupId),
    enabled: Boolean(groupId),
    staleTime: 30_000,
    retry: false,
  });
}

export function useRoomingRosterFieldValues(
  groupId: string,
  fieldKey: string | null,
) {
  return useQuery({
    queryKey: [
      ...roomingWorkspaceKey(groupId),
      "roster-field-values",
      fieldKey,
    ],
    queryFn: () => operationsApi.roomingRosterFieldValues(
      groupId,
      fieldKey as string,
    ),
    enabled: Boolean(groupId && fieldKey),
    staleTime: 30_000,
    retry: false,
  });
}

export function useRoomingActions(groupId: string) {
  const queryClient = useQueryClient();
  const workspaceKey = roomingWorkspaceKey(groupId);
  const refresh = () => queryClient.invalidateQueries({ queryKey: workspaceKey });
  const currentWorkspace = () => {
    const workspace = queryClient.getQueryData<RoomingWorkspace>(workspaceKey);
    if (!workspace) {
      throw new Error("Rooming data is no longer available. Refresh and try again.");
    }
    return workspace;
  };
  const applyAllocationMutation = (
    mutation: RoomingAllocationMutationResponse,
  ) => {
    let mergeStatus: RoomingMutationMergeStatus = "incompatible";
    queryClient.setQueryData<RoomingWorkspace>(workspaceKey, (workspace) => {
      if (!workspace) return workspace;
      const result = mergeRoomingAllocationMutation(workspace, mutation);
      mergeStatus = result.status;
      return result.workspace;
    });
    if (mergeStatus === "incompatible") {
      void queryClient.invalidateQueries({ queryKey: workspaceKey });
    }
    if (mutation.changed) {
      void queryClient.invalidateQueries({ queryKey: ["rooming", "checkins"] });
    }
  };
  const handleAllocationError = (error: unknown) => {
    if (!isRoomingRevisionConflict(error)) return;
    void queryClient.invalidateQueries({ queryKey: workspaceKey });
    void queryClient.invalidateQueries({ queryKey: ["rooming", "checkins"] });
  };

  return {
    createHotel: usePrivateMutation({
      mutationFn: (body: { hotel_name: string; city?: string; check_in_date?: string; check_out_date?: string }) =>
        operationsApi.createRoomingHotel(groupId, body),
      onSuccess: refresh,
    }),
    updateHotel: usePrivateMutation({
      mutationFn: ({ hotelId, ...body }: {
        hotelId: string;
        hotel_name: string;
        city?: string;
        check_in_date?: string;
        check_out_date?: string;
      }) => operationsApi.updateRoomingHotel(hotelId, body),
      onSuccess: refresh,
    }),
    selectHotelPassengers: usePrivateMutation({
      mutationFn: ({ hotelId, passengerIds, mode = "add" }: {
        hotelId: string;
        passengerIds: string[];
        mode?: "replace" | "add" | "remove";
      }) => {
        const workspace = currentWorkspace();
        return operationsApi.updateRoomingPassengerSelection(hotelId, {
          passenger_ids: passengerIds,
          mode,
          expected_allocation_revisions: expectedRoomingRevisionsForSelection(
            workspace,
            { hotelId, passengerIds, mode },
          ),
        });
      },
      onSuccess: applyAllocationMutation,
      onError: handleAllocationError,
    }),
    setPassengerVip: usePrivateMutation({
      mutationFn: ({ hotelId, passengerIds, isVip }: {
        hotelId: string;
        passengerIds: string[];
        isVip: boolean;
      }) => {
        const workspace = currentWorkspace();
        return operationsApi.updateRoomingVip(hotelId, {
          passenger_ids: passengerIds,
          is_vip: isVip,
          expected_allocation_revisions: expectedRoomingRevisionsForHotel(
            workspace,
            hotelId,
          ),
        });
      },
      onSuccess: applyAllocationMutation,
      onError: handleAllocationError,
    }),
    autoAllocate: usePrivateMutation({
      mutationFn: ({ hotelId, priorityFields }: {
        hotelId: string;
        priorityFields: string[];
      }) => {
        const workspace = currentWorkspace();
        return operationsApi.autoAllocateRoomingHotel(hotelId, {
          priority_fields: priorityFields,
          expected_allocation_revisions: expectedRoomingRevisionsForHotel(
            workspace,
            hotelId,
          ),
        });
      },
      onSuccess: applyAllocationMutation,
      onError: handleAllocationError,
    }),
  };
}
