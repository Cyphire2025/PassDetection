/**
 * Auth — Zod Schemas
 * ==================
 * Form validation schemas for all auth forms.
 * Zod schemas are the single source of truth for validation
 * — shared between react-hook-form and any server-side validation.
 */

import { z } from "zod";

export const loginSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Must be a valid email address"),
  password: z
    .string()
    .min(1, "Password is required")
    .min(8, "Password must be at least 8 characters"),
});

export type LoginFormData = z.infer<typeof loginSchema>;
