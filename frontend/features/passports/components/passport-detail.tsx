"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { AlertCircle, ArrowLeft, CheckCircle2, RotateCcw, Save } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import { useConfirmPassportSubmission, usePassportSubmission, useReextractPassportSubmission } from "../hooks/use-passports";

interface PassportDetailProps {
  id: string;
}

const REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "issuing_country",
  "date_of_birth",
  "date_of_expiry",
  "sex",
] as const;

export function PassportDetail({ id }: PassportDetailProps) {
  const { data, isLoading, error } = usePassportSubmission(id);
  const confirmMutation = useConfirmPassportSubmission(id);
  const reextractMutation = useReextractPassportSubmission();
  const [formError, setFormError] = useState<string | null>(null);

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

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title={data.client_name}
          description="Submission details, extraction output, and current processing state."
        />
        <Link href={ROUTES.dashboard.passports}>
          <Button variant="outline" className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back to Passports
          </Button>
        </Link>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="overflow-hidden rounded-3xl">
          <CardContent className="p-0">
            {data.image_url ? (
              <div className="relative aspect-[4/3] min-h-[24rem] bg-slate-100">
                <Image
                  src={data.image_url}
                  alt={`Passport submission from ${data.client_name}`}
                  fill
                  unoptimized
                  className="object-contain"
                />
              </div>
            ) : (
              <div className="flex min-h-[24rem] items-center justify-center bg-slate-50 text-slate-400">
                Preview unavailable
              </div>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <ReviewFieldsCard
            key={`${data.id}:${data.updated_at}`}
            passport={data}
            sourceFields={data.confirmed_fields ?? data.extracted_fields ?? {}}
            validation={data.extracted_fields?.field_validation}
            isSaving={confirmMutation.isPending}
            canReextract={needsReextraction(data)}
            isReextracting={reextractMutation.isPending}
            formError={formError}
            onFormError={setFormError}
            onConfirm={(fields) => confirmMutation.mutateAsync(fields)}
            onReextract={() => reextractMutation.mutate(data.id)}
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

function needsReextraction(passport: {
  status: string;
  extracted_fields: ExtractedPassportFields | null;
  overall_confidence: number | null;
}) {
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
  isSaving: boolean;
  canReextract: boolean;
  isReextracting: boolean;
  formError: string | null;
  onFormError: (error: string | null) => void;
  onConfirm: (fields: Record<string, string>) => Promise<unknown>;
  onReextract: () => void;
}

function ReviewFieldsCard({
  passport,
  sourceFields,
  validation,
  isSaving,
  canReextract,
  isReextracting,
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
    const cleanedFields = Object.fromEntries(
      Object.entries(reviewFields)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value),
    );

    if (Object.keys(cleanedFields).length === 0) {
      onFormError("Add at least one reviewed field before confirming.");
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

        <div className="grid gap-4 sm:grid-cols-2">
          {REVIEW_FIELDS.map((key) => (
            <label key={key} className="space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-400">{toLabel(key)}</span>
              <Input
                value={reviewFields[key] ?? ""}
                onChange={(event) => handleFieldChange(key, event.target.value)}
                placeholder="Not extracted"
                className="h-10 rounded-lg border-slate-200 bg-white"
              />
            </label>
          ))}
        </div>

        {validation?.issues && validation.issues.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <div className="font-medium">Fields needing attention</div>
            <ul className="mt-2 space-y-1">
              {validation.issues.map((issue, index) => (
                <li key={`${issue.field}:${index}`}>
                  <span className="font-medium">{toLabel(issue.field)}:</span> {issue.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {formError && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {formError}
          </div>
        )}

        {canReextract && (
          <Button
            variant="secondary"
            className="w-full gap-2"
            disabled={isReextracting}
            onClick={onReextract}
          >
            <RotateCcw className="h-4 w-4" />
            {isReextracting ? "Re-extracting" : "Re-extract Passport"}
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

function getStringField(fields: ExtractedPassportFields, key: string) {
  const value = fields[key];
  return typeof value === "string" ? value : "";
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
