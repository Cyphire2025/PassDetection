import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  PassportImageCropState,
  SavePassportImageCropRequest,
  VisaAiEditPreview,
  ApplyVisaAiEditRequest,
  VisaAiLibraryImage,
  VisaAiLibrary,
  VisaAiGenerationJob,
} from "./passport-images.types";

export const passportVisaAiApi = {
  generateVisaAiPreview: async (
    id: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<VisaAiEditPreview> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.visaAiPreview(id),
      { prompt },
      { responseType: "blob", timeout: 120_000, signal },
    );
    const token = response.headers["x-visa-ai-edit-token"];
    if (typeof token !== "string" || !token) {
      throw new Error("The generated Visa image did not include a save token.");
    }
    return { blob: response.data, token };
  },

  applyVisaAiEdit: async (
    id: string,
    request: ApplyVisaAiEditRequest,
  ): Promise<PassportImageCropState> => {
    const formData = new FormData();
    formData.append("image", request.image, "visa-ai-preview.jpg");
    formData.append("preview_token", request.previewToken);
    formData.append("prompt", request.prompt);
    formData.append("x", String(request.x));
    formData.append("y", String(request.y));
    formData.append("width", String(request.width));
    formData.append("height", String(request.height));
    formData.append("rotation_degrees", String(request.rotation_degrees));
    formData.append("sharpness", String(request.sharpness));
    formData.append("expected_revision", String(request.expected_revision));
    const { data } = await apiClient.post<PassportImageCropState>(
      API_ENDPOINTS.passports.visaAiApply(id),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      },
    );
    return data;
  },

  listVisaAiLibrary: async (id: string): Promise<VisaAiLibraryImage[]> => {
    const { data } = await apiClient.get<VisaAiLibrary>(
      API_ENDPOINTS.passports.visaAiLibrary(id),
    );
    return data.items;
  },

  generateVisaAiLibraryImage: async (
    id: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<VisaAiLibraryImage> => {
    const { data } = await apiClient.post<VisaAiLibraryImage>(
      API_ENDPOINTS.passports.visaAiLibrary(id),
      { prompt },
      { timeout: 120_000, signal },
    );
    return data;
  },

  createVisaAiGenerationJob: async (
    id: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<VisaAiGenerationJob> => {
    const { data } = await apiClient.post<VisaAiGenerationJob>(
      API_ENDPOINTS.passports.visaAiJobs(id),
      { prompt },
      { signal },
    );
    return data;
  },

  getActiveVisaAiGenerationJob: async (
    id: string,
    signal?: AbortSignal,
  ): Promise<VisaAiGenerationJob | null> => {
    const { data } = await apiClient.get<VisaAiGenerationJob | null>(
      API_ENDPOINTS.passports.visaAiActiveJob(id),
      { signal },
    );
    return data ?? null;
  },

  getVisaAiGenerationJob: async (
    id: string,
    jobId: string,
    signal?: AbortSignal,
  ): Promise<VisaAiGenerationJob> => {
    const { data } = await apiClient.get<VisaAiGenerationJob>(
      API_ENDPOINTS.passports.visaAiJob(id, jobId),
      { signal },
    );
    return data;
  },

  useVisaAiLibraryImage: async (
    id: string,
    generationId: string,
    request: SavePassportImageCropRequest,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.post<PassportImageCropState>(
      API_ENDPOINTS.passports.visaAiLibraryUse(id, generationId),
      request,
      { timeout: 120_000 },
    );
    return data;
  },
};

