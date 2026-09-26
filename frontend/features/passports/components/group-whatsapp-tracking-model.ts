"use client";

import type { GroupWhatsAppMatch, GroupWhatsAppMatchStatus, GroupWhatsAppSubmissionDetail, ReplacementCandidate } from "../api/upload-links.api";


export type MatchFilter = "all" | GroupWhatsAppMatchStatus;

export const MATCH_FILTERS: Array<{
  value: MatchFilter;
  label: string;
  description?: string;
}> = [
  { value: "all", label: "All records" },
  { value: "submitted", label: "Identified" },
  { value: "not_submitted", label: "Not submitted" },
  { value: "multiple_submissions", label: "Duplicate uploads" },
  { value: "needs_review", label: "Needs review" },
  {
    value: "unmatched_submission",
    label: "Unidentified uploads",
    description:
      "People who uploaded their details but are not in the linked WhatsApp broadcast lists.",
  },
  {
    value: "replacement",
    label: "Replaced",
    description:
      "People added as replacements, together with the original broadcast recipients they replaced.",
  },
  {
    value: "rejected_upload",
    label: "Removed uploads",
    description:
      "Unidentified uploads removed from the active list. They can be added back at any time.",
  },
];

export function firstDisplayValue(values: string[]) {
  return values.find((value) => value.trim()) ?? "";
}

export function fieldLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function uniqueEvidenceKinds(
  row: GroupWhatsAppMatch,
): GroupWhatsAppMatch["match_evidence"][number]["kind"][] {
  return Array.from(new Set(row.match_evidence.map((item) => item.kind)));
}

export function uniqueImportedDetails(
  row: GroupWhatsAppMatch,
): Array<[string, string]> {
  const unique = new Map<string, [string, string]>();
  for (const recipient of row.recipient_fields) {
    for (const [key, value] of Object.entries(recipient.fields)) {
      const normalizedValue = value.trim();
      if (!normalizedValue) continue;
      unique.set(
        `${key.toLowerCase()}:${normalizedValue.toLowerCase()}`,
        [key, normalizedValue],
      );
    }
  }
  return Array.from(unique.values()).sort(([left], [right]) =>
    fieldLabel(left).localeCompare(fieldLabel(right)),
  );
}

export function submissionDetailEntries(
  detail: GroupWhatsAppSubmissionDetail,
): Array<[string, string]> {
  const entries = new Map<string, [string, string]>();
  const add = (key: string, rawValue: unknown) => {
    const value = displaySubmissionValue(rawValue);
    if (!value) return;
    const normalizedKey = key.trim().toLocaleLowerCase();
    if (!normalizedKey || entries.has(normalizedKey)) return;
    entries.set(normalizedKey, [key, value]);
  };
  add("name", detail.name);
  add("phone", detail.phone);
  add("email", detail.email);
  for (const [key, value] of Object.entries(detail.fields)) add(key, value);
  return Array.from(entries.values());
}

export function displaySubmissionValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(displaySubmissionValue).filter(Boolean).join(", ");
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function rowPrimaryName(row: GroupWhatsAppMatch): string {
  return firstDisplayValue(row.submission_names)
    || firstDisplayValue(row.recipient_names)
    || "This person";
}

export function submissionPrimaryPhone(row: GroupWhatsAppMatch): string {
  return row.submission_details.find((detail) => detail.phone?.trim())
    ?.phone?.trim() ?? "";
}

export function replacementCandidateSearchText(
  candidate: ReplacementCandidate,
): string {
  return [
    candidate.name,
    candidate.phone,
    ...candidate.broadcast_names,
    ...Object.keys(candidate.imported_fields),
    ...Object.values(candidate.imported_fields),
  ]
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .toLocaleLowerCase();
}

export function createRosterRequestId(): string {
  if (
    typeof globalThis.crypto !== "undefined"
    && typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (
    typeof globalThis.crypto !== "undefined"
    && typeof globalThis.crypto.getRandomValues === "function"
  ) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}
