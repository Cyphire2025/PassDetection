import { Badge, Button, Card, CardContent } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import {
  formatPassportCountry,
  formatPassportNationality,
} from "@/lib/utils/passport-country";
import { formatPassportDateForUi } from "@/lib/utils/passport-date";
import type {
  ExtractedPassportFields,
  PassportSubmission,
} from "@/types/passport.types";
import { Eye, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import type {
  PassportDocumentImportPreview,
  PassportImageType,
} from "../api/passports.api";
import { useReextractPassportSubmission } from "../hooks/use-passports";
import { matchPreviewFiles } from "../utils/passport-document-import";
import { DocumentCell } from "./passport-document-cell";

export function isDuplicatePassport(passport: PassportSubmission) {
  return Boolean(
    passport.duplicate_cluster_id && (passport.duplicate_cluster_size ?? 0) > 1,
  );
}

export function isDuplicateClusterStart(
  passports: PassportSubmission[],
  index: number,
) {
  const passport = passports[index];
  if (!passport || !isDuplicatePassport(passport)) return false;
  return (
    index === 0 ||
    passports[index - 1]?.duplicate_cluster_id !== passport.duplicate_cluster_id
  );
}

export function DuplicateClusterHeader({
  passport,
  searchActive,
  compact = false,
}: {
  passport: PassportSubmission;
  searchActive: boolean;
  compact?: boolean;
}) {
  const count =
    passport.duplicate_cluster_size ??
    passport.duplicate_cluster_member_ids?.length ??
    2;
  return (
    <div
      className={
        compact
          ? "flex flex-wrap items-center gap-2"
          : "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"
      }
    >
      <span className="inline-flex items-center rounded-full bg-amber-200/70 px-2.5 py-1 text-xs font-bold text-amber-950">
        Possible duplicate set
      </span>
      <span className="text-xs font-medium text-amber-900">
        Part of a possible duplicate set with {count} submissions
        {searchActive
          ? " · all set members are shown when one matches your search"
          : ""}
      </span>
    </div>
  );
}

export function PassportMobileCard({
  passport,
  selected,
  onToggle,
  detailHref,
  onOpen,
}: {
  passport: PassportSubmission;
  selected: boolean;
  onToggle: () => void;
  detailHref: string;
  onOpen: () => void;
}) {
  const cardClassName = selected
    ? "rounded-2xl border-blue-300 bg-blue-50/40"
    : isDuplicatePassport(passport)
      ? "rounded-2xl border-amber-200 bg-amber-50/30"
      : "rounded-2xl";
  return (
    <Card className={cardClassName} onClick={onToggle}>
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex gap-3">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              onClick={(event) => event.stopPropagation()}
              aria-label={`Select ${passport.client_name}`}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-slate-900">
                {passport.client_name}
              </h3>
              <p className="mt-1 break-all text-xs text-slate-500">
                {passport.client_email ?? "No email provided"}
              </p>
            </div>
          </div>
          <StatusBadge status={passport.status} />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoPair
            label="Passport"
            value={
              getStringField(getDashboardFields(passport), "passport_number") ||
              "Not extracted"
            }
          />
          <InfoPair
            label="Nationality"
            value={getDashboardCountry(passport) || "Manual review"}
          />
          <InfoPair
            label="Confidence"
            value={formatConfidence(passport.verification_confidence ?? null)}
          />
          <InfoPair
            label="Updated"
            value={formatDateTime(passport.updated_at)}
          />
          <InfoPair
            label="Date of Birth"
            value={getDashboardPassportDate(passport, "date_of_birth")}
          />
          <InfoPair
            label="Date of Issue"
            value={getDashboardPassportDate(passport, "date_of_issue")}
          />
          <InfoPair
            label="Date of Expiry"
            value={getDashboardPassportDate(passport, "date_of_expiry")}
          />
        </div>

        <div
          className={`grid gap-2 ${needsReextraction(passport) || passport.extraction_status === "processing" ? "sm:grid-cols-2" : ""}`}
        >
          <ReextractPassportControl passport={passport} />
          <Link
            href={detailHref as never}
            className="block"
            onClick={(event) => {
              event.stopPropagation();
              onOpen();
            }}
          >
            <Button variant="outline" className="w-full gap-2">
              <Eye className="h-4 w-4" />
              Open Submission
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export function ReextractPassportControl({
  passport,
  compact = false,
}: {
  passport: PassportSubmission;
  compact?: boolean;
}) {
  const reextractMutation = useReextractPassportSubmission();
  const [feedback, setFeedback] = useState<{
    tone: "success" | "warning" | "error";
    message: string;
  } | null>(null);
  const reextractInFlightRef = useRef(false);
  const isProcessing = passport.extraction_status === "processing";
  const backgroundFinished = feedback?.tone === "warning" && !isProcessing;
  const backgroundFailed =
    backgroundFinished &&
    (passport.extraction_status === "extraction_failed" ||
      passport.status === "failed");
  const backgroundConflictCount = getExtractionConflictCount(passport);
  const effectiveFeedback = backgroundFinished
    ? {
        tone: backgroundFailed ? ("error" as const) : ("success" as const),
        message: backgroundFailed
          ? "Automatic extraction failed. You can retry safely."
          : backgroundConflictCount > 0
            ? `Finished with ${backgroundConflictCount} ${backgroundConflictCount === 1 ? "difference" : "differences"} to review.`
            : "Extraction finished. Open the passport to review the results.",
      }
    : feedback;

  const handleReextract = async (
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    event.stopPropagation();
    if (reextractMutation.isPending || reextractInFlightRef.current) return;
    reextractInFlightRef.current = true;
    setFeedback(null);
    try {
      const result = await reextractMutation.mutateAsync(passport.id);
      if (result.outcome === "timed_out") {
        setFeedback({
          tone: "warning",
          message: "Still processing. This row will refresh automatically.",
        });
        return;
      }
      if (result.outcome === "failed") {
        setFeedback({
          tone: "error",
          message:
            "Automatic extraction failed. The saved image is unchanged; try again.",
        });
        return;
      }
      const conflictCount = getExtractionConflictCount(result.submission);
      setFeedback({
        tone: "success",
        message:
          conflictCount > 0
            ? `Finished with ${conflictCount} ${conflictCount === 1 ? "difference" : "differences"} to review.`
            : "Extraction finished. Open the passport to review the results.",
      });
    } catch (error) {
      setFeedback({
        tone: "error",
        message:
          error instanceof Error
            ? error.message
            : "Could not start re-extraction. Please try again.",
      });
    } finally {
      reextractInFlightRef.current = false;
    }
  };

  if (!needsReextraction(passport) && !isProcessing && !effectiveFeedback)
    return null;

  return (
    <div
      className={compact ? "max-w-52 text-right" : "w-full"}
      onClick={(event) => event.stopPropagation()}
    >
      <Button
        variant="secondary"
        size={compact ? "sm" : "md"}
        className={compact ? "gap-2" : "w-full gap-2"}
        disabled={reextractMutation.isPending || isProcessing}
        onClick={(event) => void handleReextract(event)}
        aria-busy={reextractMutation.isPending || isProcessing}
      >
        {reextractMutation.isPending || isProcessing ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        )}
        {reextractMutation.isPending
          ? "Extracting"
          : isProcessing
            ? "Processing"
            : effectiveFeedback?.tone === "error"
              ? "Try again"
              : "Re-extract"}
      </Button>
      {effectiveFeedback && (
        <p
          className={`mt-1.5 text-xs leading-4 ${
            effectiveFeedback.tone === "success"
              ? "text-emerald-700"
              : effectiveFeedback.tone === "warning"
                ? "text-amber-700"
                : "text-red-700"
          }`}
          role={effectiveFeedback.tone === "error" ? "alert" : "status"}
        >
          {effectiveFeedback.message}
        </p>
      )}
    </div>
  );
}

export function PassportDocumentMatrix({
  passports,
  preview,
  files = [],
  canEdit = false,
  revision = 0,
  onEdit,
}: {
  passports: PassportSubmission[];
  preview?: PassportDocumentImportPreview;
  files?: File[];
  canEdit?: boolean;
  revision?: number;
  onEdit?: (
    submissionId: string,
    imageType: PassportImageType,
    label: string,
    returnFocusTarget: HTMLButtonElement,
  ) => void;
}) {
  const matchedFiles = useMemo(
    () => matchPreviewFiles(preview?.accepted_documents ?? [], files),
    [files, preview?.accepted_documents],
  );
  const previewByPassenger = useMemo(() => {
    const map = new Map<
      string,
      Partial<
        Record<
          "photo" | "front" | "back",
          PassportDocumentImportPreview["accepted_documents"][number]
        >
      >
    >();
    preview?.accepted_documents.forEach((item) => {
      if (!item.passenger_id || !item.document_type) return;
      const current = map.get(item.passenger_id) ?? {};
      current[item.document_type] = item;
      map.set(item.passenger_id, current);
    });
    return map;
  }, [preview]);

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <caption className="sr-only">
              Current passenger document assignments
            </caption>
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th scope="col" className="px-5 py-4">
                  Person
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport pic
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport front
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport back
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {passports.map((passport) => {
                const previewDocs = previewByPassenger.get(passport.id);
                return (
                  <tr key={passport.id} className="align-top">
                    <td className="px-5 py-4">
                      <div className="font-semibold text-slate-900">
                        {passport.client_name}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {getPersonnelCode(passport) ||
                          "No staff or Agent/Employee code"}
                      </div>
                    </td>
                    <DocumentCell
                      label="Visa Photo"
                      url={passport.passport_photo_url}
                      file={
                        previewDocs?.photo
                          ? matchedFiles.get(previewDocs.photo)
                          : undefined
                      }
                      filename={previewDocs?.photo?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) =>
                        onEdit?.(
                          passport.id,
                          "visa_photo",
                          "Visa Photo",
                          trigger,
                        )
                      }
                    />
                    <DocumentCell
                      label="Passport front"
                      url={passport.image_url}
                      file={
                        previewDocs?.front
                          ? matchedFiles.get(previewDocs.front)
                          : undefined
                      }
                      filename={previewDocs?.front?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) =>
                        onEdit?.(
                          passport.id,
                          "passport_front",
                          "Passport front",
                          trigger,
                        )
                      }
                    />
                    <DocumentCell
                      label="Passport back"
                      url={passport.passport_back_url}
                      file={
                        previewDocs?.back
                          ? matchedFiles.get(previewDocs.back)
                          : undefined
                      }
                      filename={previewDocs?.back?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) =>
                        onEdit?.(
                          passport.id,
                          "passport_back",
                          "Passport back",
                          trigger,
                        )
                      }
                    />
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export function needsReextraction(passport: PassportSubmission) {
  if (!hasRealPassportFront(passport)) return false;
  return (
    passport.status === "failed" ||
    !getStringField(passport.extracted_fields, "passport_number") ||
    (passport.overall_confidence ?? 0) <= 0.2
  );
}

export function hasRealPassportFront(passport: PassportSubmission) {
  return Boolean(
    passport.image_s3_key &&
      !passport.image_s3_key.startsWith("excel-imports/"),
  );
}

export function getDashboardFields(passport: PassportSubmission) {
  return passport.confirmed_fields ?? passport.extracted_fields;
}

export function getDashboardCountry(passport: PassportSubmission) {
  const fields = getDashboardFields(passport);
  const nationality = getStringField(fields, "nationality");
  if (nationality) return formatPassportNationality(nationality);
  return formatPassportCountry(getStringField(fields, "issuing_country"));
}

export function getDashboardPassportDate(
  passport: PassportSubmission,
  field: "date_of_birth" | "date_of_issue" | "date_of_expiry",
) {
  return (
    formatPassportDateForUi(
      getStringField(getDashboardFields(passport), field),
    ) || "Not provided"
  );
}

export function getExtractionConflictCount(passport: PassportSubmission) {
  if (Array.isArray(passport.extraction_conflicts))
    return passport.extraction_conflicts.length;
  const fallback = passport.extracted_fields?.manual_review_conflicts;
  return Array.isArray(fallback) ? fallback.length : 0;
}

export function getStringField(
  fields: ExtractedPassportFields | null,
  key: string,
) {
  const value = fields?.[key];
  return typeof value === "string" ? value : "";
}

export function getPersonnelCode(passport: PassportSubmission) {
  const fields = passport.confirmed_fields ?? passport.extracted_fields;
  const agentEmployeeType = getStringField(
    fields,
    "agent_employee_type",
  ).toLowerCase();
  const agentEmployeeCode = getStringField(fields, "agent_employee_code");
  if (agentEmployeeCode && agentEmployeeType === "agent")
    return `AGT_${agentEmployeeCode}`;
  if (agentEmployeeCode && agentEmployeeType === "employee")
    return `EMP_${agentEmployeeCode}`;
  if (agentEmployeeCode) return agentEmployeeCode;
  const metadataCode =
    passport.staff_metadata?.staff_code ?? passport.staff_metadata?.staffcode;
  const fieldCode = getStringField(fields, "staff_code");
  const value = metadataCode || fieldCode;
  if (!value) return "";
  const normalized = String(value).trim().toUpperCase();
  const prefixed = normalized.match(/^STF[_\-\s]+(.+)$/);
  return prefixed ? `STF_${prefixed[1]}` : `STF_${normalized}`;
}

export function createExportRequestId() {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.getRandomValues === "function"
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

export function mutationErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof error.message === "string" &&
    error.message
  ) {
    return error.message;
  }
  return fallback;
}

export function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="mt-1 font-medium text-slate-800">{value}</div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={PASSPORT_STATUS_COLORS[status] || "default"} dot>
      {PASSPORT_STATUS_LABELS[status] || status}
    </Badge>
  );
}
