"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, QrCode, RotateCcw, Save } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import {
  formatPassportCountry,
  getPassportCountryOptions,
  isRecognizedPassportCountryCode,
} from "@/lib/utils/passport-country";
import type {
  ExtractedPassportFields,
  PassportExtractionConflict,
  PassportSubmission,
} from "@/types/passport.types";
import { useConfirmPassportSubmission, usePassportSubmission, useReextractPassportSubmission } from "../hooks/use-passports";

interface PassportDetailProps {
  id: string;
}

interface ReextractFeedback {
  tone: "processing" | "success" | "warning" | "error";
  message: string;
}

const REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "issuing_country",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "sex",
] as const;

export function PassportDetail({ id }: PassportDetailProps) {
  const { data, isLoading, error } = usePassportSubmission(id);
  const confirmMutation = useConfirmPassportSubmission(id);
  const reextractMutation = useReextractPassportSubmission();
  const [formError, setFormError] = useState<string | null>(null);
  const [reextractFeedback, setReextractFeedback] = useState<ReextractFeedback | null>(null);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-14 w-80 rounded-xl" />
        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <Skeleton className="h-[32rem] w-full rounded-3xl" />
          <Skeleton className="h-[32rem] w-full rounded-3xl" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Passport Submission" description="Submission details and extracted fields" />
        <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-700">
          Failed to load this passport submission.
        </div>
      </div>
    );
  }

  const handleReextract = async () => {
    setFormError(null);
    setReextractFeedback({
      tone: "processing",
      message: "Re-extraction queued. Reading and verifying the saved passport image.",
    });
    try {
      const result = await reextractMutation.mutateAsync(data.id);
      if (result.outcome === "timed_out") {
        setReextractFeedback({
          tone: "warning",
          message: "Extraction is still running. This page will keep refreshing automatically.",
        });
        return;
      }
      if (result.outcome === "failed") {
        setReextractFeedback({
          tone: "error",
          message: result.submission.error_message
            || "The saved image could not be extracted. It remains available for another retry.",
        });
        return;
      }
      const conflictCount = getExtractionConflicts(result.submission).length;
      setReextractFeedback({
        tone: "success",
        message: conflictCount > 0
          ? `Re-extraction finished with ${conflictCount} ${conflictCount === 1 ? "difference" : "differences"} for you to review below.`
          : "Re-extraction finished. Matching manual values were kept and empty fields were filled where possible.",
      });
    } catch (reextractError) {
      setReextractFeedback({
        tone: "error",
        message: reextractError instanceof Error
          ? reextractError.message
          : "Could not start re-extraction. Please try again.",
      });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title={data.client_name}
          description="Submission details, extraction output, and current processing state."
        />
        <Link href={ROUTES.dashboard.passportGroup(data.group_id) as never}>
          <Button variant="outline" className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back to Passports
          </Button>
        </Link>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="overflow-hidden rounded-3xl">
          <CardContent className="space-y-5 p-4">
            <PassportImagePreview label="VISA selfie photo" url={data.passport_photo_url} clientName={data.client_name} />
            <PassportImagePreview label="Passport front" url={data.image_url} clientName={data.client_name} />
            <PassportImagePreview label="Passport back" url={data.passport_back_url} clientName={data.client_name} />
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card className="rounded-3xl">
            <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                  <QrCode className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <h3 className="font-semibold text-slate-900">Attendance QR status</h3>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <Badge variant={qrStatusVariant(data.qr_status?.status)} dot>
                      {formatQrStatus(data.qr_status?.status ?? "not_generated")}
                    </Badge>
                    {data.qr_status?.token_version && (
                      <span className="text-xs text-slate-500">Version {data.qr_status.token_version}</span>
                    )}
                  </div>
                  {data.qr_status?.expires_at && (
                    <p className="mt-1.5 text-xs text-slate-500">
                      Expires {formatDateTime(data.qr_status.expires_at)}
                    </p>
                  )}
                </div>
              </div>
              <Link href={ROUTES.dashboard.tourOperationsGroupQrCodes(data.group_id) as never}>
                <Button variant="secondary" className="w-full sm:w-auto">Manage QR</Button>
              </Link>
            </CardContent>
          </Card>

          <ClientProvidedFieldsCard passport={data} />

          <ReviewFieldsCard
            key={`${data.id}:${data.extraction_revision}:${data.updated_at}`}
            passport={data}
            sourceFields={data.confirmed_fields ?? data.extracted_fields ?? {}}
            validation={data.extracted_fields?.field_validation}
            conflicts={getExtractionConflicts(data)}
            isSaving={confirmMutation.isPending}
            canReextract={needsReextraction(data)}
            isReextracting={reextractMutation.isPending}
            reextractFeedback={reextractFeedback}
            formError={formError}
            onFormError={setFormError}
            onConfirm={(fields) => confirmMutation.mutateAsync(fields)}
            onReextract={() => void handleReextract()}
          />

          {data.error_message && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{data.error_message}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PassportImagePreview({ label, url, clientName }: { label: string; url?: string | null; clientName: string }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-slate-700">{label}</h3>
      {url ? (
        <div className="relative aspect-[4/3] min-h-[15rem] overflow-hidden rounded-xl bg-slate-100">
          <Image src={url} alt={`${label} for ${clientName}`} fill unoptimized className="object-contain" />
        </div>
      ) : (
        <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 text-sm text-slate-400">
          Not uploaded
        </div>
      )}
    </section>
  );
}

function ClientProvidedFieldsCard({ passport }: { passport: PassportSubmission }) {
  const fields = passport.confirmed_fields ?? passport.extracted_fields ?? {};
  const values = [
    ["Nearest International Airport", passport.departure_city],
    ["Nearest Domestic Airport", passport.nearest_domestic_airport],
    ["Base City", getStringField(fields, "base_city")],
    ["Staff Code", getStringField(fields, "staff_code")],
    ["Meal Preference", getStringField(fields, "meal_preference")],
  ].filter((item): item is [string, string] => Boolean(item[1]));

  if (values.length === 0) return null;

  return (
    <Card className="rounded-3xl">
      <CardContent className="p-5">
        <h3 className="font-semibold text-slate-900">Client-provided group details</h3>
        <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2">
          {values.map(([label, value]) => <MetaItem key={label} label={label} value={value} />)}
        </div>
      </CardContent>
    </Card>
  );
}

function formatQrStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function qrStatusVariant(status?: string): "default" | "success" | "warning" | "destructive" | "outline" {
  if (status === "active") return "success";
  if (status === "inactive" || status === "expired") return "warning";
  if (status === "revoked") return "destructive";
  return "outline";
}

function needsReextraction(passport: {
  image_s3_key?: string | null;
  status: string;
  extracted_fields: ExtractedPassportFields | null;
  overall_confidence: number | null;
}) {
  if (!passport.image_s3_key || passport.image_s3_key.startsWith("excel-imports/")) return false;
  return (
    passport.status === "failed" ||
    !getStringField(passport.extracted_fields ?? {}, "passport_number") ||
    (passport.overall_confidence ?? 0) <= 0.2
  );
}

interface ReviewFieldsCardProps {
  passport: PassportSubmission;
  sourceFields: ExtractedPassportFields;
  validation?: ExtractedPassportFields["field_validation"];
  conflicts: PassportExtractionConflict[];
  isSaving: boolean;
  canReextract: boolean;
  isReextracting: boolean;
  reextractFeedback: ReextractFeedback | null;
  formError: string | null;
  onFormError: (error: string | null) => void;
  onConfirm: (fields: Record<string, string>) => Promise<unknown>;
  onReextract: () => void;
}

function ReviewFieldsCard({
  passport,
  sourceFields,
  validation,
  conflicts,
  isSaving,
  canReextract,
  isReextracting,
  reextractFeedback,
  formError,
  onFormError,
  onConfirm,
  onReextract,
}: ReviewFieldsCardProps) {
  const initialFields = useMemo(
    () =>
      REVIEW_FIELDS.reduce<Record<string, string>>((fields, key) => {
        fields[key] = getStringField(sourceFields, key);
        return fields;
      }, {}),
    [sourceFields],
  );
  const [reviewFields, setReviewFields] = useState<Record<string, string>>(initialFields);

  const handleFieldChange = (key: string, value: string) => {
    setReviewFields((current) => ({ ...current, [key]: value }));
  };

  const handleConfirm = async () => {
    const cleanedFields: Record<string, string> = Object.fromEntries(
      Object.entries(reviewFields)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value),
    );
    for (const key of ["base_city", "staff_code", "meal_preference"] as const) {
      const value = getStringField(sourceFields, key);
      if (value) cleanedFields[key] = value;
    }

    if (Object.keys(cleanedFields).length === 0) {
      onFormError("Add at least one reviewed field before confirming.");
      return;
    }
    if (!hasValidReviewDates(cleanedFields)) {
      onFormError("Enter valid passport dates in YYYY-MM-DD format. Date of Issue may be empty, but it cannot be in the future, before birth, or after passport expiry.");
      return;
    }

    onFormError(null);
    await onConfirm(cleanedFields);
  };

  return (
    <Card className="rounded-3xl">
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-center gap-2 text-slate-900">
              <CheckCircle2 className="h-5 w-5 text-green-600" />
              <h3 className="text-base font-semibold">Review Fields</h3>
            </div>
            <Badge variant={PASSPORT_STATUS_COLORS[passport.status] || "default"} dot>
              {PASSPORT_STATUS_LABELS[passport.status] || passport.status}
            </Badge>
          </div>
          <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2">
            <MetaItem label="Confidence" value={formatConfidence(passport.overall_confidence)} />
            <MetaItem label="Submitted" value={formatDateTime(passport.created_at)} />
            <MetaItem label="Updated" value={formatDateTime(passport.updated_at)} />
            <MetaItem label="Expiry" value={reviewFields.date_of_expiry || "Not extracted"} />
          </div>
        </div>

        <ReextractStatus
          passport={passport}
          feedback={reextractFeedback}
          isReextracting={isReextracting}
        />

        {conflicts.length > 0 && (
          <ExtractionConflictPanel
            conflicts={conflicts}
            reviewFields={reviewFields}
            onSelect={(field, value) => {
              handleFieldChange(field, value);
              onFormError(null);
            }}
          />
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          {REVIEW_FIELDS.map((key) => {
            const isDate = key === "date_of_birth" || key === "date_of_issue" || key === "date_of_expiry";
            const isCountry = key === "nationality" || key === "issuing_country";
            return (
              <label key={key} className="space-y-1.5">
                <span className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                  {toLabel(key)}
                  {key === "date_of_issue" && <span className="normal-case tracking-normal">(optional)</span>}
                </span>
                {isCountry ? (
                  <PassportCountryField
                    value={reviewFields[key] ?? ""}
                    onChange={(value) => handleFieldChange(key, value)}
                  />
                ) : (
                  <Input
                    type={isDate ? "date" : "text"}
                    value={reviewFields[key] ?? ""}
                    onChange={(event) => handleFieldChange(key, event.target.value)}
                    placeholder={key === "date_of_issue" ? "Leave empty if unavailable" : "Not extracted"}
                    min="1900-01-01"
                    max={key === "date_of_birth" ? yesterdayIsoDate() : key === "date_of_issue" ? todayIsoDate() : "2200-12-31"}
                    className="h-10 rounded-lg border-slate-200 bg-white"
                  />
                )}
              </label>
            );
          })}
        </div>

        {validation?.issues && validation.issues.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <div className="font-medium">Fields needing attention</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {getAttentionFieldLabels(validation.issues).map((label) => (
                <span
                  key={label}
                  className="rounded-full border border-amber-200 bg-white px-2.5 py-1 text-xs font-medium text-amber-800"
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}

        {formError && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {formError}
          </div>
        )}

        {(canReextract || passport.extraction_status === "processing") && (
          <Button
            variant="secondary"
            className="w-full gap-2"
            disabled={isReextracting || passport.extraction_status === "processing"}
            onClick={onReextract}
            aria-busy={isReextracting || passport.extraction_status === "processing"}
          >
            {isReextracting || passport.extraction_status === "processing" ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            )}
            {isReextracting || passport.extraction_status === "processing"
              ? "Extracting saved passport"
              : "Re-extract Passport"}
          </Button>
        )}

        <Button
          onClick={() => void handleConfirm()}
          disabled={isSaving}
          className="w-full gap-2 bg-blue-600 text-white hover:bg-blue-700"
        >
          <Save className="h-4 w-4" />
          {isSaving ? "Saving Review" : passport.status === "confirmed" ? "Update Confirmed Fields" : "Confirm Reviewed Fields"}
        </Button>
      </CardContent>
    </Card>
  );
}

function ReextractStatus({
  passport,
  feedback,
  isReextracting,
}: {
  passport: PassportSubmission;
  feedback: ReextractFeedback | null;
  isReextracting: boolean;
}) {
  const isProcessing = isReextracting || passport.extraction_status === "processing";
  const backgroundFinished = feedback?.tone === "warning" && !isProcessing;
  const backgroundFailed = backgroundFinished
    && (passport.extraction_status === "extraction_failed" || passport.status === "failed");
  const effectiveFeedback = backgroundFinished
    ? {
      tone: backgroundFailed ? "error" as const : "success" as const,
      message: backgroundFailed
        ? passport.error_message || "Automatic extraction failed. You can retry the saved image."
        : getExtractionConflicts(passport).length > 0
          ? "Extraction finished with differences for you to review below."
          : "Extraction finished and the latest details are ready to review.",
    }
    : feedback;
  if (!effectiveFeedback && !isProcessing) return null;

  const tone = isProcessing && effectiveFeedback?.tone !== "warning"
    ? "processing"
    : effectiveFeedback?.tone ?? "processing";
  const styles = {
    processing: "border-blue-200 bg-blue-50 text-blue-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    error: "border-red-200 bg-red-50 text-red-900",
  }[tone];
  const message = isProcessing
    ? processingStageLabel(passport.processing_stage ?? passport.processing_job_status)
    : effectiveFeedback?.message;

  return (
    <div className={`rounded-2xl border p-4 ${styles}`} role={tone === "error" ? "alert" : "status"} aria-live="polite">
      <div className="flex items-start gap-3">
        {isProcessing ? (
          <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin" aria-hidden="true" />
        ) : tone === "success" ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        ) : (
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">
            {isProcessing ? "Re-extraction in progress" : tone === "success" ? "Re-extraction complete" : "Re-extraction update"}
          </p>
          <p className="mt-1 text-sm leading-5 opacity-90">{message}</p>
          {isProcessing && typeof passport.processing_progress === "number" && (
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/70" aria-hidden="true">
              <div
                className="h-full rounded-full bg-blue-600 transition-all duration-500"
                style={{ width: `${Math.max(8, Math.min(100, Math.round(passport.processing_progress * 100)))}%` }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ExtractionConflictPanel({
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
                <div className={`rounded-lg border p-3 ${
                  extractedSelected ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-slate-50"
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

function PassportCountryField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  if (!isRecognizedPassportCountryCode(value)) {
    return (
      <Input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Not extracted"
        className="h-10 rounded-lg border-slate-200 bg-white"
      />
    );
  }

  const normalizedCode = value.trim().toUpperCase();
  const codeLength = normalizedCode.length === 2 ? 2 : 3;
  return (
    <select
      value={normalizedCode}
      onChange={(event) => onChange(event.target.value)}
      className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
    >
      {getPassportCountryOptions(codeLength).map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  );
}

function getStringField(fields: ExtractedPassportFields, key: string) {
  const value = fields[key];
  return typeof value === "string" ? value : "";
}

function getExtractionConflicts(passport: PassportSubmission): PassportExtractionConflict[] {
  const direct = normalizeExtractionConflicts(passport.extraction_conflicts);
  if (direct.length > 0) return direct;
  return normalizeExtractionConflicts(passport.extracted_fields?.manual_review_conflicts);
}

function normalizeExtractionConflicts(value: unknown): PassportExtractionConflict[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Record<string, unknown>;
      if (
        typeof candidate.field !== "string"
        || typeof candidate.manual_value !== "string"
        || (candidate.extracted_value !== null && typeof candidate.extracted_value !== "string")
      ) {
        return [];
      }
      const status = candidate.status === "not_extracted" ? "not_extracted" : "mismatch";
      return [{
        field: candidate.field,
        manual_value: candidate.manual_value,
        extracted_value: candidate.extracted_value,
        status,
      }];
    });
  }

  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([field, item]) => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Record<string, unknown>;
      if (
        typeof candidate.manual_value !== "string"
        || (candidate.extracted_value !== null && typeof candidate.extracted_value !== "string")
      ) {
        return [];
      }
      return [{
        field,
        manual_value: candidate.manual_value,
        extracted_value: candidate.extracted_value,
        status: candidate.status === "not_extracted" ? "not_extracted" as const : "mismatch" as const,
      }];
    });
  }
  return [];
}

function processingStageLabel(stage: string | null | undefined) {
  const labels: Record<string, string> = {
    queued: "Queued safely. Processing will begin shortly.",
    running: "Reading the saved passport image.",
    downloading_image: "Preparing the saved passport image.",
    extracting_passport_fields: "Extracting passport details from the image.",
    verifying_passport_fields: "Checking extracted details against the passport.",
    saving_extraction_result: "Saving the verified details and comparison.",
  };
  return labels[stage ?? ""] ?? "Reading and verifying the saved passport image.";
}

function isReviewField(field: string): field is typeof REVIEW_FIELDS[number] {
  return (REVIEW_FIELDS as readonly string[]).includes(field);
}

function valuesMatch(left: string, right: string) {
  return left.trim().toLocaleUpperCase("en") === right.trim().toLocaleUpperCase("en");
}

function formatConflictValue(field: string, value: string) {
  if (field === "nationality" || field === "issuing_country") {
    return formatPassportCountry(value) || value;
  }
  return value;
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-800">{value}</div>
    </div>
  );
}

function toLabel(value: string) {
  if (value === "given_names") return "Name";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function hasValidReviewDates(fields: Record<string, string>) {
  const dateOfBirth = fields.date_of_birth?.trim() ?? "";
  const dateOfIssue = fields.date_of_issue?.trim() ?? "";
  const dateOfExpiry = fields.date_of_expiry?.trim() ?? "";
  for (const value of [dateOfBirth, dateOfIssue, dateOfExpiry]) {
    if (value && !isValidIsoDate(value)) return false;
  }
  const today = todayIsoDate();
  if (dateOfBirth && dateOfBirth >= today) return false;
  if (dateOfIssue && dateOfIssue > today) return false;
  if (dateOfBirth && dateOfIssue && dateOfIssue <= dateOfBirth) return false;
  if (dateOfIssue && dateOfExpiry && dateOfIssue >= dateOfExpiry) return false;
  if (dateOfBirth && dateOfExpiry && dateOfExpiry <= dateOfBirth) return false;
  return true;
}

function isValidIsoDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return year >= 1900
    && year <= 2200
    && parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day;
}

function todayIsoDate() {
  const now = new Date();
  return new Date(now.getTime() - (now.getTimezoneOffset() * 60_000)).toISOString().slice(0, 10);
}

function yesterdayIsoDate() {
  const today = new Date(`${todayIsoDate()}T00:00:00`);
  today.setDate(today.getDate() - 1);
  return today.toISOString().slice(0, 10);
}

function getAttentionFieldLabels(
  issues: Array<{ field: string; message: string; severity: string }>,
) {
  const labels = new Set<string>();
  for (const issue of issues) {
    const text = `${issue.field} ${issue.message}`.toLowerCase();
    if (text.includes("name") || issue.field === "surname" || issue.field === "given_names") {
      labels.add("Name");
      continue;
    }
    if (text.includes("passport_number") || text.includes("passport number")) {
      labels.add("Passport number");
      continue;
    }
    if (text.includes("date_of_birth") || text.includes("birth")) {
      labels.add("Date of birth");
      continue;
    }
    if (text.includes("date_of_expiry") || text.includes("expiry")) {
      labels.add("Date of expiry");
      continue;
    }
    if (text.includes("date_of_issue") || text.includes("issue date")) {
      labels.add("Date of issue");
      continue;
    }
    if (text.includes("nationality")) {
      labels.add("Nationality");
      continue;
    }
    if (text.includes("issuing_country") || text.includes("issuing country")) {
      labels.add("Issuing country");
      continue;
    }
    if (text.includes("sex")) {
      labels.add("Sex");
      continue;
    }
    labels.add(toLabel(issue.field));
  }
  return Array.from(labels);
}
