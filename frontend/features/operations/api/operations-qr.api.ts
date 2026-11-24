import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  PassengerQrToken,
  GroupPassengerQrCodes,
  QrDeliveryPreview,
  SendQrBroadcastResponse,
} from "./operations-qr.types";

export const qrOperationsApi = {
  groupQrCodes: async (groupId: string): Promise<GroupPassengerQrCodes> => {
    const { data } = await apiClient.get<GroupPassengerQrCodes>(API_ENDPOINTS.tourOperations.groupQrCodes(groupId));
    return data;
  },

  qrDeliveryPreview: async (groupId: string): Promise<QrDeliveryPreview> => {
    const { data } = await apiClient.get<QrDeliveryPreview>(
      API_ENDPOINTS.tourOperations.groupQrWhatsAppPreview(groupId),
    );
    return data;
  },

  sendQrBroadcast: async (
    groupId: string,
    body: { qr_token_ids: string[]; message_content: string },
  ): Promise<SendQrBroadcastResponse> => {
    const { data } = await apiClient.post<SendQrBroadcastResponse>(
      API_ENDPOINTS.tourOperations.groupQrWhatsAppSend(groupId),
      body,
    );
    return data;
  },

  generatePassengerQr: async (groupId: string, passengerId: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.post<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQr(groupId, passengerId));
    return data;
  },

  regeneratePassengerQr: async (groupId: string, passengerId: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.post<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrRegenerate(groupId, passengerId));
    return data;
  },

  revokePassengerQr: async (groupId: string, passengerId: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.post<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrRevoke(groupId, passengerId));
    return data;
  },

  setPassengerQrActive: async (groupId: string, passengerId: string, isActive: boolean): Promise<PassengerQrToken> => {
    const { data } = await apiClient.patch<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrActive(groupId, passengerId), {
      is_active: isActive,
    });
    return data;
  },

  setPassengerQrExpiration: async (groupId: string, passengerId: string, expiresAt: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.patch<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrExpiration(groupId, passengerId), {
      expires_at: expiresAt,
    });
    return data;
  },
};
