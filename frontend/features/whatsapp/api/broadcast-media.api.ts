import apiClient from '@/lib/api/client';
import { API_ENDPOINTS } from '@/lib/api/endpoints';
import type { WhatsAppWelcomeMediaResponse } from '../types/messages';

export async function uploadWelcomeImage(
  groupId: string,
  image: File,
): Promise<WhatsAppWelcomeMediaResponse> {
  const formData = new FormData();
  formData.append("image", image);
  const { data } = await apiClient.post<WhatsAppWelcomeMediaResponse>(
    API_ENDPOINTS.whatsapp.welcomeMedia(groupId),
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}
