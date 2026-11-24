import type { PassportImageCropState, VisaAiGenerationJob } from "../api/passports.api";

export const cropMetadata: PassportImageCropState = {
  image_type: "passport_front",
  original_url: "/api/v1/passports/passport-1/images/passport_front/original",
  editable_source_url: "/api/v1/passports/passport-1/images/passport_front/original",
  cropped_url: "/api/v1/passports/passport-1/images/passport_front",
  crop: { x: 0.1, y: 0.2, width: 0.8, height: 0.6, rotation_degrees: 90 },
  revision: 7,
  source_width: 1200,
  source_height: 1800,
  sharpness: 1.5,
  sharpness_algorithm_version: 2,
  ai_edited: false,
};

export const queuedJob: VisaAiGenerationJob = {
  id: "job-1", status: "queued", prompt: "Studio lighting", attempts: 0,
  max_attempts: 3, error_message: null, result: null,
  created_at: "2026-10-30T00:00:00Z", updated_at: "2026-10-30T00:00:00Z",
};

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}
