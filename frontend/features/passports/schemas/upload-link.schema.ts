import { z } from "zod";
import { isSupportedIanaTimeZone } from "../utils/trip-timezone";

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
});

export const customDetailSchema = z.object({
  id: z.string().uuid(),
  label: z.string().trim().min(1, "Enter a custom detail heading").max(100),
  enabled: z.boolean(),
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
  custom_questions: z.array(customQuestionSchema).max(20),
  custom_details: z.array(customDetailSchema).max(20),
  whatsapp_broadcast_group_ids: z.array(z.string().uuid()).max(50),
  notes: z.string().trim().max(2000).optional(),
}).superRefine((data, context) => {
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
