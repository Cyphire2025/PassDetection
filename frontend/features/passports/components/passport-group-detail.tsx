"use client";

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, CalendarDays, CheckCircle2, ChevronDown, Download, Eye, FileSpreadsheet, FileText, Loader2, MapPin, MoreVertical, Pencil, RotateCcw, Search, Trash2, UploadCloud, UserCheck, UsersRound, X } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
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
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { useUpdateUploadLink, useUploadLinks } from "../hooks/use-upload-links";
import {
  useExportPassportGroup,
  useExportPassportGroupImages,
  useExportSelectedPassportImages,
  useExportSelectedPassports,
  useBulkDeletePassportSubmissions,
  useBulkStaffApprovePassportSubmissions,
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
import { DocumentCell } from "./passport-document-cell";
import { matchPreviewFiles } from "../utils/passport-document-import";
import { normalizeCities } from "../utils/passport-group-trip";
import { DEFAULT_TRIP_TIMEZONE } from "../utils/trip-timezone";
import {
  buildPassportDetailNavigationHref,
  buildPassportGroupHref,
  createPassportNavigationToken,
  parsePassportGroupViewState,
  storePassportNavigationContext,
  type PassportDetailNavigationState,
  type PassportGroupViewState,
} from "../utils/passport-group-navigation";

const GroupWhatsAppBroadcastPanel = dynamic(
  () => import("./group-whatsapp-broadcast-panel").then((module) => module.GroupWhatsAppBroadcastPanel),
  { loading: () => <Skeleton className="h-56 w-full rounded-xl" /> },
);
const GroupDocumentDeliveryPanel = dynamic(
  () => import("./group-document-delivery-panel").then((module) => module.GroupDocumentDeliveryPanel),
  { loading: () => <Skeleton className="h-44 w-full rounded-xl" /> },
);
const PassportImageCropEditor = dynamic(
  () => import("./passport-image-crop-editor").then((module) => module.PassportImageCropEditor),
  { loading: () => null },
);
const PassportExportDialog = dynamic(
  () => import("./passport-export-dialog").then((module) => module.PassportExportDialog),
  { loading: () => null },
);
const PassportDocumentImportProgress = dynamic(
  () => import("./passport-document-import-dialog").then(
    (module) => module.PassportDocumentImportProgress,
  ),
  { loading: () => <PassportWorkflowLoadingOverlay label="Loading passport import progress" /> },
);
const PassportDocumentImportDialog = dynamic(
  () => import("./passport-document-import-dialog").then(
    (module) => module.PassportDocumentImportDialog,
  ),
  { loading: () => <PassportWorkflowLoadingOverlay label="Loading passport document review" /> },
);
const TripDetailsDialog = dynamic(
  () => import("./passport-trip-details-dialog").then((module) => module.TripDetailsDialog),
  { loading: () => <PassportWorkflowLoadingOverlay label="Loading trip settings" /> },
);
const PassportRetentionControl = dynamic(
  () => import("./passport-retention-control").then((module) => module.PassportRetentionControl),
  { loading: () => <Skeleton className="h-48 w-full rounded-xl" /> },
);

function PassportWorkflowLoadingOverlay({ label }: { label: string }) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4"
      role="status"
      aria-live="polite"
    >
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <p className="text-sm font-semibold text-slate-700">{label}</p>
        <Skeleton className="mt-4 h-3 w-full rounded-full" />
      </div>
    </div>
  );
}

interface PassportGroupDetailProps {
  groupId: string;
}

const MAX_BULK_SELECTION = 1500;
const MAX_SELECTED_IMAGE_DOWNLOAD = 500;

