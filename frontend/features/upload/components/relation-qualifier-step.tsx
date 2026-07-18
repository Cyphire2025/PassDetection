"use client";

import { type KeyboardEvent, useRef } from "react";
import { CheckCircle2, ChevronRight, User, UsersRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { QualifierRelationOption } from "@/features/passports/api/upload-links.api";
import type { QualifierPath } from "../services/relation-qualifier";

export function RelationQualifierStep({
  path,
  relationCode,
  options,
  isSaving,
  onPathChange,
  onRelationChange,
  onContinue,
}: {
  path: QualifierPath;
  relationCode: string;
  options: QualifierRelationOption[];
  isSaving: boolean;
  onPathChange: (path: Exclude<QualifierPath, null>) => void;
  onRelationChange: (code: string) => void;
  onContinue: () => void;
}) {
  const selfOptionRef = useRef<HTMLButtonElement>(null);
  const relationOptionRef = useRef<HTMLButtonElement>(null);
  const hasRelationOptions = options.length > 0;
  const relationIsAllowed = options.some((option) => option.code === relationCode);
  const canContinue = path === "self" || (
    path === "relation"
    && relationIsAllowed
  );
  const handleRadioKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentPath: Exclude<QualifierPath, null>,
  ) => {
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const nextPath = currentPath === "self" ? "relation" : "self";
    if (nextPath === "relation" && !hasRelationOptions) return;
    onPathChange(nextPath);
    (nextPath === "self" ? selfOptionRef : relationOptionRef).current?.focus();
  };

  return (
    <section
      className="animate-in fade-in slide-in-from-right-4 duration-500"
      aria-labelledby="qualifier-choice-title"
      aria-busy={isSaving}
    >
      <h3 id="qualifier-choice-title" className="mb-2 text-xl font-bold text-slate-900">
        Relation with Qualifier
      </h3>
      <p id="qualifier-choice-description" className="mb-6 text-sm leading-6 text-slate-600">
        If the person is travelling personally, select Self. If someone else will
        travel in the qualifier&apos;s place, select the passenger&apos;s relationship
        with the qualifier and upload that passenger&apos;s details in the following steps.
      </p>

      <div
        className="space-y-4"
        role="radiogroup"
        aria-label="Passenger relationship"
        aria-describedby="qualifier-choice-description"
      >
        <button
          ref={selfOptionRef}
          type="button"
          role="radio"
          aria-checked={path === "self"}
          tabIndex={path === "relation" ? -1 : 0}
          disabled={isSaving}
          onClick={() => onPathChange("self")}
          onKeyDown={(event) => handleRadioKeyDown(event, "self")}
          className={`${choiceClassName(path === "self")} flex items-start gap-3 text-left disabled:cursor-not-allowed disabled:opacity-60`}
        >
          <span className={iconClassName(path === "self")}>
            <User className="h-6 w-6" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-base font-bold text-slate-900">Self</span>
            <span className="mt-1 block text-sm leading-5 text-slate-500">
              The qualifier is the passenger whose documents will be uploaded.
            </span>
          </span>
          {path === "self" && (
            <CheckCircle2 className="h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
          )}
        </button>

        <div className={choiceClassName(path === "relation")}>
          <button
            ref={relationOptionRef}
            type="button"
            role="radio"
            aria-checked={path === "relation"}
            tabIndex={path === "relation" && hasRelationOptions ? 0 : -1}
            disabled={isSaving || !hasRelationOptions}
            onClick={() => onPathChange("relation")}
            onKeyDown={(event) => handleRadioKeyDown(event, "relation")}
            className="flex min-w-0 flex-1 items-start gap-3 text-left disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className={iconClassName(path === "relation")}>
              <UsersRound className="h-6 w-6" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-base font-bold text-slate-900">
                Relationship
              </span>
              <span className="mt-1 block text-sm leading-5 text-slate-500">
                The passenger is an eligible family relation of the qualifier.
              </span>
            </span>
            {path === "relation" && (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
            )}
          </button>

          <label className="mt-4 block border-t border-slate-200 pt-4">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Passenger&apos;s relationship
            </span>
            <select
              value={relationCode}
              disabled={isSaving || !hasRelationOptions}
              onFocus={() => onPathChange("relation")}
              onChange={(event) => {
                onPathChange("relation");
                onRelationChange(event.target.value);
              }}
              className="h-12 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="">Select relationship</option>
              {options.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {!hasRelationOptions && (
            <p role="status" className="mt-3 text-xs leading-5 text-amber-700">
              No eligible relationships are currently available. Select Self or
              contact the travel coordinator.
            </p>
          )}
        </div>
      </div>

      <Button
        type="button"
        size="lg"
        disabled={!canContinue || isSaving}
        isLoading={isSaving}
        onClick={onContinue}
        className="mt-6 h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700"
      >
        Continue
        {!isSaving && <ChevronRight className="ml-1 h-5 w-5" aria-hidden="true" />}
      </Button>
    </section>
  );
}

function choiceClassName(selected: boolean) {
  return `w-full rounded-2xl border-2 p-4 transition ${
    selected
      ? "border-blue-500 bg-blue-50/70 shadow-sm"
      : "border-slate-200 bg-white hover:border-blue-200"
  }`;
}

function iconClassName(selected: boolean) {
  return `flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
    selected ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"
  }`;
}
