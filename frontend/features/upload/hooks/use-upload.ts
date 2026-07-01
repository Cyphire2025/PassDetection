import { useMutation } from "@tanstack/react-query";
import { uploadApi } from "../api/upload.api";

export function useUploadPassport() {
  return useMutation({
    mutationFn: ({ token, client_name, file }: { token: string; client_name: string; file: File }) =>
      uploadApi.uploadPassport(token, client_name, file),
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
    }: {
      submissionId: string;
      group_token: string;
      confirmed_fields: Record<string, string>;
      client_email: string;
      client_phone: string;
    }) =>
      uploadApi.submitClientReview(submissionId, {
        group_token,
        confirmed_fields,
        client_email,
        client_phone,
      }),
  });
}
