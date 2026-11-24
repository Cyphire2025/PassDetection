import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type {
  RoomingPriorityFieldOptions,
  RoomingRosterFieldValues,
  RoomingHotel,
  RoomingWorkspace,
  RoomingAllocationMutationResponse,
} from "./operations-rooming.types";

export const roomingOperationsApi = {
  roomingWorkspace: async (groupId: string): Promise<RoomingWorkspace> => {
    const { data } = await apiClient.get<RoomingWorkspace>(API_ENDPOINTS.rooming.group(groupId));
    return data;
  },

  roomingPriorityFields: async (groupId: string): Promise<RoomingPriorityFieldOptions> => {
    const { data } = await apiClient.get<RoomingPriorityFieldOptions>(
      API_ENDPOINTS.rooming.priorityFields(groupId),
    );
    return data;
  },

  roomingRosterFieldValues: async (
    groupId: string,
    fieldKey: string,
  ): Promise<RoomingRosterFieldValues> => {
    const { data } = await apiClient.get<RoomingRosterFieldValues>(
      API_ENDPOINTS.rooming.rosterFieldValues(groupId),
      { params: { field_key: fieldKey } },
    );
    return data;
  },

  createRoomingHotel: async (groupId: string, body: {
    hotel_name: string;
    city?: string;
    check_in_date?: string;
    check_out_date?: string;
  }): Promise<RoomingHotel> => {
    const { data } = await apiClient.post<RoomingHotel>(API_ENDPOINTS.rooming.hotels(groupId), body);
    return data;
  },

  updateRoomingHotel: async (hotelId: string, body: {
    hotel_name: string;
    city?: string;
    check_in_date?: string;
    check_out_date?: string;
  }): Promise<RoomingHotel> => {
    const { data } = await apiClient.patch<RoomingHotel>(API_ENDPOINTS.rooming.hotel(hotelId), body);
    return data;
  },

  updateRoomingPassengerSelection: async (
    hotelId: string,
    body: {
      passenger_ids: string[];
      mode: "replace" | "add" | "remove";
      expected_allocation_revisions: Record<string, number>;
    },
  ): Promise<RoomingAllocationMutationResponse> => {
    const { data } = await apiClient.put<RoomingAllocationMutationResponse>(
      API_ENDPOINTS.rooming.passengerSelection(hotelId),
      body,
    );
    return data;
  },

  updateRoomingVip: async (
    hotelId: string,
    body: {
      passenger_ids: string[];
      is_vip: boolean;
      expected_allocation_revisions: Record<string, number>;
    },
  ): Promise<RoomingAllocationMutationResponse> => {
    const { data } = await apiClient.put<RoomingAllocationMutationResponse>(
      API_ENDPOINTS.rooming.vip(hotelId),
      body,
    );
    return data;
  },

  autoAllocateRoomingHotel: async (
    hotelId: string,
    body: {
      priority_fields: string[];
      expected_allocation_revisions: Record<string, number>;
    },
  ): Promise<RoomingAllocationMutationResponse> => {
    const { data } = await apiClient.post<RoomingAllocationMutationResponse>(
      API_ENDPOINTS.rooming.autoAllocate(hotelId),
      body,
    );
    return data;
  },

  exportRoomingHotel: async (hotelId: string, hotelName = "hotel"): Promise<void> => {
    await downloadStreamedResponse({
      url: API_ENDPOINTS.rooming.hotelExport(hotelId),
      suggestedFilename: `${hotelName}_rooming_list.xlsx`,
    });
  },
};