export function PassportGroupDetail({ groupId }: PassportGroupDetailProps) {
  const searchParams = useSearchParams();
  const includeDeleted = searchParams.get("old_data") === "1";
  const currentUser = useAuthStore(selectUser);
  const currentUserId = currentUser?.id ?? null;
  const role = currentUser?.role ?? null;
  const canPermanentlyDelete = role === "super_admin" || role === "agency_admin";
  const canBulkStaffApprove = role === "super_admin"
    || role === "agency_admin"
    || role === "agency_manager"
    || role === "agency_staff";
  const canEditImages = canEditPassportImages(role);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);
  const [search, setSearch] = useState(
    () => parsePassportGroupViewState(searchParams).search,
  );
  const [debouncedSearch, setDebouncedSearch] = useState(
    () => parsePassportGroupViewState(searchParams).search,
  );
  const [selectedPassports, setSelectedPassports] = useState<string[]>([]);
  const [selectedPassportRevisions, setSelectedPassportRevisions] = useState<
    Record<string, number>
  >({});
  const [submissionFilter, setSubmissionFilter] =
    useState<PassportGroupSubmissionFilter>(
      () => parsePassportGroupViewState(searchParams).submissionFilter,
    );
  const [sortBy, setSortBy] =
    useState<PassportGroupSubmissionSort>(
      () => parsePassportGroupViewState(searchParams).sortBy,
    );
  const [sortOrder, setSortOrder] =
    useState<"asc" | "desc">(
      () => parsePassportGroupViewState(searchParams).sortOrder,
    );
  const [page, setPage] = useState(
    () => parsePassportGroupViewState(searchParams).page,
  );
  const pageSize = 50;
  const [viewMode, setViewMode] =
    useState<"table" | "docs">(
      () => parsePassportGroupViewState(searchParams).viewMode,
    );
  const [navigationContextKey, setNavigationContextKey] = useState<{
    token: string;
    userId: string;
    groupId: string;
  } | null>(null);
  const navigationToken =
    navigationContextKey?.userId === currentUserId
    && navigationContextKey.groupId === groupId
      ? navigationContextKey.token
      : null;
  const [imageRevision, setImageRevision] = useState(0);
  const [imageEditor, setImageEditor] = useState<{
    submissionId: string;
    imageType: PassportImageType;
    label: string;
    returnFocusTarget: HTMLButtonElement;
  } | null>(null);
  const [isTripDetailsExpanded, setIsTripDetailsExpanded] = useState(false);
  const tripDetailsRegionId = useId();
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
    timezone: deletedGroup.timezone,
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
    designation_enabled: deletedGroup.designation_enabled ?? false,
    agency_dealership_name_enabled:
      deletedGroup.agency_dealership_name_enabled ?? false,
    notes: deletedGroup.notes,
  } : undefined);
  const exportMutation = useExportPassportGroup();
  const exportImagesMutation = useExportPassportGroupImages();
  const importMutation = useImportPassportGroup(groupId);
  const passportPreviewMutation = usePreviewPassportDocuments(groupId);
  const passportSaveMutation = useSavePassportDocuments(groupId);
  const exportSelected = useExportSelectedPassports();
  const exportSelectedImages = useExportSelectedPassportImages();
  const bulkDelete = useBulkDeletePassportSubmissions(groupId);
  const bulkStaffApprove = useBulkStaffApprovePassportSubmissions(groupId);
  const updateGroup = useUpdateUploadLink();
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const passportImportInputRef = useRef<HTMLInputElement | null>(null);
  const actionsMenuRef = useRef<HTMLDivElement | null>(null);
  const actionsMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const actionsMenuPopupRef = useRef<HTMLDivElement | null>(null);
  const bulkActionsMenuRef = useRef<HTMLDivElement | null>(null);
  const bulkActionsButtonRef = useRef<HTMLButtonElement | null>(null);
  const bulkActionsDisclosureId = useId();
  const selectedImageDownloadStartedRef = useRef(false);
  const [isActionsMenuOpen, setIsActionsMenuOpen] = useState(false);
  const [actionsMenuPosition, setActionsMenuPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const [isBulkActionsMenuOpen, setIsBulkActionsMenuOpen] = useState(false);
  const [selectionPreset, setSelectionPreset] = useState("");
  const [customSelectionCount, setCustomSelectionCount] = useState("");
  const [exportDialogKind, setExportDialogKind] =
    useState<PassportGroupExportKind | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [bulkDeleteFeedback, setBulkDeleteFeedback] = useState<{
    tone: "success" | "warning" | "error";
    message: string;
  } | null>(null);
  const [isBulkDeleteConfirmationOpen, setIsBulkDeleteConfirmationOpen] = useState(false);
  const [isBulkApprovalConfirmationOpen, setIsBulkApprovalConfirmationOpen] = useState(false);
  const [passportImportFiles, setPassportImportFiles] = useState<File[]>([]);
  const [passportImportPreview, setPassportImportPreview] = useState<PassportDocumentImportPreview | null>(null);
  const [passportImportProgress, setPassportImportProgress] = useState<{ processed: number; total: number; label: string } | null>(null);
  const [isEditingTrip, setIsEditingTrip] = useState(false);
  const [tripForm, setTripForm] = useState({
    name: "",
    destination: "",
    travel_date: "",
    return_date: "",
    timezone: DEFAULT_TRIP_TIMEZONE,
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
    designation_enabled: false,
    agency_dealership_name_enabled: false,
    notes: "",
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const token = createPassportNavigationToken();
      setNavigationContextKey(
        token && currentUserId ? { token, userId: currentUserId, groupId } : null,
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [groupId, currentUserId]);

  useEffect(() => {
    const viewState: PassportGroupViewState = {
      search: debouncedSearch,
      submissionFilter,
      sortBy,
      sortOrder,
      page,
      viewMode,
    };
    const href = buildPassportGroupHref(groupId, viewState, includeDeleted);
    const currentHref = `${window.location.pathname}${window.location.search}`;
    if (href !== currentHref) window.history.replaceState(null, "", href);
  }, [
    groupId,
    includeDeleted,
    page,
    debouncedSearch,
    sortBy,
    sortOrder,
    submissionFilter,
    viewMode,
  ]);

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
      const target = event.target as Node;
      if (
        !actionsMenuRef.current?.contains(target)
        && !actionsMenuPopupRef.current?.contains(target)
      ) {
        setIsActionsMenuOpen(false);
        setActionsMenuPosition(null);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsActionsMenuOpen(false);
        setActionsMenuPosition(null);
        actionsMenuButtonRef.current?.focus();
      }
    };
    const closeOnViewportChange = () => {
      setIsActionsMenuOpen(false);
      setActionsMenuPosition(null);
    };

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnViewportChange);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnViewportChange);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [isActionsMenuOpen]);

  useEffect(() => {
    if (!isBulkActionsMenuOpen) return;

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!bulkActionsMenuRef.current?.contains(event.target as Node)) {
        setIsBulkActionsMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsBulkActionsMenuOpen(false);
        bulkActionsButtonRef.current?.focus();
      }
    };

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isBulkActionsMenuOpen]);

  const expiryAlerts = useMemo(() => {
    return submissionsView?.expiry_alerts ?? [];
  }, [submissionsView?.expiry_alerts]);

  const filteredPassports = data ?? [];
  const selectedPassportIdSet = useMemo(
    () => new Set(selectedPassports),
    [selectedPassports],
  );
  const selectionRevisionById = useMemo(
    () => {
      const revisions = new Map(
        (submissionsView?.ordered_selection_snapshot ?? []).map((snapshot) => [
          snapshot.submission_id,
          snapshot.extraction_revision,
        ]),
      );
      for (const submission of submissionsView?.items ?? []) {
        revisions.set(submission.id, submission.extraction_revision);
      }
      return revisions;
    },
    [submissionsView?.items, submissionsView?.ordered_selection_snapshot],
  );
  const maxBulkSelectionCount = Math.min(
    MAX_BULK_SELECTION,
    submissionsView?.total ?? 0,
  );
  const parsedCustomSelectionCount = Number.parseInt(customSelectionCount, 10);
  const customSelectionIsValid = Number.isInteger(parsedCustomSelectionCount)
    && parsedCustomSelectionCount >= 1
    && parsedCustomSelectionCount <= maxBulkSelectionCount;

  const detailNavigation: PassportDetailNavigationState = useMemo(() => ({
    token: navigationToken,
    groupId,
    includeDeleted,
    viewState: {
      search: debouncedSearch,
      submissionFilter,
      sortBy,
      sortOrder,
      page,
      viewMode,
    },
  }), [
    debouncedSearch,
    groupId,
    includeDeleted,
    navigationToken,
    page,
    sortBy,
    sortOrder,
    submissionFilter,
    viewMode,
  ]);

  const persistNavigationContext = useCallback(() => {
    if (!navigationToken || !currentUserId || !submissionsView) return;
    storePassportNavigationContext({
      token: navigationToken,
      userId: currentUserId,
      groupId,
      includeDeleted,
      viewState: detailNavigation.viewState,
      orderedSubmissionIds:
        submissionsView.ordered_submission_ids
        ?? submissionsView.items.map((submission) => submission.id),
    });
  }, [
    currentUserId,
    detailNavigation.viewState,
    groupId,
    includeDeleted,
    navigationToken,
    submissionsView,
  ]);

  useEffect(() => {
    persistNavigationContext();
  }, [persistNavigationContext]);

  const passportDetailHref = (submissionId: string) =>
    buildPassportDetailNavigationHref(submissionId, detailNavigation);

  const resetBulkSelection = () => {
    setSelectedPassports([]);
    setSelectedPassportRevisions({});
    setSelectionPreset("");
    setCustomSelectionCount("");
    setIsBulkActionsMenuOpen(false);
  };

  const togglePassport = (passportId: string) => {
    setSelectionPreset("");
    if (selectedPassportIdSet.has(passportId)) {
      setSelectedPassports((current) => current.filter((id) => id !== passportId));
      setSelectedPassportRevisions((revisions) => ({
        ...Object.fromEntries(
          Object.entries(revisions).filter(([submissionId]) => submissionId !== passportId),
        ),
      }));
      return;
    }
    const revision = selectionRevisionById.get(passportId);
    if (revision === undefined) return;
    if (selectedPassports.length >= MAX_BULK_SELECTION) {
      setBulkDeleteFeedback({
        tone: "warning",
        message: `Select at most ${MAX_BULK_SELECTION.toLocaleString()} submissions at a time.`,
      });
      return;
    }
    setSelectedPassports((current) => [...current, passportId]);
    setSelectedPassportRevisions((revisions) => ({
      ...revisions,
      [passportId]: revision,
    }));
  };

  const selectFirstPassports = (requestedCount: number) => {
    const orderedIds = submissionsView?.ordered_submission_ids ?? [];
    const boundedCount = Math.min(
      Math.max(0, requestedCount),
      orderedIds.length,
      MAX_BULK_SELECTION,
    );
    const selectedIds = orderedIds.slice(0, boundedCount);
    setSelectedPassports(selectedIds);
    setSelectedPassportRevisions(Object.fromEntries(
      selectedIds.flatMap((submissionId) => {
        const revision = selectionRevisionById.get(submissionId);
        return revision === undefined ? [] : [[submissionId, revision]];
      }),
    ));
    setIsBulkActionsMenuOpen(false);
  };

  const handleSelectionPreset = (preset: string) => {
    setSelectionPreset(preset);
    if (preset === "custom") {
      setCustomSelectionCount((current) => current || "1");
      return;
    }
    if (preset === "all") {
      selectFirstPassports(submissionsView?.ordered_submission_ids.length ?? 0);
      return;
    }
    const count = Number.parseInt(preset, 10);
    if (Number.isFinite(count)) selectFirstPassports(count);
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

  const handleSelectedPassportDownload = () => {
    if (
      selectedPassports.length === 0
      || selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD
      || selectedImageDownloadStartedRef.current
      || exportSelectedImages.isPending
    ) {
      return;
    }

    selectedImageDownloadStartedRef.current = true;
    setImportMessage(null);
    exportSelectedImages.mutate(
      {
        groupId,
        groupName: groupDetails?.group_name,
        submissionIds: [...selectedPassports],
      },
      {
        onError: (downloadError) => {
          setImportMessage(
            mutationErrorMessage(
              downloadError,
              "Selected passport download failed",
            ),
          );
        },
        onSettled: () => {
          selectedImageDownloadStartedRef.current = false;
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-5">
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
              setSelectedPassportRevisions({});
              setSelectionPreset("");
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

      <WorkspacePageHeader
        eyebrow={includeDeleted ? "Retained passport archive" : "Group passport workspace"}
        title={groupDetails?.group_name ?? "Group Submissions"}
        description="Review passenger records, resolve exceptions, manage group exports, and move each passport through the existing confirmation workflow."
        icon={UsersRound}
        accent={includeDeleted ? "amber" : "sky"}
        context={(
          <>
            {groupDetails?.destination && (
              <WorkspaceHeaderContext icon={MapPin}>{groupDetails.destination}</WorkspaceHeaderContext>
            )}
            {groupDetails?.travel_date && (
              <WorkspaceHeaderContext icon={CalendarDays}>{groupDetails.travel_date}</WorkspaceHeaderContext>
            )}
            <WorkspaceHeaderContext icon={FileText}>
              {(submissionsView?.group_total ?? groupDetails?.total_passports ?? 0).toLocaleString()} passengers
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <div className="flex items-center gap-2">
            {exportImagesMutation.isPending && (
              <div
                role="status"
                aria-live="polite"
                className="flex shrink-0 items-center gap-2 text-sm font-medium text-slate-100"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                <span className="hidden xl:inline">Downloading passport images</span>
              </div>
            )}
            <IntentPrefetchLink
              href={ROUTES.dashboard.passports}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              All Groups
            </IntentPrefetchLink>
            <div ref={actionsMenuRef} className="relative">
            <Button
              ref={actionsMenuButtonRef}
              type="button"
              size="icon"
              aria-label="Open group actions"
              aria-haspopup="menu"
              aria-expanded={isActionsMenuOpen}
              className="border border-white/20 bg-white/10 text-white shadow-none hover:bg-white/15 active:bg-white/20"
              onClick={() => {
                if (isActionsMenuOpen) {
                  setIsActionsMenuOpen(false);
                  setActionsMenuPosition(null);
                  return;
                }
                const rect = actionsMenuButtonRef.current?.getBoundingClientRect();
                if (!rect) return;
                const menuWidth = 256;
                const menuHeight = 224;
                const top = rect.bottom + 8 + menuHeight > window.innerHeight
                  ? Math.max(8, rect.top - menuHeight - 8)
                  : rect.bottom + 8;
                setActionsMenuPosition({
                  left: Math.max(
                    8,
                    Math.min(window.innerWidth - menuWidth - 8, rect.right - menuWidth),
                  ),
                  top,
                });
                setIsActionsMenuOpen(true);
              }}
            >
              <MoreVertical className="h-4 w-4" aria-hidden="true" />
            </Button>
            {isActionsMenuOpen && actionsMenuPosition && createPortal(
              <div
                ref={actionsMenuPopupRef}
                role="menu"
                className="fixed z-[70] w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl"
                style={{ left: actionsMenuPosition.left, top: actionsMenuPosition.top }}
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
              </div>,
              document.body,
            )}
          </div>
          </div>
        )}
      />

      <WorkspaceSummaryStrip label="Group passport readiness">
        {isLoading && !groupDetails ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Submitted"
              value={(submissionsView?.group_total ?? groupDetails?.total_passports ?? 0).toLocaleString()}
              helper="passengers"
              icon={UsersRound}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Needs review"
              value={(groupDetails?.pending_review_count ?? 0).toLocaleString()}
              helper="records"
              icon={AlertTriangle}
              tone={(groupDetails?.pending_review_count ?? 0) > 0 ? "attention" : "success"}
            />
            <WorkspaceSummaryItem
              label="Confirmed"
              value={(groupDetails?.confirmed_count ?? 0).toLocaleString()}
              helper="ready"
              icon={CheckCircle2}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Failed"
              value={(groupDetails?.failed_count ?? 0).toLocaleString()}
              helper="need recovery"
              icon={X}
              tone={(groupDetails?.failed_count ?? 0) > 0 ? "attention" : "default"}
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      {groupDetails && (
        <>
          <Card>
          <CardContent className="p-5">
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
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-expanded={isTripDetailsExpanded}
                  aria-controls={tripDetailsRegionId}
                  onClick={() => setIsTripDetailsExpanded((current) => !current)}
                >
                  <ChevronDown
                    className={`h-4 w-4 transition-transform ${isTripDetailsExpanded ? "rotate-180" : ""}`}
                    aria-hidden="true"
                  />
                  {isTripDetailsExpanded ? "Hide details" : "Show details"}
                </Button>
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
                      timezone: groupDetails.timezone ?? DEFAULT_TRIP_TIMEZONE,
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
                      designation_enabled: groupDetails.designation_enabled ?? false,
                      agency_dealership_name_enabled:
                        groupDetails.agency_dealership_name_enabled ?? false,
                      notes: groupDetails.notes ?? "",
                    });
                    setIsEditingTrip(true);
                  }}
                >
                  <Pencil className="h-4 w-4" />
                  Edit
                </Button>
              </div>
            </div>
            {isTripDetailsExpanded && (
              <div
                id={tripDetailsRegionId}
                role="region"
                aria-label="Destination and trip details"
                className="mt-4 grid gap-3 text-sm sm:grid-cols-3"
              >
                <InfoPair label="Destination" value={groupDetails.destination || "Not set"} />
                <InfoPair label="Travel/Departure Date" value={groupDetails.travel_date || "Not set"} />
                <InfoPair label="Return Date" value={groupDetails.return_date || "Not set"} />
                <InfoPair label="Trip Timezone" value={groupDetails.timezone || DEFAULT_TRIP_TIMEZONE} />
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
                <InfoPair label="Designation" value={groupDetails.designation_enabled ? "Required" : "Disabled"} />
                <InfoPair label="Agency/Dealership Name" value={groupDetails.agency_dealership_name_enabled ? "Required" : "Disabled"} />
                <div className="sm:col-span-2">
                  <InfoPair label="Notes" value={groupDetails.notes || "No notes"} />
                </div>
              </div>
            )}
          </CardContent>
          </Card>
          <PassportRetentionControl
            allowed={canPermanentlyDelete}
            enabled={!error}
            groupId={groupId}
            groupName={groupDetails.group_name}
          />
        </>
      )}

      {!includeDeleted && groupDetails && !error && (
        <>
          {canAccessWhatsApp && (
            <GroupWhatsAppBroadcastPanel groupId={groupId} />
          )}
          <GroupDocumentDeliveryPanel groupId={groupId} />
        </>
      )}

      {importMessage && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800"
        >
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
                    href={passportDetailHref(passport.submission_id) as never}
                    onClick={persistNavigationContext}
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
            resetBulkSelection();
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

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <label className="sr-only" htmlFor="group-submission-sort">Sort submissions by</label>
        <select
          id="group-submission-sort"
          value={sortBy}
          onChange={(event) => {
            setSortBy(event.target.value as PassportGroupSubmissionSort);
            setPage(1);
            resetBulkSelection();
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
            resetBulkSelection();
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
            resetBulkSelection();
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
        <label className="sr-only" htmlFor="group-submission-selection">Select submissions</label>
        <select
          id="group-submission-selection"
          value={selectionPreset}
          disabled={(submissionsView?.total ?? 0) === 0}
          onChange={(event) => handleSelectionPreset(event.target.value)}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="">Select passengers</option>
          <option value="all">
            {(submissionsView?.total ?? 0) > MAX_BULK_SELECTION
              ? "First 1,500 (maximum)"
              : "All"}
          </option>
          <option value="50">First 50</option>
          <option value="100">First 100</option>
          <option value="200">First 200</option>
          <option value="custom">Custom number</option>
        </select>
        {selectionPreset === "custom" && (
          <div className="flex shrink-0 items-center gap-2">
            <label className="sr-only" htmlFor="group-submission-custom-selection">
              Number of submissions to select
            </label>
            <Input
              id="group-submission-custom-selection"
              type="number"
              min={1}
              max={Math.min(
                MAX_BULK_SELECTION,
                Math.max(1, submissionsView?.total ?? 1),
              )}
              value={customSelectionCount}
              onChange={(event) => setCustomSelectionCount(event.target.value)}
              className="h-9 w-28"
              placeholder="Count"
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={!customSelectionIsValid}
              onClick={() => {
                if (customSelectionIsValid) {
                  selectFirstPassports(parsedCustomSelectionCount);
                }
              }}
            >
              Apply
            </Button>
          </div>
        )}
        {selectedPassports.length > 0 && (
          <>
            <span className="shrink-0 text-sm font-medium text-slate-700" aria-live="polite">
              {selectedPassports.length.toLocaleString()} selected
            </span>
            <div ref={bulkActionsMenuRef} className="relative shrink-0">
              <Button
                ref={bulkActionsButtonRef}
                type="button"
                variant="secondary"
                size="icon"
                aria-label={`Open bulk actions for ${selectedPassports.length} selected submissions`}
                aria-expanded={isBulkActionsMenuOpen}
                aria-controls={bulkActionsDisclosureId}
                onClick={() => setIsBulkActionsMenuOpen((open) => !open)}
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
              {isBulkActionsMenuOpen && (
                <div
                  id={bulkActionsDisclosureId}
                  aria-label="Bulk submission actions"
                  className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl"
                >
                  {canBulkStaffApprove && !includeDeleted && (
                    <button
                      type="button"
                      disabled={bulkStaffApprove.isPending}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        setIsBulkActionsMenuOpen(false);
                        setBulkDeleteFeedback(null);
                        setIsBulkApprovalConfirmationOpen(true);
                      }}
                    >
                      <UserCheck className="h-4 w-4 text-emerald-600" />
                      Staff approve all selected ({selectedPassports.length})
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={exportSelected.isPending}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => {
                      setIsBulkActionsMenuOpen(false);
                      exportSelected.mutate(selectedPassports);
                    }}
                  >
                    <FileSpreadsheet className="h-4 w-4 text-slate-500" />
                    Export Excel ({selectedPassports.length})
                  </button>
                  <button
                    type="button"
                    disabled={
                      exportSelectedImages.isPending
                      || selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD
                    }
                    className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => {
                      setIsBulkActionsMenuOpen(false);
                      handleSelectedPassportDownload();
                    }}
                  >
                    <Download className="h-4 w-4 text-slate-500" />
                    {selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD
                      ? `Download Passport Images (select up to ${MAX_SELECTED_IMAGE_DOWNLOAD})`
                      : `Download Passport Images (${selectedPassports.length})`}
                  </button>
                  {canPermanentlyDelete && !includeDeleted && (
                    <button
                      type="button"
                      disabled={bulkDelete.isPending}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        setIsBulkActionsMenuOpen(false);
                        setBulkDeleteFeedback(null);
                        setIsBulkDeleteConfirmationOpen(true);
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete selected ({selectedPassports.length})
                    </button>
                  )}
                </div>
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="shrink-0 whitespace-nowrap"
              onClick={resetBulkSelection}
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
                  selected={selectedPassportIdSet.has(passport.id)}
                  onToggle={() => togglePassport(passport.id)}
                  detailHref={passportDetailHref(passport.id)}
                  onOpen={persistNavigationContext}
                />
              </Fragment>
            ))}
          </div>

          <Card className="hidden lg:block">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Group passenger passport readiness</caption>
                  <thead>
                    <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                      <th scope="col" className="px-6 py-4">Client</th>
                      <th scope="col" className="px-6 py-4">Status</th>
                      <th scope="col" className="px-6 py-4">Passport</th>
                      <th scope="col" className="px-6 py-4">Passport Dates</th>
                      <th scope="col" className="px-6 py-4">Confidence</th>
                      <th scope="col" className="px-6 py-4">Updated</th>
                      <th scope="col" className="px-6 py-4 text-right">Action</th>
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
                              checked={selectedPassportIdSet.has(passport.id)}
                              onChange={() => togglePassport(passport.id)}
                              onClick={(event) => event.stopPropagation()}
                              aria-label={`Select ${passport.client_name}`}
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
                            <Link
                              href={passportDetailHref(passport.id) as never}
                              onClick={(event) => {
                                event.stopPropagation();
                                persistNavigationContext();
                              }}
                            >
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
                timezone: tripForm.timezone.trim(),
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
                designation_enabled: tripForm.designation_enabled,
                agency_dealership_name_enabled:
                  tripForm.agency_dealership_name_enabled,
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
          onDownload={({
            mode,
            baselineExportId,
            supplementalFields,
            groupByField,
            agencyMatchField,
          }) => {
            const mutation = exportDialogKind === "passport_images"
              ? exportImagesMutation
              : exportMutation;
            mutation.mutate(
              {
                groupId,
                groupName: groupDetails?.group_name,
                mode,
                baselineExportId,
                supplementalFields,
                groupByField,
                agencyMatchField,
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
        isOpen={isBulkApprovalConfirmationOpen}
        title="Staff approve selected submissions?"
        description={`Mark eligible records, including Client Submitted records, among ${selectedPassports.length} selected submission${selectedPassports.length === 1 ? "" : "s"} as Staff Approved? Processing, failed, and incomplete records will be left unchanged and reported.`}
        confirmLabel={`Approve ${selectedPassports.length} selected`}
        isLoading={bulkStaffApprove.isPending}
        onClose={() => {
          if (!bulkStaffApprove.isPending) {
            setIsBulkApprovalConfirmationOpen(false);
          }
        }}
        onConfirm={() => {
          if (selectedPassports.length === 0 || bulkStaffApprove.isPending) return;
          const approvalSelections = selectedPassports.flatMap((submissionId) => {
            const expectedRevision = selectedPassportRevisions[submissionId];
            return expectedRevision === undefined
              ? []
              : [{
                submission_id: submissionId,
                expected_extraction_revision: expectedRevision,
              }];
          });
          if (approvalSelections.length !== selectedPassports.length) {
            setIsBulkApprovalConfirmationOpen(false);
            setBulkDeleteFeedback({
              tone: "error",
              message: "The selection snapshot is incomplete. Refresh the group and select the submissions again.",
            });
            void refetchSubmissions();
            return;
          }
          bulkStaffApprove.mutate(approvalSelections, {
            onSuccess: (result) => {
              const retryableSkippedIds = result.skipped_submissions
                .filter((item) => item.reason === "not_completed")
                .map((item) => item.submission_id);
              const retryableSkippedIdSet = new Set(retryableSkippedIds);
              const staleCount = result.skipped_submissions.filter(
                (item) => item.reason === "stale",
              ).length;
              const incompleteCount = result.skipped_count - staleCount;
              setSelectedPassports(retryableSkippedIds);
              setSelectedPassportRevisions((revisions) => Object.fromEntries(
                Object.entries(revisions).filter(([submissionId]) => (
                  retryableSkippedIdSet.has(submissionId)
                )),
              ));
              setSelectionPreset("");
              setIsBulkApprovalConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: result.skipped_count > 0 ? "warning" : "success",
                message: [
                  `Staff approved ${result.approved_count} submission${result.approved_count === 1 ? "" : "s"}.`,
                  result.already_approved_count > 0
                    ? `${result.already_approved_count} were already Staff Approved.`
                    : "",
                  staleCount > 0
                    ? `${staleCount} submission${staleCount === 1 ? " changed" : "s changed"} after selection and must be refreshed and reviewed again.`
                    : "",
                  incompleteCount > 0
                    ? `${incompleteCount} incomplete or in-progress submission${incompleteCount === 1 ? " was" : "s were"} left unchanged.`
                    : "",
                  incompleteCount > 0
                    ? "Incomplete submissions remain selected."
                    : "",
                ].filter(Boolean).join(" "),
              });
              if (staleCount > 0) void refetchSubmissions();
            },
            onError: (approvalError) => {
              setIsBulkApprovalConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: "error",
                message: mutationErrorMessage(
                  approvalError,
                  "The selected passport submissions could not be staff approved.",
                ),
              });
            },
          });
        }}
      />
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
              setSelectedPassportRevisions({});
              setSelectionPreset("");
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
            <caption className="sr-only">Current passenger document assignments</caption>
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th scope="col" className="px-5 py-4">Person</th>
                <th scope="col" className="px-5 py-4">Passport pic</th>
                <th scope="col" className="px-5 py-4">Passport front</th>
                <th scope="col" className="px-5 py-4">Passport back</th>
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
