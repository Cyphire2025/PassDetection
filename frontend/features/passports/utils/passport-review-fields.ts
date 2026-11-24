import type { PassportVerificationField, PassportVerificationFieldName, PassportVerificationVerdict } from "@/types/passport.types";

export const PASSPORT_REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "place_of_issue",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "sex",
] as const satisfies readonly PassportVerificationFieldName[];

export type PassportReviewFieldName = typeof PASSPORT_REVIEW_FIELDS[number];

export type PassportFieldReview = Omit<PassportVerificationField, "verdict"> & {
  verdict: Exclude<PassportVerificationVerdict, "correct">;
  label: "Incorrect" | "Suspicious" | "Not verified";
};
