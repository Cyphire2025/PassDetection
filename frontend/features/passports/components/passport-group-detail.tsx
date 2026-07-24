"use client";

import { Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, CalendarDays, ChevronDown, Download, Eye, FileText, Loader2, MoreVertical, Pencil, RotateCcw, Search, Trash2, UploadCloud, X } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, ConfirmDialog, Input, Skeleton } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import { formatPassportDateForUi } from "@/lib/utils/passport-date";
import {
  formatPassportCountry,
  formatPassportNationality,
} from "@/lib/utils/passport-country";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { useUpdateUploadLink, useUploadLinks } from "../hooks/use-upload-links";
import {
  useExportPassportGroup,
  useExportPassportGroupImages,
  useExportSelectedPassports,
  useBulkDeletePassportSubmissions,
  useGroupSubmissionsView,
  useImportPassportGroup,
  usePassportGroups,
  useReextractPassportSubmission,
  usePreviewPassportDocuments,
  useSavePassportDocuments,
} from "../hooks/use-passports";
import type {
  PassportDocumentImportPreview,
  PassportGroupExportKind,
  PassportGroupSubmissionFilter,
  PassportGroupSubmissionSort,
  PassportImageType,
} from "../api/passports.api";
import { canEditPassportImages } from "../utils/passport-image-crop-permissions";
import {
  acquireDocumentThumbnailSlot,
  documentThumbnailUrl,
} from "../services/document-thumbnail-scheduler";
import { GroupWhatsAppBroadcastPanel } from "./group-whatsapp-broadcast-panel";
import { GroupDocumentDeliveryPanel } from "./group-document-delivery-panel";
import { GroupOptionToggle } from "./group-option-toggle";
import { PassportImageCropEditor } from "./passport-image-crop-editor";
import { PassportExportDialog } from "./passport-export-dialog";

interface PassportGroupDetailProps {
  groupId: string;
}

