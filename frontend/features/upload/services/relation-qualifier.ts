import type { QualifierRelationOption } from "@/features/passports/api/upload-links.api";

export type QualifierPath = "self" | "relation" | null;

export interface QualifierSelectionRequest {
  is_self: boolean;
  relation_code: string | null;
}

export function buildQualifierSelectionRequest(
  path: QualifierPath,
  relationCode: string,
  options: QualifierRelationOption[],
): QualifierSelectionRequest | null {
  if (path === "self") {
    return { is_self: true, relation_code: null };
  }
  if (path !== "relation") return null;

  const normalizedCode = relationCode.trim();
  if (!options.some((option) => option.code === normalizedCode)) return null;
  return { is_self: false, relation_code: normalizedCode };
}

export function qualifierChoiceKey(
  path: Exclude<QualifierPath, null>,
  relationCode: string,
) {
  return path === "self" ? "self" : `relation:${relationCode.trim()}`;
}
