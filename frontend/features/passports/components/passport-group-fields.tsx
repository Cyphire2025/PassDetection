import { Badge } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { formatPassportCountry, formatPassportNationality } from "@/lib/utils/passport-country";
import { formatPassportDateForUi } from "@/lib/utils/passport-date";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";

export function hasRealPassportFront(passport: PassportSubmission) {
  return Boolean(
    passport.image_s3_key &&
      !passport.image_s3_key.startsWith("excel-imports/"),
  );
}

export function getDashboardFields(passport: PassportSubmission) {
  return passport.confirmed_fields ?? passport.extracted_fields;
}

export function getDashboardCountry(passport: PassportSubmission) {
  const fields = getDashboardFields(passport);
  const nationality = getStringField(fields, "nationality");
  if (nationality) return formatPassportNationality(nationality);
  return formatPassportCountry(getStringField(fields, "issuing_country"));
}

export function getDashboardPassportDate(
  passport: PassportSubmission,
  field: "date_of_birth" | "date_of_issue" | "date_of_expiry",
) {
  return (
    formatPassportDateForUi(
      getStringField(getDashboardFields(passport), field),
    ) || "Not provided"
  );
}

export function getExtractionConflictCount(passport: PassportSubmission) {
  if (Array.isArray(passport.extraction_conflicts))
    return passport.extraction_conflicts.length;
  const fallback = passport.extracted_fields?.manual_review_conflicts;
  return Array.isArray(fallback) ? fallback.length : 0;
}

export function getStringField(
  fields: ExtractedPassportFields | null,
  key: string,
) {
  const value = fields?.[key];
  return typeof value === "string" ? value : "";
}

export function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="mt-1 font-medium text-slate-800">{value}</div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={PASSPORT_STATUS_COLORS[status] || "default"} dot>
      {PASSPORT_STATUS_LABELS[status] || status}
    </Badge>
  );
}
