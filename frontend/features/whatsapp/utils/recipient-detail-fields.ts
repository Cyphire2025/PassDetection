import { importedFieldLabel } from "./imported-field-label";
export { importedFieldLabel } from "./imported-field-label";

const ROSTER_SOURCE_FIELD_KEYS = new Set([
  "source_file",
  "source_order",
  "source_sheet",
  "source_row",
]);

export function visibleImportedFieldEntries(
  importedFields: Record<string, string> | null | undefined,
): Array<[string, string]> {
  return Object.entries(importedFields ?? {})
    .filter(([key]) => !ROSTER_SOURCE_FIELD_KEYS.has(key))
    .sort(([left], [right]) =>
      importedFieldLabel(left).localeCompare(importedFieldLabel(right)),
    );
}
