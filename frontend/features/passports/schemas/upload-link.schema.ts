import { z } from "zod";

export const createUploadLinkSchema = z.object({
  name: z.string().min(1, "Group name is required").max(100),
  destination: z.string().max(255).optional(),
  travel_date: z.string().optional(),
  return_date: z.string().optional(),
  notes: z.string().max(2000).optional(),
});

export type CreateUploadLinkFormData = z.infer<typeof createUploadLinkSchema>;
