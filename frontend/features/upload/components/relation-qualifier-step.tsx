"use client";

import { type KeyboardEvent, useRef } from "react";
import { CheckCircle2, ChevronRight, PencilLine, User, UsersRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { QualifierRelationOption } from "@/features/passports/api/upload-links.api";
import {
  buildQualifierSelectionRequest,
  qualifierOtherRelationError,
  type QualifierPath,
} from "../services/relation-qualifier";

export function RelationQualifierStep({
  path,
  relationCode,
  otherRelation,
  listEnabled,
  otherEnabled,
  options,
  isSaving,
  onPathChange,
  onRelationChange,
  onOtherRelationChange,
  onContinue,
}: {
  path: QualifierPath;
  relationCode: string;
  otherRelation: string;
  listEnabled: boolean;
  otherEnabled: boolean;
  options: QualifierRelationOption[];
  isSaving: boolean;
  onPathChange: (path: Exclude<QualifierPath, null>) => void;
  onRelationChange: (code: string) => void;
  onOtherRelationChange: (relation: string) => void;
  onContinue: () => void;
}) {
  const selfOptionRef = useRef<HTMLButtonElement>(null);
  const relationOptionRef = useRef<HTMLButtonElement>(null);
  const otherOptionRef = useRef<HTMLButtonElement>(null);
  const hasRelationOptions = listEnabled && options.length > 0;
  const availablePaths: Exclude<QualifierPath, null>[] = [
    "self", ...(hasRelationOptions ? ["relation" as const] : []), ...(otherEnabled ? ["other" as const] : []),
  ];
  const focusPath = path && availablePaths.includes(path) ? path : "self";
  const optionRefs = { self: selfOptionRef, relation: relationOptionRef, other: otherOptionRef };
  const canContinue = buildQualifierSelectionRequest(path, relationCode, options, otherRelation, { listEnabled, otherEnabled }) !== null;
  const otherError = path === "other" ? qualifierOtherRelationError(otherRelation) : null;
  const handleRadioKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentPath: Exclude<QualifierPath, null>,
  ) => {
    if (isSaving || !["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const direction = event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 1;
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? availablePaths.length - 1
      : (availablePaths.indexOf(currentPath) + direction + availablePaths.length) % availablePaths.length;
    const nextPath = availablePaths[nextIndex]!;
    onPathChange(nextPath);
    optionRefs[nextPath].current?.focus();
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
        travel in the qualifier&apos;s place, provide the passenger&apos;s relationship
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
          tabIndex={focusPath === "self" ? 0 : -1}
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

        <div data-testid="qualifier-relationship-methods" className={`grid items-stretch gap-3 ${listEnabled && otherEnabled ? "grid-cols-2" : "grid-cols-1"}`}>
        {listEnabled && <div data-testid="qualifier-list-card" className={`${choiceClassName(path === "relation")} flex min-w-0 flex-col`}>
          <button
            ref={relationOptionRef}
            type="button"
            role="radio"
            aria-checked={path === "relation"}
            tabIndex={focusPath === "relation" ? 0 : -1}
            disabled={isSaving || !hasRelationOptions}
            onClick={() => onPathChange("relation")}
            onKeyDown={(event) => handleRadioKeyDown(event, "relation")}
            className="relative flex w-full min-w-0 flex-col gap-2 text-left disabled:cursor-not-allowed disabled:opacity-60 sm:flex-row sm:items-start"
          >
            <span className={iconClassName(path === "relation")}>
              <UsersRound className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-bold leading-5 text-slate-900">
                Choose from list
              </span>
              <span className="mt-1 block text-xs leading-5 text-slate-500">
                Select one of the available relationships.
              </span>
            </span>
            {path === "relation" && (
              <CheckCircle2 className="absolute right-0 top-1 h-4 w-4 shrink-0 text-blue-600 sm:static" aria-hidden="true" />
            )}
          </button>

          <label className="mt-auto block pt-4">
            <span className="mb-2 block text-xs font-semibold text-slate-600">
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
              className={fieldClassName}
            >
              <option value="">Select relationship</option>
              {options.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-2 text-xs text-slate-500">Choose one option.</p>
          {!hasRelationOptions && (
            <p role="status" className="mt-3 text-xs leading-5 text-amber-700">
              No eligible relationships are currently available. Select Self or
              contact the travel coordinator.
            </p>
          )}
        </div>}

        {otherEnabled && <div data-testid="qualifier-other-card" className={`${choiceClassName(path === "other")} flex min-w-0 flex-col`}>
          <button
            ref={otherOptionRef}
            type="button"
            role="radio"
            aria-checked={path === "other"}
            tabIndex={focusPath === "other" ? 0 : -1}
            disabled={isSaving}
            onClick={() => onPathChange("other")}
            onKeyDown={(event) => handleRadioKeyDown(event, "other")}
            className="relative flex w-full min-w-0 flex-col gap-2 text-left disabled:cursor-not-allowed disabled:opacity-60 sm:flex-row sm:items-start"
          >
            <span className={iconClassName(path === "other")}><PencilLine className="h-5 w-5" aria-hidden="true" /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-bold leading-5 text-slate-900">Other relationship</span>
              <span className="mt-1 block text-xs leading-5 text-slate-500">Enter the relationship in your own words.</span>
            </span>
            {path === "other" && <CheckCircle2 className="absolute right-0 top-1 h-4 w-4 shrink-0 text-blue-600 sm:static" aria-hidden="true" />}
          </button>
          <label className="mt-auto block pt-4">
            <span className="mb-2 block text-xs font-semibold text-slate-600">Specify relationship</span>
            <input
              type="text"
              value={otherRelation}
              disabled={isSaving}
              autoComplete="off"
              placeholder="e.g. Cousin"
              aria-invalid={Boolean(otherError)}
              aria-describedby={otherError ? "qualifier-other-error" : "qualifier-other-hint"}
              onFocus={() => onPathChange("other")}
              onChange={(event) => {
                onPathChange("other");
                onOtherRelationChange(event.target.value);
              }}
              className={fieldClassName}
            />
          </label>
          <p id="qualifier-other-hint" className="mt-2 text-xs text-slate-500">Up to 100 characters.</p>
        </div>}
        </div>
      </div>
      {otherEnabled && otherError && <p id="qualifier-other-error" role="status" className="mt-3 text-sm text-red-600">{otherError}</p>}

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
  return `w-full rounded-2xl border-2 p-3 transition sm:p-4 ${
    selected
      ? "border-blue-500 bg-blue-50/70 shadow-sm"
      : "border-slate-200 bg-white hover:border-blue-200"
  }`;
}

function iconClassName(selected: boolean) {
  return `flex h-8 w-8 shrink-0 items-center justify-center rounded-lg sm:h-10 sm:w-10 ${
    selected ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"
  }`;
}

const fieldClassName = "h-12 w-full min-w-0 rounded-xl border border-slate-300 bg-white px-2 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60 sm:px-3";
