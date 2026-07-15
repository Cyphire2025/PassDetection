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
    }: {
      token: string;
      client_name: string;
      file: File;
      passportPhotoFile?: File | null;
      passportBackFile?: File | null;
    }) => uploadApi.uploadPassport(token, client_name, file, passportPhotoFile, passportBackFile),
  });
}

export function useSubmitClientPassportReview() {
  return useMutation({
    mutationFn: ({
      submissionId,
      group_token,
      confirmed_fields,
      client_email,
      client_phone,
      departure_city,
      submission_mode,
      family_group_id,
      family_member_index,
      family_relation,
      family_gender,
      family_head_name,
      family_head_email,
      family_head_phone,
    }: {
      submissionId: string;
      group_token: string;
      confirmed_fields: Record<string, string>;
      client_email?: string | null;
      client_phone?: string | null;
      departure_city?: string | null;
      submission_mode?: "single" | "family";
      family_group_id?: string | null;
      family_member_index?: number | null;
      family_relation?: string | null;
      family_gender?: string | null;
      family_head_name?: string | null;
      family_head_email?: string | null;
      family_head_phone?: string | null;
    }) =>
      uploadApi.submitClientReview(submissionId, {
        group_token,
        confirmed_fields,
        client_email,
        client_phone,
        departure_city,
        submission_mode,
        family_group_id,
        family_member_index,
        family_relation,
        family_gender,
        family_head_name,
        family_head_email,
        family_head_phone,
      }),
  });
}
