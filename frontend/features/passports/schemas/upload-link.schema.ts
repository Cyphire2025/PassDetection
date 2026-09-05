import { z } from "zod";
import { isSupportedIanaTimeZone } from "../utils/trip-timezone";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../types/upload-configuration";

export const uploadConfigurationSchema = z.object({
  passport_enabled: z.boolean(),
  passport_required: z.boolean(),
  passport_live_scan: z.boolean(),
  passport_upload_pages: z.array(z.enum(["cover", "back_cover", "front", "back"])).max(4),
  visa_photo_required: z.boolean(),
  visa_photo_live_capture: z.boolean(),
  visa_photo_upload: z.boolean(),
  required_fields: z.partialRecord(z.enum([
    "base_city", "nearest_domestic_airport", "departure_city", "staff_code",
    "agent_employee_code", "designation", "agency_dealership_name", "meal_preference",
    "relation_with_qualifier",
  ]), z.boolean()),
  agent_employee_code_label: z.string().trim().min(1, "Enter a code field label").max(100),
  agency_dealership_name_label: z.string().trim().min(1, "Enter an organisation field label").max(100),
});

export const customQuestionSchema = z.object({
  id: z.string().uuid(),
  label: z.string().trim().min(1, "Enter a question or activity name").max(100),
  options: z.array(z.string().trim().min(1).max(120)).min(
    2,
    "Add at least two options",
  ).max(50).superRefine((options, context) => {
    const normalized = options.map((option) => option.toLocaleLowerCase());
    if (new Set(normalized).size !== normalized.length) {
      context.addIssue({
        code: "custom",
        message: "Options must be unique",
      });
    }
  }),
  enabled: z.boolean(),
  required: z.boolean().optional(),
});

export const customDetailSchema = z.object({
  id: z.string().uuid(),
  label: z.string().trim().min(1, "Enter a custom detail heading").max(100),
  enabled: z.boolean(),
  required: z.boolean().optional(),
});

export const createUploadLinkSchema = z.object({
  name: z.string().trim().min(1, "Group name is required").max(100),
  destination: z.string().trim().min(1, "Destination is required").max(255),
  travel_date: z.string().trim().min(1, "Travel/Departure date is required"),
  return_date: z.string().trim().min(1, "Return date is required"),
  timezone: z.string()
    .trim()
    .min(1, "Trip timezone is required")
    .max(64, "Trip timezone must be 64 characters or fewer")
    .refine(isSupportedIanaTimeZone, "Enter a valid IANA timezone, such as Asia/Kolkata"),
  departure_cities: z.array(z.string().trim().min(1).max(120)).max(50),
  base_city_enabled: z.boolean(),
  nearest_international_airport_enabled: z.boolean(),
  staff_code_enabled: z.boolean(),
  agent_employee_code_enabled: z.boolean(),
  meal_preference_enabled: z.boolean(),
  require_selfie: z.boolean(),
  allow_files_from_device: z.boolean(),
  ask_nearest_domestic_airport: z.boolean(),
  relation_with_qualifier_enabled: z.boolean(),
  designation_enabled: z.boolean(),
  agency_dealership_name_enabled: z.boolean(),
  upload_configuration: uploadConfigurationSchema.optional(),
  custom_questions: z.array(customQuestionSchema).max(20),
  custom_details: z.array(customDetailSchema).max(20),
  whatsapp_broadcast_group_ids: z.array(z.string().uuid()).max(50),
  notes: z.string().trim().max(2000).optional(),
}).superRefine((data, context) => {
  const configuration = data.upload_configuration ?? DEFAULT_UPLOAD_CONFIGURATION;
  if (data.require_selfie && !configuration.visa_photo_live_capture && !configuration.visa_photo_upload) {
    context.addIssue({ code: "custom", path: ["upload_configuration"], message: "Enable at least one method for Visa Photo." });
  }
  if (configuration.passport_enabled && !configuration.passport_live_scan && !data.allow_files_from_device) {
    context.addIssue({ code: "custom", path: ["upload_configuration"], message: "Enable at least one method for Passport." });
  }
  if (configuration.passport_enabled && data.allow_files_from_device && configuration.passport_upload_pages.length === 0) {
    context.addIssue({ code: "custom", path: ["upload_configuration"], message: "Select at least one passport page to upload." });
  }
  const questionNames = data.custom_questions.map(
    (question) => question.label.trim().toLocaleLowerCase(),
  );
  if (new Set(questionNames).size !== questionNames.length) {
    context.addIssue({
      code: "custom",
      path: ["custom_questions"],
      message: "Custom question names must be unique",
    });
  }
  const detailNames = data.custom_details.map(
    (detail) => detail.label.trim().toLocaleLowerCase(),
  );
  if (new Set(detailNames).size !== detailNames.length) {
    context.addIssue({
      code: "custom",
      path: ["custom_details"],
      message: "Custom detail names must be unique",
    });
  }
  if (data.nearest_international_airport_enabled && data.departure_cities.length === 0) {
    context.addIssue({
      code: "custom",
      path: ["departure_cities"],
      message: "Add at least one nearest international airport",
    });
  }
  if (data.travel_date && data.return_date && data.return_date < data.travel_date) {
    context.addIssue({
      code: "custom",
      path: ["return_date"],
      message: "Return date cannot be before the Travel/Departure date",
    });
  }
});

export type CreateUploadLinkFormData = z.infer<typeof createUploadLinkSchema>;
