export const REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "place_of_issue",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "sex",
] as const;

export const REQUIRED_REVIEW_FIELDS = REVIEW_FIELDS.filter(
  (field) => field !== "date_of_issue" && field !== "surname",
);

export const FAMILY_RELATIONS = [
  "Head",
  "Spouse",
  "Son",
  "Daughter",
  "Father",
  "Mother",
  "Brother",
  "Sister",
  "Other",
];

export const GENDERS = ["Male", "Female", "Other", "Prefer not to say"];

export const PASSIVE_PROGRESS_STEPS: ReadonlySet<UploadFlowStep> = new Set([
  "BOOTSTRAP",
  "QUALIFIER_SELECT",
  "MODE_SELECT",
]);

export const PASSPORT_IMAGE_ACCEPT = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".heic",
  ".heif",
  ".avif",
  ".bmp",
  ".tif",
  ".tiff",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/avif",
  "image/bmp",
  "image/tiff",
].join(",");
import type { UploadFlowStep } from "./upload-flow.types";
