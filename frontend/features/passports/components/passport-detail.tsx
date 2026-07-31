"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, CheckCircle2, ChevronLeft, ChevronRight, ExternalLink, Loader2, Pencil, QrCode, RotateCcw, Save, Upload } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import { Badge, Button, buttonVariants, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import {
  formatPassportDateForUi,
  previousPassportIsoDate,
} from "@/lib/utils/passport-date";
import { formatPassportNationality } from "@/lib/utils/passport-country";
import { getPassportTextField } from "@/lib/utils/passport-fields";
import { cn } from "@/lib/utils/cn";
import type {
  ExtractedPassportFields,
  PassportExtractionConflict,
  PassportSubmission,
  StaffApprovalResult,
} from "@/types/passport.types";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useConfirmPassportSubmission,
  useGroupSubmissionsView,
  usePassportSubmission,
  useReextractPassportSubmission,
  useRetryPassportAiVerification,
  useStaffApprovePassportSubmission,
} from "../hooks/use-passports";
import {
  canRetryPassportAiVerification,
  buildStaffApprovalRequest,
  cleanPassportReviewFields,
  formatPassportFieldReviewConfidence,
  formatPassportVerificationReason,
  getPassportFieldReview,
  getPassportFieldReviewClassName,
  getPassportReviewerLabel,
  getPassportReviewActionState,
  getPassportVerificationConfidence,
  getStaffApprovalErrorFeedback,
  getStaffApprovalOutcomeFeedback,
  PASSPORT_REVIEW_FIELDS,
  type PassportFieldReview,
  type StaffApprovalFeedback,
} from "../utils/passport-review";
import { passportsApi, type PassportImageType } from "../api/passports.api";
import { canEditPassportImages } from "../utils/passport-image-crop-permissions";
import {
  PASSPORT_LIBRARY_IMAGE_ACCEPT,
  validatePassportLibraryImage,
} from "../utils/passport-image-library";
import {
  buildPassportDetailNavigationHref,
  buildPassportGroupHref,
  isPassportNavigationKeyboardTarget,
  parsePassportDetailNavigation,
  readPassportNavigationContext,
  type PassportDetailNavigationState,
  type StoredPassportNavigationContext,
} from "../utils/passport-group-navigation";

const PassportImageCropEditor = dynamic(() =>
  import("./passport-image-crop-editor").then(
    (module) => module.PassportImageCropEditor,
  ),
);

interface PassportDetailProps {
  id: string;
  navigationQuery?: string;
}

interface ReextractFeedback {
  tone: "processing" | "success" | "warning" | "error";
  message: string;
}

const REVIEW_FIELDS = PASSPORT_REVIEW_FIELDS;

