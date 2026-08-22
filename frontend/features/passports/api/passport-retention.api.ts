import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { z } from "zod";

export interface PassportRetentionControl {
  group_id: string;
  passport_purge_at: string | null;
  passport_retention_days_applied: number | null;
  legal_hold: boolean;
  legal_hold_reason: string | null;
  legal_hold_set_at: string | null;
  legal_hold_set_by_user_id: string | null;
}

export interface UpdatePassportRetentionControl {
  legalHold: boolean;
  reason: string;
}

const passportRetentionControlSchema = z.object({
  group_id: z.string().min(1),
  passport_purge_at: z.string().min(1).nullable(),
  passport_retention_days_applied: z.number().int().positive().nullable(),
  legal_hold: z.boolean(),
  legal_hold_reason: z.string().min(3).max(500).nullable(),
  legal_hold_set_at: z.string().min(1).nullable(),
  legal_hold_set_by_user_id: z.string().min(1).nullable(),
}).strict().superRefine((value, context) => {
  if (
    value.legal_hold
    && (!value.legal_hold_reason || !value.legal_hold_set_at || !value.legal_hold_set_by_user_id)
  ) {
    context.addIssue({
      code: "custom",
      message: "An active legal hold is missing its audited placement evidence",
    });
  }
  if (
    !value.legal_hold
    && (value.legal_hold_reason || value.legal_hold_set_at || value.legal_hold_set_by_user_id)
  ) {
    context.addIssue({
      code: "custom",
      message: "An inactive legal hold contains stale placement evidence",
    });
  }
});

export function parsePassportRetentionControl(value: unknown): PassportRetentionControl {
  return passportRetentionControlSchema.parse(value);
}

export const passportRetentionApi = {
  async get(groupId: string): Promise<PassportRetentionControl> {
    const response = await apiClient.get<PassportRetentionControl>(
      API_ENDPOINTS.admin.passportRetention(groupId),
    );
    return parsePassportRetentionControl(response.data);
  },

  async update(
    groupId: string,
    request: UpdatePassportRetentionControl,
  ): Promise<PassportRetentionControl> {
    const response = await apiClient.put<PassportRetentionControl>(
      API_ENDPOINTS.admin.passportRetention(groupId),
      {
        legal_hold: request.legalHold,
        reason: request.reason,
      },
    );
    return parsePassportRetentionControl(response.data);
  },
};
