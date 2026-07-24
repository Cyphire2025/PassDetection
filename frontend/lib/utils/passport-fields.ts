import type { ExtractedPassportFields } from "@/types/passport.types";

type PassportFieldSource = ExtractedPassportFields | null | undefined;

export function getPassportTextField(
  fields: PassportFieldSource,
  field: string,
) {
  if (!fields) return "";
  const value = fields[field];
  if (typeof value === "string") return value;
  return "";
}
