import { z } from "zod";

export const createUploadLinkSchema = z.object({
  name: z.string().trim().min(1, "Group name is required").max(100),
  destination: z.string().trim().min(1, "Destination is required").max(255),
  travel_date: z.string().trim().min(1, "Travel/Departure date is required"),
  return_date: z.string().trim().min(1, "Return date is required"),
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
  whatsapp_broadcast_group_ids: z.array(z.string().uuid()).max(50),
  notes: z.string().trim().max(2000).optional(),
}).superRefine((data, context) => {
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
