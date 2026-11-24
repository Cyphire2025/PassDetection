"use client";
import { AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { PassportExtractionConflict } from "@/types/passport.types";
import { isReviewField, valuesMatch, formatConflictValue, toLabel } from "./passport-review-model";

export function ExtractionConflictPanel({
  conflicts,
  reviewFields,
  onSelect,
}: {
  conflicts: PassportExtractionConflict[];
  reviewFields: Record<string, string>;
  onSelect: (field: string, value: string) => void;
}) {
  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50/70 p-4" aria-labelledby="extraction-conflicts-heading">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" />
        <div>
          <h4 id="extraction-conflicts-heading" className="font-semibold text-amber-950">
            Compare re-extracted details
          </h4>
          <p className="mt-1 text-sm leading-5 text-amber-800">
            Your manually entered values were preserved. Review each difference, choose the correct value, then save.
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {conflicts.map((conflict) => {
          const canEdit = isReviewField(conflict.field);
          const selectedValue = reviewFields[conflict.field] ?? "";
          const manualSelected = valuesMatch(selectedValue, conflict.manual_value);
          const extractedSelected = conflict.extracted_value !== null
            && valuesMatch(selectedValue, conflict.extracted_value);
          return (
            <article key={conflict.field} className="rounded-xl border border-amber-200 bg-white p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h5 className="text-sm font-semibold text-slate-900">{toLabel(conflict.field)}</h5>
                <Badge variant={conflict.status === "mismatch" ? "warning" : "outline"}>
                  {conflict.status === "mismatch" ? "Different values" : "Could not verify"}
                </Badge>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <div className={`rounded-lg border p-3 ${manualSelected ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-slate-50"}`}>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Manually entered</div>
                  <div className="mt-1 break-words text-sm font-semibold text-slate-900">
                    {formatConflictValue(conflict.field, conflict.manual_value)}
                  </div>
                  {canEdit && (
                    <button
                      type="button"
                      className="mt-2 text-xs font-semibold text-blue-700 hover:underline"
                      onClick={() => onSelect(conflict.field, conflict.manual_value)}
                    >
                      {manualSelected ? "Using this value" : "Use manual value"}
                    </button>
                  )}
                </div>
                <div className={`rounded-lg border p-3 ${extractedSelected ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-slate-50"
                  }`}>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Read from passport</div>
                  <div className="mt-1 break-words text-sm font-semibold text-slate-900">
                    {conflict.extracted_value
                      ? formatConflictValue(conflict.field, conflict.extracted_value)
                      : "Not extracted from the image"}
                  </div>
                  {canEdit && conflict.extracted_value && (
                    <button
                      type="button"
                      className="mt-2 text-xs font-semibold text-emerald-700 hover:underline"
                      onClick={() => onSelect(conflict.field, conflict.extracted_value ?? "")}
                    >
                      {extractedSelected ? "Using this value" : "Use extracted value"}
                    </button>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
