"use client";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  PassportDocumentImportPreview,
  PassportGroupExportKind,
  PassportGroupSubmissionFilter,
  PassportGroupSubmissionSort,
  PassportImageType,
} from "../api/passports.api";
import {
  useBulkDeletePassportSubmissions,
  useBulkStaffApprovePassportSubmissions,
  useExportPassportGroup,
  useExportPassportGroupImages,
  useExportSelectedPassportImages,
  useExportSelectedPassports,
  useGroupSubmissionsView,
  useImportPassportGroup,
  usePassportGroups,
  usePreviewPassportDocuments,
  useSavePassportDocuments,
} from "../hooks/use-passports";
import { useUpdateUploadLink, useUploadLinks } from "../hooks/use-upload-links";
import {
  buildPassportDetailNavigationHref,
  buildPassportGroupHref,
  createPassportNavigationToken,
  parsePassportGroupViewState,
  storePassportNavigationContext,
  type PassportDetailNavigationState,
  type PassportGroupViewState,
} from "../utils/passport-group-navigation";
import { canEditPassportImages } from "../utils/passport-image-crop-permissions";
import { DEFAULT_TRIP_TIMEZONE } from "../utils/trip-timezone";
import {
  MAX_BULK_SELECTION,
  MAX_SELECTED_IMAGE_DOWNLOAD,
} from "./passport-group-bindings";
import { mutationErrorMessage } from "./passport-group-model";
import type { TripDetailsForm } from "./passport-trip-details-dialog";
export function usePassportGroupController({ groupId }: { groupId: string }) {
  const searchParams = useSearchParams();
  const includeDeleted = searchParams.get("old_data") === "1";
  const currentUser = useAuthStore(selectUser);
  const currentUserId = currentUser?.id ?? null;
  const role = currentUser?.role ?? null;
  const canPermanentlyDelete =
    role === "super_admin" || role === "agency_admin";
  const canBulkStaffApprove =
    role === "super_admin" ||
    role === "agency_admin" ||
    role === "agency_manager" ||
    role === "agency_staff";
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
  const [sortBy, setSortBy] = useState<PassportGroupSubmissionSort>(
    () => parsePassportGroupViewState(searchParams).sortBy,
  );
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(
    () => parsePassportGroupViewState(searchParams).sortOrder,
  );
  const [page, setPage] = useState(
    () => parsePassportGroupViewState(searchParams).page,
  );
  const pageSize = 50;
  const [viewMode, setViewMode] = useState<"table" | "docs">(
    () => parsePassportGroupViewState(searchParams).viewMode,
  );
  const [navigationContextKey, setNavigationContextKey] = useState<{
    token: string;
    userId: string;
    groupId: string;
  } | null>(null);
  const navigationToken =
    navigationContextKey?.userId === currentUserId &&
    navigationContextKey.groupId === groupId
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
  const { data: deletedGroups = [] } = useUploadLinks(
    "deleted",
    includeDeleted,
  );
  const deletedGroup = deletedGroups.find((item) => item.id === groupId);
  const group = groups.find((item) => item.group_id === groupId);
  const groupDetails =
    group ??
    (deletedGroup
      ? {
          group_id: deletedGroup.id,
          group_name: deletedGroup.name,
          group_status: deletedGroup.status,
          total_passports: deletedGroup.deleted_passport_count,
          pending_review_count: 0,
          confirmed_count: 0,
          failed_count: 0,
          latest_submission_at:
            deletedGroup.deleted_at ?? deletedGroup.created_at,
          destination: deletedGroup.destination,
          travel_date: deletedGroup.travel_date,
          return_date: deletedGroup.return_date,
          timezone: deletedGroup.timezone,
          package_name: deletedGroup.package_name,
          departure_cities: deletedGroup.departure_cities ?? [],
          base_city_enabled: deletedGroup.base_city_enabled,
          nearest_international_airport_enabled:
            deletedGroup.nearest_international_airport_enabled,
          staff_code_enabled: deletedGroup.staff_code_enabled,
          agent_employee_code_enabled: deletedGroup.agent_employee_code_enabled,
          meal_preference_enabled: deletedGroup.meal_preference_enabled,
          require_selfie: deletedGroup.require_selfie,
          upload_configuration: deletedGroup.upload_configuration,
          custom_questions: deletedGroup.custom_questions,
          custom_details: deletedGroup.custom_details,
          allow_files_from_device: deletedGroup.allow_files_from_device ?? true,
          ask_nearest_domestic_airport:
            deletedGroup.ask_nearest_domestic_airport ?? false,
          relation_with_qualifier_enabled:
            deletedGroup.relation_with_qualifier_enabled ?? false,
          designation_enabled: deletedGroup.designation_enabled ?? false,
          agency_dealership_name_enabled:
            deletedGroup.agency_dealership_name_enabled ?? false,
          notes: deletedGroup.notes,
        }
      : undefined);
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
  const [isBulkDeleteConfirmationOpen, setIsBulkDeleteConfirmationOpen] =
    useState(false);
  const [isBulkApprovalConfirmationOpen, setIsBulkApprovalConfirmationOpen] =
    useState(false);
  const [passportImportFiles, setPassportImportFiles] = useState<File[]>([]);
  const [passportImportPreview, setPassportImportPreview] =
    useState<PassportDocumentImportPreview | null>(null);
  const [passportImportProgress, setPassportImportProgress] = useState<{
    processed: number;
    total: number;
    label: string;
  } | null>(null);
  const [isEditingTrip, setIsEditingTrip] = useState(false);
  const [tripForm, setTripForm] = useState<TripDetailsForm>({
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
        token && currentUserId
          ? { token, userId: currentUserId, groupId }
          : null,
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
        !actionsMenuRef.current?.contains(target) &&
        !actionsMenuPopupRef.current?.contains(target)
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
  const selectionRevisionById = useMemo(() => {
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
  }, [submissionsView?.items, submissionsView?.ordered_selection_snapshot]);
  const maxBulkSelectionCount = Math.min(
    MAX_BULK_SELECTION,
    submissionsView?.total ?? 0,
  );
  const parsedCustomSelectionCount = Number.parseInt(customSelectionCount, 10);
  const customSelectionIsValid =
    Number.isInteger(parsedCustomSelectionCount) &&
    parsedCustomSelectionCount >= 1 &&
    parsedCustomSelectionCount <= maxBulkSelectionCount;

  const detailNavigation: PassportDetailNavigationState = useMemo(
    () => ({
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
    }),
    [
      debouncedSearch,
      groupId,
      includeDeleted,
      navigationToken,
      page,
      sortBy,
      sortOrder,
      submissionFilter,
      viewMode,
    ],
  );

  const persistNavigationContext = useCallback(() => {
    if (!navigationToken || !currentUserId || !submissionsView) return;
    storePassportNavigationContext({
      token: navigationToken,
      userId: currentUserId,
      groupId,
      includeDeleted,
      viewState: detailNavigation.viewState,
      orderedSubmissionIds:
        submissionsView.ordered_submission_ids ??
        submissionsView.items.map((submission) => submission.id),
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
      setSelectedPassports((current) =>
        current.filter((id) => id !== passportId),
      );
      setSelectedPassportRevisions((revisions) => ({
        ...Object.fromEntries(
          Object.entries(revisions).filter(
            ([submissionId]) => submissionId !== passportId,
          ),
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
    setSelectedPassports((current) =>
      Array.from(new Set([...current, ...selectedIds])).slice(
        0,
        MAX_BULK_SELECTION,
      ),
    );
    setSelectedPassportRevisions((current) => ({
      ...current,
      ...Object.fromEntries(
        selectedIds.flatMap((submissionId) => {
          const revision = selectionRevisionById.get(submissionId);
          return revision === undefined ? [] : [[submissionId, revision]];
        }),
      ),
    }));
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
    passportPreviewMutation.mutate(
      {
        files,
        onProgress: (progress) => {
          setPassportImportProgress({
            processed: progress.loaded,
            total: progress.total,
            label:
              progress.phase === "uploading"
                ? "Uploading files for document check"
                : "Checking documents against the full group",
          });
        },
      },
      {
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
      },
    );
  };

  const handleSelectedPassportDownload = () => {
    if (
      selectedPassports.length === 0 ||
      selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD ||
      selectedImageDownloadStartedRef.current ||
      exportSelectedImages.isPending
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

  return {
    actionsMenuButtonRef,
    actionsMenuPopupRef,
    actionsMenuPosition,
    actionsMenuRef,
    bulkActionsButtonRef,
    bulkActionsDisclosureId,
    bulkActionsMenuRef,
    bulkDelete,
    bulkDeleteFeedback,
    bulkStaffApprove,
    canAccessWhatsApp,
    canBulkStaffApprove,
    canEditImages,
    canPermanentlyDelete,
    customSelectionCount,
    customSelectionIsValid,
    data,
    debouncedSearch,
    error,
    expiryAlerts,
    expiryAlertsRegionId,
    exportDialogKind,
    exportImagesMutation,
    exportMutation,
    exportSelected,
    exportSelectedImages,
    filteredPassports,
    groupDetails,
    groupId,
    handlePassportImportFiles,
    handleSelectedPassportDownload,
    handleSelectionPreset,
    imageEditor,
    imageRevision,
    importInputRef,
    importMessage,
    importMutation,
    includeDeleted,
    isActionsMenuOpen,
    isBulkActionsMenuOpen,
    isBulkApprovalConfirmationOpen,
    isBulkDeleteConfirmationOpen,
    isEditingTrip,
    isExpiryAlertsExpanded,
    isFetching,
    isLoading,
    isTripDetailsExpanded,
    page,
    parsedCustomSelectionCount,
    passportDetailHref,
    passportImportFiles,
    passportImportInputRef,
    passportImportPreview,
    passportImportProgress,
    passportPreviewMutation,
    passportSaveMutation,
    persistNavigationContext,
    refetchSubmissions,
    resetBulkSelection,
    search,
    selectFirstPassports,
    selectedPassportIdSet,
    selectedPassportRevisions,
    selectedPassports,
    selectionPreset,
    setActionsMenuPosition,
    setBulkDeleteFeedback,
    setCustomSelectionCount,
    setDebouncedSearch,
    setExportDialogKind,
    setImageEditor,
    setImageRevision,
    setImportMessage,
    setIsActionsMenuOpen,
    setIsBulkActionsMenuOpen,
    setIsBulkApprovalConfirmationOpen,
    setIsBulkDeleteConfirmationOpen,
    setIsEditingTrip,
    setIsExpiryAlertsExpanded,
    setIsTripDetailsExpanded,
    setPage,
    setPassportImportFiles,
    setPassportImportPreview,
    setPassportImportProgress,
    setSearch,
    setSelectedPassportRevisions,
    setSelectedPassports,
    setSelectionPreset,
    setSortBy,
    setSortOrder,
    setSubmissionFilter,
    setTripForm,
    setViewMode,
    sortBy,
    sortOrder,
    submissionFilter,
    submissionsView,
    togglePassport,
    tripDetailsRegionId,
    tripForm,
    updateGroup,
    viewMode,
  };
}
export type PassportGroupController = ReturnType<
  typeof usePassportGroupController
>;
