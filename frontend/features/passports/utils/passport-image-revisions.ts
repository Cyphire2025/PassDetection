import type { PassportImageType } from "../api/passports.api";

export type PassportImageRevisions = Readonly<
  Record<string, Partial<Record<PassportImageType, number>>>
>;
