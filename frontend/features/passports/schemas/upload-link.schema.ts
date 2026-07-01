import { z } from "zod";

export const createUploadLinkSchema = z.object({
  name: z.string().min(1, "Group name is required").max(100),
});

export type CreateUploadLinkFormData = z.infer<typeof createUploadLinkSchema>;
