import type { PassportImageType } from "@/types/passport.types";

export interface PassportImageCropRect {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: number;
}

export interface PassportImageCropState {
  image_type: PassportImageType;
  original_url: string;
  editable_source_url: string;
  cropped_url: string;
  crop: PassportImageCropRect | null;
  revision: number;
  source_width: number | null;
  source_height: number | null;
  sharpness: number;
  sharpness_algorithm_version: 1 | 2;
  ai_edited: boolean;
}

export interface SavePassportImageCropRequest extends PassportImageCropRect {
  sharpness: number;
  expected_revision: number;
}

export interface VisaAiEditPreview {
  blob: Blob;
  token: string;
}

export interface ApplyVisaAiEditRequest extends SavePassportImageCropRequest {
  image: Blob;
  previewToken: string;
  prompt: string;
}

export type PassportImageLibrarySource =
  | "original"
  | "manual"
  | "ai_generated";

export interface PassportImageLibraryItem {
  id: string;
  image_type: PassportImageType;
  image_url: string;
  source: PassportImageLibrarySource;
  created_at: string;
  is_current: boolean;
  prompt?: string | null;
  model?: string | null;
}

export interface PassportImageLibrary {
  items: PassportImageLibraryItem[];
}

export interface VisaAiLibraryImage {
  id: string;
  image_url: string;
  prompt: string;
  model: string;
  created_at: string;
  is_current: boolean;
}

export interface VisaAiLibrary {
  items: VisaAiLibraryImage[];
}

export type VisaAiGenerationJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed";

export interface VisaAiGenerationJob {
  id: string;
  status: VisaAiGenerationJobStatus;
  prompt: string;
  attempts: number;
  max_attempts: number;
  error_message: string | null;
  result: VisaAiLibraryImage | null;
  created_at: string;
  updated_at: string;
}
