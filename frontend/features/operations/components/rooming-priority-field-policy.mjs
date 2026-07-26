const FIXED_EXPORT_FIELD_KEYS = new Set([
  "staff_code",
  "staffcode",
  "staff_id",
  "agent_code",
  "employee_code",
  "agent_employee_code",
  "agent_employee_type",
  "age",
  "age_group",
  "given_names",
  "given_name",
  "first_name",
  "surname",
  "last_name",
  "family_name",
  "name",
  "full_name",
  "client_name",
  "passenger_name",
  "recipient_name",
  "gender",
  "sex",
  "passport_num",
  "passport_number",
  "passport_no",
  "passport",
  "passportnum",
  "dob",
  "date_of_birth",
  "birth_date",
  "doi",
  "date_of_issue",
  "dateofissue",
  "issue_date",
  "doe",
  "date_of_expiry",
  "dateofexpiry",
  "expiry_date",
  "expiration_date",
  "place_of_issue",
  "placeofissue",
  "issue_place",
]);
const FIXED_EXPORT_FIELD_COMPACT_KEYS = new Set(
  Array.from(FIXED_EXPORT_FIELD_KEYS, compactFieldKey),
);
const KNOWN_FIELD_NAMESPACES = ["field_", "whatsapp_"];

/**
 * Keep fixed Excel columns and any form of Gender out of rooming priorities.
 * @param {{ key: string, label: string }} field
 */
export function isRoomingPriorityFieldAllowed(field) {
  return [field.key, field.label].every((value) => {
    const candidates = normalizedCandidates(value);
    return candidates.every((candidate) => (
      !isFixedExportField(candidate)
      && !isGenderField(candidate)
    ));
  });
}

function normalizedCandidates(value) {
  const normalized = normalizeFieldKey(value);
  const candidates = [normalized];
  for (const namespace of KNOWN_FIELD_NAMESPACES) {
    if (normalized.startsWith(namespace)) {
      candidates.push(normalized.slice(namespace.length));
    }
  }
  return candidates;
}

function isFixedExportField(value) {
  return (
    FIXED_EXPORT_FIELD_KEYS.has(value)
    || FIXED_EXPORT_FIELD_COMPACT_KEYS.has(compactFieldKey(value))
  );
}

function isGenderField(value) {
  const tokens = value.split("_").filter(Boolean);
  const compact = compactFieldKey(value);
  return (
    tokens.some((token) => token === "gender" || token === "sex")
    || compact.startsWith("gender")
    || compact.endsWith("gender")
  );
}

function normalizeFieldKey(value) {
  return String(value ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function compactFieldKey(value) {
  return value.replaceAll("_", "");
}
