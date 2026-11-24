import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PassportImageType } from "@/types/passport.types";
import type {
  PassportImageCropState,
  SavePassportImageCropRequest,
  PassportImageLibraryItem,
  PassportImageLibrary,
} from "./passport-images.types";

export const passportImagesApi = {
  getImageCrop: async (
    id: string,
    imageType: PassportImageType,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.get<PassportImageCropState>(
      API_ENDPOINTS.passports.imageCrop(id, imageType),
    );
    return data;
  },

  getOriginalImage: async (
    id: string,
    imageType: PassportImageType,
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(
      API_ENDPOINTS.passports.originalImage(id, imageType),
      { responseType: "blob", signal },
    );
    return data;
  },

  getEditableImage: async (
    url: string,
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(url, {
      responseType: "blob",
      signal,
    });
    return data;
  },

  listImageLibrary: async (
    id: string,
    imageType: PassportImageType,
    signal?: AbortSignal,
  ): Promise<PassportImageLibraryItem[]> => {
    const { data } = await apiClient.get<PassportImageLibrary>(
      API_ENDPOINTS.passports.imageLibrary(id, imageType),
      { signal },
    );
    return data.items;
  },

  uploadImageLibraryImage: async (
    id: string,
    imageType: PassportImageType,
    image: File,
    expectedRevision: number,
  ): Promise<PassportImageLibraryItem> => {
    const formData = new FormData();
    formData.append("image", image, image.name);
    formData.append("expected_revision", String(expectedRevision));
    const { data } = await apiClient.post<PassportImageLibraryItem>(
      API_ENDPOINTS.passports.imageLibrary(id, imageType),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      },
    );
    return data;
  },

  useImageLibraryImage: async (
    id: string,
    imageType: PassportImageType,
    itemId: string,
    request: SavePassportImageCropRequest,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.post<PassportImageCropState>(
      API_ENDPOINTS.passports.imageLibraryUse(id, imageType, itemId),
      request,
      { timeout: 120_000 },
    );
    return data;
  },

  saveImageCrop: async (
    id: string,
    imageType: PassportImageType,
    request: SavePassportImageCropRequest,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.put<PassportImageCropState>(
      API_ENDPOINTS.passports.imageCrop(id, imageType),
      request,
    );
    return data;
  },

  resetImageCrop: async (
    id: string,
    imageType: PassportImageType,
    expectedRevision: number,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.delete<PassportImageCropState>(
      API_ENDPOINTS.passports.imageCrop(id, imageType),
      {
        data: { expected_revision: expectedRevision },
      },
    );
    return data;
  },
};

