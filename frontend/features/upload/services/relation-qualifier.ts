import type { QualifierRelationOption } from "@/features/passports/api/upload-links.api";

export type QualifierPath = "self" | "relation" | "other" | null;

export interface QualifierEntryMethods {
  listEnabled: boolean;
  otherEnabled: boolean;
}

export interface QualifierSelectionRequest {
  is_self: boolean;
  relation_code: string | null;
  other_relation?: string;
}

function normalizeOtherRelation(value: string) {
  return value.normalize("NFC").trim();
}

export function qualifierOtherRelationError(value: string): string | null {
  const normalized = normalizeOtherRelation(value);
  if (!normalized) return "Enter the passenger’s relationship.";
  if (Array.from(normalized).length > 100) return "Use 100 characters or fewer.";
  if (normalized.toLowerCase() === "self") {
    return "Choose Self if the qualifier is travelling.";
  }
  if (/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(normalized)) {
    return "Enter the relationship on one line without hidden characters.";
  }
  return null;
}

export function buildQualifierSelectionRequest(
  path: QualifierPath,
  relationCode: string,
  options: QualifierRelationOption[],
  otherRelation = "",
  methods: QualifierEntryMethods = { listEnabled: true, otherEnabled: false },
): QualifierSelectionRequest | null {
  if (path === "self") {
    return { is_self: true, relation_code: null };
  }
  if (path === "other") {
    if (!methods.otherEnabled || qualifierOtherRelationError(otherRelation)) return null;
    return {
      is_self: false,
      relation_code: "other",
      other_relation: normalizeOtherRelation(otherRelation),
    };
  }
  if (path !== "relation" || !methods.listEnabled) return null;

  const normalizedCode = relationCode.trim();
  if (!options.some((option) => option.code === normalizedCode)) return null;
  return { is_self: false, relation_code: normalizedCode };
}

export function qualifierChoiceKey(
  path: Exclude<QualifierPath, null>,
  relationCode: string,
  otherRelation = "",
) {
  if (path === "self") return "self";
  if (path === "other") return `other:${normalizeOtherRelation(otherRelation)}`;
  return `relation:${relationCode.trim()}`;
}