export function PassportGroupDetail({ groupId }: PassportGroupDetailProps) {
  const searchParams = useSearchParams();
  const includeDeleted = searchParams.get("old_data") === "1";
  const role = useAuthStore(selectUserRole);
  const canPermanentlyDelete = role === "super_admin" || role === "agency_admin";
  const canEditImages = canEditPassportImages(role);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedPassports, setSelectedPassports] = useState<string[]>([]);
  const [submissionFilter, setSubmissionFilter] = useState<PassportGroupSubmissionFilter>("all");
  const [sortBy, setSortBy] = useState<PassportGroupSubmissionSort>("name");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [viewMode, setViewMode] = useState<"table" | "docs">("table");
  const [imageRevision, setImageRevision] = useState(0);
  const [imageEditor, setImageEditor] = useState<{
    submissionId: string;
    imageType: PassportImageType;
    label: string;
    returnFocusTarget: HTMLButtonElement;
  } | null>(null);
  const [isExpiryAlertsExpanded, setIsExpiryAlertsExpanded] = useState(true);
  const expiryAlertsRegionId = useId();
  const {
    data: submissionsView,
    isLoading,
    error,
    isFetching,
    refetch: refetchSubmissions,
  } = useGroupSubmissionsView(groupId, {
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    include_deleted: includeDeleted,
    submission_filter: submissionFilter,
    sort_by: sortBy,
    sort_order: sortOrder,
    page,
    page_size: pageSize,
  });
  const data = submissionsView?.items;
  const { data: groups = [] } = usePassportGroups();
  const { data: deletedGroups = [] } = useUploadLinks("deleted", includeDeleted);
  const deletedGroup = deletedGroups.find((item) => item.id === groupId);
  const group = groups.find((item) => item.group_id === groupId);
  const groupDetails = group ?? (deletedGroup ? {
    group_id: deletedGroup.id,
    group_name: deletedGroup.name,
    group_status: deletedGroup.status,
    total_passports: deletedGroup.deleted_passport_count,
    pending_review_count: 0,
    confirmed_count: 0,
    failed_count: 0,
    latest_submission_at: deletedGroup.deleted_at ?? deletedGroup.created_at,
    destination: deletedGroup.destination,
    travel_date: deletedGroup.travel_date,
    return_date: deletedGroup.return_date,
    package_name: deletedGroup.package_name,
    departure_cities: deletedGroup.departure_cities ?? [],
    base_city_enabled: deletedGroup.base_city_enabled,
    nearest_international_airport_enabled: deletedGroup.nearest_international_airport_enabled,
    staff_code_enabled: deletedGroup.staff_code_enabled,
    agent_employee_code_enabled: deletedGroup.agent_employee_code_enabled,
    meal_preference_enabled: deletedGroup.meal_preference_enabled,
    require_selfie: deletedGroup.require_selfie,
    allow_files_from_device: deletedGroup.allow_files_from_device ?? true,
    ask_nearest_domestic_airport: deletedGroup.ask_nearest_domestic_airport ?? false,
    relation_with_qualifier_enabled:
      deletedGroup.relation_with_qualifier_enabled ?? false,
    notes: deletedGroup.notes,
  } : undefined);
  const exportMutation = useExportPassportGroup();
  const exportImagesMutation = useExportPassportGroupImages();
  const importMutation = useImportPassportGroup(groupId);
  const passportPreviewMutation = usePreviewPassportDocuments(groupId);
  const passportSaveMutation = useSavePassportDocuments(groupId);
  const exportSelected = useExportSelectedPassports();
  const bulkDelete = useBulkDeletePassportSubmissions(groupId);
  const updateGroup = useUpdateUploadLink();
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const passportImportInputRef = useRef<HTMLInputElement | null>(null);
  const actionsMenuRef = useRef<HTMLDivElement | null>(null);
  const [isActionsMenuOpen, setIsActionsMenuOpen] = useState(false);
  const [exportDialogKind, setExportDialogKind] =
    useState<PassportGroupExportKind | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [bulkDeleteFeedback, setBulkDeleteFeedback] = useState<{
    tone: "success" | "warning" | "error";
    message: string;
  } | null>(null);
  const [isBulkDeleteConfirmationOpen, setIsBulkDeleteConfirmationOpen] = useState(false);
  const [passportImportFiles, setPassportImportFiles] = useState<File[]>([]);
  const [passportImportPreview, setPassportImportPreview] = useState<PassportDocumentImportPreview | null>(null);
  const [passportImportProgress, setPassportImportProgress] = useState<{ processed: number; total: number; label: string } | null>(null);
  const [isEditingTrip, setIsEditingTrip] = useState(false);
  const [tripForm, setTripForm] = useState({
    name: "",
    destination: "",
    travel_date: "",
    return_date: "",
    departure_cities: [] as string[],
    base_city_enabled: false,
    nearest_international_airport_enabled: false,
    staff_code_enabled: false,
    agent_employee_code_enabled: false,
    meal_preference_enabled: false,
    require_selfie: false,
    allow_files_from_device: true,
    ask_nearest_domestic_airport: false,
    relation_with_qualifier_enabled: false,
    notes: "",
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!submissionsView || page <= submissionsView.total_pages) return;
    const timer = window.setTimeout(() => {
      setPage(Math.max(1, submissionsView.total_pages));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [page, submissionsView]);

  useEffect(() => {
    if (!isActionsMenuOpen) return;

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!actionsMenuRef.current?.contains(event.target as Node)) {
        setIsActionsMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsActionsMenuOpen(false);
    };

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isActionsMenuOpen]);

  const expiryAlerts = useMemo(() => {
    return submissionsView?.expiry_alerts ?? [];
  }, [submissionsView?.expiry_alerts]);

  const filteredPassports = data ?? [];

  const togglePassport = (passportId: string) => {
    setSelectedPassports((current) =>
      current.includes(passportId) ? current.filter((id) => id !== passportId) : [...current, passportId],
    );
  };

  const handlePassportImportFiles = (files: File[]) => {
    setImportMessage(null);
    setPassportImportPreview(null);
    setPassportImportFiles(files);
    setPassportImportProgress({
      processed: 0,
      total: files.reduce((sum, file) => sum + file.size, 0),
      label: "Uploading files for document check",
    });
    passportPreviewMutation.mutate({
      files,
      onProgress: (progress) => {
        setPassportImportProgress({
          processed: progress.loaded,
          total: progress.total,
          label: progress.phase === "uploading"
            ? "Uploading files for document check"
            : "Checking documents against the full group",
        });
      },
    }, {
      onSuccess: (preview) => {
        setPassportImportPreview(preview);
        setPassportImportProgress(null);
      },
      onError: (previewError) => {
        setPassportImportFiles([]);
        setPassportImportProgress(null);
        setImportMessage(
          previewError instanceof Error
            ? previewError.message
            : "Passport document check failed",
        );
      },
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Group Submissions"
          description="Review the passport submissions uploaded through this group link."
        />
        <div className="flex items-center gap-2">
          <input
            ref={importInputRef}
            type="file"
            accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              setImportMessage(null);
              importMutation.mutate(file, {
                onSuccess: (result) => {
                  setSelectedPassports([]);
                  setImportMessage(
                    `Imported ${result.imported_count} new, updated ${result.updated_count}, skipped ${result.skipped_count} duplicate row${result.skipped_count === 1 ? "" : "s"}.`,
                  );
                },
                onError: (error) => {
                  const message = error instanceof Error ? error.message : "Import failed";
                  setImportMessage(message);
                },
              });
            }}
          />
          <input
            ref={passportImportInputRef}
            type="file"
            multiple
            accept=".zip,image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (!files.length) return;
              void handlePassportImportFiles(files);
            }}
          />
          {exportImagesMutation.isPending && (
            <div
              role="status"
              aria-live="polite"
              className="flex shrink-0 items-center gap-2 text-sm font-medium text-slate-600"
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              <span>Downloading passport images</span>
            </div>
          )}
          <Link href={ROUTES.dashboard.passports}>
            <Button variant="outline" className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to Groups
            </Button>
          </Link>
          <div ref={actionsMenuRef} className="relative">
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Open group actions"
              aria-haspopup="menu"
              aria-expanded={isActionsMenuOpen}
              onClick={() => setIsActionsMenuOpen((open) => !open)}
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
            {isActionsMenuOpen && (
              <div
                role="menu"
                className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl"
              >
                <button
                  type="button"
                  role="menuitem"
                  disabled={
                    exportImagesMutation.isPending
                    || (submissionsView?.group_total ?? 0) === 0
                  }
                  className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => {
                    setIsActionsMenuOpen(false);
                    setImportMessage(null);
                    setExportDialogKind("passport_images");
                  }}
                >
                  <Download className="h-4 w-4 text-slate-500" />
                  {exportImagesMutation.isPending ? "Preparing Images" : "Download Passport Images"}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={importMutation.isPending}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => {
                    setIsActionsMenuOpen(false);
                    importInputRef.current?.click();
                  }}
                >
                  <UploadCloud className="h-4 w-4 text-slate-500" />
                  {importMutation.isPending ? "Importing" : "Import Excel"}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={passportPreviewMutation.isPending || passportSaveMutation.isPending}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => {
                    setIsActionsMenuOpen(false);
                    passportImportInputRef.current?.click();
                  }}
                >
                  <UploadCloud className="h-4 w-4 text-slate-500" />
                  {passportPreviewMutation.isPending ? "Checking documents" : "Import Passports"}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={
                    exportMutation.isPending
                    || (submissionsView?.group_total ?? 0) === 0
                  }
                  className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => {
                    setIsActionsMenuOpen(false);
                    setImportMessage(null);
                    setExportDialogKind("passport_excel");
                  }}
                >
                  <Download className="h-4 w-4 text-slate-500" />
                  {exportMutation.isPending ? "Exporting" : "Export Excel"}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {groupDetails && (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                  <CalendarDays className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Destination / Trip Details</h2>
                  <p className="text-sm text-slate-500">Used for search, filters, and exports.</p>
                </div>
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  setTripForm({
                    name: groupDetails.group_name,
                    destination: groupDetails.destination ?? "",
                    travel_date: groupDetails.travel_date ?? "",
                    return_date: groupDetails.return_date ?? "",
                    departure_cities: groupDetails.departure_cities ?? [],
                    base_city_enabled: groupDetails.base_city_enabled,
                    nearest_international_airport_enabled: groupDetails.nearest_international_airport_enabled,
                    staff_code_enabled: groupDetails.staff_code_enabled,
                    agent_employee_code_enabled: groupDetails.agent_employee_code_enabled,
                    meal_preference_enabled: groupDetails.meal_preference_enabled,
                    require_selfie: groupDetails.require_selfie,
                    allow_files_from_device: groupDetails.allow_files_from_device ?? true,
                    ask_nearest_domestic_airport: groupDetails.ask_nearest_domestic_airport ?? false,
                    relation_with_qualifier_enabled:
                      groupDetails.relation_with_qualifier_enabled ?? false,
                    notes: groupDetails.notes ?? "",
                  });
                  setIsEditingTrip(true);
                }}
              >
                <Pencil className="h-4 w-4" />
                Edit
              </Button>
            </div>
            <div className="grid gap-3 text-sm sm:grid-cols-3">
              <InfoPair label="Destination" value={groupDetails.destination || "Not set"} />
              <InfoPair label="Travel/Departure Date" value={groupDetails.travel_date || "Not set"} />
              <InfoPair label="Return Date" value={groupDetails.return_date || "Not set"} />
              <InfoPair label="Base City" value={groupDetails.base_city_enabled ? "Required" : "Disabled"} />
              <InfoPair label="Nearest International Airport" value={groupDetails.nearest_international_airport_enabled ? ((groupDetails.departure_cities ?? []).join(", ") || "Not configured") : "Disabled"} />
              <InfoPair label="Staff Code" value={groupDetails.staff_code_enabled ? "Required" : "Disabled"} />
              <InfoPair label="Agent/Employee Code" value={groupDetails.agent_employee_code_enabled ? "Required" : "Disabled"} />
              <InfoPair label="Meal Preference" value={groupDetails.meal_preference_enabled ? "Required" : "Disabled"} />
              <InfoPair label="Visa Photo Upload" value={groupDetails.require_selfie ? "Required" : "Disabled"} />
              <InfoPair label="Files From Device" value={(groupDetails.allow_files_from_device ?? true) ? "Allowed" : "Live scanner only"} />
              <InfoPair label="Nearest Domestic Airport" value={(groupDetails.ask_nearest_domestic_airport ?? false) ? "Required" : "Disabled"} />
              <InfoPair
                label="Relation with Qualifier"
                value={(groupDetails.relation_with_qualifier_enabled ?? false) ? "Enabled" : "Disabled"}
              />
              <div className="sm:col-span-2">
                <InfoPair label="Notes" value={groupDetails.notes || "No notes"} />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {!includeDeleted && (
        <>
          {canAccessWhatsApp && (
            <GroupWhatsAppBroadcastPanel groupId={groupId} />
          )}
          <GroupDocumentDeliveryPanel groupId={groupId} />
        </>
      )}

      {importMessage && (
        <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          {importMessage}
        </div>
      )}

      {bulkDeleteFeedback && (
        <div
          role={bulkDeleteFeedback.tone === "error" ? "alert" : "status"}
          className={
            bulkDeleteFeedback.tone === "error"
              ? "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              : bulkDeleteFeedback.tone === "warning"
                ? "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
                : "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
          }
        >
          {bulkDeleteFeedback.message}
        </div>
      )}

      {passportImportProgress && (
        <PassportDocumentImportProgress
          processed={passportImportProgress.processed}
          total={passportImportProgress.total}
          label={passportImportProgress.label}
        />
      )}

      {passportImportPreview && (
        <PassportDocumentImportDialog
          preview={passportImportPreview}
          files={passportImportFiles}
          saving={passportSaveMutation.isPending}
          onClose={() => {
            if (!passportSaveMutation.isPending) setPassportImportPreview(null);
          }}
          onSave={() => {
            passportSaveMutation.mutate({
              files: passportImportFiles,
              onProgress: (progress) => {
                setPassportImportProgress({
                  processed: progress.loaded,
                  total: progress.total,
                  label: progress.phase === "uploading" ? "Uploading accepted documents" : "Saving accepted documents",
                });
              },
            }, {
              onSuccess: (result) => {
                setImportMessage(`Saved ${result.saved_count} passport document${result.saved_count === 1 ? "" : "s"}. Rejected files were not stored.`);
                setPassportImportPreview(null);
                setPassportImportFiles([]);
                setPassportImportProgress(null);
              },
              onError: (error) => {
                setPassportImportProgress(null);
                setImportMessage(error instanceof Error ? error.message : "Could not save passport documents");
              },
            });
          }}
        />
      )}

      {expiryAlerts.length > 0 && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-0">
            <button
              type="button"
              aria-expanded={isExpiryAlertsExpanded}
              aria-controls={expiryAlertsRegionId}
              onClick={() => setIsExpiryAlertsExpanded((current) => !current)}
              className="flex w-full items-center justify-between gap-3 rounded-xl p-5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
            >
              <div className="flex items-center gap-3">
                <AlertTriangle className="h-5 w-5 text-red-700" aria-hidden="true" />
                <div>
                  <h2 className="text-base font-semibold text-red-950">Passport Expiry Alerts</h2>
                  <p className="text-sm text-red-800">
                    {groupDetails?.travel_date
                      ? `Expired passports, or passports expiring within 6 months of the Travel/Departure date (${formatPassportDateForUi(groupDetails.travel_date)}).`
                      : "Expired passports, or passports expiring within the next 6 months."}
                  </p>
                </div>
              </div>
              <span className="flex shrink-0 items-center gap-2">
                <Badge variant="destructive">{expiryAlerts.length}</Badge>
                <ChevronDown
                  className={`h-4 w-4 text-red-800 transition-transform ${
                    isExpiryAlertsExpanded ? "rotate-180" : ""
                  }`}
                  aria-hidden="true"
                />
              </span>
            </button>
            {isExpiryAlertsExpanded && (
              <div
                id={expiryAlertsRegionId}
                className="grid gap-3 border-t border-red-200 px-5 pb-5 pt-4 md:grid-cols-2"
              >
                {expiryAlerts.map((passport) => (
                  <Link
                    key={passport.submission_id}
                    href={ROUTES.dashboard.passportDetail(passport.submission_id) as never}
                    className="rounded-lg border border-red-200 bg-white p-3 hover:bg-red-50"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-semibold text-slate-900">{passport.client_name}</div>
                        <div className="text-xs text-slate-500">
                          {passport.passport_number || "Passport number not extracted"}
                        </div>
                      </div>
                      <div className="text-right text-sm font-medium text-red-800">
                        {formatPassportDateForUi(
                          passport.date_of_expiry,
                        ) || "Expiry missing"}
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <Input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
          placeholder="Search name, email, phone, passport number"
          className="h-10 pl-9"
        />
        {isFetching && !isLoading && (
          <Loader2
            className="absolute right-3 top-3 h-4 w-4 animate-spin text-blue-600"
            aria-label="Updating submissions"
          />
        )}
      </div>

      <div className="flex flex-nowrap items-center gap-2 overflow-x-auto rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <label className="sr-only" htmlFor="group-submission-sort">Sort submissions by</label>
        <select
          id="group-submission-sort"
          value={sortBy}
          onChange={(event) => {
            setSortBy(event.target.value as PassportGroupSubmissionSort);
            setPage(1);
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="name">Sort by: Name</option>
          <option value="updated_at">Sort by: Updated</option>
          <option value="verification_confidence">Sort by: Verification confidence</option>
        </select>
        <label className="sr-only" htmlFor="group-submission-filter">Filter submissions</label>
        <select
          id="group-submission-filter"
          value={submissionFilter}
          onChange={(event) => {
            setSubmissionFilter(event.target.value as PassportGroupSubmissionFilter);
            setPage(1);
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All submissions</option>
          <option value="pending_ai">Pending AI Verification</option>
          <option value="ai_approved">AI Approved</option>
          <option value="needs_review">Needs Review</option>
          <option value="staff_approved">Staff Approved</option>
          <option value="duplicates">Duplicates</option>
        </select>
        <label className="sr-only" htmlFor="group-submission-sort-order">Sort direction</label>
        <select
          id="group-submission-sort-order"
          value={sortOrder}
          onChange={(event) => {
            setSortOrder(event.target.value as "asc" | "desc");
            setPage(1);
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
        {selectedPassports.length > 0 && (
          <>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="shrink-0 whitespace-nowrap"
              isLoading={exportSelected.isPending}
              onClick={() => exportSelected.mutate(selectedPassports)}
            >
              <Download className="h-4 w-4" />
              Export Selected ({selectedPassports.length})
            </Button>
            {canPermanentlyDelete && !includeDeleted && (
              <Button
                type="button"
                variant="danger"
                size="sm"
                className="shrink-0 whitespace-nowrap"
                disabled={bulkDelete.isPending}
                isLoading={bulkDelete.isPending}
                onClick={() => {
                  setBulkDeleteFeedback(null);
                  setIsBulkDeleteConfirmationOpen(true);
                }}
              >
                <Trash2 className="h-4 w-4" />
                Delete Selected ({selectedPassports.length})
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="shrink-0 whitespace-nowrap"
              onClick={() => setSelectedPassports([])}
            >
              Clear selection
            </Button>
          </>
        )}
        <Button
          type="button"
          variant={viewMode === "docs" ? "primary" : "secondary"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setViewMode((current) => current === "docs" ? "table" : "docs")}
        >
          {viewMode === "docs" ? "Table view" : "DOCS view"}
        </Button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load passport submissions for this group.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : error ? null : (submissionsView?.group_total ?? 0) === 0 ? (
        <EmptyState
          icon={<UploadCloud className="h-5 w-5" />}
          title="Drop passport here"
          description="Share this group link with clients or upload a passport through the client page. Submitted passports will appear here."
        />
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No passports match these filters"
          description="Adjust the search or submission filter to find more submissions."
          action={{
            label: "Reset Filters",
            onClick: () => {
              setSearch("");
              setDebouncedSearch("");
              setSubmissionFilter("all");
              setSortBy("name");
              setSortOrder("asc");
              setPage(1);
            },
          }}
        />
      ) : viewMode === "docs" ? (
        <PassportDocumentMatrix
          passports={filteredPassports}
          canEdit={canEditImages && !includeDeleted}
          revision={imageRevision}
          onEdit={(submissionId, imageType, label, returnFocusTarget) => {
            setImageEditor({ submissionId, imageType, label, returnFocusTarget });
          }}
        />
      ) : (
        <>
          <div className="grid gap-4 lg:hidden">
            {filteredPassports.map((passport, index) => (
              <Fragment key={passport.id}>
                {isDuplicateClusterStart(filteredPassports, index) && (
                  <DuplicateClusterHeader
                    passport={passport}
                    searchActive={Boolean(debouncedSearch)}
                  />
                )}
                <PassportMobileCard
                  passport={passport}
                  selected={selectedPassports.includes(passport.id)}
                  onToggle={() => togglePassport(passport.id)}
                />
              </Fragment>
            ))}
          </div>

          <Card className="hidden lg:block">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                      <th className="px-6 py-4">Client</th>
                      <th className="px-6 py-4">Status</th>
                      <th className="px-6 py-4">Passport</th>
                      <th className="px-6 py-4">Passport Dates</th>
                      <th className="px-6 py-4">Confidence</th>
                      <th className="px-6 py-4">Updated</th>
                      <th className="px-6 py-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filteredPassports.map((passport, index) => (
                      <Fragment key={passport.id}>
                        {isDuplicateClusterStart(filteredPassports, index) && (
                          <tr className="border-y border-amber-200 bg-amber-50">
                            <td colSpan={7} className="px-6 py-2">
                              <DuplicateClusterHeader
                                passport={passport}
                                searchActive={Boolean(debouncedSearch)}
                                compact
                              />
                            </td>
                          </tr>
                        )}
                        <tr
                          className={`cursor-pointer hover:bg-slate-50/60 ${
                            isDuplicatePassport(passport) ? "bg-amber-50/30" : ""
                          }`}
                          onClick={() => togglePassport(passport.id)}
                        >
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={selectedPassports.includes(passport.id)}
                              onChange={() => togglePassport(passport.id)}
                              onClick={(event) => event.stopPropagation()}
                              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            />
                            <div className="min-w-0">
                              <div className="font-semibold text-slate-900">{passport.client_name}</div>
                              <div className="mt-1 break-all text-xs text-slate-500">{passport.client_email ?? "No email provided"}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={passport.status} />
                        </td>
                        <td className="px-6 py-4">
                          <div className="font-medium text-slate-800">{getStringField(getDashboardFields(passport), "passport_number") || "Not extracted"}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {getDashboardCountry(passport) || "Manual review"}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-xs text-slate-600">
                          <div><span className="font-medium text-slate-500">DOB:</span> {getDashboardPassportDate(passport, "date_of_birth")}</div>
                          <div className="mt-1"><span className="font-medium text-slate-500">Issued:</span> {getDashboardPassportDate(passport, "date_of_issue")}</div>
                          <div className="mt-1"><span className="font-medium text-slate-500">Expires:</span> {getDashboardPassportDate(passport, "date_of_expiry")}</div>
                        </td>
                        <td className="px-6 py-4 text-slate-700">
                          {formatConfidence(passport.verification_confidence ?? null)}
                        </td>
                        <td className="px-6 py-4 text-slate-500">{formatDateTime(passport.updated_at)}</td>
                        <td className="px-6 py-4">
                          <div className="flex items-center justify-end gap-2">
                            <ReextractPassportControl passport={passport} compact />
                            <Link href={ROUTES.dashboard.passportDetail(passport.id) as never} onClick={(event) => event.stopPropagation()}>
                              <Button variant="outline" size="sm" className="gap-2">
                                <Eye className="h-4 w-4" />
                                Open
                              </Button>
                            </Link>
                          </div>
                        </td>
                        </tr>
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {submissionsView && submissionsView.total > 0 && (
        <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-600">
            Showing {submissionsView.items.length.toLocaleString()} of{" "}
            {submissionsView.total.toLocaleString()} matching submissions
            {submissionsView.cluster_boundaries_preserved
              ? " · duplicate sets stay together"
              : ""}
          </p>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={page <= 1 || isFetching}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </Button>
            <span className="min-w-24 text-center text-sm font-medium text-slate-700">
              Page {submissionsView.page} of {Math.max(1, submissionsView.total_pages)}
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={page >= submissionsView.total_pages || isFetching}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {isEditingTrip && groupDetails && (
        <TripDetailsDialog
          form={tripForm}
          isLoading={updateGroup.isPending}
          onChange={setTripForm}
          onClose={() => setIsEditingTrip(false)}
          onSave={() => {
            updateGroup.mutate(
              {
                id: groupId,
                name: tripForm.name.trim() || groupDetails.group_name,
                destination: tripForm.destination || null,
                travel_date: tripForm.travel_date || null,
                return_date: tripForm.return_date || null,
                departure_cities: tripForm.nearest_international_airport_enabled
                  ? normalizeCities(tripForm.departure_cities)
                  : [],
                base_city_enabled: tripForm.base_city_enabled,
                nearest_international_airport_enabled: tripForm.nearest_international_airport_enabled,
                staff_code_enabled: tripForm.staff_code_enabled,
                agent_employee_code_enabled: tripForm.agent_employee_code_enabled,
                meal_preference_enabled: tripForm.meal_preference_enabled,
                require_selfie: tripForm.require_selfie,
                allow_files_from_device: tripForm.allow_files_from_device,
                ask_nearest_domestic_airport: tripForm.ask_nearest_domestic_airport,
                relation_with_qualifier_enabled:
                  tripForm.relation_with_qualifier_enabled,
                notes: tripForm.notes || null,
              },
              { onSuccess: () => setIsEditingTrip(false) },
            );
          }}
        />
      )}
      {imageEditor && canEditImages && (
        <PassportImageCropEditor
          submissionId={imageEditor.submissionId}
          imageType={imageEditor.imageType}
          label={imageEditor.label}
          returnFocusTarget={imageEditor.returnFocusTarget}
          onClose={() => setImageEditor(null)}
          onSaved={() => {
            setImageRevision((current) => current + 1);
            void refetchSubmissions();
          }}
        />
      )}
      {exportDialogKind && (
        <PassportExportDialog
          groupId={groupId}
          kind={exportDialogKind}
          isDownloading={
            exportDialogKind === "passport_images"
              ? exportImagesMutation.isPending
              : exportMutation.isPending
          }
          onClose={() => setExportDialogKind(null)}
          onDownload={({ mode, baselineExportId }) => {
            const mutation = exportDialogKind === "passport_images"
              ? exportImagesMutation
              : exportMutation;
            mutation.mutate(
              {
                groupId,
                mode,
                baselineExportId,
                requestId: createExportRequestId(),
              },
              {
                onSuccess: () => setExportDialogKind(null),
                onError: (exportError) => {
                  setExportDialogKind(null);
                  setImportMessage(
                    mutationErrorMessage(
                      exportError,
                      exportDialogKind === "passport_images"
                        ? "Image download failed"
                        : "Excel export failed",
                    ),
                  );
                },
              },
            );
          }}
        />
      )}
      <ConfirmDialog
        isOpen={isBulkDeleteConfirmationOpen}
        title="Delete selected submissions?"
        description={`Permanently delete ${selectedPassports.length} selected passport submission${selectedPassports.length === 1 ? "" : "s"}, including uploaded passport and Visa Photo files? This cannot be undone.`}
        confirmLabel={`Delete ${selectedPassports.length} submission${selectedPassports.length === 1 ? "" : "s"}`}
        variant="danger"
        isLoading={bulkDelete.isPending}
        onClose={() => {
          if (!bulkDelete.isPending) setIsBulkDeleteConfirmationOpen(false);
        }}
        onConfirm={() => {
          if (selectedPassports.length === 0 || bulkDelete.isPending) return;
          bulkDelete.mutate(selectedPassports, {
            onSuccess: (result) => {
              setSelectedPassports([]);
              setIsBulkDeleteConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: result.storage_cleanup_deferred ? "warning" : "success",
                message: result.storage_cleanup_deferred
                  ? `Deleted ${result.deleted_count} passport submission${result.deleted_count === 1 ? "" : "s"}. Stored-file cleanup could not finish and was logged for administrator follow-up.`
                  : `Deleted ${result.deleted_count} passport submission${result.deleted_count === 1 ? "" : "s"} and ${result.deleted_storage_objects} stored file${result.deleted_storage_objects === 1 ? "" : "s"}.`,
              });
            },
            onError: (deleteError) => {
              setIsBulkDeleteConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: "error",
                message: mutationErrorMessage(
                  deleteError,
                  "The selected passport submissions could not be deleted.",
                ),
              });
            },
          });
        }}
      />
    </div>
  );
}

function isDuplicatePassport(passport: PassportSubmission) {
  return Boolean(
    passport.duplicate_cluster_id
    && (passport.duplicate_cluster_size ?? 0) > 1,
  );
}

function isDuplicateClusterStart(
  passports: PassportSubmission[],
  index: number,
) {
  const passport = passports[index];
  if (!passport || !isDuplicatePassport(passport)) return false;
  return index === 0
    || passports[index - 1]?.duplicate_cluster_id !== passport.duplicate_cluster_id;
}

function DuplicateClusterHeader({
  passport,
  searchActive,
  compact = false,
}: {
  passport: PassportSubmission;
  searchActive: boolean;
  compact?: boolean;
}) {
  const count = passport.duplicate_cluster_size ?? (
    passport.duplicate_cluster_member_ids?.length ?? 2
  );
  return (
    <div className={compact ? "flex flex-wrap items-center gap-2" : "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"}>
      <span className="inline-flex items-center rounded-full bg-amber-200/70 px-2.5 py-1 text-xs font-bold text-amber-950">
        Possible duplicate set
      </span>
      <span className="text-xs font-medium text-amber-900">
        Part of a possible duplicate set with {count} submissions
        {searchActive ? " · all set members are shown when one matches your search" : ""}
      </span>
    </div>
  );
}

function PassportMobileCard({
  passport,
  selected,
  onToggle,
}: {
  passport: PassportSubmission;
  selected: boolean;
  onToggle: () => void;
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
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-slate-900">{passport.client_name}</h3>
              <p className="mt-1 break-all text-xs text-slate-500">{passport.client_email ?? "No email provided"}</p>
            </div>
          </div>
          <StatusBadge status={passport.status} />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoPair label="Passport" value={getStringField(getDashboardFields(passport), "passport_number") || "Not extracted"} />
          <InfoPair
            label="Nationality"
            value={getDashboardCountry(passport) || "Manual review"}
          />
          <InfoPair
            label="Confidence"
            value={formatConfidence(passport.verification_confidence ?? null)}
          />
          <InfoPair label="Updated" value={formatDateTime(passport.updated_at)} />
          <InfoPair label="Date of Birth" value={getDashboardPassportDate(passport, "date_of_birth")} />
          <InfoPair label="Date of Issue" value={getDashboardPassportDate(passport, "date_of_issue")} />
          <InfoPair label="Date of Expiry" value={getDashboardPassportDate(passport, "date_of_expiry")} />
        </div>

        <div className={`grid gap-2 ${needsReextraction(passport) || passport.extraction_status === "processing" ? "sm:grid-cols-2" : ""}`}>
          <ReextractPassportControl passport={passport} />
          <Link href={ROUTES.dashboard.passportDetail(passport.id) as never} className="block" onClick={(event) => event.stopPropagation()}>
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

function ReextractPassportControl({
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
  const backgroundFailed = backgroundFinished
    && (passport.extraction_status === "extraction_failed" || passport.status === "failed");
  const backgroundConflictCount = getExtractionConflictCount(passport);
  const effectiveFeedback = backgroundFinished
    ? {
      tone: backgroundFailed ? "error" as const : "success" as const,
      message: backgroundFailed
        ? "Automatic extraction failed. You can retry safely."
        : backgroundConflictCount > 0
          ? `Finished with ${backgroundConflictCount} ${backgroundConflictCount === 1 ? "difference" : "differences"} to review.`
          : "Extraction finished. Open the passport to review the results.",
    }
    : feedback;

  const handleReextract = async (event: React.MouseEvent<HTMLButtonElement>) => {
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
          message: "Automatic extraction failed. The saved image is unchanged; try again.",
        });
        return;
      }
      const conflictCount = getExtractionConflictCount(result.submission);
      setFeedback({
        tone: "success",
        message: conflictCount > 0
          ? `Finished with ${conflictCount} ${conflictCount === 1 ? "difference" : "differences"} to review.`
          : "Extraction finished. Open the passport to review the results.",
      });
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof Error ? error.message : "Could not start re-extraction. Please try again.",
      });
    } finally {
      reextractInFlightRef.current = false;
    }
  };

  if (!needsReextraction(passport) && !isProcessing && !effectiveFeedback) return null;

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

function PassportDocumentMatrix({
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
    const map = new Map<string, Partial<Record<"photo" | "front" | "back", PassportDocumentImportPreview["accepted_documents"][number]>>>();
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
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th className="px-5 py-4">Person</th>
                <th className="px-5 py-4">Passport pic</th>
                <th className="px-5 py-4">Passport front</th>
                <th className="px-5 py-4">Passport back</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {passports.map((passport) => {
                const previewDocs = previewByPassenger.get(passport.id);
                return (
                  <tr key={passport.id} className="align-top">
                    <td className="px-5 py-4">
                      <div className="font-semibold text-slate-900">{passport.client_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{getPersonnelCode(passport) || "No staff or Agent/Employee code"}</div>
                    </td>
                    <DocumentCell
                      label="Visa Photo"
                      url={passport.passport_photo_url}
                      file={previewDocs?.photo ? matchedFiles.get(previewDocs.photo) : undefined}
                      filename={previewDocs?.photo?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) => onEdit?.(passport.id, "visa_photo", "Visa Photo", trigger)}
                    />
                    <DocumentCell
                      label="Passport front"
                      url={passport.image_url}
                      file={previewDocs?.front ? matchedFiles.get(previewDocs.front) : undefined}
                      filename={previewDocs?.front?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) => onEdit?.(passport.id, "passport_front", "Passport front", trigger)}
                    />
                    <DocumentCell
                      label="Passport back"
                      url={passport.passport_back_url}
                      file={previewDocs?.back ? matchedFiles.get(previewDocs.back) : undefined}
                      filename={previewDocs?.back?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) => onEdit?.(passport.id, "passport_back", "Passport back", trigger)}
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

function DocumentCell({
  label,
  url,
  file,
  filename,
  revision = 0,
  canEdit = false,
  onEdit,
}: {
  label: string;
  url?: string | null;
  file?: File;
  filename?: string | null;
  revision?: number;
  canEdit?: boolean;
  onEdit?: (trigger: HTMLButtonElement) => void;
}) {
  const effectiveUrl = url ? appendCacheRevision(url, revision) : null;
  return (
    <td className="px-5 py-4">
      {effectiveUrl || file ? (
        <div className="space-y-2">
          {file ? (
            <LocalDocumentThumbnail file={file} label={label} />
          ) : effectiveUrl ? (
            <a
              href={effectiveUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open ${label} in a new tab`}
              className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <DeferredDocumentThumbnail key={effectiveUrl} url={effectiveUrl} label={label} />
            </a>
          ) : null}
          <div className="flex max-w-44 items-center justify-between gap-2">
            <div className="min-w-0 truncate text-xs text-slate-500">{filename ?? "Saved document"}</div>
            {!file && effectiveUrl && canEdit && onEdit && (
              <button
                type="button"
                onClick={(event) => onEdit(event.currentTarget)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <Pencil className="h-3.5 w-3.5" /> Edit
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="flex h-24 w-36 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-xs font-medium text-slate-400">
          No document
        </div>
      )}
    </td>
  );
}

function DeferredDocumentThumbnail({ url, label }: { url: string; label: string }) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const releaseSlotRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const [shouldLoad, setShouldLoad] = useState(false);
  const [loadUrl, setLoadUrl] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const thumbnailUrl = documentThumbnailUrl(url);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    if (typeof IntersectionObserver === "undefined") {
      const timer = globalThis.setTimeout(() => setShouldLoad(true), 0);
      return () => globalThis.clearTimeout(timer);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setShouldLoad(true);
        observer.disconnect();
      },
      { rootMargin: "200px 0px" },
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!shouldLoad || failed) return;
    const controller = new AbortController();
    let disposed = false;

    void acquireDocumentThumbnailSlot(controller.signal)
      .then((release) => {
        if (disposed) {
          release();
          return;
        }
        releaseSlotRef.current = release;
        setLoadUrl(thumbnailUrl);
      })
      .catch((error: unknown) => {
        if (
          !disposed
          && (!(error instanceof Error) || error.name !== "AbortError")
        ) {
          setFailed(true);
        }
      });

    return () => {
      disposed = true;
      controller.abort();
      releaseSlotRef.current?.();
      releaseSlotRef.current = null;
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [failed, loadAttempt, shouldLoad, thumbnailUrl]);

  const releaseSlot = () => {
    releaseSlotRef.current?.();
    releaseSlotRef.current = null;
  };

  const handleLoadError = () => {
    releaseSlot();
    setLoadUrl(null);
    if (loadAttempt === 0) {
      retryTimerRef.current = window.setTimeout(() => {
        retryTimerRef.current = null;
        setLoadAttempt(1);
      }, 1_000);
      return;
    }
    setFailed(true);
  };

  return (
    <div
      ref={frameRef}
      className="flex h-24 w-36 items-center justify-center rounded-lg border border-slate-200 bg-slate-50"
      aria-live="polite"
    >
      {loadUrl ? (
        <>
          {/* Keep this browser-side so the HttpOnly authentication cookie is attached. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={loadUrl}
            alt={label}
            loading="eager"
            decoding="async"
            fetchPriority="low"
            onLoad={releaseSlot}
            onError={handleLoadError}
            className="h-full w-full rounded-lg object-contain"
          />
        </>
      ) : failed ? (
        <span className="px-2 text-center text-xs text-slate-400">
          Preview unavailable
        </span>
      ) : shouldLoad ? (
        <Loader2 className="h-4 w-4 animate-spin text-slate-400" aria-label="Loading preview" />
      ) : (
        <span className="text-xs text-slate-400" aria-hidden="true">Preview</span>
      )}
    </div>
  );
}

function appendCacheRevision(url: string, revision: number) {
  if (revision === 0) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}ui_edit_revision=${revision}`;
}

function needsReextraction(passport: PassportSubmission) {
  if (!hasRealPassportFront(passport)) return false;
  return (
    passport.status === "failed" ||
    !getStringField(passport.extracted_fields, "passport_number") ||
    (passport.overall_confidence ?? 0) <= 0.2
  );
}

function hasRealPassportFront(passport: PassportSubmission) {
  return Boolean(passport.image_s3_key && !passport.image_s3_key.startsWith("excel-imports/"));
}

function LocalDocumentThumbnail({ file, label }: { file: File; label: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    const nextUrl = URL.createObjectURL(file);
    const timer = window.setTimeout(() => setObjectUrl(nextUrl), 0);
    return () => {
      window.clearTimeout(timer);
      URL.revokeObjectURL(nextUrl);
    };
  }, [file]);
  if (!objectUrl) {
    return (
      <div
        className="flex h-24 w-36 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-xs text-slate-400"
        role="status"
      >
        Loading preview
      </div>
    );
  }
  return (
    <a
      href={objectUrl}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open ${label} preview in a new tab`}
      className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      {/* Document imports accept image files; the object URL is revoked on replacement/unmount. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={objectUrl}
        alt={label}
        loading="lazy"
        decoding="async"
        className="h-24 w-36 rounded-lg border border-slate-200 bg-slate-50 object-contain"
      />
    </a>
  );
}

function getDashboardFields(passport: PassportSubmission) {
  return passport.confirmed_fields ?? passport.extracted_fields;
}

function getDashboardCountry(passport: PassportSubmission) {
  const fields = getDashboardFields(passport);
  const nationality = getStringField(fields, "nationality");
  if (nationality) return formatPassportNationality(nationality);
  return formatPassportCountry(getStringField(fields, "issuing_country"));
}

function getDashboardPassportDate(
  passport: PassportSubmission,
  field: "date_of_birth" | "date_of_issue" | "date_of_expiry",
) {
  return formatPassportDateForUi(
    getStringField(getDashboardFields(passport), field),
  ) || "Not provided";
}

function getExtractionConflictCount(passport: PassportSubmission) {
  if (Array.isArray(passport.extraction_conflicts)) return passport.extraction_conflicts.length;
  const fallback = passport.extracted_fields?.manual_review_conflicts;
  return Array.isArray(fallback) ? fallback.length : 0;
}

function getStringField(fields: ExtractedPassportFields | null, key: string) {
  const value = fields?.[key];
  return typeof value === "string" ? value : "";
}

function getPersonnelCode(passport: PassportSubmission) {
  const fields = passport.confirmed_fields ?? passport.extracted_fields;
  const agentEmployeeType = getStringField(fields, "agent_employee_type").toLowerCase();
  const agentEmployeeCode = getStringField(fields, "agent_employee_code");
  if (agentEmployeeCode && agentEmployeeType === "agent") return `AGT_${agentEmployeeCode}`;
  if (agentEmployeeCode && agentEmployeeType === "employee") return `EMP_${agentEmployeeCode}`;
  const metadataCode = passport.staff_metadata?.staff_code ?? passport.staff_metadata?.staffcode;
  const fieldCode = getStringField(fields, "staff_code");
  const value = metadataCode || fieldCode;
  if (!value) return "";
  const normalized = String(value).trim().toUpperCase();
  const prefixed = normalized.match(/^STF[_\-\s]+(.+)$/);
  return prefixed ? `STF_${prefixed[1]}` : `STF_${normalized}`;
}

function createExportRequestId() {
  if (
    typeof globalThis.crypto !== "undefined"
    && typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (
    typeof globalThis.crypto !== "undefined"
    && typeof globalThis.crypto.getRandomValues === "function"
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

function PassportDocumentImportProgress({
  processed,
  total,
  label,
}: {
  processed: number;
  total: number;
  label: string;
}) {
  const percentage = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const unit = total > 1024 * 1024 ? "bytes" : "files";
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Passport document import</h2>
            <p className="mt-1 text-sm text-slate-500">{label}</p>
          </div>
          <div className="text-sm font-semibold text-blue-700">{percentage}%</div>
        </div>
        <div className="mt-5 h-3 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-blue-600 transition-all duration-150" style={{ width: `${Math.max(4, percentage)}%` }} />
        </div>
        <div className="mt-3 text-sm text-slate-500">
          {unit === "bytes"
            ? `${formatBytes(processed)} of ${formatBytes(total)}`
            : `${processed.toLocaleString()} of ${total.toLocaleString()} files checked`}
        </div>
      </div>
    </div>
  );
}

function PassportImportPreviewMatrix({
  preview,
  files,
}: {
  preview: PassportDocumentImportPreview;
  files: File[];
}) {
  const matchedFiles = useMemo(
    () => matchPreviewFiles(preview.accepted_documents, files),
    [files, preview.accepted_documents],
  );
  const passengers = useMemo(() => {
    const byPassenger = new Map<string, {
      id: string;
      name: string;
      staffCode: string;
      documents: Partial<Record<
        "photo" | "front" | "back",
        PassportDocumentImportPreview["accepted_documents"][number]
      >>;
    }>();
    preview.accepted_documents.forEach((document) => {
      if (!document.passenger_id || !document.document_type) return;
      const passenger = byPassenger.get(document.passenger_id) ?? {
        id: document.passenger_id,
        name: document.passenger_name || "Unnamed passenger",
        staffCode: document.staff_code || "",
        documents: {},
      };
      passenger.documents[document.document_type] = document;
      byPassenger.set(document.passenger_id, passenger);
    });
    return [...byPassenger.values()].sort((left, right) => (
      left.name.localeCompare(right.name, undefined, {
        sensitivity: "base",
        numeric: true,
      })
    ));
  }, [preview.accepted_documents]);

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th className="px-5 py-4">Person</th>
                <th className="px-5 py-4">Passport pic</th>
                <th className="px-5 py-4">Passport front</th>
                <th className="px-5 py-4">Passport back</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {passengers.map((passenger) => (
                <tr key={passenger.id} className="align-top">
                  <td className="px-5 py-4">
                    <div className="font-semibold text-slate-900">{passenger.name}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {passenger.staffCode || "No staff code"}
                    </div>
                  </td>
                  {(["photo", "front", "back"] as const).map((documentType) => {
                    const document = passenger.documents[documentType];
                    return (
                      <DocumentCell
                        key={documentType}
                        label={documentType}
                        file={document ? matchedFiles.get(document) : undefined}
                        filename={document?.filename}
                      />
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function matchPreviewFiles(
  documents: PassportDocumentImportPreview["accepted_documents"],
  files: File[],
) {
  const queues = new Map<string, File[]>();
  for (const file of files) {
    const queue = queues.get(file.name) ?? [];
    queue.push(file);
    queues.set(file.name, queue);
  }
  const matches = new Map<PassportDocumentImportPreview["accepted_documents"][number], File>();
  for (const document of documents) {
    const file = queues.get(document.filename)?.shift();
    if (file) matches.set(document, file);
  }
  return matches;
}

function PassportDocumentImportDialog({
  preview,
  files,
  saving,
  onClose,
  onSave,
}: {
  preview: PassportDocumentImportPreview;
  files: File[];
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
}) {
  const [step, setStep] = useState<"distribution" | "documents">("distribution");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="flex max-h-[85vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="border-b border-slate-200 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Passport document distribution</h2>
          <p className="mt-1 text-sm text-slate-500">
            {step === "distribution"
              ? `${preview.accepted_count} accepted, ${preview.rejected_count} rejected. Only accepted files will be saved.`
              : "Review every person against passport pic, passport front, and passport back before saving."}
          </p>
        </div>
        <div className="overflow-y-auto p-6">
          {step === "distribution" ? (
            <div className="grid gap-5 md:grid-cols-2">
              <section>
                <h3 className="mb-2 text-sm font-semibold text-emerald-800">Accepted ({preview.accepted_count})</h3>
                <div className="space-y-2">
                  {preview.accepted_documents.map((item) => (
                    <div key={`${item.filename}-${item.document_type}`} className="rounded-lg border border-emerald-100 bg-emerald-50 p-3 text-sm">
                      <div className="font-medium text-slate-800">{item.filename}</div>
                      <div className="mt-1 text-emerald-800">{item.passenger_name} - {item.document_type}</div>
                    </div>
                  ))}
                  {preview.accepted_count === 0 && <p className="text-sm text-slate-500">No files can be saved.</p>}
                </div>
              </section>
              <section>
                <h3 className="mb-2 text-sm font-semibold text-red-800">Rejected ({preview.rejected_count})</h3>
                <div className="space-y-2">
                  {preview.rejected_documents.map((item, index) => (
                    <div key={`${item.filename}-${index}`} className="rounded-lg border border-red-100 bg-red-50 p-3 text-sm">
                      <div className="font-medium text-slate-800">{item.filename}</div>
                      <div className="mt-1 text-red-700">{item.reason}</div>
                    </div>
                  ))}
                  {preview.rejected_count === 0 && <p className="text-sm text-slate-500">All files passed validation.</p>}
                </div>
              </section>
            </div>
          ) : (
            <PassportImportPreviewMatrix preview={preview} files={files} />
          )}
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <Button type="button" variant="outline" disabled={saving} onClick={onClose}>Cancel</Button>
          {step === "distribution" ? (
            <Button type="button" disabled={preview.accepted_count === 0} onClick={() => setStep("documents")}>
              Next
            </Button>
          ) : (
            <>
              <Button type="button" variant="secondary" disabled={saving} onClick={() => setStep("distribution")}>Back</Button>
              <Button type="button" disabled={saving || preview.accepted_count === 0} onClick={onSave}>
                {saving ? "Saving accepted files" : `Upload accepted (${preview.accepted_count})`}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 MB";
  const mb = bytes / (1024 * 1024);
  if (mb < 1) return `${Math.round(bytes / 1024)} KB`;
  return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`;
}

function mutationErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  if (
    error
    && typeof error === "object"
    && "message" in error
    && typeof error.message === "string"
    && error.message
  ) {
    return error.message;
  }
  return fallback;
}

function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 font-medium text-slate-800">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={PASSPORT_STATUS_COLORS[status] || "default"} dot>
      {PASSPORT_STATUS_LABELS[status] || status}
    </Badge>
  );
}

function TripDetailsDialog({
  form,
  isLoading,
  onChange,
  onClose,
  onSave,
}: {
  form: {
    name: string;
    destination: string;
    travel_date: string;
    return_date: string;
    departure_cities: string[];
    base_city_enabled: boolean;
    nearest_international_airport_enabled: boolean;
    staff_code_enabled: boolean;
    agent_employee_code_enabled: boolean;
    meal_preference_enabled: boolean;
    require_selfie: boolean;
    allow_files_from_device: boolean;
    ask_nearest_domestic_airport: boolean;
    relation_with_qualifier_enabled: boolean;
    notes: string;
  };
  isLoading: boolean;
  onChange: (form: {
    name: string;
    destination: string;
    travel_date: string;
    return_date: string;
    departure_cities: string[];
    base_city_enabled: boolean;
    nearest_international_airport_enabled: boolean;
    staff_code_enabled: boolean;
    agent_employee_code_enabled: boolean;
    meal_preference_enabled: boolean;
    require_selfie: boolean;
    allow_files_from_device: boolean;
    ask_nearest_domestic_airport: boolean;
    relation_with_qualifier_enabled: boolean;
    notes: string;
  }) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const [cityInput, setCityInput] = useState("");
  const updateField = (key: keyof typeof form, value: string) => {
    onChange({ ...form, [key]: value });
  };
  const addCity = () => {
    const nextCity = normalizeCity(cityInput);
    if (!nextCity) return;
    onChange({ ...form, departure_cities: normalizeCities([...form.departure_cities, nextCity]) });
    setCityInput("");
  };
  const removeCity = (city: string) => {
    onChange({ ...form, departure_cities: form.departure_cities.filter((item) => item !== city) });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Edit Trip Details</h2>
          <p className="mt-1 text-sm text-slate-500">These details appear in group views, search, filters, and exports.</p>
        </div>
        <div className="grid max-h-[70vh] gap-4 overflow-y-auto p-6 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Group Name</span>
            <Input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Destination</span>
            <Input value={form.destination} onChange={(event) => updateField("destination", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Travel/Departure Date</span>
            <Input type="date" value={form.travel_date} onChange={(event) => updateField("travel_date", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Return Date</span>
            <Input type="date" value={form.return_date} onChange={(event) => updateField("return_date", event.target.value)} />
          </label>
          <GroupOptionToggle
            label="Visa Photo Upload"
            description="Require a Visa Photo against a plain white or off-white wall."
            checked={form.require_selfie}
            onChange={(checked) => onChange({ ...form, require_selfie: checked })}
          />
          <GroupOptionToggle
            label="Allow files from device"
            description="Let travellers choose existing passport images as well as use the live scanner."
            checked={form.allow_files_from_device}
            onChange={(checked) => onChange({ ...form, allow_files_from_device: checked })}
          />
          <GroupOptionToggle
            label="Ask for nearest domestic airport"
            description="Require each traveller to enter their nearest domestic airport."
            checked={form.ask_nearest_domestic_airport}
            onChange={(checked) => onChange({ ...form, ask_nearest_domestic_airport: checked })}
          />
          <GroupOptionToggle
            label="Relation with Qualifier"
            description="Require Self or one approved family relationship before a single-passenger upload."
            checked={form.relation_with_qualifier_enabled}
            onChange={(checked) => onChange({
              ...form,
              relation_with_qualifier_enabled: checked,
            })}
          />
          <GroupOptionToggle
            label="Base City"
            description="Require each client to enter their city of residence."
            checked={form.base_city_enabled}
            onChange={(checked) => onChange({ ...form, base_city_enabled: checked })}
          />
          <GroupOptionToggle
            label="Staff Code"
            description="Require each client to enter a staff code."
            checked={form.staff_code_enabled}
            onChange={(checked) => onChange({ ...form, staff_code_enabled: checked })}
          />
          <GroupOptionToggle
            label="Agent/Employee Code"
            description="Require each client to select Agent or Employee and enter a numeric code."
            checked={form.agent_employee_code_enabled}
            onChange={(checked) => onChange({ ...form, agent_employee_code_enabled: checked })}
          />
          <div className="space-y-3 rounded-xl border border-slate-200 p-4 sm:col-span-2">
            <GroupOptionToggle
              label="Nearest International Airport"
              description="Require clients to select one configured airport."
              checked={form.nearest_international_airport_enabled}
              onChange={(checked) => onChange({
                ...form,
                nearest_international_airport_enabled: checked,
                departure_cities: checked ? form.departure_cities : [],
              })}
              borderless
            />
            {form.nearest_international_airport_enabled && (
              <div className="space-y-2 border-t border-slate-100 pt-3">
                <div className="flex gap-2">
                  <Input
                    value={cityInput}
                    onChange={(event) => setCityInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addCity();
                      }
                    }}
                    placeholder="e.g. Delhi, Chennai, Mumbai"
                  />
                  <Button type="button" variant="secondary" onClick={addCity}>Add</Button>
                </div>
                {form.departure_cities.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {form.departure_cities.map((city) => (
                      <button
                        key={city}
                        type="button"
                        onClick={() => removeCity(city)}
                        className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-800 transition hover:bg-blue-100"
                      >
                        {city}
                        <X className="h-3 w-3" aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                )}
                {form.departure_cities.length === 0 && <p className="text-xs text-amber-700">Add at least one airport.</p>}
              </div>
            )}
          </div>
          <GroupOptionToggle
            label="Meal Preference"
            description="Require Veg, Non Veg, or Jain selection."
            checked={form.meal_preference_enabled}
            onChange={(checked) => onChange({ ...form, meal_preference_enabled: checked })}
          />
          <label className="space-y-2 sm:col-span-2">
            <span className="text-sm font-medium text-slate-700">Notes</span>
            <textarea
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              rows={4}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSave}
            isLoading={isLoading}
            disabled={isLoading || (form.nearest_international_airport_enabled && form.departure_cities.length === 0)}
          >
            Save Details
          </Button>
        </div>
      </div>
    </div>
  );
}

function normalizeCity(value: string) {
  return value.trim().replace(/\s+/g, " ").slice(0, 120);
}

function normalizeCities(values: string[]) {
  const seen = new Set<string>();
  const cities: string[] = [];
  for (const value of values) {
    const city = normalizeCity(value);
    if (!city) continue;
    const key = city.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cities.push(city);
  }
  return cities;
}
