import { z } from "zod";

export const createUploadLinkSchema = z.object({
  name: z.string().trim().min(1, "Group name is required").max(100),
  destination: z.string().trim().max(255).optional(),
  travel_date: z.string().optional(),
  return_date: z.string().optional(),
  departure_cities: z.array(z.string().trim().min(1).max(120)).max(50),
  base_city_enabled: z.boolean(),
  nearest_international_airport_enabled: z.boolean(),
  staff_code_enabled: z.boolean(),
  meal_preference_enabled: z.boolean(),
  require_selfie: z.boolean(),
  allow_files_from_device: z.boolean(),
  ask_nearest_domestic_airport: z.boolean(),
  relation_with_qualifier_enabled: z.boolean(),
  notes: z.string().trim().max(2000).optional(),
}).superRefine((data, context) => {
  if (data.nearest_international_airport_enabled && data.departure_cities.length === 0) {
    context.addIssue({
      code: "custom",
      path: ["departure_cities"],
      message: "Add at least one nearest international airport",
    });
  }
});

export type CreateUploadLinkFormData = z.infer<typeof createUploadLinkSchema>;
