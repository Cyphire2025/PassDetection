import type { GroupWhatsAppMatch } from "../api/upload-links.api";

const BUILT_IN_EVIDENCE_LABELS: Record<string, string> = {
  phone: "Phone number",
  email: "Email",
  passport_number: "Passport number",
  staff_code: "Staff code",
  entered_name: "Name entered in form",
  passport_name: "Name read from passport",
};

function normalizedFieldKey(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function fieldLabel(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toLocaleUpperCase() + part.slice(1))
    .join(" ");
}

export function groupWhatsAppEvidenceLabel(
  value: GroupWhatsAppMatch["match_evidence"][number]["kind"],
  row: GroupWhatsAppMatch,
): string {
  for (const detail of row.submission_details) {
    const directLabel = detail.fields[`${value}_label`];
    if (typeof directLabel === "string" && directLabel.trim()) {
      return directLabel.trim();
    }
    for (const [key, candidateLabel] of Object.entries(detail.fields)) {
      if (
        key.endsWith("_label")
        && typeof candidateLabel === "string"
        && normalizedFieldKey(candidateLabel) === value
      ) {
        return candidateLabel.trim();
      }
    }
  }
  return BUILT_IN_EVIDENCE_LABELS[value] ?? fieldLabel(value);
}
