import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export type PublicUploadPurpose = "passport" | "visa";

export const PUBLIC_UPLOAD_ACCEPT = [
  ".jpg", ".jpeg", ".png", ".heic", ".heif", ".avif", ".pdf",
  "image/jpeg", "image/jpg", "image/png", "image/heic", "image/heif", "image/avif", "application/pdf",
].join(",");

export const PUBLIC_DOCUMENT_MAX_BYTES = 2 * 1024 * 1024;
export const PUBLIC_VISA_IMAGE_MAX_BYTES = 10 * 1024 * 1024;

export function isPdfUpload(file: Pick<File, "name" | "type">): boolean {
  return file.type.toLowerCase() === "application/pdf" || /\.pdf$/i.test(file.name);
}

/** Fast picker feedback; the server checks the actual bytes and PDF page count. */
export function publicUploadFileError(file: File, purpose: PublicUploadPurpose): string | null {
  if (!file.size) return "This file is empty. Please choose an image or a single-page PDF.";
  const pdf = isPdfUpload(file);
  const limit = purpose === "passport" || pdf ? PUBLIC_DOCUMENT_MAX_BYTES : PUBLIC_VISA_IMAGE_MAX_BYTES;
  if (file.size > limit) {
    return pdf
      ? "Each PDF must be 2 MB or smaller and contain exactly one page."
      : `Each ${purpose === "passport" ? "passport file" : "Visa Photo"} must be ${limit / (1024 * 1024)} MB or smaller. Please choose a smaller file.`;
  }
  const allowedType = /^(?:image\/(?:jpe?g|png|heic|heif|avif)|application\/pdf)$/i.test(file.type);
  const allowedName = /\.(?:jpe?g|png|hei[cf]|avif|pdf)$/i.test(file.name);
  const removedFormat = /^image\/(?:webp|bmp|tiff)$/i.test(file.type) || /\.(?:webp|bmp|tiff?)$/i.test(file.name);
  if (removedFormat || (!allowedType && !allowedName)) {
    return "Choose a JPG/JPEG, PNG, HEIC/HEIF, AVIF image or a single-page PDF.";
  }
  return null;
}

export interface PreparePublicUploadOptions {
  token?: string;
  uploadSessionId?: string;
  purpose: PublicUploadPurpose;
  signal?: AbortSignal;
}

/** Validate and render once so PDF and HEIC previews work on every supported browser. */
export async function preparePublicUploadFile(file: File, options: PreparePublicUploadOptions): Promise<File> {
  const error = publicUploadFileError(file, options.purpose);
  if (error) throw new Error(error);
  if (!options.token || !options.uploadSessionId) {
    throw new Error("The secure upload session is unavailable. Reload the upload link and try again.");
  }
  const body = new FormData();
  body.append("file", file);
  body.append("purpose", options.purpose);
  const response = await apiClient.post<Blob>(API_ENDPOINTS.passports.prepareUploadFile(options.token), body, {
    headers: { "Content-Type": "multipart/form-data", "X-Upload-Session-ID": options.uploadSessionId },
    responseType: "blob",
    signal: options.signal,
    timeout: 60_000,
  });
  if (!response.data.size || response.data.type.split(";")[0] !== "image/jpeg") {
    throw new Error("The file preview could not be prepared. Please choose the file again.");
  }
  return new File([response.data], `${file.name.replace(/\.[^.]+$/, "")}.jpg`, {
    type: "image/jpeg", lastModified: file.lastModified,
  });
}
