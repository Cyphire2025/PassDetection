import { useMutation } from "@tanstack/react-query";
import { uploadApi } from "../api/upload.api";

export function useUploadPassport() {
  return useMutation({
    mutationFn: ({
      token,
      client_name,
      file,
      passportPhotoFile,
      passportBackFile,
      acquisitionMode,
      uploadIdempotencyKey,
      qualifierSelectionToken,
      signal,
    }: {
      token: string;
      client_name: string;
      file: File;
      passportBackFile: File;
      acquisitionMode: "camera" | "file";
      uploadIdempotencyKey: string;
      qualifierSelectionToken?: string | null;
      passportPhotoFile?: File | null;
      signal?: AbortSignal;
    }) => uploadApi.uploadPassport(
      token,
      client_name,
      file,
      passportBackFile,
      acquisitionMode,
      uploadIdempotencyKey,
      passportPhotoFile,
      qualifierSelectionToken,
      signal,
    ),
  });
}

export function useSubmitClientPassportReview() {
  return useMutation({
    mutationFn: ({
      submissionId,
      uploadSessionId,
      group_token,
      confirmed_fields,
      client_email,
      client_phone,
      departure_city,
      base_city,
      nearest_domestic_airport,
      staff_code,
      agent_employee_type,
      agent_employee_code,
      meal_preference,
      submission_mode,
      family_group_id,
      family_member_index,
      family_relation,
      family_gender,
      family_head_name,
      family_head_email,
      family_head_phone,
      custom_answers,
    }: {
      submissionId: string;
      uploadSessionId: string;
      group_token: string;
      confirmed_fields: Record<string, string>;
      client_email?: string | null;
      client_phone?: string | null;
      departure_city?: string | null;
      base_city?: string | null;
      nearest_domestic_airport?: string | null;
      staff_code?: string | null;
      agent_employee_type?: "agent" | "employee" | null;
      agent_employee_code?: string | null;
      meal_preference?: string | null;
      submission_mode?: "single" | "family";
      family_group_id?: string | null;
      family_member_index?: number | null;
      family_relation?: string | null;
      family_gender?: string | null;
      family_head_name?: string | null;
      family_head_email?: string | null;
      family_head_phone?: string | null;
      custom_answers?: Array<{ question_id: string; value: string }>;
    }) =>
      uploadApi.submitClientReview(submissionId, uploadSessionId, {
        group_token,
        confirmed_fields,
        client_email,
        client_phone,
        departure_city,
        base_city,
        nearest_domestic_airport,
        staff_code,
        agent_employee_type,
        agent_employee_code,
        meal_preference,
        submission_mode,
        family_group_id,
        family_member_index,
        family_relation,
        family_gender,
        family_head_name,
        family_head_email,
        family_head_phone,
        custom_answers,
      }),
  });
}
