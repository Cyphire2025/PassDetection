import type { ReactNode } from "react";
import { AlertCircle, ArrowLeft } from "lucide-react";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ExtractedPassportFields } from "@/types/passport.types";
import type { PassportDocumentVerificationGate } from "../services/passport-document-verification";
import {
  formatReviewFieldValue,
  toLabel,
  todayIsoDate,
  yesterdayIsoDate,
} from "../services/upload-flow-helpers";
import { REVIEW_FIELDS } from "./upload-flow.constants";

export function ReviewLayout({
  title,
  description,
  documents,
  onBack,
  children,
}: {
  title: string;
  description: string;
  documents: ReactNode;
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 font-sans sm:py-10">
      <div className="mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="space-y-4">
          <div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onBack}
              className="mb-4 -ml-2 gap-2 text-slate-600 hover:text-slate-900"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
            <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
          </div>
          {documents}
        </div>
        {children}
      </div>
    </div>
  );
}

export function ReviewWarning() {
  return (
    <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
      <p>
        Please compare these details with the passport image. Submit only after confirming the information is correct.
      </p>
    </div>
  );
}

export function ReviewFields({
  fields,
  onChange,
}: {
  fields: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {REVIEW_FIELDS.map((key) => {
        const isDate = key === "date_of_birth" || key === "date_of_issue" || key === "date_of_expiry";
        const isOptional = key === "date_of_issue" || key === "surname";
        return (
          <div key={key} className="space-y-1.5">
            <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {toLabel(key)}
            </span>
            {isDate ? (
              <PassportDateInput
                value={fields[key] ?? ""}
                onValueChange={(value) => onChange(key, value)}
                minIso="1900-01-01"
                maxIso={key === "date_of_birth"
                  ? yesterdayIsoDate()
                  : key === "date_of_issue"
                    ? todayIsoDate()
                    : "2200-12-31"}
                required={!isOptional}
                aria-label={toLabel(key)}
                className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-slate-50 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white"
              />
            ) : (
              <Input
                type="text"
                value={formatReviewFieldValue(key, fields[key] ?? "")}
                onChange={(event) => onChange(key, event.target.value)}
                placeholder={key === "surname" ? "Leave blank if not present" : "Not extracted"}
                required={!isOptional}
                aria-label={toLabel(key)}
                className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-slate-50 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ExtractionNotice({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-medium leading-5 text-blue-900"
    >
      {message}
    </div>
  );
}

export function DocumentVerificationBlock({
  gate,
  onRetry,
  onReplace,
  isRetrying,
  isReplacing,
}: {
  gate: Extract<PassportDocumentVerificationGate, { accepted: false }>;
  onRetry: () => void;
  onReplace: () => void;
  isRetrying: boolean;
  isReplacing: boolean;
}) {
  const busy = isRetrying || isReplacing;
  return (
    <div
      role="alert"
      className="rounded-2xl border border-amber-300 bg-amber-50 p-5 text-amber-950"
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <h3 className="font-bold">Passport page not verified</h3>
          <p className="mt-2 text-sm leading-6">{gate.message}</p>
          <p className="mt-2 text-xs leading-5 text-amber-800">
            Passport fields stay locked and cannot be submitted until this check passes.
          </p>
        </div>
      </div>
      <Button
        type="button"
        className="mt-4 h-11 w-full"
        onClick={gate.action === "retry" ? onRetry : onReplace}
        disabled={busy}
      >
        {gate.action === "retry"
          ? isRetrying
            ? "Retrying verification"
            : "Retry verification on saved image"
          : isReplacing
            ? "Preparing replacement"
            : "Replace passport pages"}
      </Button>
    </div>
  );
}

export function PassportRoiOverlays({ fields }: { fields: ExtractedPassportFields | null }) {
  const boxes = roiOverlayBoxes(fields);
  if (boxes.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      {boxes.map((box) => (
        <div
          key={box.field}
          className="absolute rounded-sm border-2 border-red-500 shadow-[0_0_0_9999px_rgba(239,68,68,0.04)]"
          style={{
            left: `${box.left * 100}%`,
            top: `${box.top * 100}%`,
            width: `${(box.right - box.left) * 100}%`,
            height: `${(box.bottom - box.top) * 100}%`,
          }}
        >
          <span className="absolute -top-6 left-0 rounded bg-red-600 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white shadow-sm">
            {toLabel(box.field)}
          </span>
        </div>
      ))}
    </div>
  );
}

function roiOverlayBoxes(fields: ExtractedPassportFields | null) {
  const provenance = fields?.field_provenance;
  if (!provenance) return [];

  return Object.entries(provenance)
    .map(([field, item]) => {
      const bbox = item?.debug?.image_relative_bbox;
      if (!isNormalizedBbox(bbox)) return null;
      return { field, left: bbox[0], top: bbox[1], right: bbox[2], bottom: bbox[3] };
    })
    .filter((box): box is {
      field: string;
      left: number;
      top: number;
      right: number;
      bottom: number;
    } => Boolean(box));
}

function isNormalizedBbox(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value)
    && value.length === 4
    && value.every((item) => typeof item === "number" && item >= 0 && item <= 1)
    && value[2] > value[0]
    && value[3] > value[1];
}
