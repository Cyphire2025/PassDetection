import { getCoordinatorDeviceId } from "@/lib/utils/coordinator-device-id";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type {
  HotelCheckinPassenger,
  HotelCheckinDashboard,
  HotelCheckinScanResponse,
} from "./operations-checkin.types";

export const checkinOperationsApi = {
  hotelCheckins: async (hotelId: string): Promise<HotelCheckinDashboard> => {
    const { data } = await apiClient.get<HotelCheckinDashboard>(
      API_ENDPOINTS.rooming.checkins(hotelId),
    );
    return data;
  },

  scanHotelCheckin: async (
    hotelId: string,
    qr_payload: string,
    client_event_id?: string,
  ): Promise<HotelCheckinScanResponse> => {
    const { data } = await apiClient.post<HotelCheckinScanResponse>(
      API_ENDPOINTS.rooming.checkinScan(hotelId),
      {
        qr_payload,
        client_event_id,
        device_id: typeof window === "undefined" ? undefined : getCoordinatorDeviceId(),
      },
    );
    return data;
  },

  updateHotelCheckin: async (
    checkinId: string,
    body: {
      key_issued?: boolean;
      welcome_letter_issued?: boolean;
      remarks?: string;
    },
  ): Promise<HotelCheckinPassenger> => {
    const { data } = await apiClient.patch<HotelCheckinPassenger>(
      API_ENDPOINTS.rooming.checkin(checkinId),
      body,
    );
    return data;
  },

  exportHotelCheckins: async (hotelId: string, hotelName = "hotel"): Promise<void> => {
    await downloadStreamedResponse({
      url: API_ENDPOINTS.rooming.checkinExport(hotelId),
      suggestedFilename: `${hotelName}_checkins.xlsx`,
    });
  },
};