export function PassportDetail({ id, navigationQuery = "" }: PassportDetailProps) {
  const router = useRouter();
  const navigationFromUrl = useMemo(
    () => parsePassportDetailNavigation(new URLSearchParams(navigationQuery)),
    [navigationQuery],
  );
  const { data, isLoading, error, refetch } = usePassportSubmission(id);
  const confirmMutation = useConfirmPassportSubmission(id);
  const staffApproveMutation = useStaffApprovePassportSubmission(id);
  const retryAiVerificationMutation = useRetryPassportAiVerification(id);
  const reextractMutation = useReextractPassportSubmission();
  const currentUser = useAuthStore(selectUser);
  const canCropPassportImages = canEditPassportImages(currentUser?.role);
  const [formError, setFormError] = useState<string | null>(null);
  const [approvalFeedback, setApprovalFeedback] = useState<StaffApprovalFeedback | null>(null);
  const [reextractFeedback, setReextractFeedback] = useState<ReextractFeedback | null>(null);
  const [cropEditor, setCropEditor] = useState<{
    imageType: PassportImageType;
    label: string;
    returnFocusTarget: HTMLButtonElement;
  } | null>(null);
  const [imageRevision, setImageRevision] = useState(0);
  const [changingImageType, setChangingImageType] =
    useState<PassportImageType | null>(null);
  const [imageChangeErrors, setImageChangeErrors] = useState<
    Partial<Record<PassportImageType, string>>
  >({});
  const reextractInFlightRef = useRef(false);
  const [storedNavigation, setStoredNavigation] =
    useState<StoredPassportNavigationContext | null>(null);
  const navigationGroupMatches = Boolean(
    data
    && navigationFromUrl
    && data.group_id === navigationFromUrl.groupId,
  );
  const {
    data: fallbackNavigationView,
  } = useGroupSubmissionsView(
    navigationFromUrl?.groupId ?? "",
    {
      ...(navigationFromUrl?.viewState.search
        ? { search: navigationFromUrl.viewState.search }
        : {}),
      include_deleted: navigationFromUrl?.includeDeleted ?? false,
      submission_filter:
        navigationFromUrl?.viewState.submissionFilter ?? "all",
      sort_by: navigationFromUrl?.viewState.sortBy ?? "name",
      sort_order: navigationFromUrl?.viewState.sortOrder ?? "asc",
      page: 1,
      page_size: 1,
    },
    navigationGroupMatches,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!navigationFromUrl || !currentUser?.id || !navigationGroupMatches) {
        setStoredNavigation(null);
        return;
      }
      setStoredNavigation(
        readPassportNavigationContext({
          token: navigationFromUrl.token,
          userId: currentUser.id,
          groupId: navigationFromUrl.groupId,
        }),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    currentUser?.id,
    navigationFromUrl,
    navigationGroupMatches,
  ]);

  const validStoredNavigation =
    storedNavigation
    && storedNavigation.userId === currentUser?.id
    && storedNavigation.groupId === data?.group_id
      ? storedNavigation
      : null;
  const activeNavigation: PassportDetailNavigationState | null =
    validStoredNavigation ?? (navigationGroupMatches ? navigationFromUrl : null);
  const orderedSubmissionIds = validStoredNavigation?.orderedSubmissionIds
    ?? fallbackNavigationView?.ordered_submission_ids
    ?? [];
  const navigationIndex = data
    ? orderedSubmissionIds.indexOf(data.id)
    : -1;
  const previousSubmissionId = navigationIndex > 0
    ? orderedSubmissionIds[navigationIndex - 1]
    : null;
  const nextSubmissionId =
    navigationIndex >= 0 && navigationIndex < orderedSubmissionIds.length - 1
      ? orderedSubmissionIds[navigationIndex + 1]
      : null;
  const previousHref =
    previousSubmissionId && activeNavigation
      ? buildPassportDetailNavigationHref(previousSubmissionId, activeNavigation)
      : null;
  const nextHref =
    nextSubmissionId && activeNavigation
      ? buildPassportDetailNavigationHref(nextSubmissionId, activeNavigation)
      : null;

  useEffect(() => {
    const handleArrowNavigation = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented
        || event.altKey
        || event.ctrlKey
        || event.metaKey
        || event.shiftKey
        || cropEditor
        || isPassportNavigationKeyboardTarget(event.target)
      ) {
        return;
      }
      const destination = event.key === "ArrowLeft"
        ? previousHref
        : event.key === "ArrowRight"
          ? nextHref
          : null;
      if (!destination) return;
      event.preventDefault();
      router.push(destination as never);
    };
    window.addEventListener("keydown", handleArrowNavigation);
    return () => window.removeEventListener("keydown", handleArrowNavigation);
  }, [cropEditor, nextHref, previousHref, router]);

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
    if (reextractMutation.isPending || reextractInFlightRef.current) return;
    reextractInFlightRef.current = true;
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
    } finally {
      reextractInFlightRef.current = false;
    }
  };

  const handleManualImageChange = async (
    imageType: PassportImageType,
    file: File,
  ) => {
    if (changingImageType) return;
    const validationError = validatePassportLibraryImage(file);
    if (validationError) {
      setImageChangeErrors((current) => ({
        ...current,
        [imageType]: validationError,
      }));
      return;
    }
    setChangingImageType(imageType);
    setImageChangeErrors((current) => {
      const next = { ...current };
      delete next[imageType];
      return next;
    });
    try {
      const metadata = await passportsApi.getImageCrop(data.id, imageType);
      await passportsApi.uploadImageLibraryImage(
        data.id,
        imageType,
        file,
        metadata.revision,
      );
      setImageRevision((current) => current + 1);
      await refetch();
    } catch (uploadError) {
      setImageChangeErrors((current) => ({
        ...current,
        [imageType]: readManualImageChangeError(uploadError),
      }));
    } finally {
      setChangingImageType(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title={data.client_name}
          description="Submission details, extraction output, and current processing state."
        />
        <div className="flex flex-wrap items-center gap-2">
          {activeNavigation && navigationIndex >= 0 && (
            <div
              className="flex items-center gap-1 rounded-xl border border-slate-200 bg-white p-1"
              role="group"
              aria-label="Passport profile navigation"
            >
              {previousHref ? (
                <Link
                  href={previousHref as never}
                  aria-label="Previous passport"
                  className={buttonVariants({ variant: "ghost", size: "icon" })}
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                </Link>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled
                  aria-label="No previous passport"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
              )}
              <span className="min-w-20 px-1 text-center text-xs font-medium text-slate-600">
                {navigationIndex + 1} of {orderedSubmissionIds.length}
              </span>
              {nextHref ? (
                <Link
                  href={nextHref as never}
                  aria-label="Next passport"
                  className={buttonVariants({ variant: "ghost", size: "icon" })}
                >
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled
                  aria-label="No next passport"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}
          <Link
            href={(
              activeNavigation
                ? buildPassportGroupHref(
                  data.group_id,
                  activeNavigation.viewState,
                  activeNavigation.includeDeleted,
                )
                : ROUTES.dashboard.passportGroup(data.group_id)
            ) as never}
            className={cn(buttonVariants({ variant: "outline" }), "gap-2")}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to Passports
          </Link>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="overflow-hidden rounded-3xl">
          <CardContent className="space-y-5 p-4">
            <PassportImagePreview
              label="Visa Photo"
              imageType="visa_photo"
              url={data.passport_photo_url}
              clientName={data.client_name}
              revision={imageRevision}
              canCrop={canCropPassportImages}
              canChange={canCropPassportImages && Boolean(data.passport_photo_url)}
              changeDisabled={changingImageType !== null}
              isChanging={changingImageType === "visa_photo"}
              changeError={imageChangeErrors.visa_photo}
              onChange={(file) => void handleManualImageChange("visa_photo", file)}
              onCrop={(returnFocusTarget) => setCropEditor({ imageType: "visa_photo", label: "Visa Photo", returnFocusTarget })}
            />
            <PassportImagePreview
              label="Passport front"
              imageType="passport_front"
              url={data.image_url}
              clientName={data.client_name}
              revision={imageRevision}
              canCrop={canCropPassportImages}
              canChange={canCropPassportImages && Boolean(data.image_url)}
              changeDisabled={changingImageType !== null}
              isChanging={changingImageType === "passport_front"}
              changeError={imageChangeErrors.passport_front}
              onChange={(file) => void handleManualImageChange("passport_front", file)}
              onCrop={(returnFocusTarget) => setCropEditor({ imageType: "passport_front", label: "Passport front", returnFocusTarget })}
            />
            <PassportImagePreview
              label="Passport back"
              imageType="passport_back"
              url={data.passport_back_url}
              clientName={data.client_name}
              revision={imageRevision}
              canCrop={canCropPassportImages}
              canChange={canCropPassportImages && Boolean(data.passport_back_url)}
              changeDisabled={changingImageType !== null}
              isChanging={changingImageType === "passport_back"}
              changeError={imageChangeErrors.passport_back}
              onChange={(file) => void handleManualImageChange("passport_back", file)}
              onCrop={(returnFocusTarget) => setCropEditor({ imageType: "passport_back", label: "Passport back", returnFocusTarget })}
            />
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
            isSaving={confirmMutation.isPending || staffApproveMutation.isPending}
            canRetryAiVerification={canRetryPassportAiVerification(data)}
            isRetryingAiVerification={retryAiVerificationMutation.isPending}
            canReextract={needsReextraction(data)}
            isReextracting={reextractMutation.isPending}
            reextractFeedback={reextractFeedback}
            approvalFeedback={approvalFeedback}
            formError={formError}
            onFormError={setFormError}
            onConfirm={(fields) => confirmMutation.mutateAsync(fields)}
            onStaffApprove={async (fields, reviewReason) => {
              setApprovalFeedback(null);
              const result = await staffApproveMutation.mutateAsync(
                buildStaffApprovalRequest(
                  fields,
                  data.extraction_revision,
                  reviewReason,
                ),
              );
              setApprovalFeedback(
                getStaffApprovalOutcomeFeedback(result.outcome),
              );
              return result;
            }}
            onRetryAiVerification={() => retryAiVerificationMutation.mutateAsync()}
            reviewerLabel={getPassportReviewerLabel(data, currentUser)}
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
      {cropEditor && canCropPassportImages && (
        <PassportImageCropEditor
          submissionId={data.id}
          imageType={cropEditor.imageType}
          label={cropEditor.label}
          returnFocusTarget={cropEditor.returnFocusTarget}
          onClose={() => setCropEditor(null)}
          onSaved={() => {
            setImageRevision((current) => current + 1);
            void refetch();
          }}
        />
      )}
    </div>
  );
}

function PassportImagePreview({
  label,
  imageType,
  url,
  clientName,
  revision,
  canCrop,
  canChange,
  changeDisabled,
  isChanging,
  changeError,
  onChange,
  onCrop,
}: {
  label: string;
  imageType: PassportImageType;
  url?: string | null;
  clientName: string;
  revision: number;
  canCrop: boolean;
  canChange: boolean;
  changeDisabled: boolean;
  isChanging: boolean;
  changeError?: string;
  onChange: (file: File) => void;
  onCrop: (trigger: HTMLButtonElement) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const effectiveUrl = url ? appendCacheRevision(url, revision) : null;
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-700">{label}</h3>
        {(effectiveUrl || canChange) && (
          <div className="flex items-center gap-2">
            {effectiveUrl && (
              <a
                href={effectiveUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <ExternalLink className="h-3.5 w-3.5" /> Open
              </a>
            )}
            {canChange && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={PASSPORT_LIBRARY_IMAGE_ACCEPT}
                  aria-label={`Choose a replacement ${label} image`}
                  className="sr-only"
                  disabled={changeDisabled}
                  onChange={(event) => {
                    const selected = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (selected) onChange(selected);
                  }}
                />
                <button
                  type="button"
                  disabled={changeDisabled}
                  aria-busy={isChanging}
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-blue-700 shadow-sm hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isChanging ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : (
                    <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {isChanging ? "Changing…" : "Change"}
                </button>
              </>
            )}
            {effectiveUrl && canCrop && (
              <button
                type="button"
                onClick={(event) => onCrop(event.currentTarget)}
                data-image-type={imageType}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-blue-700 shadow-sm hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <Pencil className="h-3.5 w-3.5" /> Edit
              </button>
            )}
          </div>
        )}
      </div>
      {changeError && (
        <p role="alert" className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {changeError}
        </p>
      )}
      {effectiveUrl ? (
        <a
          href={effectiveUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${label} for ${clientName} in a new tab`}
          className="relative block aspect-[4/3] min-h-[15rem] overflow-hidden rounded-xl bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          <Image src={effectiveUrl} alt={`${label} for ${clientName}`} fill unoptimized className="object-contain" />
        </a>
      ) : (
        <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 text-sm text-slate-400">
          Not uploaded
        </div>
      )}
    </section>
  );
}

function readManualImageChangeError(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    if ("response" in error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return "Could not change this image. Please try again.";
}

function ClientProvidedFieldsCard({ passport }: { passport: PassportSubmission }) {
  const fields = passport.confirmed_fields ?? passport.extracted_fields ?? {};
  const values: Array<[string, string | null | undefined]> = [
    ["Email entered by client", passport.client_email],
    ["Phone entered by client", passport.client_phone],
    [
      "Agency/Dealership Name",
      getStringField(fields, "agency_dealership_name")
        || getStringField(passport.staff_metadata ?? {}, "agency_dealership_name"),
    ],
    ["Nearest International Airport", passport.departure_city],
    ["Nearest Domestic Airport", passport.nearest_domestic_airport],
    ["Base City", getStringField(fields, "base_city")],
    ["Staff Code", prefixedStaffCode(getStringField(fields, "staff_code"))],
    ["Agent/Employee Code", prefixedAgentEmployeeCode(fields)],
    ["Meal Preference", getStringField(fields, "meal_preference")],
    ...(passport.custom_answers ?? []).map(
      (answer): [string, string] => [answer.label, answer.value],
    ),
  ];
  const visibleValues = values.filter(
    (item): item is [string, string] => Boolean(item[1]),
  );

  if (visibleValues.length === 0) return null;

  return (
    <Card className="rounded-3xl">
      <CardContent className="p-5">
        <h3 className="font-semibold text-slate-900">Client-provided group details</h3>
        <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2">
          {visibleValues.map(([label, value]) => <MetaItem key={label} label={label} value={value} />)}
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
  canRetryAiVerification: boolean;
  isRetryingAiVerification: boolean;
  canReextract: boolean;
  isReextracting: boolean;
  reextractFeedback: ReextractFeedback | null;
  approvalFeedback: StaffApprovalFeedback | null;
  formError: string | null;
  onFormError: (error: string | null) => void;
  onConfirm: (fields: Record<string, string>) => Promise<unknown>;
  onStaffApprove: (
    fields: Record<string, string>,
    reviewReason?: string,
  ) => Promise<StaffApprovalResult>;
  onRetryAiVerification: () => Promise<unknown>;
  reviewerLabel: string | null;
  onReextract: () => void;
}

function appendCacheRevision(url: string, revision: number) {
  if (revision === 0) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}ui_crop_revision=${revision}`;
}

function ReviewFieldsCard({
  passport,
  sourceFields,
  validation,
  conflicts,
  isSaving,
  canRetryAiVerification,
  isRetryingAiVerification,
  canReextract,
  isReextracting,
  reextractFeedback,
  approvalFeedback,
  formError,
  onFormError,
  onConfirm,
  onStaffApprove,
  onRetryAiVerification,
  reviewerLabel,
  onReextract,
}: ReviewFieldsCardProps) {
  const initialFields = useMemo(
    () =>
      REVIEW_FIELDS.reduce<Record<string, string>>((fields, key) => {
        fields[key] = getPassportTextField(sourceFields, key);
        return fields;
      }, {}),
    [sourceFields],
  );
  const [reviewFields, setReviewFields] = useState<Record<string, string>>(initialFields);
  const [reviewReason, setReviewReason] = useState("");
  const reviewActionInFlightRef = useRef(false);
  const verificationRetryInFlightRef = useRef(false);

  const handleFieldChange = (key: string, value: string) => {
    setReviewFields((current) => ({ ...current, [key]: value }));
  };

  const handleConfirm = async () => {
    if (isSaving || reviewActionInFlightRef.current) return;
    const cleanedFields = cleanPassportReviewFields(reviewFields);

    if (Object.keys(cleanedFields).length === 0) {
      onFormError("Add at least one reviewed field before confirming.");
      return;
    }
    if (!hasValidReviewDates(cleanedFields)) {
      onFormError("Enter valid passport dates in DD/MM/YYYY format. Check that birth, issue, and expiry are chronological and no entered birth or issue date is in the future.");
      return;
    }

    onFormError(null);
    reviewActionInFlightRef.current = true;
    try {
      if (passport.status === "needs_review") {
        await onStaffApprove(cleanedFields, reviewReason.trim() || undefined);
      } else {
        await onConfirm(cleanedFields);
      }
    } catch (error) {
      onFormError(
        passport.status === "needs_review"
          ? getStaffApprovalErrorFeedback(error).message
          : readReviewActionError(
            error,
            "Could not save the reviewed passport fields. Please try again.",
          ),
      );
    } finally {
      reviewActionInFlightRef.current = false;
    }
  };

  const actionState = getPassportReviewActionState(passport.status, isSaving);
  const workflowStatusMessage = getWorkflowStatusMessage(passport.status);
  const verificationIsStale = (
    passport.post_submission_verification?.stale_after_staff_edit === true
  );
  const currentVerification = verificationIsStale
    ? null
    : passport.post_submission_verification;
  const handleRetryAiVerification = async () => {
    if (
      isRetryingAiVerification
      || verificationRetryInFlightRef.current
    ) return;
    verificationRetryInFlightRef.current = true;
    onFormError(null);
    try {
      await onRetryAiVerification();
    } catch (error) {
      onFormError(readReviewActionError(
        error,
        "Could not retry AI verification. The existing review remains unchanged.",
      ));
    } finally {
      verificationRetryInFlightRef.current = false;
    }
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
            <MetaItem label="Submitted" value={formatDateTime(passport.created_at)} />
            <MetaItem label="Updated" value={formatDateTime(passport.updated_at)} />
            <MetaItem
              label="Expiry"
              value={formatPassportDateForUi(reviewFields.date_of_expiry) || "Not extracted"}
            />
            {passport.qualifier_enabled_snapshot && (
              <MetaItem
                label="Relation with Qualifier"
                value={passport.qualifier_is_self
                  ? "Self"
                  : passport.qualifier_relation_label || "Not selected"}
              />
            )}
            {currentVerification && (
              <>
                <MetaItem
                  label="AI decision"
                  value={
                    PASSPORT_STATUS_LABELS[
                      currentVerification.verification_status
                    ] || currentVerification.verification_status
                  }
                />
                <MetaItem
                  label="Verification confidence"
                  value={formatConfidence(
                    getPassportVerificationConfidence(currentVerification),
                  )}
                />
              </>
            )}
            {!verificationIsStale && passport.post_submission_verified_at && (
              <MetaItem
                label="AI verification completed"
                value={formatDateTime(passport.post_submission_verified_at)}
              />
            )}
            {reviewerLabel && (
              <MetaItem label="Reviewed by" value={reviewerLabel} />
            )}
            {passport.verification_reviewed_at && (
              <MetaItem
                label="Staff reviewed"
                value={formatDateTime(passport.verification_reviewed_at)}
              />
            )}
          </div>
          {verificationIsStale && (
            <div
              className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900"
              role="status"
              aria-live="polite"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>
                Passport details changed. The previous AI verification is no longer
                valid. Review the current fields and approve this passport again.
              </p>
            </div>
          )}
          {workflowStatusMessage && (
            <p className="text-sm leading-6 text-blue-700" role="status" aria-live="polite">
              {workflowStatusMessage}
            </p>
          )}
          {approvalFeedback && (
            <div
              className={
                approvalFeedback.kind === "success"
                  ? "rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
                  : "rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800"
              }
              role="status"
              aria-live="polite"
            >
              {approvalFeedback.message}
            </div>
          )}
          {currentVerification?.explanation && (
            <p className="text-sm leading-6 text-slate-600">
              {currentVerification.explanation}
            </p>
          )}
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
            const isCountry = key === "nationality";
            const fieldReview = getPassportFieldReview(passport, validation, key);
            const fieldClassName = getPassportFieldReviewClassName(fieldReview?.verdict);
            return (
              <div key={key} className="space-y-1.5">
                <span className="flex flex-wrap items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                  <span>{toLabel(key)}</span>
                  {fieldReview && (
                    <span className={fieldReview.verdict === "incorrect"
                      ? "rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-800"
                      : "rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800"}
                    >
                      {fieldReview.label}
                    </span>
                  )}
                </span>
                {isCountry ? (
                  <PassportCountryTextField
                    key={`${key}:${reviewFields[key] ?? ""}`}
                    value={reviewFields[key] ?? ""}
                    onChange={(value) => handleFieldChange(key, value)}
                    className={fieldClassName}
                    ariaLabel={toLabel(key)}
                  />
                ) : isDate ? (
                  <PassportDateInput
                    value={reviewFields[key] ?? ""}
                    onValueChange={(value) => handleFieldChange(key, value)}
                    minIso="1900-01-01"
                    maxIso={key === "date_of_birth" ? yesterdayIsoDate() : key === "date_of_issue" ? todayIsoDate() : "2200-12-31"}
                    aria-label={toLabel(key)}
                    className={`h-10 rounded-lg ${fieldClassName}`}
                  />
                ) : (
                  <Input
                    type="text"
                    value={reviewFields[key] ?? ""}
                    onChange={(event) => handleFieldChange(key, event.target.value)}
                    placeholder="Not extracted"
                    aria-label={toLabel(key)}
                    className={`h-10 rounded-lg ${fieldClassName}`}
                  />
                )}
                {fieldReview && (
                  <FieldReviewMessage
                    review={fieldReview}
                    editedValue={reviewFields[key] ?? ""}
                  />
                )}
              </div>
            );
          })}
        </div>

        {passport.status === "needs_review" && (
          <label className="block text-sm font-medium text-slate-700">
            Review reason <span className="font-normal text-slate-400">(optional)</span>
            <textarea
              className="mt-1.5 min-h-20 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
              value={reviewReason}
              maxLength={240}
              disabled={isSaving}
              onChange={(event) => setReviewReason(event.target.value)}
              placeholder="Briefly describe why manual approval was required. Do not enter passport values."
            />
            <span className="mt-1 block text-xs font-normal text-slate-400">
              {reviewReason.length}/240 characters
            </span>
          </label>
        )}

        {formError && (
          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {formError}
          </div>
        )}

        {(canReextract || passport.extraction_status === "processing") && (
          <Button
            variant="secondary"
            className="w-full gap-2"
            disabled={
              isReextracting
              || passport.extraction_status === "processing"
              || isSaving
              || isRetryingAiVerification
            }
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

        {canRetryAiVerification && (
          <Button
            type="button"
            variant="secondary"
            className="w-full gap-2"
            disabled={isRetryingAiVerification || isSaving || isReextracting}
            onClick={() => void handleRetryAiVerification()}
            aria-busy={isRetryingAiVerification}
          >
            {isRetryingAiVerification ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            )}
            {isRetryingAiVerification
              ? "Starting AI verification"
              : "Retry AI Verification"}
          </Button>
        )}

        <Button
          onClick={() => void handleConfirm()}
          disabled={
            actionState.disabled
            || isRetryingAiVerification
            || isReextracting
          }
          className="w-full gap-2 bg-blue-600 text-white hover:bg-blue-700"
          aria-busy={isSaving}
        >
          {isSaving ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : passport.status === "staff_approved" || passport.status === "ai_approved" ? (
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4" aria-hidden="true" />
          )}
          {actionState.label}
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

function FieldReviewMessage({
  review,
  editedValue,
}: {
  review: PassportFieldReview;
  editedValue: string;
}) {
  const observedValue = review.observed_value?.trim() ?? "";
  const showObservedValue = Boolean(observedValue) && !valuesMatch(observedValue, editedValue);
  const messageClass = review.verdict === "incorrect" ? "text-red-700" : "text-amber-700";
  const reason = formatPassportVerificationReason(review.reason_code);
  const confidence = formatPassportFieldReviewConfidence(review);

  return (
    <p className={`text-xs leading-5 ${messageClass}`}>
      {reason}
      {showObservedValue && (
        <>
          {" "}AI observed <span className="font-semibold">{formatConflictValue(review.field, observedValue)}</span>.
        </>
      )}
      {confidence && <> {confidence}.</>}
    </p>
  );
}

function PassportCountryTextField({
  value,
  onChange,
  className,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  ariaLabel: string;
}) {
  const formattedValue = formatPassportNationality(value) || value;
  const [draftValue, setDraftValue] = useState(formattedValue);
  const [isDirty, setIsDirty] = useState(false);

  return (
    <Input
      type="text"
      value={draftValue}
      onChange={(event) => {
        setDraftValue(event.target.value);
        setIsDirty(true);
      }}
      onBlur={() => {
        if (!isDirty) return;
        onChange(draftValue);
        setIsDirty(false);
      }}
      placeholder="Not extracted"
      aria-label={ariaLabel}
      className={`h-10 rounded-lg ${className ?? "border-slate-200 bg-white"}`}
    />
  );
}

function readReviewActionError(error: unknown, fallback: string) {
  if (!error || typeof error !== "object") return fallback;
  const candidate = error as { message?: unknown };
  return typeof candidate.message === "string" && candidate.message.trim()
    ? candidate.message
    : fallback;
}

function getWorkflowStatusMessage(status: PassportSubmission["status"]) {
  const messages: Partial<Record<PassportSubmission["status"], string>> = {
    pending_extraction: "The passport is saved and queued for automatic extraction. This page refreshes automatically.",
    extracting: "AI is reading the saved passport. This page refreshes automatically until the fields are ready.",
    processing: "The saved passport is being processed. This page refreshes automatically.",
    ready_for_client_review: "Automatic extraction is complete and waiting for the client to review and submit the details.",
    submitted: "AI verification is running. This page refreshes automatically until a final decision is ready.",
  };
  return messages[status] ?? null;
}

function getStringField(fields: ExtractedPassportFields, key: string) {
  const value = fields[key];
  return typeof value === "string" ? value : "";
}

function prefixedStaffCode(value: string) {
  if (!value) return "";
  const normalized = value.trim();
  const prefixed = normalized.match(/^STF[_\-\s]+(.+)$/i);
  return prefixed ? `STF_${prefixed[1]}` : `STF_${normalized}`;
}

function prefixedAgentEmployeeCode(fields: ExtractedPassportFields) {
  const personType = getStringField(fields, "agent_employee_type").toLowerCase();
  const code = getStringField(fields, "agent_employee_code");
  if (!code) return "";
  if (personType === "agent") return `AGT_${code}`;
  if (personType === "employee") return `EMP_${code}`;
  return "";
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
  if (field === "nationality") {
    return formatPassportNationality(value) || value;
  }
  if (field === "date_of_birth" || field === "date_of_issue" || field === "date_of_expiry") {
    return formatPassportDateForUi(value) || value;
  }
  return value;
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 break-all text-sm font-medium text-slate-800">{value}</div>
    </div>
  );
}

function toLabel(value: string) {
  if (value === "given_names") return "Name";
  if (value === "place_of_issue") return "Place of Issue";
  if (value === "issuing_country") return "Issuing Country (legacy)";
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
  const today = todayIsoDate();
  return previousPassportIsoDate(today) ?? today;
}
