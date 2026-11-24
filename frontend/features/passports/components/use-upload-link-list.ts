import { useDeferredValue, useMemo, useState } from "react";
import { canArchiveGroup, canPermanentlyDeleteGroup } from "@/lib/utils/role-access";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type { UploadLinkResponse } from "../api/upload-links.api";
import {
  useDeleteUploadLink,
  usePermanentlyDeleteUploadLink,
  useRestoreUploadLink,
  useRevokeUploadLink,
  useUploadLinks
} from "../hooks/use-upload-links";
import { useUploadLinkCopy } from "./use-upload-link-copy";
import { filterUploadLinks } from "./upload-link-filter";

const EMPTY_LINKS: UploadLinkResponse[] = [];

export function useUploadLinkList() {
  const role = useAuthStore(selectUserRole);
  const canPermanentlyDelete = canPermanentlyDeleteGroup(role);
  const canArchive = canArchiveGroup(role);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isArchivedExpanded, setIsArchivedExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const { copiedLinkKey, copyError, copyUploadLink } = useUploadLinkCopy();
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    description: string;
    confirmLabel: string;
    variant?: "primary" | "danger";
    onConfirm: () => void;
  } | null>(null);
  const [renameTarget, setRenameTarget] = useState<UploadLinkResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UploadLinkResponse | null>(null);
  const {
    data: activeLinksData,
    isLoading: isLoadingActive,
    error: activeLinksError,
    isFetching: isFetchingActive,
    refetch: refetchActive,
  } = useUploadLinks();
  const {
    data: archivedLinksData,
    isLoading: isLoadingArchived,
    error: archivedLinksError,
    isFetching: isFetchingArchived,
    refetch: refetchArchived,
  } = useUploadLinks("archived");
  const activeLinks = activeLinksData ?? EMPTY_LINKS;
  const archivedLinks = archivedLinksData ?? EMPTY_LINKS;
  const activeDataKnown = activeLinksData !== undefined;
  const archivedDataKnown = archivedLinksData !== undefined;
  const { mutate: closeLink, isPending: isClosing } = useRevokeUploadLink();
  const { mutate: archiveLink, isPending: isArchiving } = useDeleteUploadLink();
  const { mutate: restoreLink, isPending: isRestoring } = useRestoreUploadLink();
  const {
    mutate: permanentlyDeleteLink,
    isPending: isPermanentlyDeleting,
    isError: isPermanentDeleteError,
    error: permanentDeleteError,
    reset: resetPermanentDelete,
  } = usePermanentlyDeleteUploadLink();
  const filteredActiveLinks = useMemo(
    () => filterUploadLinks(activeLinks, deferredQuery),
    [activeLinks, deferredQuery],
  );
  const filteredArchivedLinks = useMemo(
    () => filterUploadLinks(archivedLinks, deferredQuery),
    [archivedLinks, deferredQuery],
  );
  const activeCount = activeLinks.filter((link) => link.status === "active" && !link.import_only).length;
  const closedCount = activeLinks.filter((link) => link.status === "closed").length;
  const datedCount = [...activeLinks, ...archivedLinks].filter((link) => link.travel_date).length;
  const openGroupEditor = (link: UploadLinkResponse) => {
    setRenameTarget(link);
  };
  return {
    activeDataKnown,
    activeCount,
    archivedDataKnown,
    archivedLinks,
    setIsModalOpen,
    isModalOpen,
    copyError,
    isLoadingActive,
    isLoadingArchived,
    closedCount,
    datedCount,
    activeLinks,
    query,
    setQuery,
    filteredActiveLinks,
    activeLinksError,
    isFetchingActive,
    refetchActive,
    copiedLinkKey,
    copyUploadLink,
    setConfirmAction,
    closeLink,
    restoreLink,
    canArchive,
    archiveLink,
    openGroupEditor,
    isClosing,
    isArchiving,
    isRestoring,
    isArchivedExpanded,
    setIsArchivedExpanded,
    archivedLinksError,
    isFetchingArchived,
    refetchArchived,
    filteredArchivedLinks,
    resetPermanentDelete,
    setDeleteTarget,
    canPermanentlyDelete,
    isPermanentlyDeleting,
    confirmAction,
    renameTarget,
    setRenameTarget,
    deleteTarget,
    isPermanentDeleteError,
    permanentDeleteError,
    permanentlyDeleteLink
  };
}

export type UploadLinkListState = ReturnType<typeof useUploadLinkList>;
